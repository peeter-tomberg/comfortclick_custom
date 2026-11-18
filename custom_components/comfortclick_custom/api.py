"""API object class."""

import asyncio
import json
import logging
import time
import typing
from http import HTTPStatus

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_read=25)
SESSION_RECOVERY_COOLDOWN = 30


# Since keys contain \\ and python handles strings differently
def _sanitise_device_name(device_name: str) -> str:
    return device_name.replace("\\\\", "\\")


def _validate_result(data: typing.Any) -> typing.Any:
    """Reject explicit application errors while allowing legacy statusless replies."""
    if not isinstance(data, dict):
        return data
    status = data.get("Status")
    normalised_status = (
        status.casefold().replace(" ", "") if isinstance(status, str) else ""
    )
    if normalised_status in {
        "unauthorized",
        "unauthorised",
        "notauthenticated",
        "authenticationrequired",
        "sessionexpired",
    }:
        raise AuthorizationError({"message": "Server rejected the session"})
    if (
        normalised_status in {"error", "failed", "failure"}
        or data.get("Success") is False
        or data.get("Error")
    ):
        raise ApiResponseError({"message": "Server reported an application error"})
    return data


def _require_updates(data: typing.Any, key: str) -> list[dict]:
    """Validate all update records before changing any cached values."""
    if not isinstance(data, dict):
        raise ApiResponseError({"message": "Expected a response object"})
    records = data.get(key, [])
    if not isinstance(records, list):
        raise ApiResponseError({"message": "Expected an update list"})
    for item in records:
        if not isinstance(item, dict):
            raise ApiResponseError({"message": "Expected an update object"})
        if not isinstance(item.get("DeviceName"), str) or not item["DeviceName"]:
            raise ApiResponseError({"message": "Update has no device name"})
        if key == "PropertyUpdates" and not isinstance(item.get("PropertyName"), str):
            raise ApiResponseError({"message": "Update has no property name"})
        if (
            key == "ValueUpdates" or item.get("PropertyName") == "Value"
        ) and "Value" not in item:
            raise ApiResponseError({"message": "Update has no value"})
    return records


class ApiInstance:
    """Class that handles communicating with ComfortClick API."""

    def __init__(
        self,
        username: str,
        password: str,
        host: str,
        *,
        session: aiohttp.ClientSession,
    ) -> None:
        """Wire up the Api Instance class with props from constructor."""
        self._username = username
        self._password = password
        self._host = host
        self._session = session

        self._state: dict[str, typing.Any] = {}
        self._authorized_headers = None
        self._session_generation = 0
        self._snapshot_generation = -1
        self._snapshot_pending = False
        self._next_reconnect = 0.0
        self._reconnect_lock = asyncio.Lock()

    def _set_state_value(self, device_name: str, value: typing.Any) -> None:
        """Update or discover a component using the same normalized identity."""
        _LOGGER.debug(
            msg="Changing component internal state",
            extra={
                "device_name": device_name,
                "value": value,
            },
        )
        self._state[_sanitise_device_name(device_name)] = value

    async def _request_json(self, path: str, payload: typing.Any = None) -> typing.Any:
        """Make one authenticated request without retrying side effects."""
        async with self._session.post(
            f"{self._host}/{path}",
            json=payload,
            headers=self._authorized_headers,
            timeout=REQUEST_TIMEOUT,
            ssl=False,
        ) as response:
            if response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                raise AuthorizationError({"status": response.status})
            if response.status != HTTPStatus.OK:
                raise HttpStatusNotOkError({"status": response.status})
            return _validate_result(await response.json())

    async def _recover_session(self, failed_generation: int) -> None:
        """Renew one rejected session even when several requests fail together."""
        async with self._reconnect_lock:
            if (
                self._session_generation != failed_generation
                and self._snapshot_generation == self._session_generation
            ):
                return
            now = time.monotonic()
            if now < self._next_reconnect:
                raise AuthorizationError(
                    {"message": "Session recovery is cooling down"}
                )
            # Polling runs every second. Bound login attempts even when the
            # credentials or the renewed session keep being rejected.
            self._next_reconnect = now + SESSION_RECOVERY_COOLDOWN
            self._snapshot_pending = True
            self._authorized_headers = None
            await self.connect()
            await self.initialize_state()

    async def _authenticated_request(
        self,
        path: str,
        payload: typing.Any = None,
        *,
        retry_read: bool = False,
    ) -> typing.Any:
        """Recover rejected credentials and retry reads at most once."""
        if self._snapshot_pending:
            await self._recover_session(self._snapshot_generation)
        generation = self._session_generation
        try:
            result = await self._request_json(path, payload)
        except AuthorizationError:
            await self._recover_session(generation)
            if not retry_read:
                # A door pulse is not replayed implicitly. The next user request
                # can use the renewed session without restarting Home Assistant.
                _LOGGER.warning("Session renewed; rejected command was not replayed")
                raise
        else:
            if not retry_read or (
                generation == self._session_generation and not self._snapshot_pending
            ):
                return result
            # A command can renew the session while a poll is in flight. Do not
            # apply its old delta over the new session's complete snapshot.
            await self._recover_session(generation)
        retry_generation = self._session_generation
        result = await self._request_json(path, payload)
        if retry_generation != self._session_generation or self._snapshot_pending:
            raise AuthorizationError({"message": "Session changed during read retry"})
        return result

    async def set_value(self, device_name: str, value: typing.Any) -> typing.Any:
        """Send a command once; never replay an ambiguously completed command."""
        payload = {
            "objectName": _sanitise_device_name(device_name),
            "valueName": "Value",
            "value": value,
        }
        return await self._authenticated_request("SetValue", payload)

    def get_value(self, device_name: str) -> typing.Any:
        """Get value for device from internal state."""
        value = self._state.get(_sanitise_device_name(device_name))

        _LOGGER.debug(
            msg="Getting component internal state value.",
            extra={
                "device_name": device_name,
                "value": value,
            },
        )
        if value is None:
            _LOGGER.warning(
                msg="Failed to find internal state value.",
                extra={
                    "device_name": device_name,
                    "value": value,
                    "payload": json.dumps(self._state, separators=(",", ":")),
                },
            )
        return value

    async def connect(self) -> bool:
        """Login to ComfortClick API."""
        body = {
            "UserName": self._username,
            "Password": self._password,
            "DeviceName": "",
            "OS": "",
            "PushToken": "",
            "RememberMe": False,
        }

        default_headers = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "en-US,en;q=0.9,et;q=0.8,ru;q=0.7,zh-CN;q=0.6,zh;q=0.5",
            "content-type": "application/json; charset=UTF-8",
        }

        login_url = f"{self._host}/Login"
        _LOGGER.info(msg="Connecting to API")

        async with self._session.post(
            login_url,
            json=body,
            headers=default_headers,
            timeout=REQUEST_TIMEOUT,
            ssl=False,
        ) as response:
            if response.status != HTTPStatus.OK:
                raise HttpStatusNotOkError(
                    {
                        "message": "Failed to login",
                        "status": response.status,
                        "text": await response.text(),
                    }
                )

            login_response = await response.json()
            if not isinstance(login_response, dict):
                raise ApiResponseError({"message": "Expected a login response object"})
            if login_response.get("Status") != "OK":
                raise AuthorizationError(
                    {
                        "message": "Login status not ok",
                        "status": login_response.get("Status"),
                    }
                )

            token_cookie = response.cookies.get("Token")
            if token_cookie is None or not token_cookie.value:
                raise AuthorizationError({"message": "Failed to get token from cookie"})

            token = token_cookie.value
            self._authorized_headers = {
                **default_headers,
                "Cookie": f"Token={token}; CurrentPath=",
            }
            self._session_generation += 1
            _LOGGER.info(msg="Connected to API")
        return True

    async def initialize_state(self) -> None:
        """Fetch a fresh snapshot for the current authenticated session."""
        data = await self._request_json("GetPanel", {"Path": ""})
        if not isinstance(data, dict) or not isinstance(data.get("ThemeObject"), dict):
            raise ApiResponseError({"message": "Snapshot has no theme object"})
        self._state = {
            _sanitise_device_name(item["DeviceName"]): item["Value"]
            for item in _require_updates(data["ThemeObject"], "ValueUpdates")
        }
        self._snapshot_generation = self._session_generation
        self._snapshot_pending = False

    async def poll(self) -> None:
        """Fetch updates, renewing a rejected session before one read retry."""
        path = f"GetClientData?_={int(time.time())}"
        data = await self._authenticated_request(path, retry_read=True)
        for item in _require_updates(data, "PropertyUpdates"):
            if item.get("PropertyName") == "Value":
                self._set_state_value(item.get("DeviceName"), item.get("Value"))

    async def disconnect(self) -> None:
        """Log out from ComfortClick API."""
        url = f"{self._host}/Logout"
        _LOGGER.info(msg="Disconnecting from API")

        async with self._session.get(
            url,
            headers=self._authorized_headers,
            timeout=REQUEST_TIMEOUT,
            ssl=False,
        ) as response:
            if response.status != HTTPStatus.OK:
                raise HttpStatusNotOkError(
                    {
                        "message": "Failed to log out",
                        "status": response.status,
                        "text": await response.text(),
                    }
                )


class HttpStatusNotOkError(Exception):
    """Raised when http request status is not 200."""


class AuthorizationError(Exception):
    """Raised when authorization fails."""


class ApiResponseError(Exception):
    """Raised when the server reports an error or returns malformed data."""

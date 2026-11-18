"""API object class."""

import asyncio
import json
import logging
import re
import time
import typing
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_read=25)
SESSION_RECOVERY_COOLDOWN = 30
DOORBELL_SOUND = "DoorBell2.mp3"
DOORBELL_HISTORY_SIZE = 128
_SCALAR_TYPES = {
    "System.Boolean": (bool,),
    "System.String": (str,),
    "System.Char": (str,),
    "System.Byte": (int,),
    "System.SByte": (int,),
    "System.Int16": (int,),
    "System.UInt16": (int,),
    "System.Int32": (int,),
    "System.UInt32": (int,),
    "System.Int64": (int,),
    "System.UInt64": (int,),
    "System.Single": (int, float),
    "System.Double": (int, float),
    "System.Decimal": (int, float),
}


def create_api_session() -> aiohttp.ClientSession:
    """Create an owned client that never reuses a controller TCP connection."""
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(force_close=True))


@dataclass(frozen=True, slots=True)
class DoorbellRing:
    """A confirmed doorbell sound action received in a live poll."""

    sound: str
    timestamp: str | None


def _parse_doorbell_ring(record: typing.Any) -> DoorbellRing | None:
    """Accept only the observed doorbell action and a safe optional timestamp."""
    if not isinstance(record, dict):
        return None
    action = record.get("Action")
    if (
        not isinstance(action, dict)
        or action.get("ActionName") != "PlaySound"
        or action.get("Sound") != DOORBELL_SOUND
    ):
        return None
    timestamp = record.get("Time")
    if timestamp is not None:
        if (
            not isinstance(timestamp, str)
            or re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})",
                timestamp,
                flags=re.ASCII,
            )
            is None
        ):
            return None
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        if parsed.utcoffset() is None:
            return None
    # Preserve the controller's seven-digit fractional precision for identity.
    return DoorbellRing(sound=DOORBELL_SOUND, timestamp=timestamp)


# Since keys contain \\ and python handles strings differently
def _sanitise_device_name(device_name: str) -> str:
    return device_name.replace("\\\\", "\\")


def _normalise_scalar_value(value: typing.Any) -> typing.Any:
    """Unwrap known JSON.NET scalars without coercing or decoding other objects."""
    if (
        not isinstance(value, dict)
        or value.keys() != {"$type", "$value"}
        or not isinstance(value["$type"], str)
    ):
        return value
    scalar_type = value["$type"].split(",", 1)[0].strip()
    scalar_value = value["$value"]
    # Exact types keep booleans distinct from integers, including False and zero.
    if type(scalar_value) in _SCALAR_TYPES.get(scalar_type, ()):
        return scalar_value
    return value


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
        verify_ssl: bool = False,
    ) -> None:
        """Wire up the Api Instance class with props from constructor."""
        self._username = username
        self._password = password
        self._host = host
        self._session = session
        self._verify_ssl = verify_ssl
        self._closed = False

        self._state: dict[str, typing.Any] = {}
        self._authorized_headers = None
        self._session_generation = 0
        self._snapshot_generation = -1
        self._snapshot_pending = False
        self._next_reconnect = 0.0
        self._reconnect_lock = asyncio.Lock()
        self._seen_doorbell_rings: deque[tuple[str, str]] = deque(
            maxlen=DOORBELL_HISTORY_SIZE
        )

    def _set_state_value(self, device_name: str, value: typing.Any) -> None:
        """Update or discover a component using the same normalized identity."""
        _LOGGER.debug(
            msg="Changing component internal state",
            extra={
                "device_name": device_name,
                "value": value,
            },
        )
        self._state[_sanitise_device_name(device_name)] = _normalise_scalar_value(value)

    async def _request_json(self, path: str, payload: typing.Any = None) -> typing.Any:
        """Make one authenticated request without retrying side effects."""
        if self._closed:
            raise ApiClosedError
        async with self._session.post(
            f"{self._host}/{path}",
            json=payload,
            headers=self._authorized_headers,
            timeout=REQUEST_TIMEOUT,
            ssl=self._verify_ssl,
            allow_redirects=False,
        ) as response:
            if response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                raise AuthorizationError({"status": response.status})
            if response.status != HTTPStatus.OK:
                raise HttpStatusNotOkError({"status": response.status})
            return _validate_result(await response.json())

    async def _recover_session(self, failed_generation: int) -> None:
        """Renew one rejected session even when several requests fail together."""
        async with self._reconnect_lock:
            if self._closed:
                raise ApiClosedError
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
            await self._login()
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
            "value": json.dumps(value, separators=(",", ":"), allow_nan=False),
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
        async with self._reconnect_lock:
            return await self._login()

    async def _login(self) -> bool:
        """Authenticate while holding the lifecycle lock."""
        if self._closed:
            raise ApiClosedError
        body = {
            "UserName": self._username,
            "Password": self._password,
            "DeviceName": "",
            "OS": "",
            "PushToken": "",
            "RememberMe": False,
        }

        default_headers = {
            "connection": "close",
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
            ssl=self._verify_ssl,
            allow_redirects=False,
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
            _sanitise_device_name(item["DeviceName"]): _normalise_scalar_value(
                item["Value"]
            )
            for item in _require_updates(data["ThemeObject"], "ValueUpdates")
        }
        self._snapshot_generation = self._session_generation
        self._snapshot_pending = False

    async def poll(self) -> tuple[DoorbellRing, ...]:
        """Apply state updates and return distinct doorbell rings from this poll."""
        path = f"GetClientData?_={int(time.time())}"
        data = await self._authenticated_request(path, retry_read=True)
        for item in _require_updates(data, "PropertyUpdates"):
            if item.get("PropertyName") == "Value":
                self._set_state_value(item.get("DeviceName"), item.get("Value"))
        actions = data.get("ActionData", [])
        if not isinstance(actions, list):
            return ()
        rings = []
        # Cache eviction during a large batch must not forget its known records.
        previously_seen = set(self._seen_doorbell_rings)
        batch_seen: set[tuple[str, str]] = set()
        for record in actions:
            ring = _parse_doorbell_ring(record)
            if ring is None:
                continue
            if ring.timestamp is not None:
                identity = (ring.timestamp, ring.sound)
                if identity in batch_seen:
                    continue
                batch_seen.add(identity)
                if identity in previously_seen:
                    continue
                self._seen_doorbell_rings.append(identity)
            rings.append(ring)
        return tuple(rings)

    async def disconnect(self) -> None:
        """Release the server session without closing Home Assistant's HTTP client."""
        self._closed = True
        async with self._reconnect_lock:
            await self._logout()

    async def _logout(self) -> None:
        """Forget and release the last token after any active login finishes."""
        headers = self._authorized_headers
        self._authorized_headers = None
        self._snapshot_pending = False
        self._snapshot_generation = -1
        if headers is None:
            return
        self._session_generation += 1
        url = f"{self._host}/Logout"
        _LOGGER.info(msg="Disconnecting from API")

        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                ssl=self._verify_ssl,
                allow_redirects=False,
            ) as response:
                if response.status not in (
                    HTTPStatus.OK,
                    HTTPStatus.UNAUTHORIZED,
                    HTTPStatus.FORBIDDEN,
                ):
                    _LOGGER.warning(
                        "Logout failed with HTTP status %s", response.status
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("Unable to log out from ComfortClick: %s", err)


class HttpStatusNotOkError(Exception):
    """Raised when http request status is not 200."""


class AuthorizationError(Exception):
    """Raised when authorization fails."""


class ApiResponseError(Exception):
    """Raised when the server reports an error or returns malformed data."""


class ApiClosedError(Exception):
    """Raised when a request outlives the integration's active session."""

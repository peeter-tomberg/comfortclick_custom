"""API object class."""

import json
import logging
import time
import typing
from http import HTTPStatus

import aiohttp

_LOGGER = logging.getLogger(__name__)


# Since keys contain \\ and python handles strings differently
def _sanitise_device_name(device_name: str) -> str:
    return device_name.replace("\\\\", "\\")


def _compare_device_names(a: str, b: str) -> bool:
    return _sanitise_device_name(a) == _sanitise_device_name(b)


class ApiInstance:
    """Class that handles communicating with ComfortClick API."""

    def __init__(self, username: str, password: str, host: str) -> None:
        """Wire up the Api Instance class with props from constructor."""
        self._username = username
        self._password = password
        self._host = host

        self._state = []
        self._authorized_headers = None

    def _set_state_value(self, device_name: str, value: typing.Any) -> None:
        """Update the internal state of a component."""
        _LOGGER.debug(
            msg="Changing component internal state",
            extra={
                "device_name": device_name,
                "value": value,
            },
        )
        for item in self._state:
            if _compare_device_names(item.get("DeviceName"), device_name):
                item["Value"] = value

    async def set_value(self, device_name: str, value: typing.Any) -> None:
        """Communicate with ComfortClick API."""
        payload = {
            "objectName": _sanitise_device_name(device_name),
            "valueName": "Value",
            "value": value,
        }
        url = f"{self._host}/SetValue"
        _LOGGER.debug(
            msg="Calling /SetValue in ComfortClick API",
            extra={
                "device_name": device_name,
                "value": value,
                "payload": json.dumps(payload, separators=(",", ":")),
            },
        )
        async with (
            aiohttp.ClientSession(headers=self._authorized_headers) as session,
            session.post(url, json=payload, ssl=False) as response,
        ):
            if response.status != HTTPStatus.OK:
                raise HttpStatusNotOkError(
                    {
                        "message": "Failed to set value",
                        "status": response.status,
                        "text": await response.text(),
                    }
                )
            result = await response.json()
            _LOGGER.debug(
                msg="Received /SetValue response from ComfortClick API",
                extra={
                    "device_name": device_name,
                    "value": value,
                    "payload": json.dumps(payload, separators=(",", ":")),
                },
            )
            return result

    def get_value(self, device_name: str) -> typing.Any:
        """Get value for device from internal state."""
        value = None
        for item in self._state:
            if _compare_device_names(item.get("DeviceName"), device_name):
                value = item.get("Value")

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

        async with (
            aiohttp.ClientSession(headers=default_headers) as session,
            session.post(login_url, json=body, ssl=False) as response,
        ):
            if response.status != HTTPStatus.OK:
                raise HttpStatusNotOkError(
                    {
                        "message": "Failed to login",
                        "status": response.status,
                        "text": await response.text(),
                    }
                )

            login_response = await response.json()
            if login_response.get("Status") != "OK":
                raise AuthorizationError(
                    {
                        "message": "Login status not ok",
                        "status": login_response.get("Status"),
                    }
                )

            token_header = response.headers.get("Set-Cookie")
            if not token_header:
                raise AuthorizationError({"message": "Failed to get token from cookie"})

            token = token_header.replace("Token=", "").split(";")[0]
            self._authorized_headers = {
                **default_headers,
                "Cookie": f"Token={token}; CurrentPath=",
            }
            _LOGGER.info(msg="Connected to API")
        return True

    async def initialize_state(self) -> None:
        """Fetch initial state from ComfortClick."""
        url = f"{self._host}/GetPanel"
        body = {"Path": ""}
        _LOGGER.info(msg="Getting initial state")

        async with (
            aiohttp.ClientSession(headers=self._authorized_headers) as session,
            session.post(url, json=body, ssl=False) as response,
        ):
            if response.status != HTTPStatus.OK:
                raise HttpStatusNotOkError(
                    {
                        "message": "Failed to get initial state",
                        "status": response.status,
                        "text": await response.text(),
                    }
                )

            data = await response.json()
            self._state = data.get("ThemeObject", {}).get("ValueUpdates", [])
            _LOGGER.debug(
                msg="Loaded initial state from ComfortClick API.",
                extra={
                    "payload": json.dumps(self._state, separators=(",", ":")),
                },
            )

    async def poll(self) -> None:
        """Poll data from ComfortClick."""
        url = f"{self._host}/GetClientData?_={int(time.time())}"
        async with (
            aiohttp.ClientSession(headers=self._authorized_headers) as session,
            session.post(url, ssl=False) as response,
        ):
            if response.status != HTTPStatus.OK:
                raise HttpStatusNotOkError(
                    {
                        "message": "Failed to poll",
                        "status": response.status,
                        "text": await response.text(),
                    }
                )

            response_data = await response.json()
            for item in response_data.get("PropertyUpdates", []):
                if item.get("PropertyName") == "Value":
                    self._set_state_value(item.get("DeviceName"), item.get("Value"))

    async def disconnect(self) -> None:
        """Log out from ComfortClick API."""
        url = f"{self._host}/Logout"
        _LOGGER.info(msg="Disconnecting from API")

        async with (
            aiohttp.ClientSession(headers=self._authorized_headers) as session,
            session.get(url, ssl=False) as response,
        ):
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

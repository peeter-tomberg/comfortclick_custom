import logging

import aiohttp
import typing
import time
import json

_LOGGER = logging.getLogger(__name__)

# Since keys contain \\ and python handles strings differently
def sanitise_device_name(device_name: str):
    return device_name.replace("\\\\", "\\")

def compare_device_names(a: str, b: str) -> bool:
    return sanitise_device_name(a) == sanitise_device_name(b)


class ApiInstance:
    def __init__(self, username: str, password: str, host: str) -> None:
        self._username = username
        self._password = password
        self._host = host

        self._state = []
        self._authorized_headers = None

    # Used for updating the internal state of a component
    def _set_state_value(self, device_name: str, value: typing.Any):
        _LOGGER.info(msg=f"Changing internal state {device_name} - {value}")
        for item in self._state:
            if compare_device_names(item.get("DeviceName"), device_name):
                item["Value"] = value

    # Used for communicating with ComfortClick API
    async def set_value(self, device_name: str, value: typing.Any):
        payload = {
            "objectName": sanitise_device_name(device_name),
            "valueName": "Value",
            "value": value
        }
        url = f"{self._host}/SetValue"
        _LOGGER.info(msg=f"Changing api state {device_name} - {value} - {json.dumps(payload, separators=(',', ':'))}")
        async with aiohttp.ClientSession(headers=self._authorized_headers) as session:
            async with session.post(url, json=payload, ssl=False) as response:
                if response.status != 200:
                    raise Exception(f"Failed to set value: {response.status} {await response.text()}")
                result = await response.json()
                _LOGGER.info(msg=f"Changed api state {device_name} - {value} - {json.dumps(result, separators=(',', ':'))}")
                return result


# Reads value from internal state
    def get_value(self, device_name: str):
        value = None
        for item in self._state:
            if compare_device_names(item.get("DeviceName"), device_name):
                value = item.get("Value")

        _LOGGER.info(msg=f"Getting value from internal state - {device_name} - {value}")
        if value is None:
            _LOGGER.info("------------------------ NOT FOUND ----------------------------")
            for item in self._state:
                _LOGGER.info(fr"{item.get("DeviceName")} - {item.get("Value")}")
            _LOGGER.info("------------------------ NOT FOUND ----------------------------")
        return value

    # Login to ComfortClick API, fetch initial state
    async def connect(self):
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

        async with aiohttp.ClientSession(headers=default_headers) as session:
            async with session.post(login_url, json=body, ssl=False) as response:
                if response.status != 200:
                    raise Exception(f"Failed to login: {response.status} {await response.text()}")

                login_response = await response.json()
                if login_response.get("Status") != "OK":
                    raise Exception(f"Login error: {login_response.get('Status')}")

                token_header = response.headers.get("Set-Cookie")
                if not token_header:
                    raise Exception("Failed to get token from cookie")

                token = token_header.replace("Token=", "").split(";")[0]
                self._authorized_headers = {
                    **default_headers,
                    "Cookie": f"Token={token}; CurrentPath=",
                }
                _LOGGER.info(msg="Connected to API")
        return True

    # Fetches the initial state of the integration
    async def initialize_state(self):
        url = f"{self._host}/GetPanel"
        body = {"Path": ""}
        _LOGGER.info(msg="Getting initial state")

        async with aiohttp.ClientSession(headers=self._authorized_headers) as session:
            async with session.post(url, json=body, ssl=False) as response:
                if response.status != 200:
                    raise Exception(f"Failed to initialize state: {response.status} {await response.text()}")
                data = await response.json()
                self._state = data.get("ThemeObject", {}).get("ValueUpdates", [])
                _LOGGER.info(f"Loaded initial state {json.dumps(self._state)}")

    # Poll function to listen to updates
    async def poll(self):
        url = f"{self._host}/GetClientData?_={int(time.time())}"
        async with aiohttp.ClientSession(headers=self._authorized_headers) as session:
            async with session.post(url, ssl=False) as response:
                if response.status != 200:
                    raise Exception(f"Polling failed: {response.status} {await response.text()}")

                response_data = await response.json()
                for item in response_data.get('PropertyUpdates', []):
                    if item.get('PropertyName') == "Value":
                        self._set_state_value(item.get('DeviceName'), item.get('Value'))

    # Logs you out
    async def disconnect(self):
        url = f"{self._host}/Logout"
        _LOGGER.info(msg="Disconnecting from API")

        async with aiohttp.ClientSession(headers=self._authorized_headers) as session:
            async with session.get(url, ssl=False) as response:
                if response.status != 200:
                    raise Exception(f"Failed to logout: {response.status} {await response.text()}")

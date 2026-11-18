"""SetValue follows the controller client's JSON string argument contract."""

import json
from typing import Any
from unittest.mock import MagicMock

import aiohttp
import pytest
from aiohttp import web

from custom_components.comfortclick_custom.api import ApiInstance, create_api_session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        (18.5, "18.5"),
        (0, "0"),
        (True, "true"),
        (False, "false"),
        (None, "null"),
        ("Home", '"Home"'),
        ("false", '"false"'),
        (r"Room\Target", r'"Room\\Target"'),
        ('"Home"', r'"\"Home\""'),
        ("Õhtu", r'"\u00d5htu"'),
        ("", '""'),
        ({"Mode": 1}, '{"Mode":1}'),
        ([1, False, "Home"], '[1,false,"Home"]'),
    ],
)
async def test_command_uses_json_string_and_poll_confirms_applied_value(
    value: Any, encoded: str
) -> None:
    commands = []
    applied_values = []

    async def controller(request: web.Request) -> web.Response:
        if request.path == "/GetClientData":
            return web.json_response(
                {
                    "PropertyUpdates": [
                        {
                            "DeviceName": r"Bedroom\Target",
                            "PropertyName": "Value",
                            "Value": applied_values[-1],
                        }
                    ]
                }
            )
        assert request.path == "/SetValue"
        assert request.content_type == "application/json"
        payload = await request.json()
        commands.append(payload)
        # The observed client sends JSON.stringify(value) inside the outer JSON.
        # Model the controller's rejection of a native, unencoded argument.
        if not isinstance(payload.get("value"), str):
            return web.Response(status=404)
        try:
            applied = json.loads(payload["value"])
        except json.JSONDecodeError:
            return web.Response(status=404)
        applied_values.append(applied)
        return web.json_response({"Success": True})

    application = web.Application()
    application.router.add_post("/{endpoint}", controller)
    runner = web.AppRunner(application)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        port = runner.addresses[0][1]
        async with create_api_session() as session:
            api = ApiInstance(
                "test-user",
                "test-password",
                f"http://127.0.0.1:{port}",
                session=session,
            )

            assert await api.set_value(r"Bedroom\\Target", value) == {"Success": True}
            await api.poll()

            assert api.get_value(r"Bedroom\Target") == value
            assert type(api.get_value(r"Bedroom\Target")) is type(value)
        assert commands == [
            {"objectName": r"Bedroom\Target", "valueName": "Value", "value": encoded}
        ]
        assert applied_values == [value]
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
async def test_nonfinite_command_value_is_rejected_without_a_request(
    value: float,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(ValueError, match="Out of range float values"):
        await api.set_value("Bedroom\\Target", value)

    session.post.assert_not_called()

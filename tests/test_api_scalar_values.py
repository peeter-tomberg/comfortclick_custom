"""Controller JSON.NET scalar values become native values at the cache boundary."""

from typing import Any
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.comfortclick_custom.api import (
    DOORBELL_SOUND,
    ApiInstance,
    DoorbellRing,
)

from .api_helpers import response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("type_name", "scalar"),
    [
        ("System.Double, System.Private.CoreLib", 370.604),
        ("System.Double, System.Private.CoreLib", 0),
        ("System.Double, mscorlib, Version=4.0.0.0", 0.0),
        ("System.Single", 21.5),
        ("System.Decimal", 0.283),
        ("System.Byte", 0),
        ("System.SByte", -1),
        ("System.Int16", -2),
        ("System.UInt16", 2),
        ("System.Int32, System.Private.CoreLib", 0),
        ("System.UInt32", 2),
        ("System.Int64", 15269),
        ("System.UInt64", 2),
        ("System.Boolean, System.Private.CoreLib", False),
        ("System.Boolean, System.Private.CoreLib", True),
        ("System.String, System.Private.CoreLib", "Home"),
        ("System.String", ""),
        ("System.Char", "A"),
    ],
)
async def test_snapshot_and_poll_unwrap_typed_scalars(
    type_name: str, scalar: Any
) -> None:
    wrapped = {"$type": type_name, "$value": scalar}
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(
            {
                "ThemeObject": {
                    "ValueUpdates": [{"DeviceName": "value", "Value": wrapped}]
                }
            }
        ),
        response(
            {
                "PropertyUpdates": [
                    {"DeviceName": "value", "PropertyName": "Value", "Value": wrapped}
                ]
            }
        ),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    await api.initialize_state()
    assert api.get_value("value") == scalar
    assert type(api.get_value("value")) is type(scalar)

    await api.poll()
    assert api.get_value("value") == scalar
    assert type(api.get_value("value")) is type(scalar)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        None,
        False,
        True,
        0,
        0.0,
        370.604,
        "",
        "Home",
        [],
        {},
        {"$type": "Unknown.Type", "$value": 1},
        {"$type": "System.Double"},
        {"$value": 1},
        {"$type": None, "$value": 1},
        {"$type": "System.Double", "$value": "370.604"},
        {"$type": "System.Double", "$value": False},
        {"$type": "System.Int32", "$value": 1.5},
        {"$type": "System.Boolean", "$value": 0},
        {"$type": "System.Boolean", "$value": "false"},
        {"$type": "System.String", "$value": 1},
        {"$type": "System.Double", "$value": {"$value": 1}},
        {"$type": "System.Double", "$value": [1]},
        {"$type": "System.Double", "$value": 1, "other": 2},
    ],
)
async def test_snapshot_and_poll_preserve_unrecognised_values(value: Any) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(
            {"ThemeObject": {"ValueUpdates": [{"DeviceName": "value", "Value": value}]}}
        ),
        response(
            {
                "PropertyUpdates": [
                    {"DeviceName": "value", "PropertyName": "Value", "Value": value}
                ]
            }
        ),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    await api.initialize_state()
    assert api.get_value("value") is value

    await api.poll()
    assert api.get_value("value") is value


@pytest.mark.asyncio
async def test_typed_value_transitions_do_not_disrupt_doorbell_events() -> None:
    timestamp = "2026-11-18T03:56:26.4511552+02:00"
    initial = [
        {"DeviceName": "meter", "Value": {"$type": "System.Double", "$value": 370.604}},
        {"DeviceName": "home", "Value": {"$type": "System.Boolean", "$value": False}},
    ]
    updates = [
        {
            "DeviceName": "meter",
            "PropertyName": "Value",
            "Value": {"$type": "System.Double", "$value": 371.0},
        },
        {
            "DeviceName": "home",
            "PropertyName": "Value",
            "Value": {"$type": "System.Boolean", "$value": True},
        },
    ]
    poll = {
        "PropertyUpdates": updates,
        "ActionData": [
            {
                "Action": {"ActionName": "PlaySound", "Sound": DOORBELL_SOUND},
                "Time": timestamp,
            }
        ],
    }
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response({"ThemeObject": {"ValueUpdates": initial}}),
        response(poll),
        response(poll),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.initialize_state()
    assert api.get_value("meter") == 370.604
    assert api.get_value("home") is False

    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, timestamp),)
    assert api.get_value("meter") == 371.0
    assert api.get_value("home") is True
    assert await api.poll() == ()

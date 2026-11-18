"""Device cache recovery through validated, normalized snapshots and deltas."""

from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.comfortclick_custom.api import ApiInstance, ApiResponseError

from .api_helpers import response


@pytest.mark.asyncio
async def test_device_missing_from_snapshot_recovers_when_update_arrives() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response({"ThemeObject": {"ValueUpdates": []}}),
        response(
            {
                "PropertyUpdates": [
                    {
                        "DeviceName": r"Apartment\Fan",
                        "PropertyName": "Value",
                        "Value": 1,
                    }
                ]
            }
        ),
        response(
            {
                "PropertyUpdates": [
                    {
                        "DeviceName": r"Apartment\\Fan",
                        "PropertyName": "Value",
                        "Value": 2,
                    }
                ]
            }
        ),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.initialize_state()
    assert api.get_value(r"Apartment\Fan") is None

    await api.poll()
    assert api.get_value(r"Apartment\\Fan") == 1
    await api.poll()
    assert api.get_value(r"Apartment\Fan") == 2
    assert api.get_value(r"Apartment\\Fan") == 2


@pytest.mark.asyncio
async def test_snapshot_normalizes_duplicate_identities_before_later_updates() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(
            {
                "ThemeObject": {
                    "ValueUpdates": [
                        {"DeviceName": r"Room\Sensor", "Value": 1},
                        {"DeviceName": r"Room\\Sensor", "Value": 2},
                    ]
                }
            }
        ),
        response(
            {
                "PropertyUpdates": [
                    {"DeviceName": r"Room\Sensor", "PropertyName": "Value", "Value": 3}
                ]
            }
        ),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.initialize_state()
    assert api.get_value(r"Room\Sensor") == 2

    await api.poll()

    assert api.get_value(r"Room\\Sensor") == 3


@pytest.mark.asyncio
async def test_malformed_replacement_snapshot_keeps_previous_cache() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(
            {"ThemeObject": {"ValueUpdates": [{"DeviceName": "sensor", "Value": 1}]}}
        ),
        response(
            {
                "ThemeObject": {
                    "ValueUpdates": [
                        {"DeviceName": "sensor", "Value": 2},
                        {"DeviceName": None, "Value": 3},
                    ]
                }
            }
        ),
        response(
            {
                "ThemeObject": {
                    "ValueUpdates": [{"DeviceName": "replacement", "Value": 0}]
                }
            }
        ),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.initialize_state()

    with pytest.raises(ApiResponseError):
        await api.initialize_state()
    assert api.get_value("sensor") == 1
    await api.initialize_state()
    assert api.get_value("sensor") is None
    assert api.get_value("replacement") == 0

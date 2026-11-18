"""Reject explicit server errors and malformed state without losing legacy replies."""

from typing import Any
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.comfortclick_custom.api import ApiInstance, ApiResponseError

from .api_helpers import response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"Status": "Error"},
        {"Status": "Failed"},
        {"Success": False},
        {"Error": "Cannot write"},
    ],
)
async def test_application_error_is_not_command_success(payload: dict) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(payload)
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(ApiResponseError):
        await api.set_value("door", value=True)

    session.post.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [None, True, {}, {"result": "legacy"}, {"Status": "OK"}]
)
async def test_statusless_and_legacy_command_replies_remain_valid(payload: Any) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(payload)
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert await api.set_value("door", value=True) == payload
    session.post.assert_called_once()


@pytest.mark.asyncio
async def test_explicit_auth_rejection_renews_session() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response({"Status": "Unauthorized"}),
        response({"Status": "OK"}, token="renewed"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response({}),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    await api.poll()

    assert session.post.call_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"PropertyUpdates": []}, {"Status": "OK"}])
async def test_empty_poll_preserves_state(payload: dict) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(
            {"ThemeObject": {"ValueUpdates": [{"DeviceName": "meter", "Value": 100}]}}
        ),
        response(payload),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.initialize_state()

    await api.poll()

    assert api.get_value("meter") == 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"PropertyUpdates": None},
        {"PropertyUpdates": {}},
        {
            "PropertyUpdates": [
                {"DeviceName": "meter", "PropertyName": "Value", "Value": 200},
                {"DeviceName": "meter", "PropertyName": "Value"},
            ]
        },
    ],
)
async def test_malformed_poll_preserves_entire_previous_state(payload: Any) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(
            {"ThemeObject": {"ValueUpdates": [{"DeviceName": "meter", "Value": 100}]}}
        ),
        response(payload),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.initialize_state()

    with pytest.raises(ApiResponseError):
        await api.poll()

    assert api.get_value("meter") == 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"ThemeObject": []},
        {"ThemeObject": {"ValueUpdates": [{"Value": 100}]}},
    ],
)
async def test_malformed_snapshot_is_rejected(payload: Any) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(payload)
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(ApiResponseError):
        await api.initialize_state()


@pytest.mark.asyncio
async def test_malformed_login_is_rejected() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response([], token="invalid")  # noqa: S106
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(ApiResponseError):
        await api.connect()

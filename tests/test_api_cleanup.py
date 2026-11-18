"""Lifecycle cleanup for temporary and configured ComfortClick sessions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components import comfortclick_custom as integration
from custom_components.comfortclick_custom import config_flow, connection
from custom_components.comfortclick_custom import coordinator as coordinator_module
from custom_components.comfortclick_custom.api import (
    ApiClosedError,
    ApiInstance,
    AuthorizationError,
)
from custom_components.comfortclick_custom.const import DOMAIN
from custom_components.comfortclick_custom.coordinator import ComfortClickCoordinator

from .api_helpers import response

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


@pytest.fixture
async def hass(tmp_path: Path) -> AsyncGenerator[HomeAssistant]:
    instance = HomeAssistant(str(tmp_path))
    try:
        yield instance
    finally:
        await instance.async_stop(force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, TimeoutError, aiohttp.ClientConnectionError])
async def test_disconnect_is_idempotent_and_does_not_close_shared_client(
    failure: type[Exception] | None,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="temporary")  # noqa: S106
    session.get.return_value = response()
    if failure:
        session.get.side_effect = failure
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.connect()

    await api.disconnect()
    await api.disconnect()

    session.get.assert_called_once()
    assert session.get.call_args.kwargs["headers"]["Cookie"].startswith(
        "Token=temporary;"
    )
    session.close.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_logout_still_forgets_token() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="temporary")  # noqa: S106
    session.get.side_effect = asyncio.CancelledError
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.connect()

    with pytest.raises(asyncio.CancelledError):
        await api.disconnect()
    await api.disconnect()

    session.get.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("login_ok", [True, False])
async def test_flow_validation_releases_temporary_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    login_ok: bool,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(
        {"Status": "OK" if login_ok else "Invalid"},
        token="temporary",  # noqa: S106
    )
    session.get.return_value = response()
    monkeypatch.setattr(connection, "create_api_session", lambda: session)
    data = {
        CONF_HOST: "https://controller.test",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "password",
    }
    hass = MagicMock(spec=HomeAssistant)

    if login_ok:
        assert await config_flow.validate_input(hass, data) == {
            "title": data[CONF_HOST]
        }
        session.get.assert_called_once()
    else:
        with pytest.raises(AuthorizationError):
            await config_flow.validate_input(hass, data)
        session.get.assert_not_called()
    session.close.assert_awaited_once()


@pytest.mark.parametrize("stage", ["login", "logout"])
@pytest.mark.parametrize("failure", [TimeoutError, asyncio.CancelledError])
async def test_validation_closes_owned_client_on_failure_or_cancellation(
    monkeypatch: pytest.MonkeyPatch, stage: str, failure: type[BaseException]
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="temporary")  # noqa: S106
    session.get.return_value = response()
    request = session.post if stage == "login" else session.get
    request.side_effect = failure
    monkeypatch.setattr(connection, "create_api_session", lambda: session)
    data = {
        CONF_HOST: "https://controller.test",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "password",
    }

    if stage == "logout" and failure is TimeoutError:
        assert await config_flow.validate_input(MagicMock(), data) == {
            "title": data[CONF_HOST]
        }
    else:
        with pytest.raises(failure):
            await config_flow.validate_input(MagicMock(), data)

    session.close.assert_awaited_once()


@pytest.mark.parametrize("failure", [None, TimeoutError, asyncio.CancelledError])
async def test_coordinator_shutdown_always_closes_owned_client_once(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    failure: type[BaseException] | None,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="active")  # noqa: S106
    session.get.return_value = response()
    session.get.side_effect = failure
    monkeypatch.setattr(coordinator_module, "create_api_session", lambda: session)
    listeners_before = hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STOP, 0)
    coordinator = ComfortClickCoordinator(
        hass, "https://controller.test", "user", "password"
    )
    await coordinator.api.connect()

    if failure is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await coordinator.async_shutdown()
    else:
        await coordinator.async_shutdown()
    await coordinator.async_shutdown()

    session.get.assert_called_once()
    session.close.assert_awaited_once()
    assert (
        hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STOP, 0) == listeners_before
    )


async def test_home_assistant_stop_closes_owned_client(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="active")  # noqa: S106
    session.get.return_value = response()
    monkeypatch.setattr(coordinator_module, "create_api_session", lambda: session)
    coordinator = ComfortClickCoordinator(
        hass, "https://controller.test", "user", "password"
    )
    await coordinator.api.connect()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    session.get.assert_called_once()
    session.close.assert_awaited_once()
    await coordinator.async_shutdown()
    session.close.assert_awaited_once()
    assert "Unable to remove unknown job listener" not in caplog.text


@pytest.mark.parametrize("stage", ["refresh", "platforms"])
async def test_failed_entry_setup_closes_owned_client(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response({"Status": "OK"}, token="active"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response({}),
    ]
    session.get.return_value = response()
    monkeypatch.setattr(coordinator_module, "create_api_session", lambda: session)
    coordinator = ComfortClickCoordinator(
        hass, "https://controller.test", "user", "password"
    )
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    entry.state = ConfigEntryState.SETUP_IN_PROGRESS
    entry.options = {}
    entry.data = {
        CONF_HOST: "https://controller.test",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "password",
    }
    coordinator.config_entry = entry
    monkeypatch.setattr(
        integration, "ComfortClickCoordinator", lambda *_args, **_kwargs: coordinator
    )
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(side_effect=TimeoutError)
    if stage == "refresh":
        session.post.side_effect = TimeoutError

    expected = ConfigEntryNotReady if stage == "refresh" else TimeoutError
    with pytest.raises(expected):
        await integration.async_setup_entry(hass, entry)

    session.close.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_successful_unload_closes_owned_client_and_removes_stop_listener(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    monkeypatch.setattr(coordinator_module, "create_api_session", lambda: session)
    coordinator = ComfortClickCoordinator(
        hass, "https://controller.test", "user", "password"
    )
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    cancel_listener = MagicMock()
    hass.data[DOMAIN] = {
        entry.entry_id: integration.RuntimeData(coordinator, cancel_listener)
    }
    hass.config_entries = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    assert await integration.async_unload_entry(hass, entry)

    session.close.assert_awaited_once()
    cancel_listener.assert_called_once()
    assert hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STOP, 0) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["refresh", "platforms"])
async def test_failed_setup_stops_coordinator_and_clears_runtime(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    entry.options = {}
    entry.data = {
        CONF_HOST: "https://controller.test",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "password",
    }
    coordinator = MagicMock(spec=ComfortClickCoordinator)
    monkeypatch.setattr(
        integration, "ComfortClickCoordinator", lambda *_args, **_kwargs: coordinator
    )
    if stage == "refresh":
        coordinator.async_config_entry_first_refresh.side_effect = TimeoutError
    else:
        hass.config_entries.async_forward_entry_setups.side_effect = TimeoutError

    with pytest.raises(TimeoutError):
        await integration.async_setup_entry(hass, entry)

    coordinator.async_shutdown.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]
    if stage == "platforms":
        entry.add_update_listener.return_value.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("unload_ok", [True, False])
async def test_only_successful_unload_shuts_down_active_session(
    *,
    unload_ok: bool,
) -> None:
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=unload_ok)
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    coordinator = MagicMock(spec=ComfortClickCoordinator)
    cancel_listener = MagicMock()
    runtime = integration.RuntimeData(coordinator, cancel_listener)
    hass.data = {DOMAIN: {entry.entry_id: runtime}}

    assert await integration.async_unload_entry(hass, entry) is unload_ok

    if unload_ok:
        coordinator.async_shutdown.assert_awaited_once()
        cancel_listener.assert_called_once()
        assert entry.entry_id not in hass.data[DOMAIN]
    else:
        coordinator.async_shutdown.assert_not_awaited()
        cancel_listener.assert_not_called()
        assert hass.data[DOMAIN][entry.entry_id] is runtime


@pytest.mark.asyncio
async def test_delayed_rejected_poll_cannot_reopen_closed_session() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    poll_started = asyncio.Event()
    release_poll = asyncio.Event()
    rejected = response(status=401)

    async def receive_poll() -> MagicMock:
        poll_started.set()
        await release_poll.wait()
        return rejected

    rejected.__aenter__.side_effect = receive_poll
    session.post.side_effect = [response({"Status": "OK"}, token="active"), rejected]  # noqa: S106
    session.get.return_value = response()
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    await api.connect()
    polling = asyncio.create_task(api.poll())
    await poll_started.wait()

    await api.disconnect()
    release_poll.set()
    with pytest.raises(ApiClosedError):
        await polling

    assert session.post.call_count == 2
    session.get.assert_called_once()


@pytest.mark.asyncio
async def test_pending_renewal_token_is_logged_out_when_closed() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    login_started = asyncio.Event()
    release_login = asyncio.Event()
    login = response(token="renewed")  # noqa: S106

    async def receive_login() -> dict:
        login_started.set()
        await release_login.wait()
        return {"Status": "OK"}

    login.json.side_effect = receive_login
    session.post.side_effect = [response(status=401), login]
    session.get.return_value = response()
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    polling = asyncio.create_task(api.poll())
    await login_started.wait()
    closing = asyncio.create_task(api.disconnect())
    await asyncio.sleep(0)
    release_login.set()

    with pytest.raises(ApiClosedError):
        await polling
    await closing

    assert session.post.call_count == 2
    session.get.assert_called_once()
    assert session.get.call_args.kwargs["headers"]["Cookie"].startswith(
        "Token=renewed;"
    )

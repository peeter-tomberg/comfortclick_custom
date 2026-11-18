"""Opt-in TLS verification preserves compatibility and explicit preferences."""

import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, call

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant

from custom_components import comfortclick_custom as integration
from custom_components.comfortclick_custom import (
    config_flow,
    connection,
)
from custom_components.comfortclick_custom import (
    coordinator as coordinator_module,
)
from custom_components.comfortclick_custom.api import ApiInstance
from custom_components.comfortclick_custom.coordinator import ComfortClickCoordinator

from .api_helpers import response


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [{}, {"verify_ssl": False}, {"verify_ssl": True}])
async def test_verification_setting_applies_to_every_request(settings: dict) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response({"Status": "OK"}, token="session"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response({"PropertyUpdates": []}),
        response({"Status": "OK"}),
    ]
    session.get.return_value = response()
    api = ApiInstance(
        "user", "password", "https://controller.test", session=session, **settings
    )

    await api.connect()
    await api.initialize_state()
    await api.poll()
    await api.set_value("device", value=True)
    await api.disconnect()

    for request in [*session.post.call_args_list, *session.get.call_args_list]:
        assert request.kwargs["ssl"] is settings.get("verify_ssl", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [{}, {"verify_ssl": True}])
async def test_coordinator_default_and_explicit_verification_reach_api(
    monkeypatch: pytest.MonkeyPatch,
    settings: dict,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="session")  # noqa: S106
    session.get.return_value = response()
    monkeypatch.setattr(coordinator_module, "create_api_session", lambda: session)
    hass = MagicMock(spec=HomeAssistant)
    hass.loop = asyncio.get_running_loop()
    hass.bus = MagicMock()
    coordinator = ComfortClickCoordinator(
        hass, "https://controller.test", "user", "password", **settings
    )

    await coordinator.api.connect()
    await coordinator.async_shutdown()

    assert session.post.call_args.kwargs["ssl"] is settings.get("verify_ssl", False)
    assert session.get.call_args.kwargs["ssl"] is settings.get("verify_ssl", False)


@pytest.mark.asyncio
async def test_validation_without_saved_preference_leaves_verification_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="session")  # noqa: S106
    session.get.return_value = response()
    monkeypatch.setattr(connection, "create_api_session", lambda: session)

    await config_flow.validate_input(
        MagicMock(spec=HomeAssistant),
        {
            CONF_HOST: "https://controller.test",
            CONF_USERNAME: "user",
            CONF_PASSWORD: "password",
        },
    )

    assert session.post.call_args.kwargs["ssl"] is False
    assert session.get.call_args.kwargs["ssl"] is False


@pytest.mark.asyncio
async def test_certificate_failure_has_actionable_form_error_and_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = aiohttp.ClientConnectorCertificateError(
        MagicMock(), ssl.SSLCertVerificationError("self-signed certificate")
    )
    monkeypatch.setattr(connection, "create_api_session", lambda: session)
    flow = config_flow.ConfigFlow()
    flow.hass = MagicMock(spec=HomeAssistant)

    result = await flow.async_step_user(
        {
            CONF_HOST: "https://controller.test",
            CONF_USERNAME: "user",
            CONF_PASSWORD: "password",
            CONF_VERIFY_SSL: True,
        }
    )

    assert result["errors"] == {"base": "ssl_error"}
    session.post.assert_called_once()
    assert session.post.call_args.kwargs["ssl"] is True


@pytest.mark.asyncio
async def test_setup_form_defaults_off_and_saves_explicit_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = config_flow.ConfigFlow()
    flow.hass = MagicMock(spec=HomeAssistant)
    form = await flow.async_step_user()
    data = {
        CONF_HOST: "https://controller.test",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "password",
    }
    assert form["data_schema"](data)[CONF_VERIFY_SSL] is False
    validate = AsyncMock(return_value={"title": "Controller"})
    monkeypatch.setattr(config_flow, "validate_input", validate)

    result = await flow.async_step_user({**data, CONF_VERIFY_SSL: True})

    assert result["data"][CONF_VERIFY_SSL] is True
    assert validate.call_args.args[1][CONF_VERIFY_SSL] is True


@pytest.mark.asyncio
async def test_options_can_enable_verification_without_connecting() -> None:
    entry = MagicMock(spec=ConfigEntry)
    entry.data = {
        CONF_HOST: "https://controller.test",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "password",
    }
    entry.options = {"unrelated": "preserve"}
    entry.state = ConfigEntryState.LOADED
    entry.update_listeners = []
    flow = config_flow.ConfigFlow.async_get_options_flow(entry)
    flow.hass = MagicMock(spec=HomeAssistant)
    flow.hass.config_entries = MagicMock()
    form = await flow.async_step_connection()
    assert form["data_schema"]({})[CONF_VERIFY_SSL] is False

    result = await flow.async_step_connection({CONF_VERIFY_SSL: True})

    assert result["type"] == "menu"
    assert result["step_id"] == "init"
    assert flow.hass.config_entries.async_update_entry.call_args.kwargs["options"] == {
        "unrelated": "preserve",
        CONF_VERIFY_SSL: True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data_settings", "options"),
    [({CONF_VERIFY_SSL: True}, {}), ({}, {CONF_VERIFY_SSL: True})],
)
async def test_options_form_preserves_saved_verification(
    data_settings: dict, options: dict
) -> None:
    entry = MagicMock(spec=ConfigEntry)
    entry.data = data_settings
    entry.options = options
    flow = config_flow.ConfigFlow.async_get_options_flow(entry)

    form = await flow.async_step_connection()

    assert form["data_schema"]({})[CONF_VERIFY_SSL] is True


@pytest.mark.asyncio
async def test_failed_setup_is_reloaded_after_saving_certificate_exception() -> None:
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    entry.data = {
        CONF_HOST: "https://controller.test",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "password",
    }
    entry.options = {CONF_VERIFY_SSL: True}
    entry.state = ConfigEntryState.SETUP_RETRY
    entry.update_listeners = []
    flow = config_flow.ConfigFlow.async_get_options_flow(entry)
    flow.hass = MagicMock(spec=HomeAssistant)
    flow.hass.config_entries = MagicMock()

    result = await flow.async_step_connection({CONF_VERIFY_SSL: False})

    assert result["type"] == "menu"
    assert result["step_id"] == "init"
    assert flow.hass.config_entries.mock_calls == [
        call.async_update_entry(
            entry,
            data={**entry.data, CONF_VERIFY_SSL: False},
            options={CONF_VERIFY_SSL: False},
        ),
        call.async_schedule_reload(entry.entry_id),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data_settings", "options", "expected"),
    [
        ({}, {}, False),
        ({CONF_VERIFY_SSL: True}, {}, True),
        ({CONF_VERIFY_SSL: False}, {}, False),
        ({CONF_VERIFY_SSL: True}, {CONF_VERIFY_SSL: False}, False),
        ({CONF_VERIFY_SSL: False}, {CONF_VERIFY_SSL: True}, True),
    ],
)
async def test_entry_setup_uses_saved_preference_and_off_legacy_default(
    monkeypatch: pytest.MonkeyPatch,
    data_settings: dict,
    options: dict,
    *,
    expected: bool,
) -> None:
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    entry.data = {
        CONF_HOST: "https://controller.test",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "password",
        **data_settings,
    }
    entry.options = options
    factory = MagicMock(return_value=MagicMock(spec=ComfortClickCoordinator))
    monkeypatch.setattr(integration, "ComfortClickCoordinator", factory)

    assert await integration.async_setup_entry(hass, entry)

    assert factory.call_args.kwargs["verify_ssl"] is expected

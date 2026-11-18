"""Connection forms protect credentials and save validated settings atomically."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import MappingProxyType
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import selector

from custom_components import comfortclick_custom as integration
from custom_components.comfortclick_custom import config_flow, connection, options_flow
from custom_components.comfortclick_custom.api import (
    AuthorizationError,
    HttpStatusNotOkError,
)
from custom_components.comfortclick_custom.const import DOMAIN
from custom_components.comfortclick_custom.migration import empty_mapping_options

from .api_helpers import response

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path
    from typing import Any

SETTINGS = {
    CONF_HOST: "https://controller.test",
    CONF_USERNAME: "current-user",
    CONF_PASSWORD: "saved-test-password",
    CONF_VERIFY_SSL: False,
}


@pytest.fixture
async def hass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[HomeAssistant]:
    instance = HomeAssistant(str(tmp_path))
    instance.config_entries = ConfigEntries(instance, {})
    monkeypatch.setattr(
        instance.config_entries, "async_setup", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        instance.config_entries, "async_reload", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        config_entries,
        "_async_get_flow_handler",
        AsyncMock(return_value=config_flow.ConfigFlow),
    )
    try:
        yield instance
    finally:
        await instance.async_stop(force=True)


@pytest.fixture
async def entry(hass: HomeAssistant) -> AsyncGenerator[ConfigEntry]:
    instance = ConfigEntry(
        data={**SETTINGS, "unrelated_data": "keep"},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options={
            **empty_mapping_options(),
            CONF_VERIFY_SSL: False,
            "unrelated_option": [1],
        },
        source=config_entries.SOURCE_USER,
        state=ConfigEntryState.LOADED,
        title="Controller",
        unique_id="connection-test",
        version=2,
    )
    await hass.config_entries.async_add(instance)
    remove = instance.add_update_listener(integration._async_update_listener)  # noqa: SLF001
    try:
        yield instance
    finally:
        remove()


async def open_connection(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    return await manager.async_configure(
        result["flow_id"], {"next_step_id": "connection"}
    )


def assert_empty_password(form: dict[str, Any]) -> None:
    marker, field = next(
        (marker, field)
        for marker, field in form["data_schema"].schema.items()
        if marker.schema == CONF_PASSWORD
    )
    assert marker.default is vol.UNDEFINED
    assert not marker.description or "suggested_value" not in marker.description
    assert isinstance(field, selector.TextSelector)
    assert field.config["type"] == selector.TextSelectorType.PASSWORD
    assert SETTINGS[CONF_PASSWORD] not in repr(form)


async def test_initial_form_has_no_example_credentials_and_creates_empty_v2_options(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = config_flow.ConfigFlow()
    flow.hass = hass
    form = await flow.async_step_user()
    assert_empty_password(form)
    for marker in form["data_schema"].schema:
        if marker.schema in (CONF_HOST, CONF_USERNAME):
            assert marker.default is vol.UNDEFINED
            assert not marker.description
    monkeypatch.setattr(
        config_flow, "validate_input", AsyncMock(return_value={"title": "Controller"})
    )
    result = await flow.async_step_user(SETTINGS)
    assert result["version"] == 2
    assert result["data"] == SETTINGS
    assert result["options"] == {**empty_mapping_options(), CONF_VERIFY_SSL: False}


@pytest.mark.parametrize("replacement", [None, "", "new-test-password"])
async def test_changed_connection_validates_and_saves_once_without_losing_mappings(
    hass: HomeAssistant,
    entry: ConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str | None,
) -> None:
    form = await open_connection(hass, entry)
    assert_empty_password(form)
    old_options = deepcopy(dict(entry.options))
    validate = AsyncMock(return_value={"title": "New controller"})
    monkeypatch.setattr(options_flow, "validate_input", validate)
    submitted = {
        CONF_HOST: "http://other-controller.test/base/",
        CONF_USERNAME: "new-user",
        CONF_VERIFY_SSL: True,
    }
    if replacement is not None:
        submitted[CONF_PASSWORD] = replacement
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], submitted
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["flow_id"] == form["flow_id"]
    assert any(
        item["flow_id"] == form["flow_id"]
        for item in hass.config_entries.options.async_progress()
    )
    assert entry.data[CONF_HOST] == "http://other-controller.test/base"
    assert entry.data[CONF_USERNAME] == "new-user"
    assert entry.data[CONF_PASSWORD] == (replacement or SETTINGS[CONF_PASSWORD])
    assert entry.data["unrelated_data"] == "keep"
    assert dict(entry.options) == {**old_options, CONF_VERIFY_SSL: True}
    validate.assert_awaited_once_with(hass, {key: entry.data[key] for key in SETTINGS})
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


async def test_offline_tls_only_change_skips_login_and_unchanged_save_skips_reload(
    hass: HomeAssistant, entry: ConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    validate = AsyncMock(side_effect=AssertionError("TLS-only edits must work offline"))
    monkeypatch.setattr(options_flow, "validate_input", validate)
    form = await open_connection(hass, entry)
    await hass.config_entries.options.async_configure(
        form["flow_id"], {CONF_VERIFY_SSL: True}
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_VERIFY_SSL] is True
    assert entry.data[CONF_PASSWORD] == SETTINGS[CONF_PASSWORD]
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
    hass.config_entries.async_reload.reset_mock()

    form = await hass.config_entries.options.async_configure(
        form["flow_id"], {"next_step_id": "connection"}
    )
    await hass.config_entries.options.async_configure(
        form["flow_id"], {CONF_VERIFY_SSL: True}
    )
    await hass.async_block_till_done()
    validate.assert_not_awaited()
    hass.config_entries.async_reload.assert_not_awaited()


async def test_connection_can_be_changed_twice_and_closed_without_extra_save(
    hass: HomeAssistant, entry: ConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    validate = AsyncMock(return_value={"title": "Controller"})
    monkeypatch.setattr(options_flow, "validate_input", validate)
    manager = hass.config_entries.options
    form = await open_connection(hass, entry)
    flow_id = form["flow_id"]
    await manager.async_configure(
        flow_id,
        {
            CONF_USERNAME: "first-user",
            CONF_PASSWORD: "replacement-password",
        },
    )
    form = await manager.async_configure(flow_id, {"next_step_id": "connection"})
    assert_empty_password(form)
    assert "replacement-password" not in repr(form)
    assert form["data_schema"]({})[CONF_USERNAME] == "first-user"
    result = await manager.async_configure(
        flow_id, {CONF_USERNAME: "second-user", CONF_PASSWORD: ""}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.MENU
    assert result["flow_id"] == flow_id
    assert entry.data[CONF_USERNAME] == "second-user"
    assert entry.data[CONF_PASSWORD] == "replacement-password"
    assert validate.await_count == 2
    assert hass.config_entries.async_reload.await_count == 2
    done = await manager.async_configure(flow_id, {"next_step_id": "done"})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"] is None
    await hass.async_block_till_done()
    assert hass.config_entries.async_reload.await_count == 2


@pytest.mark.parametrize(
    "case",
    [
        (AuthorizationError(), "invalid_auth"),
        (TimeoutError(), "cannot_connect"),
        (
            HttpStatusNotOkError({"status": 401, "text": "saved-test-password"}),
            "invalid_auth",
        ),
        (RuntimeError("saved-test-password"), "unknown"),
    ],
)
async def test_failed_validation_is_atomic_and_never_echoes_password(
    hass: HomeAssistant,
    entry: ConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: tuple[Exception, str],
) -> None:
    failure, expected = case
    before_data, before_options = (
        deepcopy(dict(entry.data)),
        deepcopy(dict(entry.options)),
    )
    monkeypatch.setattr(options_flow, "validate_input", AsyncMock(side_effect=failure))
    form = await open_connection(hass, entry)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            CONF_USERNAME: "changed-user",
            CONF_PASSWORD: "replacement-secret",
            CONF_VERIFY_SSL: True,
        },
    )
    await hass.async_block_till_done()
    assert result["errors"] == {"base": expected}
    assert_empty_password(result)
    assert "replacement-secret" not in repr(result)
    assert SETTINGS[CONF_PASSWORD] not in caplog.text
    assert dict(entry.data) == before_data
    assert dict(entry.options) == before_options
    hass.config_entries.async_reload.assert_not_awaited()


async def test_concurrent_connection_changes_abort_and_mapping_changes_are_retained(
    hass: HomeAssistant, entry: ConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    form = await open_connection(hass, entry)

    async def change_mapping(_hass: HomeAssistant, _data: dict) -> dict:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "fans": [{"unique_id": "new-fan"}]}
        )
        return {"title": "Controller"}

    monkeypatch.setattr(options_flow, "validate_input", change_mapping)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {CONF_USERNAME: "changed-user"}
    )
    assert result["type"] is FlowResultType.MENU
    assert entry.options["fans"] == [{"unique_id": "new-fan"}]
    assert entry.data[CONF_USERNAME] == "changed-user"

    form = await open_connection(hass, entry)

    async def change_connection(_hass: HomeAssistant, _data: dict) -> dict:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_PASSWORD: "concurrent-password"}
        )
        return {"title": "Controller"}

    monkeypatch.setattr(options_flow, "validate_input", change_connection)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {CONF_USERNAME: "stale-user"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "connection_changed"
    assert entry.data[CONF_USERNAME] == "changed-user"
    assert entry.data[CONF_PASSWORD] == "concurrent-password"


@pytest.mark.parametrize(
    "host",
    [
        "",
        "controller.test",
        "ftp://controller.test",
        "https:///missing",
        "https://user:secret@controller.test",
        "https://controller.test?token=secret",
        "https://controller.test/#secret",
        "https://controller.test:bad",
        "https://controller.test:99999",
    ],
)
async def test_invalid_url_rejected_before_opening_a_client(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    create = MagicMock(side_effect=AssertionError("No network client for invalid URL"))
    monkeypatch.setattr(connection, "create_api_session", create)
    with pytest.raises(connection.InvalidHost):
        await connection.validate_input(MagicMock(), {**SETTINGS, CONF_HOST: host})
    create.assert_not_called()


async def test_validation_uses_only_login_logout_and_closes_its_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="validation-session")  # noqa: S106
    session.get.return_value = response()
    monkeypatch.setattr(connection, "create_api_session", lambda: session)
    result = await connection.validate_input(
        MagicMock(), {**SETTINGS, CONF_HOST: "http://controller.test/base/"}
    )
    assert result == {"title": "http://controller.test/base"}
    assert [call.args[0] for call in session.post.call_args_list] == [
        "http://controller.test/base/Login"
    ]
    assert [call.args[0] for call in session.get.call_args_list] == [
        "http://controller.test/base/Logout"
    ]
    session.close.assert_awaited_once()


async def test_cancelled_validation_never_saves_configuration(
    hass: HomeAssistant, entry: ConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    form = await open_connection(hass, entry)
    before = deepcopy(dict(entry.data))
    monkeypatch.setattr(
        options_flow, "validate_input", AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await hass.config_entries.options.async_configure(
            form["flow_id"], {CONF_USERNAME: "changed-user"}
        )
    assert dict(entry.data) == before

"""Configuration assets and sidebar registration remain limited and idempotent."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant import config_entries
from homeassistant.components.config.config_entries import OptionManagerFlowResourceView
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components import comfortclick_custom as integration
from custom_components.comfortclick_custom import panel
from custom_components.comfortclick_custom.config_flow import ConfigFlow
from custom_components.comfortclick_custom.const import DOMAIN
from custom_components.comfortclick_custom.migration import empty_mapping_options


@pytest.fixture
def hass() -> MagicMock:
    instance = MagicMock(spec=HomeAssistant)
    instance.data = {}
    instance.http = MagicMock()
    instance.http.async_register_static_paths = AsyncMock()
    return instance


async def test_concurrent_setup_registers_only_two_assets_and_one_admin_panel(
    hass: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    register = AsyncMock()
    monkeypatch.setattr(panel, "async_register_panel", register)

    await asyncio.gather(*(integration.async_setup(hass, {}) for _ in range(3)))

    hass.http.async_register_static_paths.assert_awaited_once()
    paths = hass.http.async_register_static_paths.call_args.args[0]
    assert [item.url_path for item in paths] == [
        "/comfortclick_custom/configuration.js",
        "/comfortclick_custom/strings.json",
    ]
    assert all(Path(item.path).is_file() for item in paths)
    assert not any(item.cache_headers for item in paths)
    register.assert_awaited_once_with(
        hass,
        frontend_url_path="comfortclick-config",
        webcomponent_name="comfortclick-configuration",
        sidebar_title="ComfortClick",
        sidebar_icon="mdi:tune-variant",
        module_url="/comfortclick_custom/configuration.js",
        config={"strings_url": "/comfortclick_custom/strings.json"},
        require_admin=True,
    )


async def test_panel_retry_does_not_duplicate_already_registered_static_routes(
    hass: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    register = AsyncMock(side_effect=[RuntimeError, None])
    monkeypatch.setattr(panel, "async_register_panel", register)

    with pytest.raises(RuntimeError):
        await integration.async_setup(hass, {})
    assert await integration.async_setup(hass, {})

    assert register.await_count == 2
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_failed_asset_registration_can_retry_without_registering_a_panel(
    hass: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    register = AsyncMock()
    monkeypatch.setattr(panel, "async_register_panel", register)
    hass.http.async_register_static_paths.side_effect = [
        OSError("Asset unavailable"),
        None,
    ]

    with pytest.raises(OSError, match="Asset unavailable"):
        await integration.async_setup(hass, {})
    register.assert_not_awaited()
    assert await integration.async_setup(hass, {})
    register.assert_awaited_once()


async def test_real_options_flow_serialization_matches_frontend_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = HomeAssistant(str(tmp_path))
    instance.config_entries = ConfigEntries(instance, {})
    monkeypatch.setattr(instance.config_entries, "async_setup", AsyncMock())
    monkeypatch.setattr(
        config_entries, "_async_get_flow_handler", AsyncMock(return_value=ConfigFlow)
    )
    options = empty_mapping_options()
    options["thermostats"] = [{"name": "Living room", "heating_id": "heat"}]
    entry = ConfigEntry(
        data={"password": "must-not-be-exposed"},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options=options,
        source=config_entries.SOURCE_USER,
        title="Controller",
        unique_id="panel-test",
        version=2,
    )
    try:
        await instance.config_entries.async_add(entry)
        manager = instance.config_entries.options
        view = OptionManagerFlowResourceView(manager)
        root = await manager.async_init(entry.entry_id)
        result = await manager.async_configure(
            root["flow_id"], {"next_step_id": "thermostats"}
        )
        serialized = view._prepare_result_json(result)  # noqa: SLF001
        assert isinstance(serialized["menu_options"], dict)
        action = next(
            key for key in serialized["menu_options"] if key.startswith("edit_")
        )
        assert serialized["menu_options"][action] == "Living room"
        assert serialized["data_schema"][0]["type"] == "select"
        assert (action, "Living room") in serialized["data_schema"][0]["options"]

        form = await manager.async_configure(root["flow_id"], {"next_step_id": action})
        schema = {
            field["name"]: field
            for field in view._prepare_result_json(form)["data_schema"]  # noqa: SLF001
        }
        assert schema["name"]["type"] == "string"
        assert schema["name"]["description"]["suggested_value"] == "Living room"
        assert "area" in schema["area_id"]["selector"]
        assert schema["heating_id"]["selector"]["select"]["custom_value"]
        assert schema["min_temp"]["selector"]["number"]["step"] == "any"

        manager.async_abort(root["flow_id"])
        root = await manager.async_init(entry.entry_id)
        form = await manager.async_configure(
            root["flow_id"], {"next_step_id": "connection"}
        )
        schema = {
            field["name"]: field
            for field in view._prepare_result_json(form)["data_schema"]  # noqa: SLF001
        }
        assert schema["password"]["selector"]["text"]["type"] == "password"
        assert "default" not in schema["password"]
        assert "description" not in schema["password"]
        assert schema["verify_ssl"]["type"] == "boolean"
        manager.async_abort(root["flow_id"])
    finally:
        await instance.async_stop(force=True)

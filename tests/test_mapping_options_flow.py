"""Exercise entity mapping options through the real Home Assistant flow class."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components import comfortclick_custom as integration
from custom_components.comfortclick_custom import config_flow, options_flow
from custom_components.comfortclick_custom.api import ApiInstance
from custom_components.comfortclick_custom.const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from homeassistant.helpers.selector import SelectSelector

FAN = {
    "name": "Bedroom fan",
    "lock_id": "Bedroom\\FanLock",
    "fan_id": "Bedroom\\FanSpeed",
    "heating_id": "Bedroom\\Heating",
    "current_temperature_id": "Bedroom\\Temperature",
    "target_temperature_id": "Bedroom\\Target",
}
THERMOSTAT = {
    "name": "Living room AC",
    "heating_id": "Living room\\Heating",
    "fan_id": "Living room\\FanSpeed",
    "current_temperature_id": "Living room\\Temperature",
    "target_temperature_id": "Living room\\Target",
    "min_temp": 18,
    "max_temp": 24,
    "target_temperature_step": 0.5,
}
UTILITY = {"name": "Heating total", "id": "Meters\\Heating", "type": "heating"}
MAPPINGS = {"fans": FAN, "thermostats": THERMOSTAT, "utilities": UTILITY}
FORM_STEPS = {"fans": "fan", "thermostats": "thermostat", "utilities": "utility"}
PRIMARY_PATHS = {"fans": "fan_id", "thermostats": "heating_id", "utilities": "id"}
LEGACY_IDENTITIES = {
    "fans": FAN["fan_id"],
    "thermostats": f"room-1-{THERMOSTAT['heating_id']}",
    "utilities": UTILITY["id"],
}
CACHED_PATHS = ("Cached\\First", "Cached\\Second")


@dataclass
class FlowContext:
    flow: options_flow.OptionsFlow
    entry: MagicMock
    hass: MagicMock
    api: MagicMock
    read_yaml: AsyncMock


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> FlowContext:
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-controller"
    entry.data = {}
    entry.options = {CONF_VERIFY_SSL: True, "unrelated": {"keep": [1]}}
    entry.state = ConfigEntryState.LOADED
    api = MagicMock(spec=ApiInstance)
    api.get_device_paths.return_value = CACHED_PATHS
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {
        DOMAIN: {
            entry.entry_id: SimpleNamespace(coordinator=SimpleNamespace(api=api)),
        },
    }
    hass.config_entries = MagicMock()
    reader = AsyncMock(
        return_value={key: [deepcopy(value)] for key, value in MAPPINGS.items()}
    )
    monkeypatch.setattr(options_flow, "read_yaml", reader)
    flow = config_flow.ConfigFlow.async_get_options_flow(entry)
    flow.hass = hass
    return FlowContext(flow, entry, hass, api, reader)


async def open_section(context: FlowContext, section: str) -> dict[str, Any]:
    return await getattr(context.flow, f"async_step_{section}")()


async def submit(
    context: FlowContext, section: str, values: dict[str, Any]
) -> dict[str, Any]:
    return await getattr(context.flow, f"async_step_{FORM_STEPS[section]}")(values)


def path_selector(form: dict[str, Any], field: str) -> SelectSelector:
    return next(
        value
        for marker, value in form["data_schema"].schema.items()
        if marker.schema == field
    )


async def test_init_menu_keeps_connection_and_each_mapping_category(
    context: FlowContext,
) -> None:
    result = await context.flow.async_step_init()

    assert isinstance(context.flow, config_flow.OptionsFlow)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["fans", "thermostats", "utilities", "connection"]
    context.read_yaml.assert_not_awaited()
    context.api.assert_not_called()


@pytest.mark.parametrize("section", MAPPINGS)
async def test_category_displays_yaml_names_without_persisting(
    context: FlowContext, section: str
) -> None:
    original_options = deepcopy(context.entry.options)

    result = await open_section(context, section)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "add_mapping",
        "edit_mapping",
        "remove_mapping",
        "init",
    ]
    assert MAPPINGS[section]["name"] in result["description_placeholders"]["configured"]
    assert context.entry.options == original_options
    assert "unique_id" not in context.read_yaml.return_value[section][0]
    context.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.parametrize("section", MAPPINGS)
async def test_explicit_empty_list_overrides_yaml_and_add_creates_new_identity(
    context: FlowContext, section: str
) -> None:
    context.entry.options[section] = []
    original_options = deepcopy(context.entry.options)

    menu = await open_section(context, section)
    form = await context.flow.async_step_add_mapping()
    result = await submit(context, section, deepcopy(MAPPINGS[section]))

    assert menu["menu_options"] == ["add_mapping", "init"]
    assert form["step_id"] == FORM_STEPS[section]
    assert result["type"] is FlowResultType.CREATE_ENTRY
    saved = result["data"][section]
    assert len(saved) == 1
    assert saved[0]["unique_id"]
    assert saved[0]["unique_id"] != LEGACY_IDENTITIES[section]
    assert saved[0]["name"] == MAPPINGS[section]["name"]
    assert result["data"][CONF_VERIFY_SSL] is True
    assert result["data"]["unrelated"] == {"keep": [1]}
    assert context.entry.options == original_options
    context.read_yaml.assert_not_awaited()
    context.hass.config_entries.async_schedule_reload.assert_not_called()


@pytest.mark.parametrize("section", MAPPINGS)
@pytest.mark.parametrize("saved_identity", [None, "immutable-mapping-id"])
async def test_edit_preserves_legacy_or_saved_identity_after_path_change(
    context: FlowContext, section: str, saved_identity: str | None
) -> None:
    original = deepcopy(MAPPINGS[section])
    if saved_identity is not None:
        original["unique_id"] = saved_identity
        context.entry.options[section] = [original]
    original_options = deepcopy(context.entry.options)
    await open_section(context, section)

    selection = await context.flow.async_step_edit_mapping()
    form = await context.flow.async_step_edit_mapping({"mapping": "0"})
    edited = {
        **MAPPINGS[section],
        "name": "Renamed",
        PRIMARY_PATHS[section]: "New\\Path",
    }
    result = await submit(context, section, edited)

    assert selection["step_id"] == "edit_mapping"
    assert form["step_id"] == FORM_STEPS[section]
    saved = result["data"][section][0]
    assert saved["unique_id"] == (saved_identity or LEGACY_IDENTITIES[section])
    assert saved["name"] == "Renamed"
    assert saved[PRIMARY_PATHS[section]] == "New\\Path"
    assert context.entry.options == original_options
    assert "unique_id" not in context.read_yaml.return_value[section][0]


@pytest.mark.parametrize("section", MAPPINGS)
async def test_removal_requires_confirmation_and_saves_explicit_empty_list(
    context: FlowContext, section: str
) -> None:
    await open_section(context, section)
    selection = await context.flow.async_step_remove_mapping()
    confirmation = await context.flow.async_step_remove_mapping({"mapping": "0"})
    cancelled = await context.flow.async_step_confirm_remove({"confirm": False})

    assert selection["step_id"] == "remove_mapping"
    assert confirmation["step_id"] == "confirm_remove"
    assert confirmation["description_placeholders"]["name"] == MAPPINGS[section]["name"]
    assert confirmation["data_schema"]({}) == {"confirm": False}
    assert cancelled["type"] is FlowResultType.MENU
    assert section not in context.entry.options

    await context.flow.async_step_remove_mapping({"mapping": "0"})
    saved = await context.flow.async_step_confirm_remove({"confirm": True})
    assert saved["data"][section] == []
    context.entry.options = saved["data"]
    reopened = await open_section(context, section)
    assert reopened["menu_options"] == ["add_mapping", "init"]


async def test_duplicate_names_are_selected_by_position(context: FlowContext) -> None:
    context.entry.options["utilities"] = [
        {**UTILITY, "id": "Meters\\First", "unique_id": "first"},
        {**UTILITY, "id": "Meters\\Second", "unique_id": "second"},
    ]
    await open_section(context, "utilities")
    selection = await context.flow.async_step_remove_mapping()
    choices = path_selector(selection, "mapping").config["options"]
    assert [choice["value"] for choice in choices] == ["0", "1"]

    await context.flow.async_step_remove_mapping({"mapping": "1"})
    result = await context.flow.async_step_confirm_remove({"confirm": True})

    assert [row["unique_id"] for row in result["data"]["utilities"]] == ["first"]


@pytest.mark.parametrize("section", MAPPINGS)
async def test_paths_offer_cached_values_and_allow_manual_missing_paths(
    context: FlowContext, section: str
) -> None:
    await open_section(context, section)
    form = await context.flow.async_step_edit_mapping({"mapping": "0"})
    field = PRIMARY_PATHS[section]
    selector = path_selector(form, field)

    assert selector.config["custom_value"] is True
    assert set(CACHED_PATHS).issubset(selector.config["options"])
    assert MAPPINGS[section][field] in selector.config["options"]
    assert selector("Offline\\Manual") == "Offline\\Manual"
    result = await submit(
        context, section, {**MAPPINGS[section], field: "Offline\\Manual"}
    )
    assert result["data"][section][0][field] == "Offline\\Manual"
    assert all(item[0] == "get_device_paths" for item in context.api.mock_calls)


async def test_offline_controller_allows_manual_mapping(context: FlowContext) -> None:
    context.hass.data = {}
    context.entry.options["utilities"] = []
    await open_section(context, "utilities")
    form = await context.flow.async_step_add_mapping()

    assert path_selector(form, "id").config["options"] == []
    assert path_selector(form, "id")("Meters\\Manual") == "Meters\\Manual"
    result = await context.flow.async_step_utility({**UTILITY, "id": "Meters\\Manual"})
    assert result["data"]["utilities"][0]["id"] == "Meters\\Manual"
    assert context.api.mock_calls == []


@pytest.mark.parametrize("section", MAPPINGS)
async def test_duplicate_paths_reject_add_but_allow_unchanged_edit(
    context: FlowContext, section: str
) -> None:
    await open_section(context, section)
    await context.flow.async_step_add_mapping()
    field = PRIMARY_PATHS[section]
    duplicate = {
        **MAPPINGS[section],
        field: MAPPINGS[section][field].replace("\\", "\\\\"),
    }
    rejected = await submit(context, section, duplicate)

    assert rejected["type"] is FlowResultType.FORM
    assert rejected["errors"][field] == "duplicate_path"
    assert section not in context.entry.options

    await context.flow.async_step_edit_mapping({"mapping": "0"})
    accepted = await submit(context, section, deepcopy(MAPPINGS[section]))
    assert accepted["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("section", "changes", "field", "error"),
    [
        ("fans", {"lock_id": " "}, "lock_id", "required"),
        ("fans", {"name": " "}, "name", "required"),
        ("thermostats", {"heating_id": ""}, "heating_id", "required"),
        ("thermostats", {"min_temp": "bad"}, "min_temp", "invalid_number"),
        ("thermostats", {"max_temp": float("nan")}, "max_temp", "invalid_number"),
        ("thermostats", {"min_temp": True}, "min_temp", "invalid_number"),
        (
            "thermostats",
            {"target_temperature_step": 0},
            "target_temperature_step",
            "invalid_number",
        ),
        ("thermostats", {"max_temp": 18}, "max_temp", "invalid_range"),
        ("utilities", {"type": "gas"}, "type", "invalid_type"),
        ("utilities", {"unit": "m³"}, "unit", "invalid_unit"),
    ],
)
async def test_invalid_input_keeps_draft_and_saved_options_unchanged(
    context: FlowContext,
    section: str,
    changes: dict[str, Any],
    field: str,
    error: str,
) -> None:
    context.entry.options[section] = []
    original_options = deepcopy(context.entry.options)
    await open_section(context, section)
    await context.flow.async_step_add_mapping()

    result = await submit(context, section, {**MAPPINGS[section], **changes})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == FORM_STEPS[section]
    assert result["errors"][field] == error
    assert context.entry.options == original_options
    context.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.parametrize("fan_value", [None, "", "   "])
async def test_heating_only_thermostat_clears_optional_fan(
    context: FlowContext, fan_value: str | None
) -> None:
    await open_section(context, "thermostats")
    await context.flow.async_step_edit_mapping({"mapping": "0"})

    result = await context.flow.async_step_thermostat(
        {**THERMOSTAT, "fan_id": fan_value}
    )

    assert result["data"]["thermostats"][0]["fan_id"] is None


@pytest.mark.parametrize(
    ("meter_type", "unit"),
    [("water", "L"), ("electricity", "Wh"), ("heating", "MWh")],
)
async def test_meter_unit_override_and_default_are_saved_without_scaling(
    context: FlowContext, meter_type: str, unit: str
) -> None:
    context.entry.options["utilities"] = [{**UTILITY, "type": meter_type}]
    await open_section(context, "utilities")
    await context.flow.async_step_edit_mapping({"mapping": "0"})
    result = await context.flow.async_step_utility(
        {**UTILITY, "type": meter_type, "unit": unit}
    )
    assert result["data"]["utilities"][0]["unit"] == unit
    context.entry.options = result["data"]

    await open_section(context, "utilities")
    await context.flow.async_step_edit_mapping({"mapping": "0"})
    reset = await context.flow.async_step_utility(
        {**UTILITY, "type": meter_type, "unit": "default"}
    )

    assert "unit" not in reset["data"]["utilities"][0]


@pytest.mark.parametrize("source", ["yaml", "options"])
@pytest.mark.parametrize(
    ("original_type", "new_type"),
    [("water", "electricity"), ("water", "heating"), ("electricity", "water")],
)
async def test_existing_meter_cannot_change_between_water_and_energy(
    context: FlowContext, source: str, original_type: str, new_type: str
) -> None:
    rows = [{**UTILITY, "type": original_type}]
    if source == "yaml":
        context.read_yaml.return_value["utilities"] = rows
    else:
        context.entry.options["utilities"] = rows
    original_options = deepcopy(context.entry.options)
    await open_section(context, "utilities")
    await context.flow.async_step_edit_mapping({"mapping": "0"})

    rejected = await context.flow.async_step_utility({**UTILITY, "type": new_type})

    assert rejected["type"] is FlowResultType.FORM
    assert rejected["errors"]["type"] == "incompatible_meter_type"
    assert context.entry.options == original_options
    assert rows[0]["type"] == original_type


async def test_energy_meter_can_change_category_without_changing_identity(
    context: FlowContext,
) -> None:
    await open_section(context, "utilities")
    await context.flow.async_step_edit_mapping({"mapping": "0"})

    result = await context.flow.async_step_utility({**UTILITY, "type": "electricity"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["utilities"][0]["unique_id"] == UTILITY["id"]
    assert result["data"]["utilities"][0]["type"] == "electricity"


@pytest.mark.parametrize("broken_source", [None, [], {"fans": None}, {"fans": ["bad"]}])
async def test_malformed_yaml_shows_recoverable_error(
    context: FlowContext, broken_source: Any
) -> None:
    context.read_yaml.return_value = broken_source

    result = await context.flow.async_step_fans()

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_load_mappings"}
    assert "fans" not in context.entry.options


async def test_unreadable_yaml_shows_recoverable_error(context: FlowContext) -> None:
    context.read_yaml.side_effect = OSError("Configuration cannot be read")

    result = await context.flow.async_step_fans()

    assert result["errors"] == {"base": "cannot_load_mappings"}


async def test_concurrent_category_edit_cannot_overwrite_other_flow(
    context: FlowContext,
) -> None:
    context.entry.options["utilities"] = []
    await open_section(context, "utilities")
    await context.flow.async_step_add_mapping()
    context.entry.options["utilities"] = [{**UTILITY, "unique_id": "concurrent-save"}]

    result = await context.flow.async_step_utility(UTILITY)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "mappings_changed"
    assert context.entry.options["utilities"][0]["unique_id"] == "concurrent-save"


async def test_saving_keeps_changes_to_other_categories(context: FlowContext) -> None:
    context.entry.options["utilities"] = []
    await open_section(context, "utilities")
    await context.flow.async_step_add_mapping()
    context.entry.options["fans"] = [{**FAN, "unique_id": "other-flow-save"}]

    result = await context.flow.async_step_utility(UTILITY)

    assert result["data"]["fans"] == context.entry.options["fans"]
    assert len(result["data"]["utilities"]) == 1


async def test_failed_entry_saves_mapping_before_scheduling_reload(
    context: FlowContext,
) -> None:
    context.entry.state = ConfigEntryState.SETUP_RETRY
    context.entry.options["utilities"] = []
    await open_section(context, "utilities")
    await context.flow.async_step_add_mapping()

    result = await context.flow.async_step_utility(UTILITY)

    assert context.hass.config_entries.mock_calls == [
        call.async_update_entry(context.entry, options=result["data"]),
        call.async_schedule_reload(context.entry.entry_id),
    ]


@pytest.mark.parametrize("section", MAPPINGS)
async def test_read_only_options_mapping_is_supported(
    context: FlowContext, section: str
) -> None:
    original_options = {
        CONF_VERIFY_SSL: True,
        section: [{**MAPPINGS[section], "unique_id": "stable"}],
    }
    context.entry.options = MappingProxyType(original_options)
    await open_section(context, section)
    await context.flow.async_step_edit_mapping({"mapping": "0"})

    result = await submit(context, section, {**MAPPINGS[section], "name": "New name"})

    assert result["data"][section][0]["name"] == "New name"
    assert result["data"][section][0]["unique_id"] == "stable"
    assert original_options[section][0]["name"] == MAPPINGS[section]["name"]
    context.read_yaml.assert_not_awaited()


@pytest.fixture
async def managed_hass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[HomeAssistant]:
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    monkeypatch.setattr(
        hass.config_entries, "async_setup", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        hass.config_entries, "async_reload", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        config_entries,
        "_async_get_flow_handler",
        AsyncMock(return_value=config_flow.ConfigFlow),
    )
    try:
        yield hass
    finally:
        await hass.async_stop(force=True)


@pytest.mark.parametrize("section", MAPPINGS)
async def test_real_flow_manager_validates_persists_and_reloads_once(
    managed_hass: HomeAssistant, section: str
) -> None:
    entry = ConfigEntry(
        data={},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options={section: [], CONF_VERIFY_SSL: True},
        source=config_entries.SOURCE_USER,
        state=ConfigEntryState.LOADED,
        title="Test controller",
        unique_id="test-controller",
        version=1,
    )
    await managed_hass.config_entries.async_add(entry)
    remove_listener = entry.add_update_listener(
        integration._async_update_listener  # noqa: SLF001
    )
    manager = managed_hass.config_entries.options
    try:
        result = await manager.async_init(entry.entry_id)
        flow_id = result["flow_id"]
        await manager.async_configure(flow_id, {"next_step_id": section})
        form = await manager.async_configure(flow_id, {"next_step_id": "add_mapping"})
        assert form["step_id"] == FORM_STEPS[section]

        result = await manager.async_configure(flow_id, deepcopy(MAPPINGS[section]))
        await managed_hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["result"] is True
        assert isinstance(entry.options, MappingProxyType)
        assert len(entry.options[section]) == 1
        assert entry.options[section][0]["name"] == MAPPINGS[section]["name"]
        assert entry.options[section][0]["unique_id"]
        assert entry.options[CONF_VERIFY_SSL] is True
        managed_hass.config_entries.async_reload.assert_awaited_once_with(
            entry.entry_id
        )
    finally:
        remove_listener()

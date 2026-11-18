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
from homeassistant.helpers import area_registry, entity_registry

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
METERS = {
    "electricity_day": {
        "name": "Electricity (day, total)",
        "id": "Meters\\Day",
        "type": "electricity",
    },
    "electricity_night": {
        "name": "Electricity (night, total)",
        "id": "Meters\\Night",
        "type": "electricity",
    },
    "water_cold": {
        "name": "Water (cold, total)",
        "id": "Meters\\Cold",
        "type": "water",
    },
    "water_hot": {
        "name": "Water (hot, total)",
        "id": "Meters\\Hot",
        "type": "water",
    },
    "heating": {"name": "Heating (total)", "id": "Meters\\Heating", "type": "heating"},
}
DOORS = {
    "main": {"door_name": "Main door", "door_id": "Doors\\Main"},
    "cellar": {"door_name": "Cellar door", "door_id": "Doors\\Cellar"},
    "garage": {"door_name": "Garage door", "door_id": "Doors\\Garage"},
}
VENT_GROUPS = {
    "vent_mode": {
        "away_mode": "Vent\\Away",
        "home_mode": "Vent\\Home",
        "guest_mode": "Vent\\Guest",
    },
    "vent_air_mode": {"vent_winter_mode": "Vent\\Winter"},
    "vent_temperature": {
        "away_vent_air_temp": "Vent\\Away temperature",
        "home_vent_air_temp": "Vent\\Home temperature",
        "guest_vent_air_temp": "Vent\\Guest temperature",
    },
}
VENT = {key: value for fields in VENT_GROUPS.values() for key, value in fields.items()}
MAPPINGS = {"fans": FAN, "thermostats": THERMOSTAT}
FORM_STEPS = {"fans": "fan", "thermostats": "thermostat"}
PRIMARY_PATHS = {"fans": "fan_id", "thermostats": "heating_id"}
LEGACY_IDENTITIES = {
    "fans": FAN["fan_id"],
    "thermostats": f"room-1-{THERMOSTAT['heating_id']}",
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
        return_value={
            **{key: [deepcopy(value)] for key, value in MAPPINGS.items()},
            "utilities": deepcopy(list(METERS.values())[::-1]),
            "locks": deepcopy(list(DOORS.values())[::-1]),
            "vent": deepcopy(VENT),
        }
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
    assert result["menu_options"] == [
        "ventilation",
        "locks",
        "utilities",
        "thermostats",
        "fans",
        "doorbell",
        "connection",
    ]
    context.read_yaml.assert_not_awaited()
    assert context.api.mock_calls == []


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
    context.entry.options["fans"] = [
        {**FAN, "fan_id": "Fan\\First", "unique_id": "first"},
        {**FAN, "fan_id": "Fan\\Second", "unique_id": "second"},
    ]
    await open_section(context, "fans")
    selection = await context.flow.async_step_remove_mapping()
    choices = path_selector(selection, "mapping").config["options"]
    assert [choice["value"] for choice in choices] == ["0", "1"]

    await context.flow.async_step_remove_mapping({"mapping": "1"})
    result = await context.flow.async_step_confirm_remove({"confirm": True})

    assert [row["unique_id"] for row in result["data"]["fans"]] == ["first"]


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


@pytest.mark.parametrize("section", MAPPINGS)
async def test_edit_round_trip_preserves_trailing_spaces_in_controller_paths(
    context: FlowContext, section: str
) -> None:
    mapping = {**MAPPINGS[section], "target_temperature_id": "Controller\\Setpoint "}
    context.entry.options[section] = [{**mapping, "unique_id": "stable"}]
    await open_section(context, section)
    form = await context.flow.async_step_edit_mapping({"mapping": "0"})
    field = next(
        marker
        for marker in form["data_schema"].schema
        if marker.schema == "target_temperature_id"
    )
    assert field.description["suggested_value"] == "Controller\\Setpoint "

    result = await submit(context, section, mapping)

    assert (
        result["data"][section][0]["target_temperature_id"] == "Controller\\Setpoint "
    )


@pytest.mark.parametrize("section", MAPPINGS)
async def test_distinct_trailing_space_paths_do_not_conflict(
    context: FlowContext, section: str
) -> None:
    context.entry.options[section] = [
        {
            **MAPPINGS[section],
            PRIMARY_PATHS[section]: "Controller\\Value",
            "lock_id": "Controller\\Lock",
            "target_temperature_id": "Controller\\Target",
        }
    ]
    await open_section(context, section)
    await context.flow.async_step_add_mapping()

    new_mapping = {
        **MAPPINGS[section],
        PRIMARY_PATHS[section]: "Controller\\Value ",
        "target_temperature_id": "Controller\\Target ",
    }
    if section == "fans":
        new_mapping["lock_id"] = "Controller\\Lock "
    result = await submit(context, section, new_mapping)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][section][1][PRIMARY_PATHS[section]] == "Controller\\Value "


async def test_offline_controller_allows_manual_mapping(context: FlowContext) -> None:
    context.hass.data = {}
    context.entry.options["fans"] = []
    await open_section(context, "fans")
    form = await context.flow.async_step_add_mapping()

    assert path_selector(form, "fan_id").config["options"] == []
    assert path_selector(form, "fan_id")("Fan\\Manual") == "Fan\\Manual"
    result = await context.flow.async_step_fan({**FAN, "fan_id": "Fan\\Manual"})
    assert result["data"]["fans"][0]["fan_id"] == "Fan\\Manual"
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
    ("section", "prefix", "slots"),
    [("utilities", "meter", METERS), ("locks", "door", DOORS)],
)
async def test_fixed_catalog_menus_have_all_slots_and_no_add_remove(
    context: FlowContext, section: str, prefix: str, slots: dict
) -> None:
    context.read_yaml.return_value = {}

    result = await open_section(context, section)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [*(f"{prefix}_{slot}" for slot in slots), "init"]
    assert section not in context.entry.options


@pytest.mark.parametrize(
    ("section", "rows"),
    [
        ("utilities", [{"name": "Unidentified", "type": "water", "id": "Meter"}]),
        (
            "utilities",
            [{"name": "Day and night", "type": "electricity", "id": "Meter"}],
        ),
        ("utilities", [METERS["water_cold"], METERS["water_cold"]]),
        ("locks", [{"door_name": "Apartment door", "door_id": "Door"}]),
        ("locks", [{"door_name": "Main and cellar door", "door_id": "Door"}]),
        ("locks", [DOORS["main"], DOORS["main"]]),
    ],
)
async def test_unrecognized_or_ambiguous_legacy_catalog_is_not_discarded(
    context: FlowContext, section: str, rows: list[dict]
) -> None:
    context.read_yaml.return_value[section] = deepcopy(rows)

    result = await open_section(context, section)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_load_fixed_mappings"}
    assert context.read_yaml.return_value[section] == rows
    assert section not in context.entry.options


@pytest.mark.parametrize("slot", METERS)
@pytest.mark.parametrize("source", ["yaml", "options"])
async def test_fixed_meter_edit_preserves_all_five_roles_and_legacy_identity(
    context: FlowContext, slot: str, source: str
) -> None:
    if source == "options":
        context.entry.options = MappingProxyType(
            {
                **context.entry.options,
                "utilities": [
                    {**row, "slot": key, "unique_id": f"saved-{key}"}
                    for key, row in METERS.items()
                ],
            }
        )
    original_options = deepcopy(dict(context.entry.options))
    await context.flow.async_step_utilities()
    form = await getattr(context.flow, f"async_step_meter_{slot}")()

    assert form["step_id"] == "utility"
    assert {marker.schema for marker in form["data_schema"].schema} == {"id", "unit"}
    selected = path_selector(form, "id")
    assert selected.config["custom_value"] is True
    assert METERS[slot]["id"] in selected.config["options"]
    result = await context.flow.async_step_utility(
        {"id": "New\\Meter", "unit": "default"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    rows = {item["slot"]: item for item in result["data"]["utilities"]}
    assert set(rows) == set(METERS)
    for key, meter in METERS.items():
        assert rows[key]["type"] == meter["type"]
        assert rows[key]["id"] == ("New\\Meter" if key == slot else meter["id"])
        expected_identity = f"saved-{key}" if source == "options" else meter["id"]
        assert rows[key]["unique_id"] == expected_identity
    assert dict(context.entry.options) == original_options
    assert result["data"][CONF_VERIFY_SSL] is True
    assert all(item[0] == "get_device_paths" for item in context.api.mock_calls)


@pytest.mark.parametrize(
    ("slot", "unit"),
    [("water_cold", "L"), ("electricity_day", "Wh"), ("heating", "MWh")],
)
async def test_fixed_meter_units_can_be_overridden_and_reset(
    context: FlowContext, slot: str, unit: str
) -> None:
    await context.flow.async_step_utilities()
    await getattr(context.flow, f"async_step_meter_{slot}")()
    result = await context.flow.async_step_utility(
        {"id": METERS[slot]["id"], "unit": unit}
    )
    saved = next(row for row in result["data"]["utilities"] if row["slot"] == slot)
    assert saved["unit"] == unit
    context.entry.options = result["data"]

    await context.flow.async_step_utilities()
    await getattr(context.flow, f"async_step_meter_{slot}")()
    reset = await context.flow.async_step_utility(
        {"id": METERS[slot]["id"], "unit": "default"}
    )

    saved = next(row for row in reset["data"]["utilities"] if row["slot"] == slot)
    assert "unit" not in saved


async def test_fixed_meter_rejects_incompatible_unit_and_duplicate_path(
    context: FlowContext,
) -> None:
    await context.flow.async_step_utilities()
    form = await context.flow.async_step_meter_heating()
    assert "m³" not in path_selector(form, "unit").config["options"]

    rejected = await context.flow.async_step_utility(
        {"id": "New\\Heating", "unit": "m³"}
    )
    assert rejected["errors"]["unit"] == "invalid_unit"
    rejected = await context.flow.async_step_utility(
        {"id": METERS["electricity_day"]["id"], "unit": "default"}
    )
    assert rejected["errors"]["id"] == "duplicate_path"
    assert "utilities" not in context.entry.options


@pytest.mark.parametrize("slot", DOORS)
@pytest.mark.parametrize("source", ["yaml", "options"])
async def test_fixed_door_edit_preserves_three_slots_and_existing_identity(
    context: FlowContext, slot: str, source: str
) -> None:
    if source == "options":
        context.entry.options = MappingProxyType(
            {
                **context.entry.options,
                "locks": [
                    {**row, "slot": key, "unique_id": f"saved-{key}"}
                    for key, row in DOORS.items()
                ],
            }
        )
    original_options = deepcopy(dict(context.entry.options))
    await context.flow.async_step_locks()
    form = await getattr(context.flow, f"async_step_door_{slot}")()

    assert form["step_id"] == "door"
    assert {marker.schema for marker in form["data_schema"].schema} == {"door_id"}
    result = await context.flow.async_step_door({"door_id": "New\\Door"})

    rows = {item["slot"]: item for item in result["data"]["locks"]}
    assert set(rows) == set(DOORS)
    for key, door in DOORS.items():
        assert rows[key]["door_id"] == ("New\\Door" if key == slot else door["door_id"])
        expected_identity = f"saved-{key}" if source == "options" else door["door_id"]
        assert rows[key]["unique_id"] == expected_identity
    assert dict(context.entry.options) == original_options
    assert all(item[0] == "get_device_paths" for item in context.api.mock_calls)


async def test_duplicate_door_paths_do_not_save_or_command_controller(
    context: FlowContext,
) -> None:
    await context.flow.async_step_locks()
    await context.flow.async_step_door_main()

    result = await context.flow.async_step_door({"door_id": DOORS["garage"]["door_id"]})

    assert result["errors"]["door_id"] == "duplicate_path"
    assert "locks" not in context.entry.options
    assert all(item[0] == "get_device_paths" for item in context.api.mock_calls)


@pytest.mark.parametrize(
    ("section", "select_step", "form_step", "field"),
    [
        ("utilities", "meter_heating", "utility", "id"),
        ("locks", "door_main", "door", "door_id"),
    ],
)
async def test_fixed_slot_can_clear_mapping_without_removing_slot(
    context: FlowContext,
    section: str,
    select_step: str,
    form_step: str,
    field: str,
) -> None:
    context.hass.data = {}
    await open_section(context, section)
    form = await getattr(context.flow, f"async_step_{select_step}")()
    assert path_selector(form, field)("Manual\\Path") == "Manual\\Path"

    result = await getattr(context.flow, f"async_step_{form_step}")({field: ""})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(result["data"][section]) == (5 if section == "utilities" else 3)
    assert any(not row[field] for row in result["data"][section])
    assert context.api.mock_calls == []


@pytest.mark.parametrize("group", VENT_GROUPS)
@pytest.mark.parametrize("source", ["yaml", "options"])
async def test_single_ventilation_preserves_other_controls_when_editing_one_group(
    context: FlowContext, group: str, source: str
) -> None:
    if source == "options":
        context.entry.options["vent"] = deepcopy(VENT)
    original_options = deepcopy(context.entry.options)
    menu = await context.flow.async_step_ventilation()
    form = await getattr(context.flow, f"async_step_{group}")()

    assert menu["menu_options"] == [*VENT_GROUPS, "init"]
    assert form["step_id"] == group
    assert {marker.schema for marker in form["data_schema"].schema} == set(
        VENT_GROUPS[group]
    )
    changes = {field: f"New\\{field}" for field in VENT_GROUPS[group]}
    result = await getattr(context.flow, f"async_step_{group}")(changes)

    assert result["data"]["vent"] == {**VENT, **changes}
    assert context.entry.options == original_options
    assert all(item[0] == "get_device_paths" for item in context.api.mock_calls)


async def test_doorbell_information_does_not_create_duplicate_entities(
    context: FlowContext,
) -> None:
    form = await context.flow.async_step_doorbell()

    assert form["type"] is FlowResultType.FORM
    assert form["data_schema"]({}) == {}
    result = await context.flow.async_step_doorbell({})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert "doorbell" not in context.entry.options
    assert context.api.mock_calls == []


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
    context.entry.options["fans"] = []
    await open_section(context, "fans")
    await context.flow.async_step_add_mapping()
    context.entry.options["fans"] = [{**FAN, "unique_id": "concurrent-save"}]

    result = await context.flow.async_step_fan(FAN)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "mappings_changed"
    assert context.entry.options["fans"][0]["unique_id"] == "concurrent-save"


async def test_saving_keeps_changes_to_other_categories(context: FlowContext) -> None:
    context.entry.options["thermostats"] = []
    await open_section(context, "thermostats")
    await context.flow.async_step_add_mapping()
    context.entry.options["fans"] = [{**FAN, "unique_id": "other-flow-save"}]

    result = await context.flow.async_step_thermostat(THERMOSTAT)

    assert result["data"]["fans"] == context.entry.options["fans"]
    assert len(result["data"]["thermostats"]) == 1


async def test_failed_entry_saves_mapping_before_scheduling_reload(
    context: FlowContext,
) -> None:
    context.entry.state = ConfigEntryState.SETUP_RETRY
    context.entry.options["fans"] = []
    await open_section(context, "fans")
    await context.flow.async_step_add_mapping()

    result = await context.flow.async_step_fan(FAN)

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


@pytest.mark.parametrize("section", MAPPINGS)
async def test_edit_can_explicitly_clear_a_room_assignment(
    context: FlowContext, section: str
) -> None:
    context.entry.options[section] = [
        {**MAPPINGS[section], "unique_id": "stable", "area_id": "old-room"}
    ]
    await open_section(context, section)
    form = await context.flow.async_step_edit_mapping({"mapping": "0"})
    area_field = next(
        marker for marker in form["data_schema"].schema if marker.schema == "area_id"
    )
    assert area_field.description["suggested_value"] == "old-room"

    result = await submit(context, section, deepcopy(MAPPINGS[section]))

    assert result["data"][section][0]["area_id"] == ""
    assert result["data"][section][0]["unique_id"] == "stable"
    assert context.entry.options[section][0]["area_id"] == "old-room"


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
        await area_registry.async_load(hass)
        yield hass
    finally:
        await hass.async_stop(force=True)


@pytest.mark.parametrize("section", MAPPINGS)
@pytest.mark.parametrize("area_settings", [{}, {"area_id": None}])
async def test_imported_mapping_prefills_existing_entity_registry_room(
    context: FlowContext,
    managed_hass: HomeAssistant,
    section: str,
    area_settings: dict,
) -> None:
    area = area_registry.async_get(managed_hass).async_create("Bedroom")
    await entity_registry.async_load(managed_hass)
    registry = entity_registry.async_get(managed_hass)
    entity = registry.async_get_or_create(
        "fan" if section == "fans" else "climate", DOMAIN, "stable"
    )
    registry.async_update_entity(entity.entity_id, area_id=area.id)
    context.flow.hass = managed_hass
    context.entry.options[section] = [
        {**MAPPINGS[section], "unique_id": "stable", **area_settings}
    ]
    await open_section(context, section)

    form = await context.flow.async_step_edit_mapping({"mapping": "0"})

    area_field = next(
        marker for marker in form["data_schema"].schema if marker.schema == "area_id"
    )
    assert area_field.description["suggested_value"] == area.id


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
    area = area_registry.async_get(managed_hass).async_create("Bedroom")
    try:
        result = await manager.async_init(entry.entry_id)
        flow_id = result["flow_id"]
        await manager.async_configure(flow_id, {"next_step_id": section})
        form = await manager.async_configure(flow_id, {"next_step_id": "add_mapping"})
        assert form["step_id"] == FORM_STEPS[section]

        result = await manager.async_configure(
            flow_id, {**MAPPINGS[section], "area_id": area.id}
        )
        await managed_hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["result"] is True
        assert isinstance(entry.options, MappingProxyType)
        assert len(entry.options[section]) == 1
        assert entry.options[section][0]["name"] == MAPPINGS[section]["name"]
        assert entry.options[section][0]["unique_id"]
        assert entry.options[section][0]["area_id"] == area.id
        assert entry.options[CONF_VERIFY_SSL] is True
        managed_hass.config_entries.async_reload.assert_awaited_once_with(
            entry.entry_id
        )
    finally:
        remove_listener()


@pytest.mark.parametrize(
    ("section", "select_step", "form_step", "values"),
    [
        (
            "utilities",
            "meter_heating",
            "utility",
            {"id": "Meter\\Heating ", "unit": "MWh"},
        ),
        ("locks", "door_main", "door", {"door_id": "Doors\\Main "}),
        ("ventilation", "vent_mode", "vent_mode", VENT_GROUPS["vent_mode"]),
        (
            "ventilation",
            "vent_air_mode",
            "vent_air_mode",
            VENT_GROUPS["vent_air_mode"],
        ),
        (
            "ventilation",
            "vent_temperature",
            "vent_temperature",
            VENT_GROUPS["vent_temperature"],
        ),
    ],
)
async def test_real_flow_manager_saves_fixed_catalog_and_single_ventilation(
    managed_hass: HomeAssistant,
    section: str,
    select_step: str,
    form_step: str,
    values: dict,
) -> None:
    options_key = "vent" if section == "ventilation" else section
    entry = ConfigEntry(
        data={},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options={"utilities": [], "locks": [], "vent": {}, CONF_VERIFY_SSL: True},
        source=config_entries.SOURCE_USER,
        state=ConfigEntryState.LOADED,
        title="Test controller",
        unique_id="test-controller",
        version=1,
    )
    await managed_hass.config_entries.async_add(entry)
    remove_listener = entry.add_update_listener(integration._async_update_listener)  # noqa: SLF001
    manager = managed_hass.config_entries.options
    try:
        menu = await manager.async_init(entry.entry_id)
        flow_id = menu["flow_id"]
        await manager.async_configure(flow_id, {"next_step_id": section})
        form = await manager.async_configure(flow_id, {"next_step_id": select_step})
        assert form["step_id"] == form_step

        result = await manager.async_configure(flow_id, values)
        await managed_hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert isinstance(entry.options, MappingProxyType)
        if options_key == "vent":
            for field, value in values.items():
                assert entry.options["vent"][field] == value
        else:
            expected_count = 5 if options_key == "utilities" else 3
            assert len(entry.options[options_key]) == expected_count
            field = "id" if options_key == "utilities" else "door_id"
            assert any(
                row[field] == values[field] for row in entry.options[options_key]
            )
        managed_hass.config_entries.async_reload.assert_awaited_once_with(
            entry.entry_id
        )
    finally:
        remove_listener()


async def test_real_flow_manager_returns_from_doorbell_info_and_saves_connection(
    managed_hass: HomeAssistant,
) -> None:
    entry = ConfigEntry(
        data={},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options={CONF_VERIFY_SSL: True},
        source=config_entries.SOURCE_USER,
        state=ConfigEntryState.LOADED,
        title="Test controller",
        unique_id="test-controller",
        version=1,
    )
    await managed_hass.config_entries.async_add(entry)
    manager = managed_hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    form = await manager.async_configure(flow_id, {"next_step_id": "doorbell"})
    assert form["step_id"] == "doorbell"
    menu = await manager.async_configure(flow_id, {})
    assert menu["step_id"] == "init"

    form = await manager.async_configure(flow_id, {"next_step_id": "connection"})
    assert form["step_id"] == "connection"
    result = await manager.async_configure(flow_id, {CONF_VERIFY_SSL: False})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {CONF_VERIFY_SSL: False}


@pytest.mark.parametrize("name", [None, ""])
@pytest.mark.parametrize("section", ["utilities", "locks"])
async def test_fixed_form_uses_slot_label_for_empty_legacy_name(
    context: FlowContext, name: str | None, section: str
) -> None:
    slot = "heating" if section == "utilities" else "main"
    select_step = "meter_heating" if section == "utilities" else "door_main"
    name_key = "name" if section == "utilities" else "door_name"
    path_key = "id" if section == "utilities" else "door_id"
    expected_name = "Heating (total)" if section == "utilities" else "Main door"
    row = {name_key: name, path_key: "Legacy\\Path "}
    if section == "utilities":
        row["type"] = "heating"
    else:
        row["slot"] = slot
    context.read_yaml.return_value[section] = [row]

    await open_section(context, section)
    form = await getattr(context.flow, f"async_step_{select_step}")()

    assert form["description_placeholders"]["name"] == expected_name
    form_step = "utility" if section == "utilities" else "door"
    result = await getattr(context.flow, f"async_step_{form_step}")(
        {path_key: row[path_key]}
    )
    saved = next(item for item in result["data"][section] if item["slot"] == slot)
    assert saved[name_key] == name
    assert saved[path_key] == row[path_key]
    assert saved["unique_id"] == row[path_key]

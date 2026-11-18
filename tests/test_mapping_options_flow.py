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
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
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
CONNECTION = {
    CONF_HOST: "http://controller.test",
    CONF_USERNAME: "test-user",
    CONF_PASSWORD: "test-password",
}
EMPTY_MAPPINGS = {
    "fans": [],
    "thermostats": [],
    "locks": [],
    "utilities": [],
    "vent": {},
}


@dataclass
class FlowContext:
    flow: options_flow.OptionsFlow
    entry: MagicMock
    hass: MagicMock
    api: MagicMock


@pytest.fixture
def context() -> FlowContext:
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-controller"
    entry.version = 2
    entry.data = CONNECTION.copy()
    entry.options = {
        CONF_VERIFY_SSL: True,
        "unrelated": {"keep": [1]},
        **{
            key: [{**deepcopy(value), "unique_id": LEGACY_IDENTITIES[key]}]
            for key, value in MAPPINGS.items()
        },
        "utilities": [
            {**deepcopy(value), "slot": slot, "unique_id": value["id"]}
            for slot, value in reversed(METERS.items())
        ],
        "locks": [
            {**deepcopy(value), "slot": slot, "unique_id": value["door_id"]}
            for slot, value in reversed(DOORS.items())
        ],
        "vent": deepcopy(VENT),
    }
    entry.state = ConfigEntryState.LOADED
    entry.update_listeners = []
    api = MagicMock(spec=ApiInstance)
    api.get_device_paths.return_value = CACHED_PATHS
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {
        DOMAIN: {
            entry.entry_id: SimpleNamespace(coordinator=SimpleNamespace(api=api)),
        },
    }
    hass.config_entries = MagicMock()

    def update_entry(updated_entry: ConfigEntry, **changes: Any) -> bool:
        changed = any(
            getattr(updated_entry, key) != value for key, value in changes.items()
        )
        for key, value in changes.items():
            setattr(
                updated_entry,
                key,
                MappingProxyType(value) if key in ("options", "data") else value,
            )
        return changed

    hass.config_entries.async_update_entry.side_effect = update_entry
    flow = config_flow.ConfigFlow.async_get_options_flow(entry)
    flow.hass = hass
    return FlowContext(flow, entry, hass, api)


async def open_section(context: FlowContext, section: str) -> dict[str, Any]:
    return await getattr(context.flow, f"async_step_{section}")()


async def submit(
    context: FlowContext, section: str, values: dict[str, Any]
) -> dict[str, Any]:
    return await getattr(context.flow, f"async_step_{FORM_STEPS[section]}")(values)


async def select_mapping(
    context: FlowContext, index: int = 0, *, remove: bool = False
) -> dict[str, Any]:
    menu = await (
        context.flow.async_step_remove_mapping()
        if remove
        else context.flow.async_step_mapping()
    )
    prefix = "remove_" if remove else "edit_"
    actions = [
        key
        for key in menu["menu_options"]
        if key.startswith(prefix) and key != "remove_mapping"
    ]
    return await getattr(context.flow, f"async_step_{actions[index]}")()


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
        "done",
    ]
    assert context.api.mock_calls == []


@pytest.mark.parametrize("section", MAPPINGS)
async def test_category_displays_saved_names_without_persisting(
    context: FlowContext, section: str
) -> None:
    original_options = deepcopy(context.entry.options)

    result = await open_section(context, section)

    assert result["type"] is FlowResultType.MENU
    assert {"add_mapping", "remove_mapping", "init"} <= result["menu_options"].keys()
    rows = {
        key: label
        for key, label in result["menu_options"].items()
        if key.startswith("edit_")
    }
    assert list(rows.values()) == [MAPPINGS[section]["name"]]
    assert context.entry.options == original_options
    context.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.parametrize("section", MAPPINGS)
async def test_empty_list_offers_add_and_creates_new_identity(
    context: FlowContext, section: str
) -> None:
    context.entry.options[section] = []
    original_options = deepcopy(context.entry.options)

    menu = await open_section(context, section)
    form = await context.flow.async_step_add_mapping()
    result = await submit(context, section, deepcopy(MAPPINGS[section]))

    assert list(menu["menu_options"]) == ["add_mapping", "init"]
    assert form["step_id"] == FORM_STEPS[section]
    assert result["type"] is FlowResultType.MENU
    saved = context.entry.options[section]
    assert len(saved) == 1
    assert saved[0]["unique_id"]
    assert saved[0]["unique_id"] != LEGACY_IDENTITIES[section]
    assert saved[0]["name"] == MAPPINGS[section]["name"]
    assert context.entry.options[CONF_VERIFY_SSL] is True
    assert context.entry.options["unrelated"] == {"keep": [1]}
    assert context.entry.options != original_options
    context.hass.config_entries.async_schedule_reload.assert_not_called()


@pytest.mark.parametrize("section", MAPPINGS)
@pytest.mark.parametrize("saved_identity", [None, "immutable-mapping-id"])
async def test_edit_preserves_migrated_or_new_identity_after_path_change(
    context: FlowContext, section: str, saved_identity: str | None
) -> None:
    original = deepcopy(MAPPINGS[section])
    if saved_identity is not None:
        original["unique_id"] = saved_identity
        context.entry.options[section] = [original]
    original_options = deepcopy(context.entry.options)
    await open_section(context, section)

    selection = await context.flow.async_step_mapping()
    form = await select_mapping(context)
    edited = {
        **MAPPINGS[section],
        "name": "Renamed",
        PRIMARY_PATHS[section]: "New\\Path",
    }
    result = await submit(context, section, edited)

    assert result["step_id"] == "init"
    assert selection["type"] is FlowResultType.MENU
    assert form["step_id"] == FORM_STEPS[section]
    saved = context.entry.options[section][0]
    assert saved["unique_id"] == (saved_identity or LEGACY_IDENTITIES[section])
    assert saved["name"] == "Renamed"
    assert saved[PRIMARY_PATHS[section]] == "New\\Path"
    assert context.entry.options != original_options


@pytest.mark.parametrize("section", MAPPINGS)
async def test_removal_requires_confirmation_and_saves_explicit_empty_list(
    context: FlowContext, section: str
) -> None:
    await open_section(context, section)
    selection = await context.flow.async_step_remove_mapping()
    confirmation = await select_mapping(context, remove=True)
    cancelled = await context.flow.async_step_confirm_remove({"confirm": False})

    assert selection["step_id"] == "remove_mapping"
    assert confirmation["step_id"] == "confirm_remove"
    assert confirmation["description_placeholders"]["name"] == MAPPINGS[section]["name"]
    assert confirmation["data_schema"]({}) == {"confirm": False}
    assert cancelled["type"] is FlowResultType.MENU
    assert len(context.entry.options[section]) == 1

    await select_mapping(context, remove=True)
    saved = await context.flow.async_step_confirm_remove({"confirm": True})
    assert saved["step_id"] == "init"
    assert context.entry.options[section] == []
    reopened = await open_section(context, section)
    assert list(reopened["menu_options"]) == ["add_mapping", "init"]


async def test_duplicate_names_are_disambiguated_and_select_correct_identity(
    context: FlowContext,
) -> None:
    context.entry.options["fans"] = [
        {**FAN, "fan_id": "Fan\\First", "unique_id": "first"},
        {**FAN, "fan_id": "Fan\\Second", "unique_id": "second"},
    ]
    await open_section(context, "fans")
    selection = await context.flow.async_step_remove_mapping()
    choices = {
        key: label
        for key, label in selection["menu_options"].items()
        if key.startswith("remove_")
    }
    assert len(choices) == 2
    assert len(set(choices.values())) == 2
    assert all("Fan\\" not in label for label in choices.values())

    await select_mapping(context, 1, remove=True)
    result = await context.flow.async_step_confirm_remove({"confirm": True})

    assert result["step_id"] == "init"
    assert [row["unique_id"] for row in context.entry.options["fans"]] == ["first"]


@pytest.mark.parametrize("section", MAPPINGS)
async def test_paths_offer_cached_values_and_allow_manual_missing_paths(
    context: FlowContext, section: str
) -> None:
    await open_section(context, section)
    form = await select_mapping(context)
    field = PRIMARY_PATHS[section]
    selector = path_selector(form, field)

    assert selector.config["custom_value"] is True
    assert set(CACHED_PATHS).issubset(selector.config["options"])
    assert MAPPINGS[section][field] in selector.config["options"]
    assert selector("Offline\\Manual") == "Offline\\Manual"
    result = await submit(
        context, section, {**MAPPINGS[section], field: "Offline\\Manual"}
    )
    assert result["step_id"] == "init"
    assert context.entry.options[section][0][field] == "Offline\\Manual"
    assert all(item[0] == "get_device_paths" for item in context.api.mock_calls)


@pytest.mark.parametrize("section", MAPPINGS)
async def test_edit_round_trip_preserves_trailing_spaces_in_controller_paths(
    context: FlowContext, section: str
) -> None:
    mapping = {**MAPPINGS[section], "target_temperature_id": "Controller\\Setpoint "}
    context.entry.options[section] = [{**mapping, "unique_id": "stable"}]
    await open_section(context, section)
    form = await select_mapping(context)
    field = next(
        marker
        for marker in form["data_schema"].schema
        if marker.schema == "target_temperature_id"
    )
    assert field.description["suggested_value"] == "Controller\\Setpoint "

    result = await submit(context, section, mapping)

    assert result["step_id"] == "init"
    assert (
        context.entry.options[section][0]["target_temperature_id"]
        == "Controller\\Setpoint "
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

    assert result["type"] is FlowResultType.MENU
    assert (
        context.entry.options[section][1][PRIMARY_PATHS[section]]
        == "Controller\\Value "
    )


async def test_offline_controller_allows_manual_mapping(context: FlowContext) -> None:
    context.hass.data = {}
    context.entry.options["fans"] = []
    await open_section(context, "fans")
    form = await context.flow.async_step_add_mapping()

    assert path_selector(form, "fan_id").config["options"] == []
    assert path_selector(form, "fan_id")("Fan\\Manual") == "Fan\\Manual"
    result = await context.flow.async_step_fan({**FAN, "fan_id": "Fan\\Manual"})
    assert result["step_id"] == "init"
    assert context.entry.options["fans"][0]["fan_id"] == "Fan\\Manual"
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
    assert len(context.entry.options[section]) == 1

    await select_mapping(context)
    accepted = await submit(context, section, deepcopy(MAPPINGS[section]))
    assert accepted["type"] is FlowResultType.MENU


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
    await select_mapping(context)

    result = await context.flow.async_step_thermostat(
        {**THERMOSTAT, "fan_id": fan_value}
    )

    assert result["step_id"] == "init"
    assert context.entry.options["thermostats"][0]["fan_id"] is None


@pytest.mark.parametrize(
    ("section", "prefix", "slots"),
    [("utilities", "meter", METERS), ("locks", "door", DOORS)],
)
async def test_fixed_catalog_menus_have_all_slots_and_no_add_remove(
    context: FlowContext, section: str, prefix: str, slots: dict
) -> None:
    context.entry.options[section] = []

    result = await open_section(context, section)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [*(f"{prefix}_{slot}" for slot in slots), "init"]
    assert context.entry.options[section] == []


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
async def test_unrecognized_or_ambiguous_saved_catalog_is_not_discarded(
    context: FlowContext, section: str, rows: list[dict]
) -> None:
    context.entry.options[section] = deepcopy(rows)

    result = await open_section(context, section)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_load_fixed_mappings"}
    assert context.entry.options[section] == rows


@pytest.mark.parametrize("slot", METERS)
@pytest.mark.parametrize("source", ["migrated", "options"])
async def test_fixed_meter_edit_preserves_all_five_roles_and_saved_identity(
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

    assert result["type"] is FlowResultType.MENU
    rows = {item["slot"]: item for item in context.entry.options["utilities"]}
    assert set(rows) == set(METERS)
    for key, meter in METERS.items():
        assert rows[key]["type"] == meter["type"]
        assert rows[key]["id"] == ("New\\Meter" if key == slot else meter["id"])
        expected_identity = f"saved-{key}" if source == "options" else meter["id"]
        assert rows[key]["unique_id"] == expected_identity
    assert dict(context.entry.options) != original_options
    assert context.entry.options[CONF_VERIFY_SSL] is True
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
    assert result["step_id"] == "init"
    saved = next(
        row for row in context.entry.options["utilities"] if row["slot"] == slot
    )
    assert saved["unit"] == unit

    await context.flow.async_step_utilities()
    await getattr(context.flow, f"async_step_meter_{slot}")()
    reset = await context.flow.async_step_utility(
        {"id": METERS[slot]["id"], "unit": "default"}
    )

    assert reset["step_id"] == "init"
    saved = next(
        row for row in context.entry.options["utilities"] if row["slot"] == slot
    )
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
    assert len(context.entry.options["utilities"]) == 5


@pytest.mark.parametrize("slot", DOORS)
@pytest.mark.parametrize("source", ["migrated", "options"])
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

    assert result["step_id"] == "init"
    rows = {item["slot"]: item for item in context.entry.options["locks"]}
    assert set(rows) == set(DOORS)
    for key, door in DOORS.items():
        assert rows[key]["door_id"] == ("New\\Door" if key == slot else door["door_id"])
        expected_identity = f"saved-{key}" if source == "options" else door["door_id"]
        assert rows[key]["unique_id"] == expected_identity
    assert dict(context.entry.options) != original_options
    assert all(item[0] == "get_device_paths" for item in context.api.mock_calls)


async def test_duplicate_door_paths_do_not_save_or_command_controller(
    context: FlowContext,
) -> None:
    await context.flow.async_step_locks()
    await context.flow.async_step_door_main()

    result = await context.flow.async_step_door({"door_id": DOORS["garage"]["door_id"]})

    assert result["errors"]["door_id"] == "duplicate_path"
    assert len(context.entry.options["locks"]) == 3
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

    assert result["type"] is FlowResultType.MENU
    assert len(context.entry.options[section]) == (5 if section == "utilities" else 3)
    assert any(not row[field] for row in context.entry.options[section])
    assert context.api.mock_calls == []


@pytest.mark.parametrize("group", VENT_GROUPS)
async def test_single_ventilation_preserves_other_controls_when_editing_one_group(
    context: FlowContext, group: str
) -> None:
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

    assert result["step_id"] == "init"
    assert context.entry.options["vent"] == {**VENT, **changes}
    assert context.entry.options != original_options
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


@pytest.mark.parametrize("broken_mappings", [None, {}, ["bad"]])
async def test_malformed_saved_options_show_recoverable_error(
    context: FlowContext, broken_mappings: Any
) -> None:
    context.entry.options["fans"] = broken_mappings

    result = await context.flow.async_step_fans()

    assert result["type"] is FlowResultType.FORM
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

    assert result["step_id"] == "init"
    assert context.entry.options["fans"] == [{**FAN, "unique_id": "other-flow-save"}]
    assert len(context.entry.options["thermostats"]) == 1


async def test_failed_entry_saves_mapping_before_scheduling_reload(
    context: FlowContext,
) -> None:
    context.entry.state = ConfigEntryState.SETUP_RETRY
    context.entry.options["fans"] = []
    await open_section(context, "fans")
    await context.flow.async_step_add_mapping()

    result = await context.flow.async_step_fan(FAN)

    assert result["step_id"] == "init"
    assert context.hass.config_entries.mock_calls == [
        call.async_update_entry(context.entry, options=context.entry.options),
        call.async_schedule_reload(context.entry.entry_id),
    ]


@pytest.mark.parametrize(
    "state",
    [
        ConfigEntryState.LOADED,
        ConfigEntryState.SETUP_RETRY,
        ConfigEntryState.NOT_LOADED,
    ],
)
@pytest.mark.parametrize("section", ["fans", "connection"])
async def test_unchanged_save_never_writes_or_reloads_any_entry_state(
    context: FlowContext, state: ConfigEntryState, section: str
) -> None:
    context.entry.state = state
    context.entry.options["fans"] = [{**FAN, "unique_id": "stable", "area_id": ""}]
    before_options = deepcopy(context.entry.options)
    before_data = deepcopy(context.entry.data)
    if section == "fans":
        await context.flow.async_step_fans()
        await select_mapping(context)
        result = await context.flow.async_step_fan(FAN)
    else:
        await context.flow.async_step_connection()
        result = await context.flow.async_step_connection({CONF_VERIFY_SSL: True})
    assert result["step_id"] == "init"
    assert context.entry.options == before_options
    assert context.entry.data == before_data
    context.hass.config_entries.async_update_entry.assert_not_called()
    context.hass.config_entries.async_schedule_reload.assert_not_called()


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
    await select_mapping(context)

    result = await submit(context, section, {**MAPPINGS[section], "name": "New name"})

    assert result["step_id"] == "init"
    assert context.entry.options[section][0]["name"] == "New name"
    assert context.entry.options[section][0]["unique_id"] == "stable"
    assert original_options[section][0]["name"] == MAPPINGS[section]["name"]


@pytest.mark.parametrize("section", MAPPINGS)
async def test_edit_can_explicitly_clear_a_room_assignment(
    context: FlowContext, section: str
) -> None:
    context.entry.options[section] = [
        {**MAPPINGS[section], "unique_id": "stable", "area_id": "old-room"}
    ]
    await open_section(context, section)
    form = await select_mapping(context)
    area_field = next(
        marker for marker in form["data_schema"].schema if marker.schema == "area_id"
    )
    assert area_field.description["suggested_value"] == "old-room"

    result = await submit(context, section, deepcopy(MAPPINGS[section]))

    assert result["step_id"] == "init"
    assert context.entry.options[section][0]["area_id"] == ""
    assert context.entry.options[section][0]["unique_id"] == "stable"


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

    form = await select_mapping(context)

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
        options={**deepcopy(EMPTY_MAPPINGS), CONF_VERIFY_SSL: True},
        source=config_entries.SOURCE_USER,
        state=ConfigEntryState.LOADED,
        title="Test controller",
        unique_id="test-controller",
        version=2,
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

        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == "init"
        assert result["flow_id"] == flow_id
        assert any(item["flow_id"] == flow_id for item in manager.async_progress())
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


def named_mapping(section: str, name: str) -> dict[str, Any]:
    mapping = {**MAPPINGS[section], "name": name, "unique_id": f"stable-{name}"}
    for key in MAPPINGS[section]:
        if key.endswith("_id"):
            mapping[key] = f"{name}\\{key}"
    return mapping


def input_for_form(form: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    return {
        key.schema: values[key.schema]
        for key in form["data_schema"].schema
        if key.schema in values
    }


def named_action(menu: dict[str, Any], name: str) -> str:
    return next(key for key, label in menu["menu_options"].items() if label == name)


@pytest.fixture
async def managed_entry(managed_hass: HomeAssistant) -> AsyncGenerator[ConfigEntry]:
    entry = ConfigEntry(
        data=CONNECTION.copy(),
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options={
            **deepcopy(EMPTY_MAPPINGS),
            **{
                section: [
                    named_mapping(section, "First"),
                    named_mapping(section, "Second"),
                ]
                for section in MAPPINGS
            },
        },
        source=config_entries.SOURCE_USER,
        state=ConfigEntryState.LOADED,
        title="Test controller",
        unique_id="multiple-operations",
        version=2,
    )
    await managed_hass.config_entries.async_add(entry)
    remove = entry.add_update_listener(integration._async_update_listener)  # noqa: SLF001
    try:
        yield entry
    finally:
        remove()


@pytest.mark.parametrize("section", MAPPINGS)
async def test_repeated_named_edits_and_done_use_one_active_flow(
    managed_hass: HomeAssistant, managed_entry: ConfigEntry, section: str
) -> None:
    manager = managed_hass.config_entries.options
    root = await manager.async_init(managed_entry.entry_id)
    flow_id = root["flow_id"]
    for name in ("Second", "First"):
        menu = await manager.async_configure(flow_id, {"next_step_id": section})
        form = await manager.async_configure(
            flow_id, {"next_step_id": named_action(menu, name)}
        )
        values = {**named_mapping(section, name), "name": f"{name} revised"}
        root = await manager.async_configure(flow_id, input_for_form(form, values))
        assert root["type"] is FlowResultType.MENU
        assert root["flow_id"] == flow_id
        assert root["step_id"] == "init"
    await managed_hass.async_block_till_done()
    assert [row["name"] for row in managed_entry.options[section]] == [
        "First revised",
        "Second revised",
    ]
    assert [row["unique_id"] for row in managed_entry.options[section]] == [
        "stable-First",
        "stable-Second",
    ]
    assert managed_hass.config_entries.async_reload.await_count == 2

    menu = await manager.async_configure(flow_id, {"next_step_id": section})
    form = await manager.async_configure(
        flow_id, {"next_step_id": named_action(menu, "Second revised")}
    )
    await manager.async_configure(
        flow_id, input_for_form(form, managed_entry.options[section][1])
    )
    await managed_hass.async_block_till_done()
    assert managed_hass.config_entries.async_reload.await_count == 2
    done = await manager.async_configure(flow_id, {"next_step_id": "done"})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"] is None
    assert all(item["flow_id"] != flow_id for item in manager.async_progress())
    await managed_hass.async_block_till_done()
    assert managed_hass.config_entries.async_reload.await_count == 2


@pytest.mark.parametrize("section", MAPPINGS)
async def test_remove_then_edit_keeps_stable_row_action_after_index_shift(
    managed_hass: HomeAssistant, managed_entry: ConfigEntry, section: str
) -> None:
    manager = managed_hass.config_entries.options
    root = await manager.async_init(managed_entry.entry_id)
    flow_id = root["flow_id"]
    menu = await manager.async_configure(flow_id, {"next_step_id": section})
    second_action = named_action(menu, "Second")
    remove_menu = await manager.async_configure(
        flow_id, {"next_step_id": "remove_mapping"}
    )
    await manager.async_configure(
        flow_id, {"next_step_id": named_action(remove_menu, "First")}
    )
    root = await manager.async_configure(flow_id, {"confirm": True})
    assert root["step_id"] == "init"
    menu = await manager.async_configure(flow_id, {"next_step_id": section})
    assert named_action(menu, "Second") == second_action
    form = await manager.async_configure(flow_id, {"next_step_id": second_action})
    await manager.async_configure(
        flow_id,
        input_for_form(
            form,
            {
                **named_mapping(section, "Second"),
                "name": "Only remaining device",
            },
        ),
    )
    await managed_hass.async_block_till_done()
    assert len(managed_entry.options[section]) == 1
    assert managed_entry.options[section][0]["unique_id"] == "stable-Second"
    assert managed_entry.options[section][0]["name"] == "Only remaining device"
    assert managed_hass.config_entries.async_reload.await_count == 2
    manager.async_abort(flow_id)
    assert managed_entry.options[section][0]["name"] == "Only remaining device"


@pytest.mark.parametrize("section", MAPPINGS)
async def test_add_then_edit_new_device_preserves_generated_identity(
    managed_hass: HomeAssistant, managed_entry: ConfigEntry, section: str
) -> None:
    manager = managed_hass.config_entries.options
    root = await manager.async_init(managed_entry.entry_id)
    flow_id = root["flow_id"]
    await manager.async_configure(flow_id, {"next_step_id": section})
    form = await manager.async_configure(flow_id, {"next_step_id": "add_mapping"})
    values = named_mapping(section, "Third")
    await manager.async_configure(flow_id, input_for_form(form, values))
    identity = managed_entry.options[section][-1]["unique_id"]
    assert identity != values["unique_id"]
    menu = await manager.async_configure(flow_id, {"next_step_id": section})
    form = await manager.async_configure(
        flow_id, {"next_step_id": named_action(menu, "Third")}
    )
    await manager.async_configure(
        flow_id, input_for_form(form, {**values, "name": "Third revised"})
    )
    assert len(managed_entry.options[section]) == 3
    assert managed_entry.options[section][-1]["unique_id"] == identity
    assert managed_entry.options[section][-1]["name"] == "Third revised"


@pytest.mark.parametrize("section", MAPPINGS)
async def test_named_rows_show_rooms_and_cannot_collide_with_navigation_labels(
    context: FlowContext, managed_hass: HomeAssistant, section: str
) -> None:
    room = area_registry.async_get(managed_hass).async_create("Bedroom")
    context.flow.hass = managed_hass
    context.entry.options[section] = [
        {**named_mapping(section, "First"), "name": "Back", "area_id": room.id},
        {**named_mapping(section, "Second"), "name": "Back", "area_id": room.id},
    ]
    menu = await open_section(context, section)
    rows = {
        key: label
        for key, label in menu["menu_options"].items()
        if key.startswith("edit_")
    }
    assert list(rows.values()) == ["Back — Bedroom (1)", "Back — Bedroom (2)"]
    assert menu["menu_options"]["init"] == "Back"
    form = await getattr(context.flow, f"async_step_{list(rows)[1]}")()
    field = next(
        key
        for key in form["data_schema"].schema
        if key.schema == PRIMARY_PATHS[section]
    )
    assert field.description["suggested_value"].startswith("Second\\")


@pytest.mark.parametrize("section", MAPPINGS)
async def test_stale_named_selection_never_edits_different_device(
    managed_hass: HomeAssistant, managed_entry: ConfigEntry, section: str
) -> None:
    manager = managed_hass.config_entries.options
    root = await manager.async_init(managed_entry.entry_id)
    menu = await manager.async_configure(root["flow_id"], {"next_step_id": section})
    action = named_action(menu, "Second")
    changed = list(reversed(managed_entry.options[section]))
    managed_hass.config_entries.async_update_entry(
        managed_entry, options={**managed_entry.options, section: changed}
    )
    rejected = await manager.async_configure(root["flow_id"], {"next_step_id": action})
    assert rejected["type"] is FlowResultType.ABORT
    assert rejected["reason"] == "mappings_changed"
    assert managed_entry.options[section] == changed


async def test_cancel_unsaved_add_does_not_validate_or_persist(
    managed_hass: HomeAssistant, managed_entry: ConfigEntry
) -> None:
    before = deepcopy(dict(managed_entry.options))
    manager = managed_hass.config_entries.options
    root = await manager.async_init(managed_entry.entry_id)
    await manager.async_configure(root["flow_id"], {"next_step_id": "fans"})
    await manager.async_configure(root["flow_id"], {"next_step_id": "add_mapping"})
    manager.async_abort(root["flow_id"])
    await managed_hass.async_block_till_done()
    assert dict(managed_entry.options) == before
    managed_hass.config_entries.async_reload.assert_not_awaited()


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
        options={**deepcopy(EMPTY_MAPPINGS), CONF_VERIFY_SSL: True},
        source=config_entries.SOURCE_USER,
        state=ConfigEntryState.LOADED,
        title="Test controller",
        unique_id="test-controller",
        version=2,
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

        assert result["type"] is FlowResultType.MENU
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
        data=CONNECTION.copy(),
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options={**deepcopy(EMPTY_MAPPINGS), CONF_VERIFY_SSL: True},
        source=config_entries.SOURCE_USER,
        state=ConfigEntryState.LOADED,
        title="Test controller",
        unique_id="test-controller",
        version=2,
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
    result = await manager.async_configure(
        flow_id,
        {
            CONF_HOST: CONNECTION[CONF_HOST],
            CONF_USERNAME: CONNECTION[CONF_USERNAME],
            CONF_VERIFY_SSL: False,
        },
    )

    assert result["type"] is FlowResultType.MENU
    assert dict(entry.options) == {**EMPTY_MAPPINGS, CONF_VERIFY_SSL: False}


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
    context.entry.options[section] = [row]

    await open_section(context, section)
    form = await getattr(context.flow, f"async_step_{select_step}")()

    assert form["description_placeholders"]["name"] == expected_name
    form_step = "utility" if section == "utilities" else "door"
    result = await getattr(context.flow, f"async_step_{form_step}")(
        {path_key: row[path_key]}
    )
    assert result["step_id"] == "init"
    saved = next(
        item for item in context.entry.options[section] if item["slot"] == slot
    )
    assert saved[name_key] == name
    assert saved[path_key] == row[path_key]
    assert saved["unique_id"] == row[path_key]

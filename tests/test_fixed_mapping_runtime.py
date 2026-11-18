"""Fixed door, meter, and ventilation mappings retain identity and safe states."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.comfortclick_custom import RuntimeData, lock, select, sensor
from custom_components.comfortclick_custom.const import DOMAIN
from custom_components.comfortclick_custom.entities.locks.building_lock import (
    BuildingLock,
)
from custom_components.comfortclick_custom.entities.vent.vent_config import VentConfig
from custom_components.comfortclick_custom.entities.vent.vent_mode_select import (
    VentModeSelect,
    VentPresetModes,
)
from custom_components.comfortclick_custom.entities.vent.vent_temp_select import (
    VentTempModes,
    VentTempSelect,
)
from custom_components.comfortclick_custom.entities.vent.vent_temp_sensor import (
    VentTemperatureSensor,
)
from custom_components.comfortclick_custom.util import (
    load_lock_config,
    load_utilities_config,
    load_vent_config,
)

if TYPE_CHECKING:
    from typing import Any

    from homeassistant.helpers.update_coordinator import CoordinatorEntity


MODE_PATHS = {"home_mode": "home", "away_mode": "away", "guest_mode": "guest"}
VENT = VentConfig("winter", "away", "home", "guest", None, "home_temp", None)


@pytest.fixture
def values() -> dict[str, Any]:
    return {
        "home": True,
        "away": False,
        "guest": False,
        "winter": True,
        "home_temp": 21,
    }


@pytest.fixture
def coordinator(values: dict[str, Any]) -> MagicMock:
    instance = MagicMock()
    instance.last_update_success = True

    def get_value(device_name: str) -> Any:
        assert isinstance(device_name, str)
        assert device_name.strip()
        return values.get(device_name)

    instance.api.get_value.side_effect = get_value
    instance.api.set_value = AsyncMock(side_effect=AssertionError("No control writes"))
    return instance


def update(entity: CoordinatorEntity) -> None:
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()  # noqa: SLF001


async def test_fixed_lock_slots_skip_blank_paths_and_keep_imported_identity(
    coordinator: MagicMock, values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    read = AsyncMock(side_effect=AssertionError("Saved options must not read YAML"))
    monkeypatch.setattr(load_lock_config, "read_yaml", read)
    options = {
        "locks": [
            {
                "slot": "main",
                "door_name": "Main door",
                "door_id": "new-door",
                "unique_id": r"Old\\Door",
            },
            {"slot": "cellar", "door_name": "Cellar door", "door_id": ""},
            {"slot": "garage", "door_name": "Garage door", "door_id": " "},
        ]
    }
    values["new-door"] = False
    configs = await load_lock_config.load_lock_config(options)
    assert len(configs) == 1
    entity = BuildingLock(coordinator, configs[0])
    assert entity.unique_id == r"Old\\Door"
    assert entity.is_locked is True
    coordinator.api.get_value.assert_called_once_with(device_name="new-door")
    coordinator.api.set_value.assert_not_called()
    read.assert_not_awaited()


async def test_lock_yaml_fallback_preserves_original_door_identity(
    coordinator: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    read = AsyncMock(
        return_value={"locks": [{"door_name": "Door", "door_id": r"Room\\Door"}]}
    )
    monkeypatch.setattr(load_lock_config, "read_yaml", read)
    configs = await load_lock_config.load_lock_config({"verify_ssl": False})
    assert BuildingLock(coordinator, configs[0]).unique_id == r"Room\\Door"
    read.assert_awaited_once_with()


async def test_unconfigured_fixed_slots_create_no_entities(
    coordinator: MagicMock,
) -> None:
    options = {
        "locks": [
            {"slot": slot, "door_id": ""} for slot in ("main", "cellar", "garage")
        ],
        "utilities": [
            {"slot": slot, "id": ""}
            for slot in (
                "electricity_day",
                "electricity_night",
                "water_cold",
                "water_hot",
                "heating",
            )
        ],
        "vent": {},
    }
    assert await load_lock_config.load_lock_config(options) == []
    assert await load_utilities_config.load_utilities_config(options) == []
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    entry.options = options
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {entry.entry_id: RuntimeData(coordinator, lambda: None)}}
    entities = []

    for platform in (lock, sensor, select):
        await platform.async_setup_entry(hass, entry, entities.extend)

    assert entities == []
    coordinator.api.get_value.assert_not_called()


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        ({}, set()),
        ({"vent_winter_mode": "winter"}, {VentTempSelect}),
        ({"home_mode": "home"}, set()),
        ({"home_vent_air_temp": "home_temp"}, set()),
        (MODE_PATHS, {VentModeSelect}),
        ({**MODE_PATHS, "home_vent_air_temp": ""}, {VentModeSelect}),
        (
            {**MODE_PATHS, "home_vent_air_temp": "home_temp"},
            {VentModeSelect, VentTemperatureSensor},
        ),
        (
            {
                **MODE_PATHS,
                "home_vent_air_temp": "home_temp",
                "vent_winter_mode": "winter",
            },
            {VentModeSelect, VentTempSelect, VentTemperatureSensor},
        ),
    ],
)
async def test_partial_vent_groups_create_only_configured_entities(
    coordinator: MagicMock, paths: dict, expected: set[type]
) -> None:
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    entry.options = {"vent": paths, "utilities": []}
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {entry.entry_id: RuntimeData(coordinator, lambda: None)}}
    entities = []

    for platform in (select, sensor):
        await platform.async_setup_entry(hass, entry, entities.extend)

    assert {type(entity) for entity in entities} == expected
    assert all(entity.available for entity in entities)
    coordinator.api.set_value.assert_not_called()


async def test_explicit_empty_vent_overrides_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = AsyncMock(return_value={"vent": MODE_PATHS})
    monkeypatch.setattr(load_vent_config, "read_yaml", read)
    assert await load_vent_config.load_vent_config({"vent": {}}) is None
    read.assert_not_awaited()
    fallback = await load_vent_config.load_vent_config({})
    assert fallback.has_mode_paths
    read.assert_awaited_once_with()


@pytest.mark.parametrize(
    "change",
    [{"home": None}, {"home": "false"}, {"home": False}, {"away": True}],
)
def test_missing_or_ambiguous_modes_clear_previous_state_and_recover(
    coordinator: MagicMock, values: dict[str, Any], change: dict
) -> None:
    entities = [
        VentModeSelect(coordinator, VENT),
        VentTemperatureSensor(coordinator, VENT),
    ]
    assert entities[0].current_option == VentPresetModes.HOME
    assert entities[1].native_value == 21
    values.update(change)
    for entity in entities:
        update(entity)
        assert entity.available is False
    assert entities[0].current_option is None
    assert entities[1].native_value is None

    values.update(home=True, away=False, guest=False, home_temp=0)
    for entity in entities:
        update(entity)
        assert entity.available is True
    assert entities[1].native_value == 0
    coordinator.api.set_value.assert_not_called()


def test_unmapped_active_temperature_is_unavailable_without_stale_value(
    coordinator: MagicMock, values: dict[str, Any]
) -> None:
    entity = VentTemperatureSensor(coordinator, VENT)
    assert entity.native_value == 21
    values.update(home=False, away=True)
    update(entity)
    assert entity.native_value is None
    assert entity.available is False
    values.update(home=True, away=False, home_temp="nan")
    update(entity)
    assert entity.native_value is None
    values["home_temp"] = 18.5
    update(entity)
    assert entity.native_value == 18.5
    assert entity.available is True


@pytest.mark.parametrize("invalid", [None, "false", 0, {}])
def test_winter_mode_does_not_invent_cold_air_from_missing_feedback(
    coordinator: MagicMock, values: dict[str, Any], invalid: Any
) -> None:
    entity = VentTempSelect(coordinator, VENT)
    assert entity.current_option == VentTempModes.WARM_AIR
    values["winter"] = invalid
    update(entity)
    assert entity.current_option is None
    assert entity.available is False
    values["winter"] = False
    update(entity)
    assert entity.current_option == VentTempModes.COLD_AIR
    assert entity.available is True


def test_blank_vent_paths_are_never_read_or_sent_to_controller(
    coordinator: MagicMock,
) -> None:
    blank = VentConfig(None, "", "", None, "", None, "")
    entities = [
        VentModeSelect(coordinator, blank),
        VentTempSelect(coordinator, blank),
        VentTemperatureSensor(coordinator, blank),
    ]
    for entity in entities:
        update(entity)
        assert entity.available is False
    assert [entity.unique_id for entity in entities] == [
        "comfortclick-apartment-vent-mode-select",
        "comfortclick-apartment-vent-temp-select",
        "comfortclick-apartment-vent-temperature-sensor",
    ]
    coordinator.api.get_value.assert_not_called()
    coordinator.api.set_value.assert_not_called()

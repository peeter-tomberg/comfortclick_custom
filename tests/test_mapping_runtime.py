"""Options mappings preserve entity identity and retain explicit YAML fallback."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.comfortclick_custom import (
    RuntimeData,
    climate,
    fan,
    lock,
    select,
    sensor,
)
from custom_components.comfortclick_custom.const import DOMAIN
from custom_components.comfortclick_custom.entities.ac.room_fan import RoomFan
from custom_components.comfortclick_custom.entities.ac.room_thermostat import (
    RoomThermostat,
)
from custom_components.comfortclick_custom.entities.utilities.utilities_sensor import (
    ElectricitySensor,
    HeatingSensor,
    UtilitiesSensor,
    WaterSensor,
)
from custom_components.comfortclick_custom.util import (
    load_fans_config,
    load_thermostats_config,
    load_utilities_config,
    load_vent_config,
    read_yaml,
)

if TYPE_CHECKING:
    from typing import Any


MAPPING_KINDS = {
    "fans": (load_fans_config, RoomFan, "fan_id", ""),
    "thermostats": (load_thermostats_config, RoomThermostat, "heating_id", "room-1-"),
    "utilities": (load_utilities_config, UtilitiesSensor, "id", ""),
}


@pytest.fixture(params=list(MAPPING_KINDS))
def mapping_kind(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def mappings() -> dict[str, list[dict[str, Any]]]:
    return {
        "fans": [
            {
                "name": "Bedroom fan",
                "fan_id": r"Room\\Fan",
                "lock_id": "lock",
                "heating_id": "heating",
                "current_temperature_id": "current",
                "target_temperature_id": "target",
            }
        ],
        "thermostats": [
            {
                "name": "Bedroom AC",
                "heating_id": r"Room\\Heating",
                "fan_id": None,
                "current_temperature_id": "current",
                "target_temperature_id": "target",
            }
        ],
        "utilities": [{"name": "Water total", "id": r"Room\\Water", "type": "water"}],
    }


def coordinator() -> MagicMock:
    instance = MagicMock()
    instance.last_update_success = True
    instance.api.get_value.return_value = 0
    return instance


async def test_missing_option_category_uses_yaml_and_keeps_legacy_identity(
    mapping_kind: str,
    mappings: dict[str, list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, entity_class, identity_field, prefix = MAPPING_KINDS[mapping_kind]
    read = AsyncMock(return_value=mappings)
    monkeypatch.setattr(module, "read_yaml", read)
    load = getattr(module, f"load_{mapping_kind}_config")

    configs = await load({"verify_ssl": True})
    entity = entity_class(coordinator(), configs[0])

    assert entity.unique_id == prefix + mappings[mapping_kind][0][identity_field]
    assert entity.name == mappings[mapping_kind][0]["name"]
    read.assert_awaited_once_with()


async def test_explicit_empty_options_disable_category_without_reading_yaml(
    mapping_kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = MAPPING_KINDS[mapping_kind][0]
    read = AsyncMock(side_effect=AssertionError("YAML must not override saved options"))
    monkeypatch.setattr(module, "read_yaml", read)
    load = getattr(module, f"load_{mapping_kind}_config")

    assert await load({mapping_kind: []}) == []
    read.assert_not_awaited()


async def test_imported_identity_survives_name_and_controller_path_edits(
    mapping_kind: str,
    mappings: dict[str, list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, entity_class, identity_field, prefix = MAPPING_KINDS[mapping_kind]
    original = mappings[mapping_kind][0]
    edited = {
        **original,
        "name": "Renamed entity",
        identity_field: "Updated controller path",
        "unique_id": prefix + original[identity_field],
    }
    read = AsyncMock(return_value=mappings)
    monkeypatch.setattr(module, "read_yaml", read)
    load = getattr(module, f"load_{mapping_kind}_config")

    configs = await load({mapping_kind: [edited]})
    entity = entity_class(coordinator(), configs[0])

    assert len(configs) == 1
    assert entity.unique_id == prefix + original[identity_field]
    assert entity.name == "Renamed entity"
    assert getattr(configs[0], identity_field) == "Updated controller path"
    read.assert_not_awaited()


async def test_new_entry_mapping_ids_are_used_instead_of_controller_paths(
    mapping_kind: str, mappings: dict[str, list[dict[str, Any]]]
) -> None:
    module, entity_class, _, _ = MAPPING_KINDS[mapping_kind]
    first = {**mappings[mapping_kind][0], "unique_id": "entry-one-mapping-one"}
    second = {**mappings[mapping_kind][0], "unique_id": "entry-two-mapping-one"}
    load = getattr(module, f"load_{mapping_kind}_config")
    first_configs = await load({mapping_kind: [first]})
    second_configs = await load({mapping_kind: [second]})

    assert entity_class(coordinator(), first_configs[0]).unique_id == first["unique_id"]
    assert (
        entity_class(coordinator(), second_configs[0]).unique_id == second["unique_id"]
    )


async def test_meter_reads_mapped_path_after_preserving_legacy_identity() -> None:
    configs = await load_utilities_config.load_utilities_config(
        {
            "utilities": [
                {
                    "name": "Water",
                    "id": "new/path",
                    "unique_id": "old/path",
                    "type": "water",
                }
            ]
        }
    )
    instance = coordinator()
    instance.api.get_value.side_effect = {"new/path": 12.5, "old/path": 99}.get
    entity = UtilitiesSensor(instance, configs[0])

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()  # noqa: SLF001

    assert entity.unique_id == "old/path"
    assert entity.native_value == 12.5
    instance.api.get_value.assert_called_once_with("new/path")


async def test_fractional_ac_limits_and_step_survive_loading(
    mappings: dict[str, list[dict[str, Any]]],
) -> None:
    mappings["thermostats"][0].update(
        min_temp=17.5, max_temp=25.5, target_temperature_step=0.25
    )
    configs = await load_thermostats_config.load_thermostats_config(mappings)
    entity = RoomThermostat(coordinator(), configs[0])

    assert entity.min_temp == 17.5
    assert entity.max_temp == 25.5
    assert entity.target_temperature_step == 0.25
    assert configs[0].fan_id is None


@pytest.mark.parametrize(
    ("kind", "unit"),
    [
        ("water", "m³"),
        ("water", "L"),
        ("electricity", "Wh"),
        ("electricity", "kWh"),
        ("electricity", "MWh"),
        ("heating", "Wh"),
        ("heating", "kWh"),
        ("heating", "MWh"),
    ],
)
async def test_meter_unit_override_preserves_statistics_description(
    kind: str, unit: str
) -> None:
    configs = await load_utilities_config.load_utilities_config(
        {"utilities": [{"id": "meter", "name": "Meter", "type": kind, "unit": unit}]}
    )
    description = configs[0].description
    defaults = {
        "water": WaterSensor,
        "electricity": ElectricitySensor,
        "heating": HeatingSensor,
    }

    assert description.native_unit_of_measurement == unit
    assert description.state_class == SensorStateClass.TOTAL_INCREASING
    assert description.device_class == defaults[kind].device_class
    assert description is not defaults[kind]
    assert WaterSensor.native_unit_of_measurement == "m³"
    assert ElectricitySensor.native_unit_of_measurement == "kWh"
    assert HeatingSensor.native_unit_of_measurement == "MWh"


@pytest.mark.parametrize(
    ("kind", "unit"), [("water", "m³"), ("electricity", "kWh"), ("heating", "MWh")]
)
async def test_meter_without_unit_keeps_existing_default(kind: str, unit: str) -> None:
    configs = await load_utilities_config.load_utilities_config(
        {"utilities": [{"id": "meter", "name": "Meter", "type": kind}]}
    )
    assert configs[0].description.native_unit_of_measurement == unit


async def test_ui_only_setup_needs_no_yaml_and_creates_no_empty_vent_entities(
    mappings: dict[str, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        read_yaml.aiofiles, "open", MagicMock(side_effect=FileNotFoundError)
    )
    hass = MagicMock(spec=HomeAssistant)
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry"
    entry.options = deepcopy(mappings)
    hass.data = {DOMAIN: {entry.entry_id: RuntimeData(coordinator(), lambda: None)}}
    entities = []

    for platform in (fan, climate, sensor, lock, select):
        await platform.async_setup_entry(hass, entry, entities.extend)

    assert len(entities) == 3
    assert {type(entity) for entity in entities} == {
        RoomFan,
        RoomThermostat,
        UtilitiesSensor,
    }
    assert await read_yaml.read_yaml() == {}


@pytest.mark.parametrize("contents", ["", "# Empty configuration", "{}"])
async def test_empty_yaml_is_an_empty_mapping(
    contents: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = MagicMock()
    file.__aenter__.return_value.read = AsyncMock(return_value=contents)
    monkeypatch.setattr(read_yaml.aiofiles, "open", MagicMock(return_value=file))

    assert await read_yaml.read_yaml() == {}
    assert await load_vent_config.load_vent_config() is None


@pytest.mark.parametrize("contents", ["fans: [", "- not-a-mapping"])
async def test_invalid_yaml_remains_a_visible_error(
    contents: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = MagicMock()
    file.__aenter__.return_value.read = AsyncMock(return_value=contents)
    monkeypatch.setattr(read_yaml.aiofiles, "open", MagicMock(return_value=file))

    with pytest.raises((yaml.YAMLError, TypeError)):
        await read_yaml.read_yaml()

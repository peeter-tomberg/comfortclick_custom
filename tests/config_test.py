"""Load native config-entry mappings without a runtime YAML dependency."""

import pytest

from custom_components.comfortclick_custom.entities.ac.room_fan import RoomFanConfig
from custom_components.comfortclick_custom.entities.ac.room_thermostat import (
    RoomThermostatConfig,
)
from custom_components.comfortclick_custom.util.load_fans_config import load_fans_config
from custom_components.comfortclick_custom.util.load_lock_config import load_lock_config
from custom_components.comfortclick_custom.util.load_thermostats_config import (
    load_thermostats_config,
)
from custom_components.comfortclick_custom.util.load_utilities_config import (
    load_utilities_config,
)
from custom_components.comfortclick_custom.util.load_vent_config import load_vent_config


@pytest.mark.parametrize(
    "options",
    [
        None,
        {},
        {"fans": [], "thermostats": [], "locks": [], "utilities": [], "vent": {}},
    ],
)
async def test_absent_or_empty_native_config_loads_no_entities(options: dict | None):
    assert await load_fans_config(options) == []
    assert await load_thermostats_config(options) == []
    assert await load_lock_config(options) == []
    assert await load_utilities_config(options) == []
    assert await load_vent_config(options) is None


async def test_fans_config_loader_preserves_native_fields():
    configs = await load_fans_config(
        {
            "fans": [
                {
                    "name": "Bedroom fan",
                    "fan_id": "Fan\\Bedroom",
                    "unique_id": "bedroom-fan",
                    "area_id": "bedroom",
                    "target_temperature_id": "Bedroom\\Setpoint ",
                },
                {
                    "name": "Living room fan",
                    "fan_id": "Fan\\Living",
                    "unique_id": "living-fan",
                    "area_id": "living-room",
                    "target_temperature_id": "Living\\Setpoint ",
                },
            ]
        }
    )
    assert isinstance(configs[0], RoomFanConfig)
    assert isinstance(configs[1], RoomFanConfig)
    assert configs[0].name == "Bedroom fan"
    assert configs[1].name == "Living room fan"
    assert configs[0].unique_id == "bedroom-fan"
    assert configs[1].unique_id == "living-fan"
    assert configs[0].area_id == "bedroom"
    assert configs[1].area_id == "living-room"
    assert configs[0].target_temperature_id == "Bedroom\\Setpoint "
    assert configs[1].target_temperature_id == "Living\\Setpoint "


async def test_vent_config_loader_uses_one_native_mapping():
    config = await load_vent_config(
        {
            "vent": {
                "away_mode": "Vent\\Away",
                "home_mode": "Vent\\Home",
                "guest_mode": "Vent\\Guest",
                "away_vent_air_temp": "Temp\\Away",
                "home_vent_air_temp": "Temp\\Home",
                "guest_vent_air_temp": "Temp\\Guest",
                "vent_winter_mode": "Vent\\Winter",
            }
        }
    )
    assert config.away_mode == "Vent\\Away"
    assert config.home_mode == "Vent\\Home"
    assert config.guest_mode == "Vent\\Guest"
    assert config.away_vent_air_temp == "Temp\\Away"
    assert config.home_vent_air_temp == "Temp\\Home"
    assert config.guest_vent_air_temp == "Temp\\Guest"
    assert config.vent_winter_mode == "Vent\\Winter"


async def test_locks_config_loader_skips_blank_fixed_slots():
    configs = await load_lock_config(
        {
            "locks": [
                {
                    "slot": "main",
                    "door_name": "Main door",
                    "door_id": "Door\\Main ",
                    "unique_id": "saved-main-door",
                },
                {"slot": "cellar", "door_name": "Cellar door", "door_id": ""},
                {"slot": "garage", "door_name": "Garage door", "door_id": " "},
            ]
        }
    )
    assert len(configs) == 1
    assert configs[0].door_name == "Main door"
    assert configs[0].door_id == "Door\\Main "
    assert configs[0].unique_id == "saved-main-door"


async def test_thermostats_config_loader_keeps_per_room_limits_and_identities():
    configs = await load_thermostats_config(
        {
            "thermostats": [
                {
                    "name": "Bedroom AC",
                    "unique_id": "bedroom-ac",
                    "area_id": "bedroom",
                    "heating_id": "Bedroom\\Heating",
                },
                {
                    "name": "Living room AC",
                    "unique_id": "living-ac",
                    "area_id": "living-room",
                    "heating_id": "Living\\Heating",
                },
                {
                    "name": "Bathroom AC",
                    "unique_id": "bathroom-ac",
                    "area_id": "bathroom",
                    "heating_id": "Bathroom\\Heating",
                    "max_temp": 28,
                },
            ]
        }
    )
    assert isinstance(configs[0], RoomThermostatConfig)
    assert isinstance(configs[1], RoomThermostatConfig)
    assert isinstance(configs[2], RoomThermostatConfig)
    assert configs[0].name == "Bedroom AC"
    assert configs[0].max_temp == 24
    assert configs[1].name == "Living room AC"
    assert configs[1].max_temp == 24
    assert configs[2].name == "Bathroom AC"
    assert configs[2].max_temp == 28
    assert [item.unique_id for item in configs] == [
        "bedroom-ac",
        "living-ac",
        "bathroom-ac",
    ]
    assert [item.area_id for item in configs] == ["bedroom", "living-room", "bathroom"]

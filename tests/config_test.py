"""Test config loading."""

import logging

import pytest

from custom_components.comfortclick_custom.entities.ac.room_fan import RoomFanConfig
from custom_components.comfortclick_custom.entities.ac.room_thermostat import (
    RoomThermostatConfig,
)
from custom_components.comfortclick_custom.entities.locks.building_lock import (
    BuildingLockConfig,
)
from custom_components.comfortclick_custom.util.load_fans_config import load_fans_config
from custom_components.comfortclick_custom.util.load_lock_config import load_lock_config
from custom_components.comfortclick_custom.util.load_thermostats_config import (
    load_thermostats_config,
)
from custom_components.comfortclick_custom.util.load_vent_config import load_vent_config
from custom_components.comfortclick_custom.util.read_yaml import read_yaml

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_config_loader():
    config = await read_yaml()
    assert config.get("fans") is not None
    assert config.get("locks") is not None
    assert config.get("thermostats") is not None
    assert config.get("utilities") is not None
    assert config.get("vent") is not None


@pytest.mark.asyncio
async def test_fans_config_loader():
    configs = await load_fans_config()
    assert isinstance(configs[0], RoomFanConfig)
    assert isinstance(configs[1], RoomFanConfig)
    assert configs[0].name == "Bedroom fan"
    assert configs[1].name == "Living room fan"
    assert configs[0].current_temperature_id == ""
    assert configs[1].current_temperature_id == ""
    assert configs[0].target_temperature_id == ""
    assert configs[1].target_temperature_id == ""


@pytest.mark.asyncio
async def test_vent_config_loader():
    config = await load_vent_config()
    assert config.away_mode == ""
    assert config.home_mode == ""
    assert config.guest_mode == ""

    assert config.away_vent_air_temp == ""
    assert config.home_vent_air_temp == ""
    assert config.guest_vent_air_temp == ""

    assert config.vent_winter_mode == ""


@pytest.mark.asyncio
async def test_locks_config_loader():
    configs = await load_lock_config()
    assert isinstance(configs[0], BuildingLockConfig)
    assert isinstance(configs[1], BuildingLockConfig)
    assert configs[0].door_name == "Main door"
    assert configs[1].door_name == "Cellar door"


@pytest.mark.asyncio
async def test_thermostats_config_loader():
    configs = await load_thermostats_config()
    assert isinstance(configs[0], RoomThermostatConfig)
    assert isinstance(configs[1], RoomThermostatConfig)
    assert isinstance(configs[2], RoomThermostatConfig)
    assert configs[0].name == "Bedroom AC"
    assert configs[0].max_temp == 24
    assert configs[1].name == "Living room AC"
    assert configs[1].max_temp == 24
    assert configs[2].name == "Bathroom AC"
    assert configs[2].max_temp == 28

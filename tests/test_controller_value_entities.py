"""Controller scalar envelopes must behave identically to plain entity readings."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from homeassistant.components.climate import HVACAction

from custom_components.comfortclick_custom.api import ApiInstance
from custom_components.comfortclick_custom.entities.ac.room_fan import (
    RoomFan,
    RoomFanConfig,
)
from custom_components.comfortclick_custom.entities.ac.room_thermostat import (
    RoomThermostat,
    RoomThermostatConfig,
)
from custom_components.comfortclick_custom.entities.locks.building_lock import (
    BuildingLock,
    BuildingLockConfig,
)
from custom_components.comfortclick_custom.entities.utilities.utilities_sensor import (
    UtilitiesSensor,
    UtilitiesSensorConfig,
    WaterSensor,
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

from .api_helpers import response

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

VALUES = {
    "home": True,
    "away": False,
    "guest": False,
    "winter": False,
    "home_temp": 20.5,
    "away_temp": 18.5,
    "guest_temp": 21.5,
    "door": False,
    "heating": False,
    "fan_lock": False,
    "fan": 10.0,
    "current": 22.0,
    "target": 20.0,
    "water": 370.604,
}
VENT = VentConfig(
    "winter", "away", "home", "guest", "away_temp", "home_temp", "guest_temp"
)


def wrapped(value: bool | float) -> dict:
    scalar_type = "Boolean" if isinstance(value, bool) else "Double"
    return {"$type": f"System.{scalar_type}, System.Private.CoreLib", "$value": value}


@pytest.fixture(params=["snapshot", "delta"])
async def coordinator(request: pytest.FixtureRequest):
    """Exercise both production cache entry paths, without any live HTTP requests."""
    session = MagicMock(spec=aiohttp.ClientSession)
    initial = {
        "ThemeObject": {
            "ValueUpdates": [
                {
                    "DeviceName": key,
                    "Value": wrapped(value) if request.param == "snapshot" else value,
                }
                for key, value in VALUES.items()
            ]
        }
    }
    updates = {
        "PropertyUpdates": [
            {"DeviceName": key, "PropertyName": "Value", "Value": wrapped(value)}
            for key, value in VALUES.items()
        ]
    }
    session.post.side_effect = [response(initial), response(updates)]
    api = ApiInstance("test", "test", "https://controller.test", session=session)
    await api.initialize_state()
    if request.param == "delta":
        await api.poll()
    result = MagicMock()
    result.api = api
    result.last_update_success = True
    yield result
    assert all("SetValue" not in call.args[0] for call in session.post.call_args_list)


def update(entity: CoordinatorEntity) -> None:
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()  # noqa: SLF001


def test_wrapped_false_does_not_oscillate_ventilation_mode(
    coordinator: MagicMock,
) -> None:
    entity = VentModeSelect(coordinator, VENT)
    observed = []
    for _ in range(6):
        update(entity)
        observed.append(entity.current_option)
    assert observed == [VentPresetModes.HOME] * 6


def test_wrapped_readings_keep_climate_and_fan_available(
    coordinator: MagicMock,
) -> None:
    climate = RoomThermostat(
        coordinator, RoomThermostatConfig("Room", "heating", "fan", "current", "target")
    )
    fan = RoomFan(
        coordinator,
        RoomFanConfig("Fan", "heating", "fan_lock", "fan", "current", "target"),
    )
    for entity in (climate, fan):
        update(entity)
        assert entity.available is True
    assert climate.current_temperature == 22.0
    assert climate.target_temperature == 20.0
    assert climate.hvac_action == HVACAction.COOLING
    assert fan.is_on is True


def test_wrapped_lock_feedback_retains_boolean_meaning(coordinator: MagicMock) -> None:
    entity = BuildingLock(coordinator, BuildingLockConfig("Door", "door"))
    update(entity)
    assert entity.available is True
    assert entity.is_open is False
    assert entity.is_locked is True


def test_wrapped_water_meter_remains_numeric(coordinator: MagicMock) -> None:
    entity = UtilitiesSensor(
        coordinator, UtilitiesSensorConfig("water", "Water", WaterSensor)
    )
    update(entity)
    assert entity.native_value == 370.604
    assert type(entity.native_value) is float


def test_wrapped_false_is_cold_air_and_selected_temperature_is_numeric(
    coordinator: MagicMock,
) -> None:
    mode = VentTempSelect(coordinator, VENT)
    temperature = VentTemperatureSensor(coordinator, VENT)
    update(mode)
    update(temperature)
    assert mode.current_option == VentTempModes.COLD_AIR
    assert temperature.native_value == 20.5

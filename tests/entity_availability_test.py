"""Regression coverage for coordinator availability transitions."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

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
    ElectricitySensor,
    UtilitiesSensor,
    UtilitiesSensorConfig,
)
from custom_components.comfortclick_custom.entities.vent.vent_config import VentConfig
from custom_components.comfortclick_custom.entities.vent.vent_mode_select import (
    VentModeSelect,
)
from custom_components.comfortclick_custom.entities.vent.vent_temp_select import (
    VentTempSelect,
)
from custom_components.comfortclick_custom.entities.vent.vent_temp_sensor import (
    VentTemperatureSensor,
)

if TYPE_CHECKING:
    from typing import Any

    from homeassistant.helpers.update_coordinator import CoordinatorEntity


VENT_CONFIG = VentConfig(
    vent_winter_mode="winter",
    away_mode="away",
    home_mode="home",
    guest_mode="guest",
    away_vent_air_temp="away_temp",
    home_vent_air_temp="home_temp",
    guest_vent_air_temp="guest_temp",
)


@pytest.mark.parametrize(
    ("entity_class", "config"),
    [
        pytest.param(
            UtilitiesSensor,
            UtilitiesSensorConfig("meter", "Electricity", ElectricitySensor),
            id="utility",
        ),
        pytest.param(
            BuildingLock,
            BuildingLockConfig("Front door", "door"),
            id="lock",
        ),
        pytest.param(
            RoomFan,
            RoomFanConfig("Fan", "heating", "fan_lock", "fan", "current", "target"),
            id="fan",
        ),
        pytest.param(
            RoomThermostat,
            RoomThermostatConfig("Thermostat", "heating", "fan", "current", "target"),
            id="thermostat",
        ),
        pytest.param(VentModeSelect, VENT_CONFIG, id="vent-mode"),
        pytest.param(VentTempSelect, VENT_CONFIG, id="vent-temperature-mode"),
        pytest.param(VentTemperatureSensor, VENT_CONFIG, id="vent-temperature"),
    ],
)
def test_unchanged_reading_publishes_failure_and_recovery(
    entity_class: type[CoordinatorEntity],
    config: Any,
) -> None:
    values = {
        "meter": 100,
        "door": False,
        "heating": False,
        "fan_lock": False,
        "fan": 10,
        "current": 22,
        "target": 20,
        "home": True,
        "away": False,
        "guest": False,
        "home_temp": 20,
        "winter": True,
    }
    coordinator = MagicMock()
    coordinator.api.get_value.side_effect = lambda device_name: values.get(device_name)
    coordinator.last_update_success = True
    entity = entity_class(coordinator, config)
    published_availability = []

    with patch.object(
        entity,
        "async_write_ha_state",
        side_effect=lambda: published_availability.append(entity.available),
    ):
        entity._handle_coordinator_update()  # noqa: SLF001
        coordinator.last_update_success = False
        entity._handle_coordinator_update()  # noqa: SLF001
        coordinator.last_update_success = True
        entity._handle_coordinator_update()  # noqa: SLF001

    assert published_availability == [True, False, True]

"""Exposes utilities sensors to home assistant."""

import logging
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...coordinator import ComfortClickCoordinator

_LOGGER = logging.getLogger(__name__)

WaterSensor = SensorEntityDescription(
    key="water_sensor",
    state_class=SensorStateClass.TOTAL_INCREASING,
    native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
    device_class=SensorDeviceClass.WATER,
)

ElectricitySensor = SensorEntityDescription(
    key="electricity_sensor",
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    device_class=SensorDeviceClass.ENERGY,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

HeatingSensor = SensorEntityDescription(
    key="heating_sensor",
    native_unit_of_measurement=UnitOfEnergy.MEGA_WATT_HOUR,
    device_class=SensorDeviceClass.ENERGY,
    state_class=SensorStateClass.TOTAL_INCREASING,
)


@dataclass
class UtilitiesSensorConfig:
    """Class for keeping all configuration options."""

    id: str = None
    name: str = None
    description: SensorEntityDescription = None


class UtilitiesSensor(CoordinatorEntity, SensorEntity):
    """Representation of a sensor that reports utilities."""

    def __init__(
        self, coordinator: ComfortClickCoordinator, config: UtilitiesSensorConfig
    ) -> None:
        """Initialize the door sensor."""
        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        # re-using sensor id as unique id for this device
        self._attr_unique_id = config.id
        self.entity_description = config.description
        # human-readable name
        self._attr_name = config.name

        # start listener on coordinator
        super().__init__(coordinator)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        updated_value = self._coordinator.api.get_value(self._attr_unique_id)
        if updated_value != self._attr_native_value:
            self._attr_native_value = updated_value
            self.async_write_ha_state()

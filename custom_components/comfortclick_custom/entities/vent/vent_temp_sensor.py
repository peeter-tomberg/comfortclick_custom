"""Exposes vent temperature to home assistant."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator
from ..ac.values import numeric_value
from .vent_config import VentConfig
from .vent_state import VentPresetModes, active_mode


class VentTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Representation of a sensor that reports the vent temperature."""

    def __init__(
        self, coordinator: ComfortClickCoordinator, config: VentConfig
    ) -> None:
        """Initialize the door sensor."""
        # re-using sensor id as unique id for this device
        self._attr_unique_id = "comfortclick-apartment-vent-temperature-sensor"
        self.entity_description = SensorEntityDescription(
            key="vent_temperature_sensor",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
        )
        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        self._attr_native_value = self._get_temperature()
        # human-readable name
        self._attr_name = "Ventilation air temperature"

        # start listener on coordinator
        super().__init__(coordinator)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._attr_native_value

    @property
    def available(self) -> bool:
        """Return availability only when the active mode's temperature is known."""
        return super().available and self.native_value is not None

    def _get_temperature(self) -> float | None:
        mode = active_mode(self._coordinator.api, self._config)
        paths = {
            VentPresetModes.HOME: self._config.home_vent_air_temp,
            VentPresetModes.AWAY: self._config.away_vent_air_temp,
            VentPresetModes.GUESTS: self._config.guest_vent_air_temp,
        }
        path = paths.get(mode)
        if not isinstance(path, str) or not path.strip():
            return None
        return numeric_value(self._coordinator.api.get_value(path))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._attr_native_value = self._get_temperature()
        super()._handle_coordinator_update()

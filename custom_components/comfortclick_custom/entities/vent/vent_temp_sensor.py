from enum import StrEnum

from homeassistant.components.sensor import SensorEntityDescription, SensorDeviceClass, SensorStateClass, SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .vent_config import VentConfig
from ... import ComfortClickCoordinator

class VentPresetModes(StrEnum):
    HOME = "Home"
    AWAY = "Away"
    GUESTS = "Guests"

class VentTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Representation of a door with a lock entity."""

    value = None
    _mode = VentPresetModes

    def __init__(self, coordinator: ComfortClickCoordinator, config: VentConfig) -> None:
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
        # human-readable name
        self._attr_name = "Ventilation air temperature"

        # start listener on coordinator
        super().__init__(coordinator)

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.value

    def _check_home_mode(self) -> bool:
        is_home_mode_on = self._coordinator.api.get_value(self._config.home_mode)
        home_vent_temperature = self._coordinator.api.get_value(self._config.home_vent_air_temp)
        if is_home_mode_on and (self._mode != VentPresetModes.HOME or self.value != home_vent_temperature):
            self._mode = VentPresetModes.HOME
            self.value = home_vent_temperature
            self.async_write_ha_state()
            return True
        return False

    def _check_away_mode(self) -> bool:
        is_away_mode_on = self._coordinator.api.get_value(self._config.away_mode)
        away_vent_temperature = self._coordinator.api.get_value(self._config.away_vent_air_temp)
        if is_away_mode_on and (self._mode != VentPresetModes.AWAY or self.value != away_vent_temperature):
            self._mode = VentPresetModes.AWAY
            self.value = away_vent_temperature
            self.async_write_ha_state()
            return True
        return False

    def _check_guest_mode(self) -> bool:
        is_guest_mode_on = self._coordinator.api.get_value(self._config.guest_mode)
        guest_vent_temperature = self._coordinator.api.get_value(self._config.guest_vent_air_temp)
        if is_guest_mode_on and (self._mode != VentPresetModes.GUESTS or self.value != guest_vent_temperature):
            self._mode = VentPresetModes.GUESTS
            self.value = guest_vent_temperature
            self.async_write_ha_state()
            return True
        return False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        if self._check_home_mode():
            return
        if self._check_away_mode():
            return
        if self._check_guest_mode():
            return



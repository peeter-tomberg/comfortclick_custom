"""Exposes thermostats to home assistant."""

import logging
from dataclasses import dataclass

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class RoomThermostatConfig:
    """Class for keeping room thermostat configuration options."""

    name: str | None
    heating_id: str
    fan_id: str | None
    current_temperature_id: str
    target_temperature_id: str

    target_temperature_step: float = (
        0.5  # How many degrees can we go up/down in one click
    )
    min_temp: int = 18
    max_temp: int = 24


# Some fans return 0 when off, some return 2, some return 49 when on turned on,
# some return 10. I think it might be fan speed
FAN_ON_THRESHOLD = 5


class RoomThermostat(CoordinatorEntity, ClimateEntity):
    """Enables home assistant to control the room thermostat."""

    def __init__(
        self, coordinator: ComfortClickCoordinator, config: RoomThermostatConfig
    ) -> None:
        """Initialize the AC."""
        super().__init__(coordinator)

        self._attr_should_poll = False

        self._attr_hvac_modes = [HVACMode.HEAT_COOL]
        self._attr_hvac_mode = HVACMode.HEAT_COOL
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS

        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        # human-readable name
        self._attr_name = config.name
        # re-using heating id as unique id for this device
        self._attr_unique_id = f"room-1-{config.heating_id}"

        self._attr_target_temperature_step = config.target_temperature_step
        self._attr_min_temp = config.min_temp
        self._attr_max_temp = config.max_temp
        # start listener on coordinator

        _LOGGER.debug("Finished setting up")

    def _get_hvac_action_from_api_state(self) -> HVACAction:
        if self._coordinator.api.get_value(self._config.heating_id):
            return HVACAction.HEATING
        # If we have no fan, we cant cool
        if self._config.fan_id is None:
            return HVACAction.IDLE
        if self._coordinator.api.get_value(self._config.fan_id) > FAN_ON_THRESHOLD:
            return HVACAction.COOLING
        return HVACAction.IDLE

    def _get_current_temperature_from_api_state(self) -> float:
        current_temperature = self._coordinator.api.get_value(
            self._config.current_temperature_id
        )
        if current_temperature is None:
            return 0
        return round(float(current_temperature), 1)

    def _get_target_temperature_from_api_state(self) -> float:
        target_temperature = self._coordinator.api.get_value(
            self._config.target_temperature_id
        )
        if target_temperature is None:
            return 0
        return round(float(target_temperature), 1)

    # Set target temperature
    async def async_set_temperature(self, **kwargs: int) -> None:
        """Set new target temperature."""
        temperature = kwargs["temperature"]
        _LOGGER.debug("Updating target temperature", extra={"temperature": temperature})
        await self._coordinator.api.set_value(
            self._config.target_temperature_id, temperature
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        _LOGGER.debug("Received update from coordinator")

        new_current_temperature = self._get_current_temperature_from_api_state()
        new_target_temperature = self._get_target_temperature_from_api_state()
        new_hvac_action = self._get_hvac_action_from_api_state()
        has_changed = False

        # Did we actually get a change?
        if (
            new_current_temperature != self._attr_current_temperature
            or new_target_temperature != self._attr_target_temperature
            or new_hvac_action != self._attr_hvac_action
        ):
            has_changed = True

        self._attr_current_temperature = new_current_temperature
        self._attr_target_temperature = new_target_temperature
        self._attr_hvac_action = new_hvac_action

        # Sync state to HomeAssistant
        if has_changed:
            _LOGGER.debug("Updating HA states")
            self.async_write_ha_state()

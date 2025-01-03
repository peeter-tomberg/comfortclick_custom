"""Exposes fans to home assistant."""

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator

_LOGGER = logging.getLogger(__name__)

FAN_ON_THRESHOLD = 5
FAN_TEMP_DIFF_THRESHOLD = 0.25


@dataclass
class RoomFanConfig:
    """Class for keeping room fan configuration options."""

    name: str
    heating_id: str
    lock_id: str
    fan_id: str

    current_temperature_id: str
    target_temperature_id: str


class RoomFan(CoordinatorEntity, FanEntity):
    """Enables home assistant to control the room fan."""

    def __init__(
        self, coordinator: ComfortClickCoordinator, config: RoomFanConfig
    ) -> None:
        """Initialize the Fan."""
        # Entity
        self._attr_should_poll = False
        # FanEntity
        self._attr_supported_features = (
            FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        )
        self._attr_is_on = None

        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config

        # re-using heating id as unique id for this device
        self._attr_unique_id = config.fan_id
        # human-readable name
        self._attr_name = config.name

        # start listener on coordinator
        super().__init__(coordinator)

        _LOGGER.debug("Finished setting up")

    @property
    def is_on(self) -> bool | None:
        """Return true if the entity is on."""
        return self._attr_is_on

    def _get_fan_state_from_api_state(self) -> bool:
        # If lock is on, fan cant be on
        if not self._coordinator.api.get_value(self._config.lock_id):
            return False
        # If heating is on, fan cant be on
        if self._coordinator.api.get_value(self._config.heating_id):
            return False

        # If heating is off, meaning current temp is same or lower than target temp
        # Now we are trying to optimistically assume fan state based on temp
        current_temp = self._get_current_temperature_from_api_state()
        target_temp = self._get_target_temperature_from_api_state()

        if current_temp - target_temp < FAN_TEMP_DIFF_THRESHOLD:
            return False

        # Fall back to rely on comfort click logic

        return self._coordinator.api.get_value(self._config.fan_id) > FAN_ON_THRESHOLD

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

    async def async_turn_on(
        self,
        _speed: str | None = None,
        _percentage: int | None = None,
        _preset_mode: str | None = None,
        **_kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        await self._coordinator.api.set_value(self._config.lock_id, value=False)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn the fan off."""
        await self._coordinator.api.set_value(self._config.lock_id, value=True)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        _LOGGER.debug("Received update from coordinator")

        new_is_on = self._get_fan_state_from_api_state()
        has_changed = False

        # Did we actually get a change?
        if new_is_on != self._attr_is_on:
            has_changed = True

        self._attr_is_on = new_is_on

        # Sync state to HomeAssistant
        if has_changed:
            _LOGGER.debug("Updating HA states")
            self.async_write_ha_state()

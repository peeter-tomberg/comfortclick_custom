"""Exposes fans to home assistant."""

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator
from .values import numeric_value

_LOGGER = logging.getLogger(__name__)

# 5 is considered off, anything above 5 is on
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
    unique_id: str | None = None


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

        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        self._attr_is_on = self._get_fan_state_from_api_state()

        # re-using heating id as unique id for this device
        self._attr_unique_id = (
            config.unique_id if config.unique_id is not None else config.fan_id
        )
        # human-readable name
        self._attr_name = config.name

        # start listener on coordinator
        super().__init__(coordinator)

        _LOGGER.debug("Finished setting up")

    @property
    def available(self) -> bool:
        """Return whether coordinator and required fan readings are available."""
        return super().available and self._attr_is_on is not None

    @property
    def is_on(self) -> bool | None:
        """Return true if the entity is on."""
        return self._attr_is_on

    def _get_fan_state_from_api_state(self) -> bool | None:
        lock = self._coordinator.api.get_value(self._config.lock_id)
        heating = self._coordinator.api.get_value(self._config.heating_id)
        fan = numeric_value(self._coordinator.api.get_value(self._config.fan_id))
        current_temp = self._get_current_temperature_from_api_state()
        target_temp = self._get_target_temperature_from_api_state()
        if (
            not isinstance(lock, bool)
            or not isinstance(heating, bool)
            or fan is None
            or current_temp is None
            or target_temp is None
        ):
            return None
        # If lock is on, fan cant be on
        if lock:
            return False
        # If heating is on, fan cant be on
        if heating:
            return False
        # If heating is off, meaning current temp is same or lower than target temp
        # Now we are trying to optimistically assume fan state based on temp
        temp_diff = current_temp - target_temp

        if temp_diff < FAN_TEMP_DIFF_THRESHOLD:
            return False

        return fan > FAN_ON_THRESHOLD

    def _get_current_temperature_from_api_state(self) -> float | None:
        current_temperature = numeric_value(
            self._coordinator.api.get_value(self._config.current_temperature_id)
        )
        if current_temperature is None:
            return None
        return round(current_temperature, 1)

    def _get_target_temperature_from_api_state(self) -> float | None:
        target_temperature = numeric_value(
            self._coordinator.api.get_value(self._config.target_temperature_id)
        )
        if target_temperature is None:
            return None
        return round(target_temperature, 1)

    async def async_turn_on(
        self,
        _speed: str | None = None,
        _percentage: int | None = None,
        _preset_mode: str | None = None,
        **_kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        await self._coordinator.api.set_value(self._config.lock_id, value=False)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn the fan off."""
        await self._coordinator.api.set_value(self._config.lock_id, value=True)
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        _LOGGER.debug("Received update from coordinator")

        self._attr_is_on = self._get_fan_state_from_api_state()
        super()._handle_coordinator_update()

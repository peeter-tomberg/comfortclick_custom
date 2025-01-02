import logging
from dataclasses import dataclass
from typing import Optional, Any

from homeassistant.components.fan import FanEntityFeature, FanEntity
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class RoomFanConfig:
    """Class for keeping track of an item in inventory."""
    name: str
    heating_id: str
    lock_id: str
    fan_id: str

class RoomFan(CoordinatorEntity, FanEntity):
    # Entity
    _attr_should_poll = False
    # FanEntity
    _attr_supported_features = (FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF)
    _attr_is_on = None

    def __init__(self, coordinator: ComfortClickCoordinator, config: RoomFanConfig) -> None:
        """Initialize the Fan."""
        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config

        # re-using heating id as unique id for this device
        self._attr_unique_id = config.fan_id
        # human-readable name
        self._attr_name = config.name

        # start listener on coordinator
        super().__init__(coordinator)

        _LOGGER.info("Finished setting up fan")

    @property
    def is_on(self) -> bool | None:
        """Return true if the entity is on."""
        return self._attr_is_on

    def get_fan_state_from_api_state(self):
        # Fan will not turn on if heating is on
        if self._coordinator.api.get_value(self._config.heating_id):
            return False
        # Fans use a lock mechanism, so off means lock is off meaning device is on
        if not self._coordinator.api.get_value(self._config.lock_id):
            return True
        return False

    async def async_turn_on(self, speed: Optional[str] = None, percentage: Optional[int] = None,
                            preset_mode: Optional[str] = None, **kwargs: Any) -> None:
        """Turn on the fan."""
        await self._coordinator.api.set_value(self._config.lock_id, False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        await self._coordinator.api.set_value(self._config.lock_id, True)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        _LOGGER.info("Received update from coordinator")

        new_is_on = self.get_fan_state_from_api_state()
        has_changed = False

        # Did we actually get a change?
        if new_is_on != self._attr_is_on:
            has_changed = True

        self._attr_is_on = new_is_on

        # Sync state to HomeAssistant
        if has_changed:
            _LOGGER.info("Updating HA states for fan")
            self.async_write_ha_state()

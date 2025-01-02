import logging
from dataclasses import dataclass

from homeassistant.components.lock import LockEntity
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator

_LOGGER = logging.getLogger(__name__)

@dataclass
class BuildingLockConfig:
    """Class for keeping track of an item in inventory."""

    door_name: str = None
    door_id: str = None


class BuildingLock(CoordinatorEntity, LockEntity):
    """Representation of a door with a lock entity."""

    def __init__(self, coordinator: ComfortClickCoordinator, config: BuildingLockConfig) -> None:
        super().__init__(coordinator)
        """Initialize the door sensor."""
        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        # re-using door id as unique id for this device
        self._attr_unique_id = config.door_id
        # human-readable name
        self._attr_name = config.door_name

    @property
    def is_locked(self) -> bool:
        return not self._attr_is_open

    @property
    def is_open(self) -> bool:
        return self._attr_is_open

    async def unlock_door(self):
        await self._coordinator.api.set_value(self._config.door_id, True)

    def mark_door_as(self, is_open: bool):
        _LOGGER.debug(f"Marking door is_open as {is_open}")
        self._attr_is_open = is_open
        self.async_write_ha_state()

    # The front door is by default locked and can be unlocked for a bit
    def get_is_open_from_api_state(self):
        return self._coordinator.api.get_value(self._config.door_id)

    async def async_unlock(self, **kwargs) -> None:
        _LOGGER.debug("Unlocking door")
        await self.unlock_door()
        self.mark_door_as(True)
        return None

    async def async_lock(self, **kwargs) -> None:
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        updated_state_is_open = self.get_is_open_from_api_state()
        if updated_state_is_open != self.is_open:
            self.mark_door_as(updated_state_is_open)

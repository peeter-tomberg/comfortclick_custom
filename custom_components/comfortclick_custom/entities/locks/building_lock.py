"""Exposes locks to home assistant."""

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class BuildingLockConfig:
    """Class for keeping all configuration options."""

    door_name: str = None
    door_id: str = None


class BuildingLock(CoordinatorEntity, LockEntity):
    """Representation of a door with a lock entity."""

    def __init__(
        self, coordinator: ComfortClickCoordinator, config: BuildingLockConfig
    ) -> None:
        """Initialize the door sensor."""
        super().__init__(coordinator)
        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        # re-using door id as unique id for this device
        self._attr_unique_id = config.door_id
        # human-readable name
        self._attr_name = config.door_name

    @property
    def is_locked(self) -> bool:
        """Determine if door is locked."""
        return not self._attr_is_open

    @property
    def is_open(self) -> bool:
        """Determine if door is open."""
        return self._attr_is_open

    async def _unlock_door(self) -> None:
        await self._coordinator.api.set_value(
            device_name=self._config.door_id, value=True
        )

    def _mark_door_as_open(self) -> None:
        _LOGGER.debug(msg="Marking door as open")
        self._attr_is_open = True
        self.async_write_ha_state()

    def _mark_door_as_locked(self) -> None:
        _LOGGER.debug(msg="Marking door as locked")
        self._attr_is_open = False
        self.async_write_ha_state()

    # The front door is by default locked and can be unlocked for a bit
    def _get_is_open_from_api_state(self) -> bool:
        return self._coordinator.api.get_value(device_name=self._config.door_id)

    async def async_unlock(self, **_kwargs: Any) -> None:
        """Unlocks the door."""
        _LOGGER.debug("Unlocking door")
        await self._unlock_door()
        self._mark_door_as_open()

    async def async_lock(self, **_kwargs: Any) -> None:
        """Do nothing as our locks auto lock after a time period."""
        return

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        updated_state_is_open = self._get_is_open_from_api_state()
        if updated_state_is_open != self.is_open:
            if updated_state_is_open:
                self._mark_door_as_open()
            else:
                self._mark_door_as_locked()

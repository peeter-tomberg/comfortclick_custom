"""Expose ComfortClick doorbell actions as events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_DOORBELL
from .coordinator import ComfortClickCoordinator

if TYPE_CHECKING:
    from typing import ClassVar

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one doorbell event entity for the controller connection."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator
    async_add_entities([ComfortClickDoorbell(coordinator, config_entry.entry_id)])


class ComfortClickDoorbell(CoordinatorEntity[ComfortClickCoordinator], EventEntity):
    """A ring received from the controller, which supplies no door identity."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types: ClassVar[list[str]] = ["ring"]
    _attr_has_entity_name = True
    _attr_name = "Doorbell"

    def __init__(
        self, coordinator: ComfortClickCoordinator, config_entry_id: str
    ) -> None:
        """Initialize the entity without replaying cached actions."""
        super().__init__(coordinator)
        self._config_entry_id = config_entry_id
        self._attr_unique_id = f"{config_entry_id}_doorbell"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry_id)},
            name="ComfortClick",
            manufacturer="ComfortClick",
        )
        self._last_batch = coordinator.data
        self._event_sequence = 0

    async def async_added_to_hass(self) -> None:
        """Start observing new batches and let the base class remove the listener."""
        await super().async_added_to_hass()
        self._last_batch = self.coordinator.data

    @callback
    def _handle_coordinator_update(self) -> None:
        """Publish every new ring, including multiple rings in one poll."""
        rings = self.coordinator.data
        if self.available and rings is not self._last_batch:
            self._last_batch = rings
            for ring in rings or ():
                self._event_sequence += 1
                attributes = {
                    "sound": ring.sound,
                    # Older HA event entities round receipt time to milliseconds.
                    # Keep successive rings distinct even within that millisecond.
                    "event_sequence": self._event_sequence,
                }
                if ring.timestamp is not None:
                    attributes["timestamp"] = ring.timestamp
                self._trigger_event("ring", attributes)
                self.async_write_ha_state()
                # A bus event is never emitted by state restoration or an
                # availability change, making automation triggers unambiguous.
                self.hass.bus.async_fire(
                    EVENT_DOORBELL,
                    {
                        "config_entry_id": self._config_entry_id,
                        "entity_id": self.entity_id,
                        "event_type": "ring",
                        **attributes,
                    },
                )
            if rings:
                return
        super()._handle_coordinator_update()

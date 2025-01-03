"""Entry point for home assistant to set up FanEntity classes."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities.ac.room_fan import RoomFan
from .util.load_fans_config import load_fans_config

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fans."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator

    configs = await load_fans_config()
    sensors = [RoomFan(coordinator, config) for config in configs]

    # Create the sensors.
    async_add_entities(sensors)

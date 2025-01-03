"""Entry point for home assistant to set up SelectEntity classes."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities.vent.vent_mode_select import VentModeSelect
from .entities.vent.vent_temp_select import VentTempSelect
from .util.load_vent_config import load_vent_config

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Selects."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator

    config = await load_vent_config()
    sensors = [VentModeSelect(coordinator, config), VentTempSelect(coordinator, config)]

    # Create the sensors.
    async_add_entities(sensors)

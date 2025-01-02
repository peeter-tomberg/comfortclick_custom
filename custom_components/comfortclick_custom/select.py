import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ComfortClickCoordinator
from .const import DOMAIN
from .entities.vent.vent_mode_select import VentModeSelect
from .entities.vent.vent_temp_select import VentTempSelect
from .util.load_vent_config import load_vent_config

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    """Set up the Sensors."""
    # This gets the data update coordinator from hass.data as specified in your __init__.py
    coordinator: ComfortClickCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    # Enumerate all the sensors in your data value from your DataUpdateCoordinator and add an instance of your sensor class
    # to a list for each one.
    # This maybe different in your specific case, depending on how your data is structured

    config = await load_vent_config()

    sensors = [
        VentModeSelect(coordinator, config),
        VentTempSelect(coordinator, config)
    ]

    # Create the sensors.
    async_add_entities(sensors)

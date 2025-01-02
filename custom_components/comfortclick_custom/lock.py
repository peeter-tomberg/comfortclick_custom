import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ComfortClickCoordinator
from .entities.locks.building_lock import BuildingLock
from .util.load_lock_config import load_lock_config

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

    configs = await load_lock_config()
    sensors = list(map(lambda config: BuildingLock(coordinator, config), configs))

    # Create the sensors.
    async_add_entities(sensors)

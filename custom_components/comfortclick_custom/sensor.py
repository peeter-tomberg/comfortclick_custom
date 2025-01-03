"""Entry point for home assistant to set up SensorEntity classes."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities.utilities.utilities_sensor import UtilitiesSensor
from .entities.vent.vent_temp_sensor import VentTemperatureSensor
from .util.load_utilities_config import load_utilities_config
from .util.load_vent_config import load_vent_config

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator

    utilities_configs = await load_utilities_config()
    vent_config = await load_vent_config()

    sensors = [UtilitiesSensor(coordinator, config) for config in utilities_configs]

    sensors.append(VentTemperatureSensor(coordinator, vent_config))

    # Create the sensors.
    async_add_entities(sensors)

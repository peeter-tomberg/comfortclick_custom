"""Custom ComfortClick integration for home assistant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform

from .api import ApiInstance
from .const import DOMAIN
from .coordinator import ComfortClickCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS = [
    Platform.CLIMATE,
    Platform.LOCK,
    Platform.FAN,
    Platform.SENSOR,
    Platform.SELECT,
]

type ApiConfigEntry = ConfigEntry[ApiInstance]


@dataclass
class RuntimeData:
    """Data class to keep references that are used across the package."""

    coordinator: DataUpdateCoordinator
    cancel_update_listener: Callable


async def async_setup_entry(hass: HomeAssistant, config_entry: ApiConfigEntry) -> bool:
    """Entry function for HomeAssistant to start wiring things up."""
    hass.data.setdefault(DOMAIN, {})

    host = config_entry.data[CONF_HOST]
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]

    coordinator = ComfortClickCoordinator(
        hass, host=host, username=username, password=password
    )

    await coordinator.async_config_entry_first_refresh()

    cancel_update_listener = config_entry.add_update_listener(_async_update_listener)

    hass.data[DOMAIN][config_entry.entry_id] = RuntimeData(
        coordinator, cancel_update_listener
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def _async_update_listener(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Handle config options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN][config_entry.entry_id].cancel_update_listener()

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)

    return unload_ok

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

    coordinator: ComfortClickCoordinator
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

    setup_complete = False
    cancel_update_listener = None
    try:
        await coordinator.async_config_entry_first_refresh()
        cancel_update_listener = config_entry.add_update_listener(
            _async_update_listener
        )
        hass.data[DOMAIN][config_entry.entry_id] = RuntimeData(
            coordinator, cancel_update_listener
        )
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
        setup_complete = True
        return True
    finally:
        if not setup_complete:
            if cancel_update_listener is not None:
                cancel_update_listener()
            hass.data[DOMAIN].pop(config_entry.entry_id, None)
            await coordinator.async_shutdown()


async def _async_update_listener(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Handle config options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    if unload_ok:
        runtime = hass.data[DOMAIN].pop(config_entry.entry_id)
        runtime.cancel_update_listener()
        await runtime.coordinator.async_shutdown()

    return unload_ok

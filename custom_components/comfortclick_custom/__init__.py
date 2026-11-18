"""Custom ComfortClick integration for home assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.helpers import config_validation as cv

from .api import ApiInstance
from .const import DOMAIN
from .coordinator import ComfortClickCoordinator
from .migration import CONFIG_ENTRY_VERSION, async_import_mapping_options
from .panel import async_register_configuration_panel

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS = [
    Platform.CLIMATE,
    Platform.EVENT,
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


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Make configuration available even while a controller is offline."""
    await async_register_configuration_panel(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Persist all legacy mappings before enabling options-only configuration."""
    if config_entry.version > CONFIG_ENTRY_VERSION:
        _LOGGER.error("Cannot load a newer ComfortClick configuration version")
        return False
    if config_entry.version == CONFIG_ENTRY_VERSION:
        return True
    try:
        options = await async_import_mapping_options(config_entry.options)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        # Parser exceptions can contain raw YAML values, so omit their contents.
        _LOGGER.error(  # noqa: TRY400
            "Cannot migrate ComfortClick mappings. Correct malformed mappings or "
            "ambiguous door/meter slot names in comfortclick_custom.yaml, then retry. "
            "The saved configuration and version have not been changed"
        )
        return False
    hass.config_entries.async_update_entry(
        config_entry, options=options, version=CONFIG_ENTRY_VERSION
    )
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ApiConfigEntry) -> bool:
    """Entry function for HomeAssistant to start wiring things up."""
    hass.data.setdefault(DOMAIN, {})

    host = config_entry.data[CONF_HOST]
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]

    coordinator = ComfortClickCoordinator(
        hass,
        host=host,
        username=username,
        password=password,
        verify_ssl=config_entry.options.get(
            CONF_VERIFY_SSL, config_entry.data.get(CONF_VERIFY_SSL, False)
        ),
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

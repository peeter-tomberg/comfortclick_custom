"""Connect to ComfortClick and expose its mapping options."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .connection import connection_errors, normalize_host, validate_input
from .const import DOMAIN
from .migration import CONFIG_ENTRY_VERSION, empty_mapping_options
from .options_flow import OptionsFlow

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_VERIFY_SSL, default=False): bool,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle connection setup for ComfortClick."""

    VERSION = CONFIG_ENTRY_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlow:
        """Expose entity mappings and connection preferences."""
        return OptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict | None = None) -> Any:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                data = {**user_input, CONF_HOST: normalize_host(user_input[CONF_HOST])}
                info = await validate_input(self.hass, data)
                options = empty_mapping_options()
                options[CONF_VERIFY_SSL] = data.get(CONF_VERIFY_SSL, False)
                return self.async_create_entry(
                    title=info["title"], data=data, options=options
                )
            except Exception as error:  # noqa: BLE001 - Return a credential-safe error.
                errors = connection_errors(error)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

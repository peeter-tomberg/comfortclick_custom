"""Config flow for Hello World integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ApiInstance, AuthorizationError, HttpStatusNotOkError
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_HOST, description={"suggested_value": "https://68.67.65.65"}
        ): str,
        vol.Required(CONF_USERNAME, description={"suggested_value": "test"}): str,
        vol.Required(CONF_PASSWORD, description={"suggested_value": "1234"}): str,
        vol.Optional(CONF_VERIFY_SSL, default=False): bool,
    }
)

MIN_HOST_LENGTH = 3


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """
    Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    if len(data[CONF_HOST]) < MIN_HOST_LENGTH:
        raise InvalidHost

    api = ApiInstance(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_HOST],
        session=async_get_clientsession(hass),
        verify_ssl=data.get(CONF_VERIFY_SSL, False),
    )

    try:
        result = await api.connect()
        if not result:
            raise CannotConnect
        return {"title": data[CONF_HOST]}
    finally:
        await api.disconnect()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hello World."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlow:
        """Expose certificate verification for existing entries."""
        return OptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict | None = None) -> Any:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                return self.async_create_entry(title=info["title"], data=user_input)
            except aiohttp.ClientConnectorCertificateError:
                errors["base"] = "ssl_error"
            except AuthorizationError:
                errors["base"] = "invalid_auth"
            except (
                CannotConnect,
                aiohttp.ClientError,
                TimeoutError,
                HttpStatusNotOkError,
            ):
                errors["base"] = "cannot_connect"
            except InvalidHost:
                errors["host"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class OptionsFlow(config_entries.OptionsFlow):
    """Configure certificate verification without recreating entities."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Keep the entry without assigning Home Assistant's config_entry property."""
        self._entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> Any:
        """Save verification preferences even while the controller is unavailable."""
        if user_input is not None:
            options = {**self._entry.options, **user_input}
            if self._entry.state is not config_entries.ConfigEntryState.LOADED:
                # Failed setup has no update listener. Save before scheduling
                # reload so the verification preference takes effect immediately.
                self.hass.config_entries.async_update_entry(
                    self._entry, options=options
                )
                self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
            return self.async_create_entry(title="", data=options)
        verify_ssl = self._entry.options.get(
            CONF_VERIFY_SSL, self._entry.data.get(CONF_VERIFY_SSL, False)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_VERIFY_SSL, default=verify_ssl): bool}
            ),
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""

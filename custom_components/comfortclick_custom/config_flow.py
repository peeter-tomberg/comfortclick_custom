"""Connect to ComfortClick and expose its mapping options."""

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

from .api import (
    ApiInstance,
    AuthorizationError,
    HttpStatusNotOkError,
    create_api_session,
)
from .const import DOMAIN
from .options_flow import OptionsFlow

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


async def validate_input(_hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """
    Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    if len(data[CONF_HOST]) < MIN_HOST_LENGTH:
        raise InvalidHost

    session = create_api_session()
    api = ApiInstance(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_HOST],
        session=session,
        verify_ssl=data.get(CONF_VERIFY_SSL, False),
    )

    try:
        result = await api.connect()
        if not result:
            raise CannotConnect
        return {"title": data[CONF_HOST]}
    finally:
        try:
            await api.disconnect()
        finally:
            await session.close()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle connection setup for ComfortClick."""

    VERSION = 1

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


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""

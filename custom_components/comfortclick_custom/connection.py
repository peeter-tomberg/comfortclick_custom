"""Validate controller connection settings without changing live configuration."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import aiohttp
from homeassistant import exceptions
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL

from .api import (
    ApiInstance,
    ApiResponseError,
    AuthorizationError,
    HttpStatusNotOkError,
    create_api_session,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class CannotConnect(exceptions.HomeAssistantError):
    """The controller could not be reached."""


class InvalidHost(exceptions.HomeAssistantError):
    """The controller URL is not a supported HTTP base URL."""


def normalize_host(value: Any) -> str:
    """Require an HTTP base URL with no embedded credentials or query string."""
    if not isinstance(value, str):
        raise InvalidHost
    host = value.strip().rstrip("/")
    try:
        parsed = urlsplit(host)
        invalid = (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in host
            or "#" in host
            or any(character.isspace() for character in host)
        )
        # Accessing port also rejects malformed and out-of-range port numbers.
        _ = parsed.port
    except ValueError as error:
        raise InvalidHost from error
    if invalid:
        raise InvalidHost
    return host


async def validate_input(_hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Check login with an owned client; never poll events or send device commands."""
    host = normalize_host(data[CONF_HOST])
    if not isinstance(data[CONF_USERNAME], str) or not data[CONF_USERNAME].strip():
        raise AuthorizationError
    session = create_api_session()
    api = None
    try:
        api = ApiInstance(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            host,
            session=session,
            verify_ssl=data.get(CONF_VERIFY_SSL, False),
        )
        if not await api.connect():
            raise CannotConnect
        return {"title": host}
    finally:
        try:
            if api is not None:
                await api.disconnect()
        finally:
            await session.close()


def connection_errors(error: Exception) -> dict[str, str]:
    """Classify failures without logging response bodies or credential values."""
    if isinstance(error, InvalidHost):
        return {CONF_HOST: "invalid_host"}
    if isinstance(error, aiohttp.ClientConnectorCertificateError):
        return {"base": "ssl_error"}
    if isinstance(error, AuthorizationError):
        return {"base": "invalid_auth"}
    if isinstance(error, HttpStatusNotOkError):
        details = error.args[0] if error.args else None
        if isinstance(details, dict) and details.get("status") in (
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
        ):
            return {"base": "invalid_auth"}
    if isinstance(
        error,
        CannotConnect
        | aiohttp.ClientError
        | TimeoutError
        | HttpStatusNotOkError
        | ApiResponseError,
    ):
        return {"base": "cannot_connect"}
    _LOGGER.error("Unexpected connection validation failure (%s)", type(error).__name__)
    return {"base": "unknown"}

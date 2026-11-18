"""Coordinator object class."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ApiInstance, DoorbellRing, create_api_session
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ComfortClickCoordinator(DataUpdateCoordinator[tuple[DoorbellRing, ...]]):
    """Coordinator object that has subscribers who ask it for latest data."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        username: str,
        password: str,
        *,
        verify_ssl: bool = False,
    ) -> None:
        """Initialize coordinator."""
        _LOGGER.info("Initializing coordinator")
        self._session = create_api_session()
        self._shutdown_lock = asyncio.Lock()
        self._session_closed = False
        self.api = ApiInstance(
            host=host,
            username=username,
            password=password,
            session=self._session,
            verify_ssl=verify_ssl,
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self.async_update_data,
            update_interval=timedelta(seconds=1),
        )
        self._unsub_stop = hass.bus.async_listen(
            EVENT_HOMEASSISTANT_STOP, self._async_stop
        )
        _LOGGER.info("Finished initializing coordinator")

    async def _async_setup(self) -> None:
        """Do initialization logic."""
        _LOGGER.info("Setting up coordinator / connecting to API")
        await self.api.connect()
        await self.api.initialize_state()
        _LOGGER.info("Connected and fetched initial state")

    async def async_update_data(self) -> tuple[DoorbellRing, ...]:
        """Update cached values and return only this poll's doorbell rings."""
        _LOGGER.debug("Polling API for latest state")
        return await self.api.poll()

    async def _async_stop(self, _event: Event) -> None:
        """Release the owned client when Home Assistant stops."""
        await self.async_shutdown()

    async def async_shutdown(self) -> None:
        """Stop refreshes and release the server session and owned HTTP client."""
        async with self._shutdown_lock:
            if self._session_closed:
                return
            if self._unsub_stop is not None:
                self._unsub_stop()
                self._unsub_stop = None
            try:
                await super().async_shutdown()
                await self.api.disconnect()
            finally:
                await self._session.close()
                self._session_closed = True

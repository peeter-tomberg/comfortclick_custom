import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ApiInstance
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ComfortClickCoordinator(DataUpdateCoordinator):
    def __init__(
        self, hass: HomeAssistant, host: str, username: str, password: str
    ) -> None:
        """Initialize coordinator."""
        _LOGGER.info("Initializing coordinator")
        self.api = ApiInstance(host=host, username=username, password=password)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self.async_update_data,
            update_interval=timedelta(seconds=1),
        )
        _LOGGER.info("Finished initializing coordinator")

    async def _async_setup(self) -> None:
        """Do initialization logic."""
        _LOGGER.info("Setting up coordinator / connecting to API")
        await self.api.connect()
        await self.api.initialize_state()
        _LOGGER.info("Connected and fetched initial state")

    async def async_update_data(self) -> None:
        _LOGGER.info("Polling API for latest state")
        await self.api.poll()

"""Exposes vent mode control to home assistant."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator
from .vent_config import VentConfig
from .vent_state import VentPresetModes, active_mode

_LOGGER = logging.getLogger(__name__)


class VentModeSelect(CoordinatorEntity, SelectEntity):
    """Enables home assistant to choose between vent modes."""

    def __init__(
        self, coordinator: ComfortClickCoordinator, config: VentConfig
    ) -> None:
        """Initialize the door sensor."""
        self._attr_options = [
            VentPresetModes.AWAY,
            VentPresetModes.HOME,
            VentPresetModes.GUESTS,
        ]

        # re-using sensor id as unique id for this device
        self._attr_unique_id = "comfortclick-apartment-vent-mode-select"
        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        self._attr_current_option = active_mode(coordinator.api, config)
        # human-readable name
        self._attr_name = "Ventilation mode"

        # start listener on coordinator
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        """Return availability only when the active mode is known."""
        return super().available and self.current_option is not None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug(msg="Changing option", extra={"option": option})
        if option == VentPresetModes.HOME:
            await self._coordinator.api.set_value(self._config.home_mode, value=True)
        if option == VentPresetModes.AWAY:
            await self._coordinator.api.set_value(self._config.away_mode, value=True)
        if option == VentPresetModes.GUESTS:
            await self._coordinator.api.set_value(self._config.guest_mode, value=True)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._attr_current_option = active_mode(self._coordinator.api, self._config)
        super()._handle_coordinator_update()

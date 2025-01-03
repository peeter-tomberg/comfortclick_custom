"""Exposes vent mode control to home assistant."""

import logging
from enum import StrEnum

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator
from .vent_config import VentConfig

_LOGGER = logging.getLogger(__name__)


class VentPresetModes(StrEnum):
    """Available vent modes in comfort click."""

    HOME = "Home"
    AWAY = "Away"
    GUESTS = "Guests"


class VentModeSelect(CoordinatorEntity, SelectEntity):
    """Enables home assistant to choose between vent modes."""

    current_option = None | VentPresetModes
    options: list[VentPresetModes] = frozenset(
        [VentPresetModes.AWAY, VentPresetModes.HOME, VentPresetModes.GUESTS]
    )

    def __init__(
        self, coordinator: ComfortClickCoordinator, config: VentConfig
    ) -> None:
        """Initialize the door sensor."""
        # re-using sensor id as unique id for this device
        self._attr_unique_id = "comfortclick-apartment-vent-mode-select"
        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        # human-readable name
        self._attr_name = "Ventilation mode"

        # start listener on coordinator
        super().__init__(coordinator)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug(msg="Changing option", extra={"option": option})
        if option == VentPresetModes.HOME:
            await self._coordinator.api.set_value(self._config.home_mode, value=True)
        if option == VentPresetModes.AWAY:
            await self._coordinator.api.set_value(self._config.away_mode, value=True)
        if option == VentPresetModes.GUESTS:
            await self._coordinator.api.set_value(self._config.guest_mode, value=True)

    def _check_home_mode(self) -> bool:
        is_home_mode_on = self._coordinator.api.get_value(self._config.home_mode)
        if is_home_mode_on and self.current_option != VentPresetModes.HOME:
            self.current_option = VentPresetModes.HOME
            self.async_write_ha_state()
            return True
        return False

    def _check_away_mode(self) -> bool:
        is_away_mode_on = self._coordinator.api.get_value(self._config.away_mode)
        if is_away_mode_on and self.current_option != VentPresetModes.AWAY:
            self.current_option = VentPresetModes.AWAY
            self.async_write_ha_state()
            return True
        return False

    def _check_guest_mode(self) -> bool:
        is_guest_mode_on = self._coordinator.api.get_value(self._config.guest_mode)
        if is_guest_mode_on and self.current_option != VentPresetModes.GUESTS:
            self.current_option = VentPresetModes.GUESTS
            self.async_write_ha_state()
            return True
        return False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        if self._check_home_mode():
            return
        if self._check_away_mode():
            return
        if self._check_guest_mode():
            return

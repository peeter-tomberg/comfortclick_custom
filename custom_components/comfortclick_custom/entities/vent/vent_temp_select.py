"""Exposes vent temperature control to home assistant."""

import logging
from enum import StrEnum

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ... import ComfortClickCoordinator
from .vent_config import VentConfig

_LOGGER = logging.getLogger(__name__)


class VentTempModes(StrEnum):
    """Available vent temperature modes in comfort click."""

    WARM_AIR = "Warm air"
    COLD_AIR = "Cold air"


class VentTempSelect(CoordinatorEntity, SelectEntity):
    """Enables home assistant to choose between temp modes."""

    current_option = None | VentTempModes
    options: list[VentTempModes] = frozenset(
        [VentTempModes.WARM_AIR, VentTempModes.COLD_AIR]
    )

    def __init__(
        self, coordinator: ComfortClickCoordinator, config: VentConfig
    ) -> None:
        """Initialize the door sensor."""
        # re-using sensor id as unique id for this device
        self._attr_unique_id = "comfortclick-apartment-vent-temp-select"
        # coordinator that manages state
        self._coordinator = coordinator
        self._config = config
        # human-readable name
        self._attr_name = "Ventilation temperature"

        # start listener on coordinator
        super().__init__(coordinator)

    def _update_mode(self, is_winter_mode_on: bool) -> None:
        if is_winter_mode_on and self.current_option != VentTempModes.WARM_AIR:
            _LOGGER.warning("Setting mode to warm air from update_mode")
            self.current_option = VentTempModes.WARM_AIR
            self.async_write_ha_state()
        if not is_winter_mode_on and self.current_option != VentTempModes.COLD_AIR:
            _LOGGER.warning("Setting mode to cold air from update_mode")
            self.current_option = VentTempModes.COLD_AIR
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.warning(f"Changing option to {option}")
        # If we want warm air pushing in, we should turn winter mode on
        if option == VentTempModes.WARM_AIR:
            self._update_mode(is_winter_mode_on=True)
            await self._coordinator.api.set_value(
                self._config.vent_winter_mode, value=True
            )
        if option == VentTempModes.COLD_AIR:
            self._update_mode(is_winter_mode_on=False)
            await self._coordinator.api.set_value(
                self._config.vent_winter_mode, value=False
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        # If winter mode is on, that means warm air is being pushed in
        is_winter_mode_on = self._coordinator.api.get_value(
            self._config.vent_winter_mode
        )
        self._update_mode(is_winter_mode_on=is_winter_mode_on)

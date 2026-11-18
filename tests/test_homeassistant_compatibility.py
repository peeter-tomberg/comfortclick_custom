"""Exercise compatibility with the installed Home Assistant climate API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM

from custom_components.comfortclick_custom.coordinator import ComfortClickCoordinator
from custom_components.comfortclick_custom.entities.ac.room_thermostat import (
    RoomThermostat,
    RoomThermostatConfig,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from homeassistant.util.unit_system import UnitSystem


@pytest.fixture
async def hass(tmp_path: Path) -> AsyncGenerator[HomeAssistant]:
    instance = HomeAssistant(str(tmp_path))
    try:
        yield instance
    finally:
        await instance.async_stop(force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("units", "minimum", "maximum"),
    [
        (METRIC_SYSTEM, 18, 24),
        (US_CUSTOMARY_SYSTEM, 64, 75),
    ],
)
async def test_thermostat_limits_use_native_celsius(
    hass: HomeAssistant, units: UnitSystem, minimum: float, maximum: float
):
    hass.config.units = units
    coordinator = ComfortClickCoordinator(
        hass, "http://comfortclick.test", "username", "password"
    )
    thermostat = RoomThermostat(
        coordinator,
        RoomThermostatConfig(
            name="Living room",
            heating_id="heating",
            fan_id=None,
            current_temperature_id="current",
            target_temperature_id="target",
        ),
    )
    thermostat.hass = hass

    # Home Assistant consumes the native unit when producing the user's limits.
    capabilities = thermostat.capability_attributes
    assert capabilities["min_temp"] == minimum
    assert capabilities["max_temp"] == maximum

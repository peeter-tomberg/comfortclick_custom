"""Load thermostat mappings from saved integration options."""

import logging
from collections.abc import Mapping
from typing import Any

from ..entities.ac.room_thermostat import RoomThermostatConfig

_LOGGER = logging.getLogger(__name__)


async def load_thermostats_config(
    options: Mapping[str, Any] | None = None,
) -> list[RoomThermostatConfig]:
    """Read saved AC mappings, using no entities for unconfigured sections."""
    data = options if options is not None else {}

    return [
        RoomThermostatConfig(
            name=item.get("name", None),
            heating_id=item.get("heating_id", None),
            fan_id=item.get("fan_id", None),
            current_temperature_id=item.get("current_temperature_id", None),
            target_temperature_id=item.get("target_temperature_id", None),
            target_temperature_step=float(item.get("target_temperature_step", 0.5)),
            min_temp=float(item.get("min_temp", 18)),
            max_temp=float(item.get("max_temp", 24)),
            unique_id=item.get("unique_id"),
            area_id=item.get("area_id"),
        )
        for item in data.get("thermostats", [])
    ]

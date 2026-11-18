"""Utility helper to read thermostats yaml config file."""

import logging
from collections.abc import Mapping
from typing import Any

from ..entities.ac.room_thermostat import RoomThermostatConfig
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


async def load_thermostats_config(
    options: Mapping[str, Any] | None = None,
) -> list[RoomThermostatConfig]:
    """Read saved AC mappings, falling back to YAML when not configured."""
    data = (
        options
        if options is not None and "thermostats" in options
        else await read_yaml()
    )

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
        )
        for item in data.get("thermostats", [])
    ]

"""Utility helper to read fans yaml config file."""

import logging
from collections.abc import Mapping
from typing import Any

from ..entities.ac.room_fan import RoomFanConfig
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


async def load_fans_config(
    options: Mapping[str, Any] | None = None,
) -> list[RoomFanConfig]:
    """Read saved fan mappings, falling back to YAML when not configured."""
    data = options if options is not None and "fans" in options else await read_yaml()
    return [
        RoomFanConfig(
            name=item.get("name", None),
            lock_id=item.get("lock_id", None),
            fan_id=item.get("fan_id", None),
            heating_id=item.get("heating_id", None),
            current_temperature_id=item.get("current_temperature_id", None),
            target_temperature_id=item.get("target_temperature_id", None),
            unique_id=item.get("unique_id"),
            area_id=item.get("area_id"),
        )
        for item in data.get("fans", [])
    ]

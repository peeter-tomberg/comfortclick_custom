"""Load fan mappings from saved integration options."""

import logging
from collections.abc import Mapping
from typing import Any

from ..entities.ac.room_fan import RoomFanConfig

_LOGGER = logging.getLogger(__name__)


async def load_fans_config(
    options: Mapping[str, Any] | None = None,
) -> list[RoomFanConfig]:
    """Read saved fan mappings, using no entities for unconfigured sections."""
    data = options if options is not None else {}
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

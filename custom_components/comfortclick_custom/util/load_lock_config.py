"""Load door lock mappings from saved integration options."""

import logging
from collections.abc import Mapping
from typing import Any

from ..entities.locks.building_lock import BuildingLockConfig

_LOGGER = logging.getLogger(__name__)


async def load_lock_config(
    options: Mapping[str, Any] | None = None,
) -> list[BuildingLockConfig]:
    """Read saved door mappings, using no entities for unconfigured sections."""
    data = options if options is not None else {}
    return [
        BuildingLockConfig(
            door_name=item.get("door_name", None),
            door_id=item.get("door_id", None),
            unique_id=item.get("unique_id"),
        )
        for item in data.get("locks", [])
        if isinstance(item.get("door_id"), str) and item["door_id"].strip()
    ]

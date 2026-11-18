"""Utility helper to read locks yaml config file."""

import logging
from collections.abc import Mapping
from typing import Any

from ..entities.locks.building_lock import BuildingLockConfig
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


async def load_lock_config(
    options: Mapping[str, Any] | None = None,
) -> list[BuildingLockConfig]:
    """Read saved door mappings, falling back to YAML when not configured."""
    data = options if options is not None and "locks" in options else await read_yaml()
    return [
        BuildingLockConfig(
            door_name=item.get("door_name", None),
            door_id=item.get("door_id", None),
            unique_id=item.get("unique_id"),
        )
        for item in data.get("locks", [])
        if isinstance(item.get("door_id"), str) and item["door_id"].strip()
    ]

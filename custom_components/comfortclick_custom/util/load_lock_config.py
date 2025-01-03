"""Utility helper to read locks yaml config file."""

import logging

from ..entities.locks.building_lock import BuildingLockConfig
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


async def load_lock_config() -> list[BuildingLockConfig]:
    """Read locks config file."""
    data = await read_yaml("/config/locks.yaml")
    return [
        BuildingLockConfig(
            door_name=item.get("door_name", None), door_id=item.get("door_id", None)
        )
        for item in data.get("locks", [])
    ]

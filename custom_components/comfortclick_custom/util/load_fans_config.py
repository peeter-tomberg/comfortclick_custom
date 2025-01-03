"""Utility helper to read fans yaml config file."""

import logging

from ..entities.ac.room_fan import RoomFanConfig
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


async def load_fans_config() -> list[RoomFanConfig]:
    """Read fans config file."""
    data = await read_yaml("/config/fans.yaml")
    return [
        RoomFanConfig(
            name=item.get("name", None),
            lock_id=item.get("lock_id", None),
            fan_id=item.get("fan_id", None),
            heating_id=item.get("heating_id", None),
        )
        for item in data.get("fans", [])
    ]

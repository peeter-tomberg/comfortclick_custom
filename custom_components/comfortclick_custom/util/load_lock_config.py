import logging

from ..entities.locks.building_lock import BuildingLockConfig
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


async def load_lock_config() -> list[BuildingLockConfig]:
    data = await read_yaml("/config/locks.yaml")
    return list(
        map(
            lambda item: BuildingLockConfig(
                door_name=item.get("door_name", None), door_id=item.get("door_id", None)
            ),
            data.get("locks", []),
        )
    )

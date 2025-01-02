import logging
from typing import List

from ..entities.ac.room_fan import RoomFanConfig
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


async def load_fans_config() -> List[RoomFanConfig]:
    data = await read_yaml("/config/fans.yaml")
    return list(
        map(lambda item: RoomFanConfig(name=item.get("name", None), lock_id=item.get("lock_id", None),
                                       fan_id=item.get("fan_id", None), heating_id=item.get("heating_id", None)),
            data.get("fans", [])))

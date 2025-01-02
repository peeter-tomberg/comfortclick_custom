import logging
from typing import List

from .read_yaml import read_yaml
from ..entities.ac.room_thermostat import RoomThermostatConfig

_LOGGER = logging.getLogger(__name__)


async def load_thermostats_config() -> List[RoomThermostatConfig]:
    data = await read_yaml("/config/thermostats.yaml")
    return list(
        map(lambda item: RoomThermostatConfig(name=item.get("name", None),
                                              heating_id=item.get("heating_id", None),
                                              fan_id=item.get("fan_id", None),
                                              current_temperature_id=item.get("current_temperature_id", None),
                                              target_temperature_id=item.get("target_temperature_id", None),
                                              target_temperature_step=float(item.get("target_temperature_step", 0.5)),
                                              min_temp=int(item.get("min_temp", 18)),
                                              max_temp=int(item.get("max_temp", 28))
                                              ),
            data.get("thermostats", [])))

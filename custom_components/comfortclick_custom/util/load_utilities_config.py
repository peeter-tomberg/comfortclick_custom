import logging

from ..entities.utilities.utilities_sensor import (
    ElectricitySensor,
    HeatingSensor,
    UtilitiesSensorConfig,
    WaterSensor,
)
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


def map_type_to_description(type: str):
    if type == "water":
        return WaterSensor
    if type == "electricity":
        return ElectricitySensor
    if type == "heating":
        return HeatingSensor
    Exception(f"Unknown type - {type}")


async def load_utilities_config() -> list[UtilitiesSensorConfig]:
    data = await read_yaml("/config/utilities.yaml")
    return list(
        map(
            lambda item: UtilitiesSensorConfig(
                id=item.get("id", None),
                name=item.get("name", None),
                description=map_type_to_description(item["type"]),
            ),
            data.get("utilities", []),
        )
    )

"""Utility helper to read utilities yaml config file."""

import logging

from homeassistant.components.sensor import SensorEntityDescription

from ..entities.utilities.utilities_sensor import (
    ElectricitySensor,
    HeatingSensor,
    UtilitiesSensorConfig,
    WaterSensor,
)
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


class UnknownDescriptionTypeError(Exception):
    """Raised when unknown description is provided in YAML configuration file."""


def _map_type_to_description(
    utility_type: str,
) -> SensorEntityDescription:
    if utility_type == "water":
        return WaterSensor
    if utility_type == "electricity":
        return ElectricitySensor
    if utility_type == "heating":
        return HeatingSensor
    raise UnknownDescriptionTypeError(utility_type)


async def load_utilities_config() -> list[UtilitiesSensorConfig]:
    """Read utilities config file."""
    data = await read_yaml("/config/utilities.yaml")

    return [
        UtilitiesSensorConfig(
            id=item.get("id", None),
            name=item.get("name", None),
            description=_map_type_to_description(item["type"]),
        )
        for item in data.get("utilities", [])
    ]

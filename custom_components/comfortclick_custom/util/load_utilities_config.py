"""Utility helper to read utilities yaml config file."""

import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

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
    unit: str | None = None,
) -> SensorEntityDescription:
    if utility_type == "water":
        description = WaterSensor
    elif utility_type == "electricity":
        description = ElectricitySensor
    elif utility_type == "heating":
        description = HeatingSensor
    else:
        raise UnknownDescriptionTypeError(utility_type)
    if unit is not None:
        return replace(description, native_unit_of_measurement=unit)
    return description


async def load_utilities_config(
    options: Mapping[str, Any] | None = None,
) -> list[UtilitiesSensorConfig]:
    """Read saved meter mappings, falling back to YAML when not configured."""
    data = (
        options if options is not None and "utilities" in options else await read_yaml()
    )

    return [
        UtilitiesSensorConfig(
            id=item.get("id", None),
            name=item.get("name", None),
            description=_map_type_to_description(item["type"], item.get("unit")),
            unique_id=item.get("unique_id"),
        )
        for item in data.get("utilities", [])
    ]

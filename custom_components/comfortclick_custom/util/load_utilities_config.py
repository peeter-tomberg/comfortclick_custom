"""Load utility meter mappings from saved integration options."""

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

_LOGGER = logging.getLogger(__name__)


class UnknownDescriptionTypeError(Exception):
    """Raised when a saved utility mapping specifies an unknown meter type."""


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
    """Read saved meter mappings, using no entities for unconfigured sections."""
    data = options if options is not None else {}

    return [
        UtilitiesSensorConfig(
            id=item.get("id", None),
            name=item.get("name", None),
            description=_map_type_to_description(item["type"], item.get("unit")),
            unique_id=item.get("unique_id"),
        )
        for item in data.get("utilities", [])
        if isinstance(item.get("id"), str) and item["id"].strip()
    ]

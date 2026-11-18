"""Load ventilation mappings from saved integration options."""

import logging
from collections.abc import Mapping
from typing import Any

from ..entities.vent.vent_config import VentConfig

_LOGGER = logging.getLogger(__name__)


async def load_vent_config(
    options: Mapping[str, Any] | None = None,
) -> VentConfig | None:
    """Read saved ventilation paths, using no entities for unconfigured sections."""
    config = options if options is not None else {}
    item = config.get("vent", {})
    if not item:
        return None
    return VentConfig(
        vent_winter_mode=item.get("vent_winter_mode", None),
        away_mode=item.get("away_mode", None),
        home_mode=item.get("home_mode", None),
        guest_mode=item.get("guest_mode", None),
        away_vent_air_temp=item.get("away_vent_air_temp", None),
        home_vent_air_temp=item.get("home_vent_air_temp", None),
        guest_vent_air_temp=item.get("guest_vent_air_temp", None),
    )

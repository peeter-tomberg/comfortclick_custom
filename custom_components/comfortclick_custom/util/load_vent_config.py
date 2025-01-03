"""Utility helper to read vent yaml config file."""

import logging

from ..entities.vent.vent_config import VentConfig
from .read_yaml import read_yaml

_LOGGER = logging.getLogger(__name__)


async def load_vent_config() -> VentConfig:
    """Read vent config file."""
    config = await read_yaml()
    item = config.get("vent", {})
    return VentConfig(
        vent_winter_mode=item.get("vent_winter_mode", None),
        away_mode=item.get("away_mode", None),
        home_mode=item.get("home_mode", None),
        guest_mode=item.get("guest_mode", None),
        away_vent_air_temp=item.get("away_vent_air_temp", None),
        home_vent_air_temp=item.get("home_vent_air_temp", None),
        guest_vent_air_temp=item.get("guest_vent_air_temp", None),
    )

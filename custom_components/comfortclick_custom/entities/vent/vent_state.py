"""Resolve active ventilation modes without inventing missing feedback."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...api import ApiInstance
    from .vent_config import VentConfig


class VentPresetModes(StrEnum):
    """Available ventilation modes in ComfortClick."""

    HOME = "Home"
    AWAY = "Away"
    GUESTS = "Guests"


def active_mode(api: ApiInstance, config: VentConfig) -> VentPresetModes | None:
    """Return a uniquely active mode only when all mode feedback is known."""
    if not config.has_mode_paths:
        return None
    values = {
        VentPresetModes.HOME: api.get_value(config.home_mode),
        VentPresetModes.AWAY: api.get_value(config.away_mode),
        VentPresetModes.GUESTS: api.get_value(config.guest_mode),
    }
    if any(not isinstance(value, bool) for value in values.values()):
        return None
    active = [mode for mode, value in values.items() if value]
    return active[0] if len(active) == 1 else None

"""Sharable configuration file for all classes in this directory."""

from dataclasses import dataclass


@dataclass
class VentConfig:
    """Class for keeping all configuration options."""

    vent_winter_mode: str | None
    away_mode: str | None
    home_mode: str | None
    guest_mode: str | None

    away_vent_air_temp: str | None
    home_vent_air_temp: str | None
    guest_vent_air_temp: str | None

    @property
    def has_mode_paths(self) -> bool:
        """Whether every selectable ventilation mode has a mapped path."""
        return all(
            isinstance(path, str) and path.strip()
            for path in (self.home_mode, self.away_mode, self.guest_mode)
        )

    @property
    def has_winter_mode(self) -> bool:
        """Whether warm/cold mode has a mapped path."""
        return bool(
            isinstance(self.vent_winter_mode, str) and self.vent_winter_mode.strip()
        )

    @property
    def has_temperature_paths(self) -> bool:
        """Whether mode feedback and at least one mode's temperature are mapped."""
        return self.has_mode_paths and any(
            isinstance(path, str) and path.strip()
            for path in (
                self.home_vent_air_temp,
                self.away_vent_air_temp,
                self.guest_vent_air_temp,
            )
        )

"""Sharable configuration file for all classes in this directory."""

from dataclasses import dataclass


@dataclass
class VentConfig:
    """Class for keeping all configuration options."""

    vent_winter_mode: str
    away_mode: str
    home_mode: str
    guest_mode: str

    away_vent_air_temp: str
    home_vent_air_temp: str
    guest_vent_air_temp: str

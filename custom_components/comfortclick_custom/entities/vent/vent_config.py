from dataclasses import dataclass


@dataclass
class VentConfig:
    """Class for keeping track of an item in inventory."""

    vent_winter_mode: str
    away_mode: str
    home_mode: str
    guest_mode: str

    away_vent_air_temp: str
    home_vent_air_temp: str
    guest_vent_air_temp: str

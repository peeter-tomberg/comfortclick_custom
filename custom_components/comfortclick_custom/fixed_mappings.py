"""The building's fixed door and utility-meter configuration slots."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

METER_SLOTS = {
    "electricity_day": ("Electricity (day, total)", "electricity"),
    "electricity_night": ("Electricity (night, total)", "electricity"),
    "water_cold": ("Water (cold, total)", "water"),
    "water_hot": ("Water (hot, total)", "water"),
    "heating": ("Heating (total)", "heating"),
}
DOOR_SLOTS = {"main": "Main door", "cellar": "Cellar door", "garage": "Garage door"}
VENT_FIELDS = {
    "vent_mode": ("away_mode", "home_mode", "guest_mode"),
    "vent_air_mode": ("vent_winter_mode",),
    "vent_temperature": (
        "away_vent_air_temp",
        "home_vent_air_temp",
        "guest_vent_air_temp",
    ),
}


def _identify_slot(section: str, item: dict[str, Any]) -> str | None:
    """Recognize existing named mappings without depending on list order."""
    slots = METER_SLOTS if section == "utilities" else DOOR_SLOTS
    if "slot" in item:
        return item["slot"] if item["slot"] in slots else None
    name = str(item.get("name" if section == "utilities" else "door_name", ""))
    words = set(re.findall(r"\w+", name.casefold()))
    if section == "locks":
        matches = [slot for slot in DOOR_SLOTS if slot in words]
    elif item.get("type") == "heating":
        matches = ["heating"]
    else:
        candidates = (
            {"day": "electricity_day", "night": "electricity_night"}
            if item.get("type") == "electricity"
            else {"cold": "water_cold", "hot": "water_hot"}
            if item.get("type") == "water"
            else {}
        )
        matches = [slot for word, slot in candidates.items() if word in words]
    return matches[0] if len(matches) == 1 else None


def import_fixed_mappings(
    source: Mapping[str, Any], section: str, entry_id: str
) -> list[dict[str, Any]]:
    """Fill exactly the fixed slots, preserving legacy names, paths and IDs."""
    if not isinstance(source, Mapping):
        raise TypeError
    existing = source.get(section, [])
    if not isinstance(existing, list):
        raise TypeError
    slots = METER_SLOTS if section == "utilities" else DOOR_SLOTS
    path_key = "id" if section == "utilities" else "door_id"
    imported = {}
    for item in existing:
        if not isinstance(item, dict):
            raise TypeError
        slot = _identify_slot(section, item)
        if slot is None or slot in imported:
            message = "Existing mapping cannot be assigned to a unique fixed slot"
            raise ValueError(message)
        if section == "utilities" and item.get("type") != METER_SLOTS[slot][1]:
            message = "Existing meter type does not match its fixed slot"
            raise ValueError(message)
        imported[slot] = deepcopy(item)

    result = []
    for slot in slots:
        if section == "utilities":
            name, meter_type = METER_SLOTS[slot]
            mapping = {"name": name, "type": meter_type, path_key: ""}
        else:
            mapping = {"door_name": DOOR_SLOTS[slot], path_key: ""}
        mapping.update(imported.get(slot, {}))
        mapping["slot"] = slot
        path = mapping.get(path_key)
        legacy_id = path if isinstance(path, str) and path.strip() else None
        mapping.setdefault("unique_id", legacy_id or f"{entry_id}-{section}-{slot}")
        result.append(mapping)
    return result

"""Import legacy YAML mappings once before switching to stored options."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .fixed_mappings import import_fixed_mappings
from .util.read_yaml import read_yaml

CONFIG_ENTRY_VERSION = 2

IDENTITY_FIELDS = {
    "fans": ("fan_id", ""),
    "thermostats": ("heating_id", "room-1-"),
    "locks": ("door_id", ""),
    "utilities": ("id", ""),
}


def empty_mapping_options() -> dict[str, Any]:
    """Return independent empty mappings for a new options-only entry."""
    return {"fans": [], "thermostats": [], "locks": [], "utilities": [], "vent": {}}


async def async_import_mapping_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Build complete options atomically, preserving saved overrides and IDs."""
    result = deepcopy(dict(options))
    defaults = empty_mapping_options()
    missing = defaults.keys() - options.keys()
    legacy = await read_yaml() if missing else {}
    for section, default in defaults.items():
        if section in result:
            continue
        value = deepcopy(legacy.get(section, default))
        if section == "vent":
            if not isinstance(value, dict):
                raise TypeError
            result[section] = value
            continue
        if not isinstance(value, list) or any(
            not isinstance(row, dict) for row in value
        ):
            raise TypeError
        if section in {"locks", "utilities"}:
            # Validate assignability without changing legacy names, order or paths.
            import_fixed_mappings({section: value}, section, "migration-validation")
        field, prefix = IDENTITY_FIELDS[section]
        for row in value:
            if "unique_id" not in row:
                path = row.get(field)
                if not isinstance(path, str):
                    raise TypeError
                if section in {"locks", "utilities"} and not path.strip():
                    # Unconfigured fixed slots have no entity identity to retain.
                    continue
                row["unique_id"] = prefix + path
        result[section] = value
    return result

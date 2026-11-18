"""Utility helper to read yaml files."""

from pathlib import Path
from typing import Any

import aiofiles
import yaml


async def read_yaml() -> dict[str, Any]:
    """Read legacy mappings for one-time migration without logging their contents."""
    full_path = f"{Path(__file__).parent}/../../../comfortclick_custom.yaml"
    try:
        async with aiofiles.open(full_path, encoding="utf-8") as f:
            contents = await f.read()
    except FileNotFoundError:
        return {}
    data = yaml.safe_load(contents)
    if data is None:
        return {}
    if not isinstance(data, dict):
        message = "ComfortClick YAML configuration must be a mapping"
        raise TypeError(message)
    return data

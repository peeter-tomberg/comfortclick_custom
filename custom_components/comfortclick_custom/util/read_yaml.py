"""Utility helper to read yaml files."""

import logging
from pathlib import Path
from typing import Any

import aiofiles
import yaml

_LOGGER = logging.getLogger(__name__)

logging.basicConfig(format="%(message)s - %(full_path)s", level=logging.INFO)


async def read_yaml(path: str) -> Any:
    """Read the YAML configuration file from integrations config folder."""
    full_path = f"{Path(__file__).parent}/../{path}"
    async with aiofiles.open(full_path, encoding="utf-8") as f:
        contents = await f.read()
    try:
        return yaml.safe_load(contents)

    except yaml.YAMLError:
        _LOGGER.exception(
            "Failed to load YAML configuration file", extra={full_path: full_path}
        )

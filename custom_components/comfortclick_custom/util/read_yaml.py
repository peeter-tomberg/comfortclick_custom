import logging
import os

import aiofiles
import yaml

_LOGGER = logging.getLogger(__name__)


async def read_yaml(path: str):
    full_path = f"{os.path.dirname(__file__)}/../{path}"
    async with aiofiles.open(full_path, encoding="utf-8") as f:
        contents = await f.read()
    try:
        return yaml.safe_load(contents)

    except yaml.YAMLError as exc:
        _LOGGER.error(f"Failed to load YAML configuration file from {full_path}")
        _LOGGER.error(exc)

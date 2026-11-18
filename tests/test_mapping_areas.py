"""Mapping areas are applied after registration without changing entity identity."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.helpers.entity_component import EntityComponent

from custom_components.comfortclick_custom.entities.ac.room_fan import RoomFan
from custom_components.comfortclick_custom.entities.ac.room_thermostat import (
    RoomThermostat,
)
from custom_components.comfortclick_custom.util.load_fans_config import load_fans_config
from custom_components.comfortclick_custom.util.load_thermostats_config import (
    load_thermostats_config,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


@pytest.fixture
async def hass(tmp_path: Path) -> AsyncGenerator[HomeAssistant]:
    instance = HomeAssistant(str(tmp_path))
    await entity_registry.async_load(instance)
    await device_registry.async_load(instance)
    await area_registry.async_load(instance)
    try:
        yield instance
    finally:
        await instance.async_stop(force=True)


@pytest.mark.parametrize("kind", ["fan", "climate"])
@pytest.mark.parametrize("assignment", ["legacy", "selected", "cleared", "deleted"])
async def test_area_assignment_preserves_identity_and_obeys_explicit_options(
    hass: HomeAssistant, kind: str, assignment: str
) -> None:
    areas = area_registry.async_get(hass)
    old_area = areas.async_create("Existing room")
    selected_area = areas.async_create("Selected room")
    deleted_area = areas.async_create("Deleted room")
    areas.async_delete(deleted_area.id)
    registry = entity_registry.async_get(hass)
    existing = registry.async_get_or_create(
        kind, kind, "legacy-path", suggested_object_id="preserved_entity"
    )
    registry.async_update_entity(existing.entity_id, area_id=old_area.id)
    options = {
        "name": "Mapped entity",
        "fan_id": "fan",
        "lock_id": "lock",
        "heating_id": "heating",
        "current_temperature_id": "current",
        "target_temperature_id": "target",
        "unique_id": "legacy-path",
    }
    expected_area = old_area.id
    if assignment == "selected":
        options["area_id"] = selected_area.id
        expected_area = selected_area.id
    elif assignment == "cleared":
        options["area_id"] = ""
        expected_area = None
    elif assignment == "deleted":
        options["area_id"] = deleted_area.id
    coordinator = MagicMock()
    coordinator.last_update_success = True
    values = {"fan": 10, "lock": False, "heating": False, "current": 22, "target": 20}
    coordinator.api.get_value.side_effect = values.get
    if kind == "fan":
        configs = await load_fans_config({"fans": [options]})
        entity = RoomFan(coordinator, configs[0])
    else:
        configs = await load_thermostats_config({"thermostats": [options]})
        entity = RoomThermostat(coordinator, configs[0])
    component = EntityComponent(logging.getLogger(__name__), kind, hass)

    try:
        await component.async_add_entities([entity])
        await hass.async_block_till_done()
        assert entity.entity_id == existing.entity_id
        assert entity.unique_id == "legacy-path"
        assert registry.async_get(existing.entity_id).area_id == expected_area
        assert hass.states.get(existing.entity_id) is not None
    finally:
        await component._async_reset()  # noqa: SLF001

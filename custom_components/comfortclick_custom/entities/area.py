"""Apply explicit mapping areas without changing legacy entity assignments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers import area_registry, entity_registry

if TYPE_CHECKING:
    from homeassistant.helpers.entity import Entity


@callback
def async_apply_configured_area(entity: Entity, area_id: str | None) -> None:
    """Apply a configured area after entity registration; ignore deleted areas."""
    if area_id is None:
        return
    if area_id and area_registry.async_get(entity.hass).async_get_area(area_id) is None:
        return
    registry = entity_registry.async_get(entity.hass)
    entry = registry.async_get(entity.entity_id)
    target_area = area_id or None
    if entry is not None and entry.area_id != target_area:
        registry.async_update_entity(entity.entity_id, area_id=target_area)

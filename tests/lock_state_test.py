"""Lock feedback must never invent a secure state."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from custom_components.comfortclick_custom.entities.locks.building_lock import (
    BuildingLock,
    BuildingLockConfig,
)

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.parametrize("reading", [None, "false", "true", 0, 1, {}])
def test_missing_or_invalid_lock_feedback_stays_unknown(reading: Any) -> None:
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.api.get_value.return_value = reading
    entity = BuildingLock(coordinator, BuildingLockConfig("Front door", "door"))

    assert entity.is_open is None
    assert entity.is_locked is None
    assert entity.available is False


@pytest.mark.parametrize("reading", [True, False])
def test_boolean_feedback_sets_initial_lock_state(*, reading: bool) -> None:
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.api.get_value.return_value = reading
    entity = BuildingLock(coordinator, BuildingLockConfig("Front door", "door"))

    assert entity.is_open is reading
    assert entity.is_locked is not reading
    assert entity.available is True


def test_lost_feedback_is_unavailable_until_valid_feedback_returns() -> None:
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.api.get_value.return_value = True
    entity = BuildingLock(coordinator, BuildingLockConfig("Front door", "door"))
    published = []

    with patch.object(
        entity,
        "async_write_ha_state",
        side_effect=lambda: published.append((entity.is_locked, entity.available)),
    ):
        coordinator.api.get_value.return_value = None
        entity._handle_coordinator_update()  # noqa: SLF001
        coordinator.api.get_value.return_value = False
        entity._handle_coordinator_update()  # noqa: SLF001
        coordinator.last_update_success = False
        entity._handle_coordinator_update()  # noqa: SLF001

    assert published == [(None, False), (True, True), (True, False)]

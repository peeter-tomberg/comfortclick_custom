"""Missing controller readings must not become valid climate measurements."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.climate import HVACAction

from custom_components.comfortclick_custom.entities.ac.room_fan import (
    RoomFan,
    RoomFanConfig,
)
from custom_components.comfortclick_custom.entities.ac.room_thermostat import (
    RoomThermostat,
    RoomThermostatConfig,
)

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture
def values() -> dict[str, Any]:
    return {
        "heating": False,
        "lock": False,
        "fan": 10,
        "current": 22,
        "target": 20,
    }


@pytest.fixture
def coordinator(values: dict[str, Any]) -> MagicMock:
    coordinator = MagicMock()
    coordinator.api.get_value.side_effect = lambda device_name: values.get(device_name)
    coordinator.last_update_success = True
    return coordinator


@pytest.mark.parametrize("missing", ["heating", "lock", "fan", "current", "target"])
def test_fan_missing_reading_recovers(
    coordinator: MagicMock, values: dict[str, Any], missing: str
) -> None:
    original = values.pop(missing)
    entity = RoomFan(
        coordinator, RoomFanConfig("Fan", "heating", "lock", "fan", "current", "target")
    )
    assert entity.is_on is None
    assert entity.available is False

    with patch.object(entity, "async_write_ha_state") as write_state:
        entity._handle_coordinator_update()  # noqa: SLF001
        assert entity.is_on is None
        assert entity.available is False
        values[missing] = original
        entity._handle_coordinator_update()  # noqa: SLF001
        assert entity.is_on is True
        assert entity.available is True
        assert write_state.call_count == 2


@pytest.mark.parametrize("missing", ["heating", "fan", "current", "target"])
def test_thermostat_missing_reading_recovers(
    coordinator: MagicMock, values: dict[str, Any], missing: str
) -> None:
    original = values.pop(missing)
    entity = RoomThermostat(
        coordinator, RoomThermostatConfig("Room", "heating", "fan", "current", "target")
    )
    assert entity.available is False
    assert entity.current_temperature == values.get("current")
    assert entity.target_temperature == values.get("target")
    expected_action = None if missing in {"heating", "fan"} else HVACAction.COOLING
    assert entity.hvac_action == expected_action

    with patch.object(entity, "async_write_ha_state") as write_state:
        entity._handle_coordinator_update()  # noqa: SLF001
        assert entity.available is False
        assert entity.current_temperature == values.get("current")
        assert entity.target_temperature == values.get("target")
        assert entity.hvac_action == expected_action
        values[missing] = original
        entity._handle_coordinator_update()  # noqa: SLF001
        assert entity.available is True
        assert entity.current_temperature == 22
        assert entity.target_temperature == 20
        assert entity.hvac_action == HVACAction.COOLING
        assert write_state.call_count == 2


@pytest.mark.parametrize("invalid", [None, "invalid", "nan", "inf", True, {}])
@pytest.mark.parametrize("device", ["fan", "current", "target"])
def test_invalid_numeric_readings_are_unknown(
    coordinator: MagicMock, values: dict[str, Any], device: str, invalid: Any
) -> None:
    values[device] = invalid
    fan = RoomFan(
        coordinator, RoomFanConfig("Fan", "heating", "lock", "fan", "current", "target")
    )
    thermostat = RoomThermostat(
        coordinator, RoomThermostatConfig("Room", "heating", "fan", "current", "target")
    )

    for entity in (fan, thermostat):
        with patch.object(entity, "async_write_ha_state"):
            entity._handle_coordinator_update()  # noqa: SLF001
        assert entity.available is False

    assert fan.is_on is None
    if device == "current":
        assert thermostat.current_temperature is None
    elif device == "target":
        assert thermostat.target_temperature is None
    else:
        assert thermostat.hvac_action is None


def test_zero_temperature_and_heating_only_thermostat_are_valid(
    coordinator: MagicMock, values: dict[str, Any]
) -> None:
    values.update(current=0, target=0)
    values.pop("fan")
    entity = RoomThermostat(
        coordinator, RoomThermostatConfig("Room", "heating", None, "current", "target")
    )

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()  # noqa: SLF001
    assert entity.available is True
    assert entity.current_temperature == 0
    assert entity.target_temperature == 0
    assert entity.hvac_action == HVACAction.IDLE

    values["heating"] = True
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()  # noqa: SLF001
    assert entity.hvac_action == HVACAction.HEATING

"""Failed commands must not publish their requested state."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.comfortclick_custom.entities.ac.room_fan import (
    RoomFan,
    RoomFanConfig,
)
from custom_components.comfortclick_custom.entities.vent.vent_config import VentConfig
from custom_components.comfortclick_custom.entities.vent.vent_temp_select import (
    VentTempModes,
    VentTempSelect,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("turn_on", [True, False])
async def test_fan_publishes_only_after_success(*, turn_on: bool) -> None:
    coordinator = MagicMock()
    coordinator.api.set_value = AsyncMock(side_effect=OSError("offline"))
    config = RoomFanConfig("Fan", "heating", "fan_lock", "fan", "current", "target")
    entity = RoomFan(coordinator, config)
    entity._attr_is_on = not turn_on  # noqa: SLF001
    command = entity.async_turn_on if turn_on else entity.async_turn_off

    with patch.object(entity, "async_write_ha_state") as write_state:
        with pytest.raises(OSError, match="offline"):
            await command()
        assert entity.is_on is not turn_on
        write_state.assert_not_called()

        coordinator.api.set_value.side_effect = None
        await command()
        assert entity.is_on is turn_on
        write_state.assert_called_once_with()

    coordinator.api.set_value.assert_awaited_with("fan_lock", value=not turn_on)


@pytest.mark.asyncio
@pytest.mark.parametrize("warm", [True, False])
async def test_vent_mode_publishes_only_after_success(*, warm: bool) -> None:
    coordinator = MagicMock()
    coordinator.api.set_value = AsyncMock(side_effect=OSError("offline"))
    config = VentConfig(
        "winter", "away", "home", "guest", "away_temp", "home_temp", "guest_temp"
    )
    entity = VentTempSelect(coordinator, config)
    old_option = VentTempModes.COLD_AIR if warm else VentTempModes.WARM_AIR
    requested = VentTempModes.WARM_AIR if warm else VentTempModes.COLD_AIR
    entity._attr_current_option = old_option  # noqa: SLF001

    with patch.object(entity, "async_write_ha_state") as write_state:
        with pytest.raises(OSError, match="offline"):
            await entity.async_select_option(requested)
        assert entity.current_option == old_option
        write_state.assert_not_called()

        coordinator.api.set_value.side_effect = None
        await entity.async_select_option(requested)
        assert entity.current_option == requested
        write_state.assert_called_once_with()

    coordinator.api.set_value.assert_awaited_with("winter", value=warm)

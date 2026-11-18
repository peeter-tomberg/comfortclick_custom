"""Exercise doorbell events through real Home Assistant state and event handling."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import aiohttp
import pytest
from homeassistant.components.event import EventDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_component import EntityComponent

from custom_components.comfortclick_custom import RuntimeData
from custom_components.comfortclick_custom import coordinator as coordinator_module
from custom_components.comfortclick_custom.api import DoorbellRing
from custom_components.comfortclick_custom.const import DOMAIN, EVENT_DOORBELL
from custom_components.comfortclick_custom.coordinator import ComfortClickCoordinator
from custom_components.comfortclick_custom.event import (
    ComfortClickDoorbell,
    async_setup_entry,
)

from .api_helpers import response

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from homeassistant.core import Event


TIMESTAMP = "2026-11-18T03:56:26.4511552+02:00"


def ring_action(timestamp: str | None = TIMESTAMP) -> dict:
    return {
        "Action": {"ActionName": "PlaySound", "Sound": "DoorBell2.mp3"},
        "Time": timestamp,
    }


@pytest.fixture
async def hass(tmp_path: Path) -> AsyncGenerator[HomeAssistant]:
    instance = HomeAssistant(str(tmp_path))
    try:
        yield instance
    finally:
        await instance.async_stop(force=True)


@pytest.fixture
def session() -> MagicMock:
    client = MagicMock(spec=aiohttp.ClientSession)
    client.post.return_value = response({"ActionData": []})
    client.get.return_value = response()
    return client


@pytest.fixture
async def coordinator(
    hass: HomeAssistant, session: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[ComfortClickCoordinator]:
    monkeypatch.setattr(coordinator_module, "create_api_session", lambda: session)
    instance = ComfortClickCoordinator(
        hass, "http://controller.test", "username", "password"
    )
    instance.update_interval = None
    instance.async_set_updated_data(())
    try:
        yield instance
    finally:
        await instance.async_shutdown()


@pytest.fixture
async def component(
    hass: HomeAssistant,
) -> AsyncGenerator[EntityComponent[ComfortClickDoorbell]]:
    await entity_registry.async_load(hass)
    instance = EntityComponent[ComfortClickDoorbell](
        logging.getLogger(__name__), "event", hass
    )
    try:
        yield instance
    finally:
        await instance._async_reset()  # noqa: SLF001


@pytest.fixture
def rings(hass: HomeAssistant) -> list[Event]:
    received = []

    @callback
    def receive(event: Event) -> None:
        received.append(event)

    hass.bus.async_listen(EVENT_DOORBELL, receive)
    return received


async def test_poll_action_publishes_real_event_state_and_bus(
    hass: HomeAssistant,
    coordinator: ComfortClickCoordinator,
    component: EntityComponent[ComfortClickDoorbell],
    session: MagicMock,
    rings: list[Event],
) -> None:
    session.post.side_effect = [
        response({"Status": "OK"}, token="test-session"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response({"ActionData": [ring_action()]}),
    ]
    await coordinator.api.connect()
    await coordinator.api.initialize_state()
    entity = ComfortClickDoorbell(coordinator, "entry-one")
    await component.async_add_entities([entity])
    assert hass.states.get(entity.entity_id).state == STATE_UNKNOWN

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(entity.entity_id)
    assert state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}
    assert state.attributes["event_type"] == "ring"
    assert state.attributes["event_types"] == ["ring"]
    assert state.attributes["device_class"] == EventDeviceClass.DOORBELL
    assert state.attributes["sound"] == "DoorBell2.mp3"
    assert state.attributes["timestamp"] == TIMESTAMP
    assert state.attributes["event_sequence"] == 1
    assert [event.data for event in rings] == [
        {
            "config_entry_id": "entry-one",
            "entity_id": entity.entity_id,
            "event_type": "ring",
            "sound": "DoorBell2.mp3",
            "timestamp": TIMESTAMP,
            "event_sequence": 1,
        }
    ]
    assert session.post.call_args.args[0].split("?")[0].endswith("/GetClientData")


async def test_same_millisecond_rings_each_publish_a_state_change(
    hass: HomeAssistant,
    coordinator: ComfortClickCoordinator,
    component: EntityComponent[ComfortClickDoorbell],
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = ComfortClickDoorbell(coordinator, "entry-one")
    await component.async_add_entities([entity])
    await hass.async_block_till_done()
    received = []
    states = []

    @callback
    def receive(event: Event) -> None:
        received.append(event)

    @callback
    def state_changed(event: Event) -> None:
        if event.data["entity_id"] == entity.entity_id:
            states.append(event.data["new_state"])

    hass.bus.async_listen(EVENT_DOORBELL, receive)
    hass.bus.async_listen(EVENT_STATE_CHANGED, state_changed)
    fixed_time = datetime(2026, 11, 18, tzinfo=UTC)
    monkeypatch.setattr(
        "homeassistant.components.event.dt_util.utcnow", lambda: fixed_time
    )
    session.post.return_value = response(
        {"ActionData": [ring_action(None), ring_action(None)]}
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(states) == 2
    assert states[0].state == states[1].state
    assert [state.attributes["event_sequence"] for state in states] == [1, 2]
    assert [event.data["event_sequence"] for event in received] == [1, 2]


async def test_failed_empty_and_recovered_polls_do_not_replay_rings(
    hass: HomeAssistant,
    coordinator: ComfortClickCoordinator,
    component: EntityComponent[ComfortClickDoorbell],
    session: MagicMock,
    rings: list[Event],
) -> None:
    entity = ComfortClickDoorbell(coordinator, "entry-one")
    await component.async_add_entities([entity])
    session.post.side_effect = [
        response({"ActionData": [ring_action()]}),
        TimeoutError("controller offline"),
        response({"ActionData": []}),
        response({"ActionData": []}),
        response({"ActionData": [ring_action(None)]}),
    ]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    last_ring_state = hass.states.get(entity.entity_id).state
    batch = coordinator.data

    # A repeated notification for the exact same poll cannot create another ring.
    coordinator.async_update_listeners()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data is batch
    assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
    assert len(rings) == 1

    for _ in range(2):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entity.entity_id).state == last_ring_state
        assert len(rings) == 1

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(rings) == 2
    assert rings[-1].data["event_sequence"] == 2
    assert "timestamp" not in rings[-1].data
    assert "timestamp" not in hass.states.get(entity.entity_id).attributes


async def test_add_and_readd_skip_cached_batches_and_remove_listeners(
    hass: HomeAssistant,
    coordinator: ComfortClickCoordinator,
    component: EntityComponent[ComfortClickDoorbell],
    rings: list[Event],
) -> None:
    entity = ComfortClickDoorbell(coordinator, "entry-one")
    coordinator.async_set_updated_data((DoorbellRing("DoorBell2.mp3", TIMESTAMP),))
    await component.async_add_entities([entity])
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(entity.entity_id).state == STATE_UNKNOWN
    assert rings == []
    assert len(coordinator._listeners) == 1  # noqa: SLF001

    coordinator.async_set_updated_data((DoorbellRing("DoorBell2.mp3", TIMESTAMP),))
    await hass.async_block_till_done()
    assert len(rings) == 1
    await component.async_remove_entity(entity.entity_id)
    assert not coordinator._listeners  # noqa: SLF001

    coordinator.async_set_updated_data((DoorbellRing("DoorBell2.mp3", None),))
    replacement = ComfortClickDoorbell(coordinator, "entry-one")
    await component.async_add_entities([replacement])
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert replacement.entity_id == entity.entity_id
    assert len(rings) == 1
    await component.async_remove_entity(replacement.entity_id)
    assert not coordinator._listeners  # noqa: SLF001


async def test_new_ring_is_published_when_failed_poll_recovers(
    hass: HomeAssistant,
    coordinator: ComfortClickCoordinator,
    component: EntityComponent[ComfortClickDoorbell],
    session: MagicMock,
    rings: list[Event],
) -> None:
    entity = ComfortClickDoorbell(coordinator, "entry-one")
    await component.async_add_entities([entity])
    session.post.side_effect = [
        TimeoutError("controller offline"),
        response({"ActionData": [ring_action()]}),
    ]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
    assert rings == []

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert entity.available
    assert hass.states.get(entity.entity_id).attributes["event_type"] == "ring"
    assert len(rings) == 1
    assert rings[0].data["timestamp"] == TIMESTAMP


async def test_platform_setup_creates_one_unique_entity_per_entry(
    hass: HomeAssistant,
    coordinator: ComfortClickCoordinator,
    component: EntityComponent[ComfortClickDoorbell],
) -> None:
    entities = []
    hass.data[DOMAIN] = {}
    for entry_id in ("entry-one", "entry-two"):
        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = entry_id
        hass.data[DOMAIN][entry_id] = RuntimeData(coordinator, lambda: None)
        await async_setup_entry(hass, entry, entities.extend)

    assert len(entities) == 2
    assert {entity.unique_id for entity in entities} == {
        "entry-one_doorbell",
        "entry-two_doorbell",
    }
    assert all(entity.name == "Doorbell" for entity in entities)
    assert all(entity.device_info["name"] == "ComfortClick" for entity in entities)
    await component.async_add_entities(entities)
    assert len({entity.entity_id for entity in entities}) == 2
    assert len(coordinator._listeners) == 2  # noqa: SLF001

    for entity in entities:
        await component.async_remove_entity(entity.entity_id)
    assert not coordinator._listeners  # noqa: SLF001

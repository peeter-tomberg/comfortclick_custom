"""Confirmed doorbell ActionData parsing without disrupting state polling."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.comfortclick_custom.api import (
    DOORBELL_HISTORY_SIZE,
    DOORBELL_SOUND,
    ApiInstance,
    ApiResponseError,
    DoorbellRing,
)

from .api_helpers import response

CAPTURED_TIME = "2026-11-18T03:56:26.4511552+02:00"


def ring_action(timestamp: str | None = CAPTURED_TIME) -> dict:
    return {
        "Action": {"ActionName": "PlaySound", "Sound": "DoorBell2.mp3"},
        "Time": timestamp,
    }


@pytest.mark.asyncio
async def test_captured_ring_is_returned_alongside_normal_state_updates() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(
        {
            "ActionData": [ring_action()],
            "PropertyUpdates": [
                {"DeviceName": "meter", "PropertyName": "Value", "Value": 100}
            ],
        }
    )
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, CAPTURED_TIME),)
    assert api.get_value("meter") == 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actions",
    [
        None,
        {},
        "invalid",
        1,
        [
            None,
            [],
            {},
            {"Action": None},
            {"Action": {"ActionName": "Unlock", "Sound": "DoorBell2.mp3"}},
            {"Action": {"ActionName": "PlaySound", "Sound": "Other.mp3"}},
            {"Action": {"ActionName": "playsound", "Sound": "DoorBell2.mp3"}},
        ],
    ],
)
async def test_unknown_and_malformed_actions_do_not_break_polling(actions: Any) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(
        {
            "ActionData": actions,
            "PropertyUpdates": [
                {"DeviceName": "meter", "PropertyName": "Value", "Value": 100}
            ],
        }
    )
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert await api.poll() == ()
    assert api.get_value("meter") == 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timestamp",
    [
        "arbitrary secret",
        "2026-11-18T03:56:26",
        "2026-11-18",
        "2026-13-18T03:56:26+02:00",
        "2026-11-18T03:56:26+25:00",
        "2026-11-18X03:56:26+02:00",
        "",
        123,
        {},
        [],
    ],
)
async def test_invalid_timestamp_record_is_ignored_and_valid_neighbors_survive(
    timestamp: Any,
) -> None:
    invalid = ring_action()
    invalid["Time"] = timestamp
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"ActionData": [invalid, ring_action()]})
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, CAPTURED_TIME),)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timestamp",
    ["2026-11-18T01:56:26Z", "2026-11-18T01:56:26.451155+00:00", CAPTURED_TIME],
)
async def test_valid_aware_timestamp_preserves_controller_precision(
    timestamp: str,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"ActionData": [ring_action(timestamp)]})
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, timestamp),)


@pytest.mark.asyncio
async def test_missing_timestamp_rings_are_not_deduplicated() -> None:
    missing_time = ring_action()
    missing_time.pop("Time")
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(
        {"ActionData": [missing_time, ring_action(None)]}
    )
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    expected = (DoorbellRing(DOORBELL_SOUND, None), DoorbellRing(DOORBELL_SOUND, None))

    assert await api.poll() == expected
    assert await api.poll() == expected


@pytest.mark.asyncio
async def test_distinct_rings_survive_same_poll_and_duplicates_are_suppressed() -> None:
    second_time = "2026-11-18T03:56:26.4511553+02:00"
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(
        {"ActionData": [ring_action(), ring_action(second_time), ring_action()]}
    )
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert await api.poll() == (
        DoorbellRing(DOORBELL_SOUND, CAPTURED_TIME),
        DoorbellRing(DOORBELL_SOUND, second_time),
    )
    assert await api.poll() == ()


@pytest.mark.asyncio
async def test_session_recovery_does_not_replay_seen_rings_or_snapshot_actions() -> (
    None
):
    unseen_snapshot_time = "2026-11-18T03:57:00+02:00"
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response({"ActionData": [ring_action()]}),
        response(status=401),
        response({"Status": "OK"}, token="renewed"),  # noqa: S106
        response(
            {
                "ThemeObject": {"ValueUpdates": []},
                "ActionData": [ring_action(unseen_snapshot_time)],
            }
        ),
        response({"ActionData": [ring_action()]}),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, CAPTURED_TIME),)
    assert await api.poll() == ()
    assert session.post.call_count == 5


@pytest.mark.asyncio
async def test_rejected_property_batch_does_not_consume_ring_identity() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response({"PropertyUpdates": None, "ActionData": [ring_action()]}),
        response({"ActionData": [ring_action()]}),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(ApiResponseError):
        await api.poll()
    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, CAPTURED_TIME),)


@pytest.mark.asyncio
async def test_ring_history_is_bounded() -> None:
    start = datetime(2026, 11, 18, tzinfo=UTC)
    timestamps = [
        (start + timedelta(seconds=index)).isoformat()
        for index in range(DOORBELL_HISTORY_SIZE + 1)
    ]
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(
            {"ActionData": [ring_action(timestamp) for timestamp in timestamps[:-1]]}
        ),
        response({"ActionData": [ring_action(timestamps[0])]}),
        response({"ActionData": [ring_action(timestamps[-1])]}),
        response({"ActionData": [ring_action(timestamps[0])]}),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert len(await api.poll()) == DOORBELL_HISTORY_SIZE
    assert await api.poll() == ()
    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, timestamps[-1]),)
    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, timestamps[0]),)


@pytest.mark.asyncio
async def test_large_poll_preserves_distinct_rings_without_duplicate_reemission() -> (
    None
):
    start = datetime(2026, 11, 18, tzinfo=UTC)
    timestamps = [
        (start + timedelta(seconds=index)).isoformat()
        for index in range(DOORBELL_HISTORY_SIZE + 1)
    ]
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(
        {
            "ActionData": [ring_action(timestamp) for timestamp in timestamps]
            + [ring_action(timestamps[0])],
        }
    )
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    assert await api.poll() == tuple(
        DoorbellRing(DOORBELL_SOUND, timestamp) for timestamp in timestamps
    )
    # The oldest identity exceeds the retained history, but all 128 identities
    # known at the start of this poll remain suppressed while that cache rotates.
    assert await api.poll() == (DoorbellRing(DOORBELL_SOUND, timestamps[0]),)

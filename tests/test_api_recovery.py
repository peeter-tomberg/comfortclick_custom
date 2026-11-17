"""Session expiry recovery without automatic command replay."""

import asyncio
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.comfortclick_custom import api as api_module
from custom_components.comfortclick_custom.api import (
    ApiInstance,
    AuthorizationError,
    HttpStatusNotOkError,
)

from .api_helpers import response


@pytest.mark.asyncio
async def test_expired_poll_refreshes_snapshot_and_retries_once() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(status=401),
        response({"Status": "OK"}, token="renewed"),  # noqa: S106
        response(
            {"ThemeObject": {"ValueUpdates": [{"DeviceName": "meter", "Value": 100}]}}
        ),
        response(
            {
                "PropertyUpdates": [
                    {"DeviceName": "meter", "PropertyName": "Value", "Value": 101}
                ]
            }
        ),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    await api.poll()

    assert api.get_value("meter") == 101
    paths = [
        call.args[0].split("/")[-1].split("?")[0]
        for call in session.post.call_args_list
    ]
    assert paths == ["GetClientData", "Login", "GetPanel", "GetClientData"]
    assert (
        session.post.call_args_list[-1]
        .kwargs["headers"]["Cookie"]
        .startswith("Token=renewed;")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_command_renews_session_but_is_not_replayed(status: int) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(status=status),
        response({"Status": "OK"}, token="renewed"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response({"Status": "OK"}),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(AuthorizationError):
        await api.set_value("door", value=True)

    assert session.post.call_count == 3
    await api.set_value("door", value=True)
    assert session.post.call_count == 4
    assert session.post.call_args.kwargs["headers"]["Cookie"].startswith(
        "Token=renewed;"
    )


@pytest.mark.asyncio
async def test_ambiguous_command_timeout_is_never_replayed() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    reply = response()
    reply.json.side_effect = TimeoutError
    session.post.return_value = reply
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(TimeoutError):
        await api.set_value("door", value=True)

    session.post.assert_called_once()


@pytest.mark.asyncio
async def test_server_error_does_not_replay_command_or_reauthenticate() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response(status=500)
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(HttpStatusNotOkError):
        await api.set_value("door", value=True)

    session.post.assert_called_once()


@pytest.mark.asyncio
async def test_read_retry_is_bounded_after_renewal() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(status=401),
        response({"Status": "OK"}, token="renewed"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response(status=401),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(AuthorizationError):
        await api.poll()

    assert session.post.call_count == 4


@pytest.mark.asyncio
async def test_concurrent_expiry_performs_one_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="renewed")  # noqa: S106
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    both_requests_started = asyncio.Event()
    poll_count = 0

    async def request(path: str, _payload: object = None) -> dict:
        nonlocal poll_count
        if path == "GetPanel":
            return {"ThemeObject": {"ValueUpdates": []}}
        poll_count += 1
        if poll_count <= 2:
            if poll_count == 2:
                both_requests_started.set()
            await both_requests_started.wait()
            raise AuthorizationError
        return {"PropertyUpdates": []}

    monkeypatch.setattr(api, "_request_json", request)
    await asyncio.gather(api.poll(), api.poll())

    session.post.assert_called_once()
    assert session.post.call_args.args[0].endswith("/Login")
    assert poll_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError, asyncio.CancelledError])
async def test_failed_resnapshot_is_retried_before_accepting_deltas(
    failure: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(api_module.time, "monotonic", lambda: now)
    session = MagicMock(spec=aiohttp.ClientSession)
    broken_snapshot = response()
    broken_snapshot.json.side_effect = failure
    session.post.side_effect = [
        response(status=401),
        response({"Status": "OK"}, token="first"),  # noqa: S106
        broken_snapshot,
        response({"Status": "OK"}, token="second"),  # noqa: S106
        response(
            {"ThemeObject": {"ValueUpdates": [{"DeviceName": "meter", "Value": 100}]}}
        ),
        response({"PropertyUpdates": []}),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(failure):
        await api.poll()
    now += api_module.SESSION_RECOVERY_COOLDOWN
    await api.poll()

    assert api.get_value("meter") == 100
    paths = [
        call.args[0].split("/")[-1].split("?")[0]
        for call in session.post.call_args_list
    ]
    assert paths == [
        "GetClientData",
        "Login",
        "GetPanel",
        "Login",
        "GetPanel",
        "GetClientData",
    ]


@pytest.mark.asyncio
async def test_old_poll_does_not_overwrite_renewed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = response({"Status": "OK"}, token="renewed")  # noqa: S106
    api = ApiInstance("user", "password", "https://controller.test", session=session)
    old_poll_started = asyncio.Event()
    release_old_poll = asyncio.Event()
    poll_count = 0

    async def request(path: str, _payload: object = None) -> dict:
        nonlocal poll_count
        if path == "SetValue":
            raise AuthorizationError
        if path == "GetPanel":
            return {
                "ThemeObject": {"ValueUpdates": [{"DeviceName": "meter", "Value": 100}]}
            }
        poll_count += 1
        if poll_count == 1:
            old_poll_started.set()
            await release_old_poll.wait()
            return {
                "PropertyUpdates": [
                    {"DeviceName": "meter", "PropertyName": "Value", "Value": 1}
                ]
            }
        return {"PropertyUpdates": []}

    monkeypatch.setattr(api, "_request_json", request)
    polling = asyncio.create_task(api.poll())
    await old_poll_started.wait()
    with pytest.raises(AuthorizationError):
        await api.set_value("door", value=True)
    release_old_poll.set()
    await polling

    assert api.get_value("meter") == 100
    assert poll_count == 2
    session.post.assert_called_once()


@pytest.mark.asyncio
async def test_failed_login_cools_down_before_another_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(api_module.time, "monotonic", lambda: now)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(status=401),
        response({"Status": "Unauthorized"}),
        response({"Status": "OK"}, token="renewed"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response({"PropertyUpdates": []}),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(AuthorizationError):
        await api.poll()
    with pytest.raises(AuthorizationError):
        await api.poll()
    assert session.post.call_count == 2
    now += api_module.SESSION_RECOVERY_COOLDOWN
    await api.poll()
    assert session.post.call_count == 5


@pytest.mark.asyncio
async def test_rejected_renewed_session_also_cools_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module.time, "monotonic", lambda: 100.0)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response(status=401),
        response({"Status": "OK"}, token="renewed"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response(status=401),
        response(status=401),
    ]
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(AuthorizationError):
        await api.poll()
    with pytest.raises(AuthorizationError):
        await api.poll()

    assert session.post.call_count == 5

"""HTTP session reuse and bounded request timeout regression tests."""

from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.comfortclick_custom.api import REQUEST_TIMEOUT, ApiInstance

from .api_helpers import response


@pytest.mark.asyncio
async def test_all_requests_reuse_injected_session() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = [
        response({"Status": "OK"}, token="session-token"),  # noqa: S106
        response({"ThemeObject": {"ValueUpdates": []}}),
        response({"PropertyUpdates": []}),
        response({"Status": "OK"}),
    ]
    session.get.return_value = response()
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    await api.connect()
    await api.initialize_state()
    await api.poll()
    await api.set_value("device", value=True)
    await api.disconnect()

    assert session.post.call_count == 4
    session.get.assert_called_once()
    for request in [*session.post.call_args_list, *session.get.call_args_list]:
        assert request.kwargs["timeout"] is REQUEST_TIMEOUT
    assert REQUEST_TIMEOUT.total == 30
    assert REQUEST_TIMEOUT.connect == 10
    assert REQUEST_TIMEOUT.sock_read == 25
    assert "Cookie" not in session.post.call_args_list[0].kwargs["headers"]
    assert (
        session.post.call_args_list[1]
        .kwargs["headers"]["Cookie"]
        .startswith(
            "Token=session-token;",
        )
    )
    session.close.assert_not_called()


@pytest.mark.asyncio
async def test_request_timeout_is_reported_to_caller() -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    reply = response()
    reply.json.side_effect = TimeoutError
    session.post.return_value = reply
    api = ApiInstance("user", "password", "https://controller.test", session=session)

    with pytest.raises(TimeoutError):
        await api.poll()

    session.post.assert_called_once()
    session.close.assert_not_called()

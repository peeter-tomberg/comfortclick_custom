"""Shared HTTP response doubles for API regression tests."""

from http.cookies import SimpleCookie
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp


def response(
    payload: Any = None,
    *,
    status: int = 200,
    token: str | None = None,
) -> MagicMock:
    """Build an async HTTP context manager without opening a socket."""
    result = MagicMock(spec=aiohttp.ClientResponse)
    result.status = status
    result.headers = {} if token is None else {"Set-Cookie": f"Token={token}; Path=/"}
    result.cookies = SimpleCookie()
    if token is not None:
        result.cookies["Token"] = token
    result.json = AsyncMock(return_value=payload)
    result.text = AsyncMock(return_value="test response")
    result.__aenter__.return_value = result
    result.__aexit__.return_value = False
    return result

"""Real HTTP regression for controllers that reject reused connections."""

import aiohttp
import pytest
from aiohttp import web

from custom_components.comfortclick_custom.api import ApiInstance


@pytest.mark.asyncio
async def test_shared_client_uses_fresh_connections_for_legacy_controller() -> None:
    seen_connections: set[object] = set()
    paths = []
    connection_headers = []

    async def controller(request: web.Request) -> web.Response:
        transport = request.transport
        assert transport is not None
        paths.append(request.path)
        connection_headers.append(request.headers.get("Connection"))
        if transport in seen_connections:
            # Emulate the live controller: Login succeeds, then reusing its
            # connection for GetPanel disconnects before an HTTP response.
            transport.close()
            return web.Response()
        seen_connections.add(transport)
        if request.path == "/Login":
            reply = web.json_response({"Status": "OK"})
            reply.set_cookie("Token", "test-session")
            return reply
        assert request.cookies["Token"] == "test-session"  # noqa: S105
        if request.path == "/GetPanel":
            return web.json_response(
                {
                    "ThemeObject": {
                        "ValueUpdates": [{"DeviceName": "meter", "Value": 100}]
                    },
                }
            )
        if request.path == "/GetClientData":
            return web.json_response(
                {
                    "PropertyUpdates": [
                        {"DeviceName": "meter", "PropertyName": "Value", "Value": 101}
                    ],
                }
            )
        return web.json_response({"Status": "OK"})

    application = web.Application()
    application.router.add_route("*", "/{endpoint}", controller)
    runner = web.AppRunner(application)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        port = runner.addresses[0][1]
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=1)
        ) as session:
            api = ApiInstance(
                "test-user",
                "test-password",
                f"http://127.0.0.1:{port}",
                session=session,
            )
            await api.connect()
            await api.initialize_state()
            await api.poll()
            await api.set_value("test-device", value=False)
            await api.disconnect()

            assert api.get_value("meter") == 101
            assert not session.closed
        assert paths == [
            "/Login",
            "/GetPanel",
            "/GetClientData",
            "/SetValue",
            "/Logout",
        ]
        assert connection_headers == ["close"] * len(paths)
        assert len(seen_connections) == len(paths)
    finally:
        await runner.cleanup()

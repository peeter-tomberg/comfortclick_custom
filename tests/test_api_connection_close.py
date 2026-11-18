"""Real HTTP regression for controllers that reject reused connections."""

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web

from custom_components.comfortclick_custom.api import (
    ApiInstance,
    HttpStatusNotOkError,
    create_api_session,
)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("force_close", [False, True])
async def test_server_ignoring_close_header_requires_client_force_close(
    *,
    force_close: bool,
) -> None:
    writers: set[asyncio.StreamWriter] = set()
    connection_headers = []

    async def controller(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writers.add(writer)
        requests = 0
        try:
            while True:
                raw_headers = await reader.readuntil(b"\r\n\r\n")
                lines = raw_headers.decode().split("\r\n")
                path = lines[0].split()[1].split("?", 1)[0]
                headers = dict(line.split(": ", 1) for line in lines[1:] if line)
                await reader.readexactly(int(headers.get("Content-Length", "0")))
                connection_headers.append(
                    next(
                        (
                            value
                            for key, value in headers.items()
                            if key.casefold() == "connection"
                        ),
                        None,
                    )
                )
                requests += 1
                if requests > 1:
                    # Unlike aiohttp.web, this server ignores the client's
                    # Connection: close header and falsely advertises keep-alive.
                    return
                if path == "/GetPanel":
                    payload = {"ThemeObject": {"ValueUpdates": []}}
                else:
                    payload = {"Status": "OK"}
                body = json.dumps(payload).encode()
                reply = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: keep-alive\r\n"
                    "Set-Cookie: Token=test-session; Path=/\r\n"
                    f"Content-Length: {len(body)}\r\n\r\n"
                ).encode() + body
                writer.write(reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(controller, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        session = create_api_session() if force_close else aiohttp.ClientSession()
        async with session:
            api = ApiInstance(
                "test-user",
                "test-password",
                f"http://127.0.0.1:{port}",
                session=session,
            )
            await api.connect()
            if force_close:
                await api.initialize_state()
                assert len(writers) == 2
            else:
                with pytest.raises(aiohttp.ServerDisconnectedError):
                    await api.initialize_state()
                assert len(writers) == 1
            assert connection_headers == ["close", "close"]
    finally:
        server.close()
        await server.wait_closed()
        for writer in writers:
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for writer in writers))


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect_endpoint", ["Login", "GetPanel", "Logout"])
async def test_credentials_are_never_forwarded_to_redirects(
    redirect_endpoint: str,
) -> None:
    redirected_requests = []

    async def controller(request: web.Request) -> web.Response:
        if request.path == "/redirected":
            redirected_requests.append(request.method)
        if request.path == f"/{redirect_endpoint}":
            return web.Response(status=307, headers={"Location": "/redirected"})
        reply = web.json_response({"Status": "OK"})
        if request.path == "/Login":
            reply.set_cookie("Token", "test-session")
        return reply

    application = web.Application()
    application.router.add_route("*", "/{endpoint}", controller)
    runner = web.AppRunner(application)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        port = runner.addresses[0][1]
        async with create_api_session() as session:
            api = ApiInstance(
                "test-user",
                "test-password",
                f"http://127.0.0.1:{port}",
                session=session,
            )
            if redirect_endpoint == "Login":
                with pytest.raises(HttpStatusNotOkError):
                    await api.connect()
            else:
                await api.connect()
                if redirect_endpoint == "GetPanel":
                    with pytest.raises(HttpStatusNotOkError):
                        await api.initialize_state()
            await api.disconnect()
        assert redirected_requests == []
    finally:
        await runner.cleanup()

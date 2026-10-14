
import asyncio

import pytest

import server as gateway_server


class FakeASGIApp:
    def __init__(self):
        self.calls = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def make_scope(path="/mcp", api_key="key-a"):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"x-api-key", api_key.encode())],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8100),
    }


async def invoke(middleware, scope):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = next((m.get("body", b"") for m in messages if m["type"] == "http.response.body"), b"")
    return start["status"], dict(start.get("headers", [])), body


def test_rate_limit_returns_429_and_retry_after(monkeypatch):
    monkeypatch.setattr(
        gateway_server,
        "authenticate_api_key",
        lambda key: {"id": "user-a", "api_key_id": "key-id-a", "role": "member"},
    )
    app = FakeASGIApp()
    middleware = gateway_server.MCPAPIKeyMiddleware(
    app,
    rate_limit=2,
    window_seconds=60,
)

    async def run():
        assert (await invoke(middleware, make_scope()))[0] == 200
        assert (await invoke(middleware, make_scope()))[0] == 200
        status, headers, body = await invoke(middleware, make_scope())
        assert status == 429
        assert int(headers[b"retry-after"]) >= 1
        assert b"Rate limit exceeded" in body

    asyncio.run(run())
    assert app.calls == 2


def test_rate_limit_is_per_api_key(monkeypatch):
    def authenticate(key):
        key_id = {"key-a": "key-id-a", "key-b": "key-id-b"}[key]
        return {"id": key_id, "api_key_id": key_id, "role": "member"}

    monkeypatch.setattr(gateway_server, "authenticate_api_key", authenticate)
    app = FakeASGIApp()
    middleware = gateway_server.MCPAPIKeyMiddleware(
    app,
    rate_limit=1,
    window_seconds=60,
)

    async def run():
        assert (await invoke(middleware, make_scope(api_key="key-a")))[0] == 200
        assert (await invoke(middleware, make_scope(api_key="key-a")))[0] == 429
        assert (await invoke(middleware, make_scope(api_key="key-b")))[0] == 200

    asyncio.run(run())
    assert app.calls == 2


def test_invalid_key_still_returns_401_and_does_not_call_app(monkeypatch):
    def reject(_key):
        raise ValueError("invalid key")

    monkeypatch.setattr(gateway_server, "authenticate_api_key", reject)
    app = FakeASGIApp()
    middleware = gateway_server.MCPAPIKeyMiddleware(
    app,
    rate_limit=1,
    window_seconds=60,
)

    async def run():
        status, headers, body = await invoke(middleware, make_scope(api_key="bad"))
        assert status == 401
        assert headers[b"www-authenticate"] == b"ApiKey"
        assert b"valid API key" in body

    asyncio.run(run())
    assert app.calls == 0


def test_non_mcp_path_is_not_rate_limited_or_authenticated(monkeypatch):
    def unexpected_auth(_key):
        raise AssertionError("Non-MCP paths should bypass this middleware")

    monkeypatch.setattr(gateway_server, "authenticate_api_key", unexpected_auth)
    app = FakeASGIApp()
    middleware = gateway_server.MCPAPIKeyMiddleware(app)

    async def run():
        assert (await invoke(middleware, make_scope(path="/health")))[0] == 200
        assert (await invoke(middleware, make_scope(path="/health")))[0] == 200

    asyncio.run(run())
    assert app.calls == 2

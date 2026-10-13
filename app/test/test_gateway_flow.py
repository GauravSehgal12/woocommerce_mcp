"""Gateway-flow tests using a fake upstream MCP server.

These tests exercise the gateway's API-key middleware, tool handler, and audit
logging without starting the live gateway, Kubernetes, or WooCommerce services.
"""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.Gateway import security
from app.Gateway import server as gateway


@pytest.fixture()
def gateway_test_db(tmp_path, monkeypatch):
    """Keep gateway tests isolated from the project's real security.db."""
    monkeypatch.setattr(security, "DB_FILE", tmp_path / "gateway_test.db")
    monkeypatch.setattr(security, "DATA_DIR", tmp_path)
    security.init_db()

    admin = security.create_user("gateway_test_admin", "admin")
    admin_key = security.issue_api_key(admin["id"])
    member = security.create_user("gateway_test_member", "member")
    member_key = security.issue_api_key(member["id"])

    return {
        "admin": admin,
        "admin_key": admin_key,
        "member": member,
        "member_key": member_key,
    }


def read_audit_rows():
    with security.get_db() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM audit_logs ORDER BY id ASC"
            ).fetchall()
        ]


class FakeUpstreamClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def initialize(self):
        return None

    async def call_tool(self, name, arguments=None):
        if self.error:
            raise self.error
        assert name == "get_inventory"
        assert arguments == {}
        return self.result


@pytest.fixture()
def fake_upstream(monkeypatch):
    state = {
        "result": SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(text='{"available": 7}')],
        ),
        "error": None,
        "called": False,
    }

    @asynccontextmanager
    async def fake_streamablehttp_client(url):
        assert url == "http://inventory.test/mcp"
        yield object(), object(), None

    def fake_client_session(read_stream, write_stream):
        state["called"] = True
        return FakeUpstreamClient(state["result"], state["error"])

    monkeypatch.setattr(gateway, "streamablehttp_client", fake_streamablehttp_client)
    monkeypatch.setattr(gateway, "ClientSession", fake_client_session)
    return state


@pytest.fixture()
def inventory_handler(monkeypatch):
    server = {
        "id": "inventory-test-id",
        "name": "inventory",
        "url": "http://inventory.test/mcp",
        "enabled": True,
    }
    monkeypatch.setattr(gateway, "read_registry", lambda: [server])
    return gateway.make_handler(
        server_id=server["id"],
        server_name=server["name"],
        server_url=server["url"],
        upstream_tool_name="get_inventory",
        description="Test inventory lookup",
    )


def call_as_user(handler, user):
    token = gateway.current_user_context.set(user)
    try:
        return asyncio.run(handler())
    finally:
        gateway.current_user_context.reset(token)


def test_gateway_mcp_endpoint_rejects_missing_and_invalid_keys(gateway_test_db):
    app = FastAPI()

    @app.get("/mcp")
    def mcp_endpoint():
        user = gateway.current_user_context.get()
        assert user is not None
        return {"username": user["username"]}

    secured_app = gateway.MCPAPIKeyMiddleware(app)
    with TestClient(secured_app) as client:
        assert client.get("/mcp").status_code == 401
        assert client.get(
            "/mcp", headers={"X-API-Key": "mcp_live_not-a-real-key"}
        ).status_code == 401


def test_gateway_mcp_endpoint_accepts_a_valid_key(gateway_test_db):
    app = FastAPI()

    @app.get("/mcp")
    def mcp_endpoint():
        user = gateway.current_user_context.get()
        assert user is not None
        return {"username": user["username"], "role": user["role"]}

    secured_app = gateway.MCPAPIKeyMiddleware(app)
    with TestClient(secured_app) as client:
        response = client.get(
            "/mcp",
            headers={"X-API-Key": gateway_test_db["admin_key"]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "username": "gateway_test_admin",
        "role": "admin",
    }


def test_successful_tool_call_creates_success_audit(
    gateway_test_db, fake_upstream, inventory_handler
):
    result = call_as_user(inventory_handler, gateway_test_db["admin"])

    assert result["is_error"] is False
    assert result["upstream"] == "inventory"
    assert result["tool"] == "get_inventory"
    assert result["content"] == ['{"available": 7}']
    assert fake_upstream["called"] is True

    rows = read_audit_rows()
    assert len(rows) == 1
    assert rows[0]["username"] == "gateway_test_admin"
    assert rows[0]["server_name"] == "inventory"
    assert rows[0]["tool_name"] == "get_inventory"
    assert rows[0]["outcome"] == "success"
    assert rows[0]["duration_ms"] >= 0


def test_upstream_tool_error_creates_error_audit(
    gateway_test_db, fake_upstream, inventory_handler
):
    fake_upstream["result"] = SimpleNamespace(
        isError=True,
        content=[SimpleNamespace(text="Inventory lookup failed")],
    )

    result = call_as_user(inventory_handler, gateway_test_db["member"])

    assert result["is_error"] is True
    rows = read_audit_rows()
    assert len(rows) == 1
    assert rows[0]["username"] == "gateway_test_member"
    assert rows[0]["outcome"] == "error"
    assert rows[0]["details"] == "Upstream tool returned an error"


def test_upstream_connection_exception_is_sanitized_and_audited(
    gateway_test_db, fake_upstream, inventory_handler
):
    fake_upstream["error"] = ConnectionError("private upstream details")

    result = call_as_user(inventory_handler, gateway_test_db["admin"])

    assert result["is_error"] is True
    assert result["error"] == "Upstream tool call failed."
    rows = read_audit_rows()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "error"
    assert rows[0]["details"] in {"ConnectionError", "MCP server connection failed"}
    assert "private upstream details" not in (rows[0]["details"] or "")


def test_disabled_server_is_denied_and_audited(
    gateway_test_db, monkeypatch, fake_upstream, inventory_handler
):
    monkeypatch.setattr(
        gateway,
        "read_registry",
        lambda: [{
            "id": "inventory-test-id",
            "name": "inventory",
            "url": "http://inventory.test/mcp",
            "enabled": False,
        }],
    )

    result = call_as_user(inventory_handler, gateway_test_db["admin"])

    assert result["is_error"] is True
    assert "disabled or removed" in result["error"]
    assert fake_upstream["called"] is False
    rows = read_audit_rows()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "denied"
    assert rows[0]["details"] == "Server disabled or removed"


def test_changed_server_url_is_denied_and_audited(
    gateway_test_db, monkeypatch, fake_upstream, inventory_handler
):
    monkeypatch.setattr(
        gateway,
        "read_registry",
        lambda: [{
            "id": "inventory-test-id",
            "name": "inventory",
            "url": "http://unexpected.test/mcp",
            "enabled": True,
        }],
    )

    result = call_as_user(inventory_handler, gateway_test_db["admin"])

    assert result["is_error"] is True
    assert "URL changed" in result["error"]
    assert fake_upstream["called"] is False
    rows = read_audit_rows()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "denied"
    assert rows[0]["details"] == "Server URL changed; refresh discovery"

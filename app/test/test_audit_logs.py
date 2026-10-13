import pytest
from fastapi.testclient import TestClient

from app.Gateway import security
from app.Gateway import registry_api


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Use a temporary database; never touch the real security.db."""
    monkeypatch.setattr(security, "DB_FILE", tmp_path / "security_test.db")
    monkeypatch.setattr(security, "DATA_DIR", tmp_path)
    security.init_db()

    admin = security.create_user("test_admin", "admin")
    admin_key = security.issue_api_key(admin["id"])
    member = security.create_user("test_member", "member")
    member_key = security.issue_api_key(member["id"])

    return {
        "admin": admin,
        "admin_key": admin_key,
        "member": member,
        "member_key": member_key,
    }


@pytest.fixture()
def client(test_db):
    with TestClient(registry_api.app) as test_client:
        yield test_client


def auth(api_key):
    return {"X-API-Key": api_key}


def add_record(user, server, tool, outcome, details=None, duration_ms=12):
    security.record_audit_event(
        user=user,
        server_name=server,
        tool_name=tool,
        duration_ms=duration_ms,
        outcome=outcome,
        details=details,
    )


def test_missing_api_key_returns_401(client):
    assert client.get("/audit-logs").status_code == 401


def test_invalid_api_key_returns_401(client):
    response = client.get("/audit-logs", headers=auth("mcp_live_invalid_key"))
    assert response.status_code == 401


def test_member_cannot_view_audit_logs(client, test_db):
    response = client.get("/audit-logs", headers=auth(test_db["member_key"]))
    assert response.status_code == 403


def test_admin_can_view_empty_audit_logs(client, test_db):
    response = client.get("/audit-logs", headers=auth(test_db["admin_key"]))
    assert response.status_code == 200
    assert response.json() == {
        "count": 0, "total": 0, "limit": 50, "offset": 0, "logs": []
    }


def test_audit_event_is_persisted_and_returned(client, test_db):
    add_record(
        test_db["member"], "inventory", "search_products", "success",
        "Found 3 products", duration_ms=25
    )
    response = client.get("/audit-logs", headers=auth(test_db["admin_key"]))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["count"] == 1
    record = body["logs"][0]
    assert record["username"] == "test_member"
    assert record["server_name"] == "inventory"
    assert record["tool_name"] == "search_products"
    assert record["outcome"] == "success"
    assert record["details"] == "Found 3 products"
    assert record["duration_ms"] == 25
    assert record["timestamp"]


def test_filter_by_outcome(client, test_db):
    add_record(test_db["admin"], "inventory", "list_items", "success")
    add_record(test_db["member"], "woocommerce", "get_order", "error")
    response = client.get(
        "/audit-logs", params={"outcome": "error"},
        headers=auth(test_db["admin_key"])
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert all(row["outcome"] == "error" for row in response.json()["logs"])


def test_filter_by_username_and_server(client, test_db):
    add_record(test_db["admin"], "inventory", "list_items", "success")
    add_record(test_db["member"], "woocommerce", "get_order", "success")

    response = client.get(
        "/audit-logs", params={"username": "test_member"},
        headers=auth(test_db["admin_key"])
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["logs"][0]["username"] == "test_member"

    response = client.get(
        "/audit-logs", params={"server_name": "woo"},
        headers=auth(test_db["admin_key"])
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["logs"][0]["server_name"] == "woocommerce"


def test_pagination(client, test_db):
    for index in range(3):
        add_record(test_db["admin"], "inventory", f"tool_{index}", "success")
    response = client.get(
        "/audit-logs", params={"limit": 2, "offset": 1},
        headers=auth(test_db["admin_key"])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["count"] == 2
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [row["tool_name"] for row in body["logs"]] == ["tool_1", "tool_0"]


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"limit": 0}, "Limit must be between 1 and 100."),
        ({"limit": 101}, "Limit must be between 1 and 100."),
        ({"offset": -1}, "Offset must be zero or greater."),
        ({"outcome": "unknown"}, "Outcome must be success, error, or denied."),
    ],
)
def test_invalid_query_parameters_return_400(client, test_db, params, detail):
    response = client.get(
        "/audit-logs", params=params, headers=auth(test_db["admin_key"])
    )
    assert response.status_code == 400
    assert response.json()["detail"] == detail


def test_invalid_audit_outcome_is_rejected(test_db):
    with pytest.raises(ValueError, match="Invalid audit outcome"):
        security.record_audit_event(
            user=test_db["admin"], server_name="inventory",
            tool_name="list_items", duration_ms=1, outcome="unexpected"
        )


def test_audit_details_are_limited_to_1000_characters(client, test_db):
    add_record(
        test_db["admin"], "inventory", "list_items", "error", "x" * 1200
    )
    response = client.get("/audit-logs", headers=auth(test_db["admin_key"]))
    assert response.status_code == 200
    assert len(response.json()["logs"][0]["details"]) == 1000


def test_revoked_api_key_cannot_access_audit_logs(client, test_db):
    with security.get_db() as db:
        row = db.execute(
            "SELECT id FROM api_keys WHERE user_id = ?",
            (test_db["admin"]["id"],),
        ).fetchone()
    assert row is not None
    assert security.revoke_api_key(row["id"]) is True
    response = client.get(
        "/audit-logs", headers=auth(test_db["admin_key"])
    )
    assert response.status_code == 401


import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from fastapi import (
    FastAPI,
    HTTPException,
    status,
    Depends,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .security import (
        create_user,
        get_current_user,
        get_db,
        get_db,
        issue_api_key,
        list_users,
        list_user_keys,
        require_role,
        revoke_api_key,
    )
except ImportError:
    from security import (
        create_user,
        get_current_user,
        issue_api_key,
        list_users,
        list_user_keys,
        require_role,
        revoke_api_key,
    )


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REGISTRY_FILE = DATA_DIR / "servers.json"
HEALTH_FILE = DATA_DIR / "health.json"

registry_lock = Lock()

app = FastAPI(
    title="MCP Gateway Server Registry",
    version="1.2.0",
    description="Register, manage, and monitor upstream MCP servers.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


# ---------------------------------------------------------
# Request models
# ---------------------------------------------------------

class ServerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    url: str = Field(min_length=8, max_length=500)
    description: str = Field(default="", max_length=500)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    role: str = Field(pattern=r"^(admin|member)$")


# ---------------------------------------------------------
# Registry file helpers
# ---------------------------------------------------------

def validate_server_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=400,
            detail="URL must be a valid HTTP or HTTPS URL.",
        )

    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400,
            detail="Do not put credentials in the server URL.",
        )

    return url.rstrip("/")


def read_registry() -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not REGISTRY_FILE.exists():
        return []

    try:
        with REGISTRY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise ValueError("Registry must contain a JSON list.")

        return data

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Registry file is missing, unreadable, or invalid.",
        ) from exc


def read_health_status() -> dict:
    """Read health data written by the MCP gateway."""
    if not HEALTH_FILE.exists():
        return {}

    try:
        with HEALTH_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("Health file must contain a JSON object.")

        return data

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Health data could not be read or is invalid.",
        ) from exc


def write_registry(servers: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DATA_DIR,
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump(servers, file, indent=2)
            temp_path = file.name

        os.replace(temp_path, REGISTRY_FILE)

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def find_server(servers: list[dict], server_id: str) -> dict:
    for server in servers:
        if server.get("id") == server_id:
            return server

    raise HTTPException(
        status_code=404,
        detail="Server was not found.",
    )


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/health")
def health():
    """Unauthenticated liveness check for the Registry API."""
    return {"status": "healthy"}


# ---------------------------------------------------------
# Server listing and monitoring
# ---------------------------------------------------------

@app.get("/servers")
def list_servers(
    current_user: dict = Depends(get_current_user),
):
    """List registered MCP servers for authenticated users."""
    with registry_lock:
        servers = read_registry()

    return {
        "count": len(servers),
        "servers": servers,
    }


@app.get("/servers/health")
def list_servers_health(
    current_user: dict = Depends(get_current_user),
):
    """Return health information for registered MCP servers."""
    with registry_lock:
        servers = read_registry()
        health_status = read_health_status()

    results = []

    for server in servers:
        server_id = server.get("id")
        record = health_status.get(server_id, {})

        if not server.get("enabled", False):
            current_status = "disabled"
        else:
            current_status = record.get("status", "unknown")

        results.append(
            {
                "server_id": server_id,
                "name": server.get("name"),
                "url": server.get("url"),
                "enabled": server.get("enabled", False),
                "status": current_status,
                "last_checked": record.get("last_checked"),
                "last_successful_check": record.get(
                    "last_successful_check"
                ),
                "last_error": record.get("last_error"),
                "discovered_tools_count": record.get(
                    "discovered_tools_count", 0
                ),
            }
        )

    return {
        "count": len(results),
        "servers": results,
    }


# ---------------------------------------------------------
# Server management - admin only
# ---------------------------------------------------------

@app.post(
    "/servers",
    status_code=status.HTTP_201_CREATED,
)
def register_server(
    payload: ServerCreate,
    admin: dict = Depends(require_role("admin")),
):
    """Register a new MCP server."""
    normalized_name = payload.name.strip()

    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]*",
        normalized_name,
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Name must contain only letters, numbers, "
                "underscores, or hyphens."
            ),
        )

    normalized_url = validate_server_url(payload.url)

    with registry_lock:
        servers = read_registry()

        if any(
            server["name"].lower() == normalized_name.lower()
            for server in servers
        ):
            raise HTTPException(
                status_code=409,
                detail="A server with this name already exists.",
            )

        if any(
            server["url"] == normalized_url
            for server in servers
        ):
            raise HTTPException(
                status_code=409,
                detail="A server with this URL is already registered.",
            )

        now = datetime.now(timezone.utc).isoformat()

        server = {
            "id": str(uuid.uuid4()),
            "name": normalized_name,
            "url": normalized_url,
            "description": payload.description.strip(),
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }

        servers.append(server)
        write_registry(servers)

    return {
        "message": "Server registered.",
        "server": server,
    }


@app.patch("/servers/{server_id}/disable")
def disable_server(
    server_id: str,
    admin: dict = Depends(require_role("admin")),
):
    """Disable an MCP server."""
    with registry_lock:
        servers = read_registry()
        server = find_server(servers, server_id)

        server["enabled"] = False
        server["updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        write_registry(servers)

    return {
        "message": "Server disabled.",
        "server": server,
    }


@app.patch("/servers/{server_id}/enable")
def enable_server(
    server_id: str,
    admin: dict = Depends(require_role("admin")),
):
    """Enable an MCP server."""
    with registry_lock:
        servers = read_registry()
        server = find_server(servers, server_id)

        server["enabled"] = True
        server["updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        write_registry(servers)

    return {
        "message": "Server enabled.",
        "server": server,
    }


@app.delete("/servers/{server_id}")
def remove_server(
    server_id: str,
    admin: dict = Depends(require_role("admin")),
):
    """Remove an MCP server from the registry."""
    with registry_lock:
        servers = read_registry()
        server = find_server(servers, server_id)

        servers = [
            item
            for item in servers
            if item["id"] != server_id
        ]

        write_registry(servers)

    return {
        "message": "Server removed from registry.",
        "server_id": server_id,
        "name": server["name"],
    }


# ---------------------------------------------------------
# User management - admin only
# ---------------------------------------------------------

@app.post("/users", status_code=status.HTTP_201_CREATED)
def api_create_user(
    request: CreateUserRequest,
    admin: dict = Depends(require_role("admin")),
):
    try:
        return create_user(request.username, request.role)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="That username already exists.",
            ) from exc
        raise


@app.get("/users")
def api_list_users(
    admin: dict = Depends(require_role("admin")),
):
    return {"users": list_users()}


@app.post("/users/{user_id}/api-keys", status_code=201)
def api_issue_key(
    user_id: str,
    admin: dict = Depends(require_role("admin")),
):
    try:
        api_key = issue_api_key(user_id)
        # The raw API key is returned only once.
        return {"api_key": api_key}

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.get("/users/{user_id}/api-keys")
def api_list_keys(
    user_id: str,
    admin: dict = Depends(require_role("admin")),
):
    return {"api_keys": list_user_keys(user_id)}


@app.post("/api-keys/{key_id}/revoke")
def api_revoke_key(
    key_id: str,
    admin: dict = Depends(require_role("admin")),
):
    if not revoke_api_key(key_id):
        raise HTTPException(
            status_code=404,
            detail="API key not found or already revoked.",
        )

    return {"message": "API key revoked."}


# ---------------------------------------------------------
# Audit logs - admin only
# ---------------------------------------------------------

@app.get("/audit-logs")
def list_audit_logs(
    limit: int = 50,
    offset: int = 0,
    outcome: str | None = None,
    username: str | None = None,
    server_name: str | None = None,
    admin: dict = Depends(require_role("admin")),
):
    """Return a paginated, filterable view of tool-call audit events."""
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100.")
    if offset < 0:
        raise HTTPException(status_code=400, detail="Offset must be zero or greater.")
    if outcome and outcome not in {"success", "error", "denied"}:
        raise HTTPException(status_code=400, detail="Outcome must be success, error, or denied.")

    clauses = []
    params = []
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    if username and username.strip():
        clauses.append("username LIKE ?")
        params.append(f"%{username.strip()[:80]}%")
    if server_name and server_name.strip():
        clauses.append("server_name LIKE ?")
        params.append(f"%{server_name.strip()[:80]}%")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_db() as db:
        total = db.execute(f"SELECT COUNT(*) FROM audit_logs {where_sql}", params).fetchone()[0]
        rows = db.execute(
            f"""
            SELECT id, user_id, username, server_name, tool_name,
                   timestamp, duration_ms, outcome, details
            FROM audit_logs
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    return {"count": len(rows), "total": total, "limit": limit, "offset": offset, "logs": [dict(row) for row in rows]}

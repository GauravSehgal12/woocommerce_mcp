
import asyncio
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
    Cookie,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

try:
    from .security import (
        authenticate_browser_session,
        authenticate_password,
        create_browser_session,
        create_user,
        get_current_user,
        get_db,
        init_db,
        issue_api_key,
        issue_api_key_with_metadata,
        list_api_key_permissions,
        set_api_key_permissions,
        list_users,
        list_user_keys,
        require_role,
        revoke_api_key,
        revoke_browser_session,
        SESSION_COOKIE_NAME,
        SESSION_TTL_SECONDS,
        set_user_password,
    )
except ImportError:
    from security import (
        authenticate_browser_session,
        authenticate_password,
        create_browser_session,
        create_user,
        get_current_user,
        get_db,
        init_db,
        issue_api_key,
        issue_api_key_with_metadata,
        list_api_key_permissions,
        set_api_key_permissions,
        list_users,
        list_user_keys,
        require_role,
        revoke_api_key,
        revoke_browser_session,
        SESSION_COOKIE_NAME,
        SESSION_TTL_SECONDS,
        set_user_password,
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
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def initialize_security_database() -> None:
    # Idempotent schema migration, including api_key_permissions.
    init_db()


# ---------------------------------------------------------
# Request models
# ---------------------------------------------------------

class ServerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    url: str = Field(min_length=8, max_length=500)
    description: str = Field(default="", max_length=500)
    headers: dict[str, str] = Field(default_factory=dict, max_length=50)


class ServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    url: str | None = Field(default=None, min_length=8, max_length=500)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    headers: dict[str, str] | None = Field(default=None, max_length=50)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    role: str = Field(pattern=r"^(admin|member)$")
    password: str = Field(min_length=12, max_length=1024)

class ApiKeyPermissionsRequest(BaseModel):
    tools: list[str] = Field(default_factory=list, max_length=500)


class LoginCredentialsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


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


def validate_upstream_headers(headers: dict[str, str]) -> dict[str, str]:
    """Validate custom upstream headers before persisting them."""
    if len(headers) > 50:
        raise HTTPException(status_code=400, detail="At most 50 upstream headers are allowed.")
    blocked = {"host", "content-length", "connection", "transfer-encoding"}
    clean: dict[str, str] = {}
    for name, value in headers.items():
        normalized_name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_|~-]+", normalized_name):
            raise HTTPException(status_code=400, detail="An upstream header name is invalid.")
        if normalized_name.lower() in blocked:
            raise HTTPException(status_code=400, detail=f"The {normalized_name} header cannot be overridden.")
        if not isinstance(value, str) or len(value) > 4096 or chr(13) in value or chr(10) in value:
            raise HTTPException(status_code=400, detail=f"The value for header {normalized_name} is invalid.")
        clean[normalized_name] = value
    return clean


def public_server(server: dict) -> dict:
    """Do not expose upstream credential values in registry responses."""
    result = dict(server)
    headers = result.pop("headers", {}) or {}
    result["configured_header_names"] = sorted(headers.keys())
    result["has_upstream_headers"] = bool(headers)
    return result


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/health")
def health():
    """Unauthenticated liveness check for the Registry API."""
    return {"status": "healthy"}


# ---------------------------------------------------------
# Browser authentication
# ---------------------------------------------------------

@app.post("/auth/login")
def login(request: LoginCredentialsRequest, response: Response):
    user = authenticate_password(request.username, request.password)
    token, expires_at = create_browser_session(user["id"])

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/",
    )

    return {
        "user": user,
        "expires_at": expires_at,
    }


@app.post("/auth/logout")
def logout(
    response: Response,
    woo_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    revoke_browser_session(woo_session)

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
    )

    return {"message": "Logged out."}


@app.get("/auth/me")
def current_browser_user(
    woo_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    return {"user": authenticate_browser_session(woo_session)}


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
        "servers": [public_server(server) for server in servers],
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
                "configured_header_names": sorted((server.get("headers") or {}).keys()),
                "has_upstream_headers": bool(server.get("headers")),
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
    normalized_headers = validate_upstream_headers(payload.headers)

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
            "headers": normalized_headers,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }

        servers.append(server)
        write_registry(servers)

    return {
        "message": "Server registered.",
        "server": public_server(server),
    }


@app.patch("/servers/{server_id}")
def update_server(
    server_id: str,
    payload: ServerUpdate,
    admin: dict = Depends(require_role("admin")),
):
    """Partially update an upstream MCP server's metadata and credentials."""
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Provide at least one field to update.")

    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise HTTPException(status_code=400, detail="Name must contain only letters, numbers, underscores, or hyphens.")
        changes["name"] = name

    if "url" in changes:
        changes["url"] = validate_server_url(changes["url"])

    if "description" in changes:
        changes["description"] = (changes["description"] or "").strip()

    if "headers" in changes and changes["headers"] is not None:
        changes["headers"] = validate_upstream_headers(changes["headers"])

    with registry_lock:
        servers = read_registry()
        current = find_server(servers, server_id)

        next_name = changes.get("name", current["name"])
        next_url = changes.get("url", current["url"])
        for other in servers:
            if other.get("id") == server_id:
                continue
            if other.get("name", "").lower() == next_name.lower():
                raise HTTPException(status_code=409, detail="A server with this name already exists.")
            if other.get("url") == next_url:
                raise HTTPException(status_code=409, detail="A server with this URL is already registered.")

        current.update(changes)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_registry(servers)

    return {"message": "Server updated.", "server": public_server(current)}


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
        user = create_user(request.username, request.role)
        set_user_password(user["id"], request.password)
        return user

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
def api_issue_key(user_id: str, admin: dict = Depends(require_role("admin"))):
    try:
        # The raw secret is returned once; it is never persisted in plaintext.
        return issue_api_key_with_metadata(user_id)
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@app.get("/users/{user_id}/api-keys")
def api_list_keys(user_id: str, admin: dict = Depends(require_role("admin"))):
    if not any(item["id"] == user_id for item in list_users()):
        raise HTTPException(status_code=404, detail="User was not found.")
    return {"api_keys": list_user_keys(user_id)}


@app.post("/api-keys/{key_id}/revoke")
def api_revoke_key(key_id: str, admin: dict = Depends(require_role("admin"))):
    if not revoke_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found or already revoked.")
    return {"message": "API key revoked."}


@app.get("/api-keys/{key_id}/permissions")
def api_get_key_permissions(key_id: str, admin: dict = Depends(require_role("admin"))):
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM api_keys WHERE id = ? AND revoked_at IS NULL", (key_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Active API key was not found.")
    return {"key_id": key_id, "tools": list_api_key_permissions(key_id)}


@app.put("/api-keys/{key_id}/permissions")
def api_put_key_permissions(
    key_id: str,
    request: ApiKeyPermissionsRequest,
    admin: dict = Depends(require_role("admin")),
):
    try:
        tools = set_api_key_permissions(key_id, request.tools)
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return {"key_id": key_id, "tools": tools, "count": len(tools)}


@app.get("/available-tools")
async def api_available_tools(admin: dict = Depends(require_role("admin"))):
    """Discover fully-qualified tool names from enabled upstream MCP servers."""
    with registry_lock:
        servers = read_registry()
    available, warnings = [], []
    for server in servers:
        if not server.get("enabled", False):
            continue
        try:
            async def discover_tools():
                from datetime import timedelta
                async with streamablehttp_client(
                    server["url"],
                    headers=server.get("headers") or {},
                    timeout=timedelta(seconds=5),
                    sse_read_timeout=timedelta(seconds=5),
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as client:
                        await client.initialize()
                        return await client.list_tools()

            result = await asyncio.wait_for(discover_tools(), timeout=5)
            for tool in result.tools:
                available.append({
                    "name": f"{server['name']}__{tool.name}",
                    "server_name": server["name"],
                    "tool_name": tool.name,
                    "description": tool.description or "",
                })
        except (TimeoutError, asyncio.TimeoutError):
            warnings.append({
                "server_name": server.get("name", "unknown"),
                "error": "Tool discovery timed out after 5 seconds.",
            })
        except Exception as exc:
            error_type = type(exc).__name__
            unreachable = isinstance(exc, (ConnectionError, OSError)) or error_type in {
                "ConnectError", "NetworkError", "RemoteProtocolError"
            }
            warnings.append({
                "server_name": server.get("name", "unknown"),
                "error": (
                    "Upstream MCP server is unreachable. Check its URL and network connectivity."
                    if unreachable else f"Tool discovery failed ({error_type})."
                ),
            })
    available.sort(key=lambda item: item["name"].lower())
    return {"tools": available, "warnings": warnings}


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

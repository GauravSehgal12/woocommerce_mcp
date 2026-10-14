import asyncio
import contextvars
from collections import deque
from math import ceil
import inspect
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Annotated, cast


import uvicorn
from dotenv import load_dotenv
from pydantic import Field
from starlette.types import ASGIApp, Scope, Receive, Send

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp import types

try:
    from .security import authenticate_api_key, init_db, record_audit_event, api_key_has_tool_permission
except ImportError:
    from security import authenticate_api_key, init_db, record_audit_event, api_key_has_tool_permission


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

REGISTRY_FILE = BASE_DIR / "data" / "servers.json"
HEALTH_FILE = BASE_DIR / "data" / "health.json"

GATEWAY_HOST = os.getenv("GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8100"))
REFRESH_INTERVAL = 5
# Sliding-window rate limit for authenticated MCP HTTP requests.
GATEWAY_RATE_LIMIT = max(1, int(os.getenv("GATEWAY_RATE_LIMIT", "60")))
GATEWAY_RATE_WINDOW_SECONDS = max(
    1, int(os.getenv("GATEWAY_RATE_WINDOW_SECONDS", "60"))
)

mcp = FastMCP("woo-mcp-gateway", host=GATEWAY_HOST, port=GATEWAY_PORT)
registered_tools: dict[str, dict[str, str]] = {}
current_user_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_authenticated_user", default=None
)

def install_permission_filtered_tool_listing() -> None:
    """Filter tools/list results for the authenticated API key."""
    request_handlers = mcp._mcp_server.request_handlers

    original_handler = request_handlers.get(types.ListToolsRequest)
    if original_handler is None:
        raise RuntimeError("MCP tools/list handler was not registered")

    async def filtered_handler(request):
        response = await original_handler(request)

        # FastMCP's handler returns ServerResult(ListToolsResult(...)).
        result = response.root if hasattr(response, "root") else response

        if not isinstance(result, types.ListToolsResult):
            return response

        user = current_user_context.get()

        # Fail closed if no authenticated identity is available.
        if not user:
            allowed_tools = []
        elif user.get("role") == "admin":
            allowed_tools = result.tools
        else:
            api_key_id = user.get("api_key_id")
            allowed_tools = [
                tool
                for tool in result.tools
                if api_key_has_tool_permission(
                    api_key_id,
                    tool.name,
                )
            ]

        return types.ServerResult(
            types.ListToolsResult(tools=allowed_tools)
        )

    request_handlers[types.ListToolsRequest] = filtered_handler

install_permission_filtered_tool_listing()


def read_registry() -> list[dict]:
    if not REGISTRY_FILE.exists():
        return []
    with REGISTRY_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("Server registry must be a JSON list.")
    return data


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize_exception(exc: BaseException) -> str:
    """Return a useful, sanitized audit message for a failed tool call."""
    exceptions = []

    def collect(error: BaseException) -> None:
        if isinstance(error, BaseExceptionGroup):
            for child in error.exceptions:
                collect(child)
        else:
            exceptions.append(error)

    collect(exc)

    # Prefer specific, actionable causes over the outer ExceptionGroup.
    if any(isinstance(e, (TimeoutError, asyncio.TimeoutError))
           for e in exceptions):
        return "Tool execution timed out"

    if any(isinstance(e, ConnectionRefusedError) for e in exceptions):
        return "MCP server unavailable: connection refused"

    if any(
        isinstance(e, OSError) and getattr(e, "errno", None) in (111, 10061)
        for e in exceptions
    ):
        return "MCP server unavailable: connection failed"

    if any(isinstance(e, ConnectionError) for e in exceptions):
        return "MCP server connection failed"

    if any(type(e).__name__ == "ValidationError" for e in exceptions):
        return "Tool argument validation failed"

    if any(type(e).__name__ == "CancelledError" for e in exceptions):
        return "Tool execution cancelled"

    # Never store arbitrary exception messages, which may contain secrets.
    return f"Tool execution failed ({type(exc).__name__})"

def read_health_status() -> dict:
    if not HEALTH_FILE.exists():
        return {}
    try:
        with HEALTH_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read health status: {type(exc).__name__}")
        return {}


def write_health_status(health_status: dict) -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = HEALTH_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(health_status, file, indent=2)
    os.replace(temp_file, HEALTH_FILE)


def update_server_health(
    health_status: dict,
    server: dict,
    status: str,
    error: str | None = None,
    discovered_tools_count: int | None = None,
) -> None:
    server_id = server["id"]
    previous = health_status.get(server_id, {})
    checked_at = utc_now()
    entry = {
        "server_id": server_id,
        "name": server["name"],
        "url": server["url"],
        "status": status,
        "last_checked": checked_at,
        "last_successful_check": previous.get("last_successful_check"),
        "last_error": error,
        "discovered_tools_count": previous.get("discovered_tools_count", 0),
    }
    if status == "healthy":
        entry["last_successful_check"] = checked_at
        if discovered_tools_count is not None:
            entry["discovered_tools_count"] = discovered_tools_count
    health_status[server_id] = entry


def python_type_from_json_schema(schema: dict) -> type:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), None)
    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return cast(type, type_map.get(cast(str, schema_type), Any))


async def fetch_tools(server: dict) -> list:
    async with streamablehttp_client(server["url"]) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            result = await client.list_tools()
            return result.tools


def make_handler(
    server_id: str,
    server_name: str,
    server_url: str,
    upstream_tool_name: str,
    description: str,
):
    async def handler(**kwargs):
        started = time.perf_counter()
        user = current_user_context.get()
        outcome = "error"
        details = None

        try:
            try:
                current_servers = read_registry()
            except Exception:
                details = "Registry read failed"
                return {"is_error": True, "error": "Could not read the server registry."}

            server = next(
                (item for item in current_servers if item.get("id") == server_id),
                None,
            )
            if not server or not server.get("enabled", False):
                outcome = "denied"
                details = "Server disabled or removed"
                return {
                    "is_error": True,
                    "error": f"MCP server '{server_name}' is disabled or removed.",
                }

            if server.get("url") != server_url:
                outcome = "denied"
                details = "Server URL changed; refresh discovery"
                return {
                    "is_error": True,
                    "error": "The server URL changed. Refresh tool discovery.",
                }

            gateway_tool_name = f"{server_name}__{upstream_tool_name}"
            if not user:
                outcome = "denied"
                details = "No authenticated gateway identity"
                return {"is_error": True, "error": "Authentication is required."}
            if user.get("role") != "admin" and not api_key_has_tool_permission(
                user.get("api_key_id"), gateway_tool_name
            ):
                outcome = "denied"
                details = "API key is not permitted to call this tool"
                return {
                    "is_error": True,
                    "error": f"Permission denied for tool '{gateway_tool_name}'.",
                }

            async with streamablehttp_client(server_url) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()
                    result = await client.call_tool(upstream_tool_name, arguments=kwargs)

            if result.isError:
                outcome = "error"
                details = "Upstream tool returned an error"
            else:
                outcome = "success"

            return {
                "upstream": server_name,
                "tool": upstream_tool_name,
                "is_error": result.isError,
                "content": [
                    getattr(item, "text", str(item)) for item in result.content
                ],
            }
        
        except Exception as exc:
            outcome = "error"
            details = summarize_exception(exc)
            return {
            "upstream": server_name,
            "tool": upstream_tool_name,
            "is_error": True,
            "error": "Upstream tool call failed.",
            }

        
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            try:
                record_audit_event(
                    user=user,
                    server_name=server_name,
                    tool_name=upstream_tool_name,
                    duration_ms=duration_ms,
                    outcome=outcome,
                    details=details,
                )
            except Exception as audit_exc:
                print(f"Audit logging failed: {type(audit_exc).__name__}")

    handler.__doc__ = description or f"Call {upstream_tool_name} on {server_name}"
    return handler


def register_tool(server: dict, tool) -> None:
    server_name = server["name"]
    upstream_name = tool.name
    gateway_name = f"{server_name}__{upstream_name}"
    input_schema = tool.inputSchema or {}
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    parameters = []

    for field_name, field_schema in properties.items():
        field_type = python_type_from_json_schema(field_schema)
        field_description = field_schema.get("description")
        if field_description:
            field_type = Annotated[field_type, Field(description=field_description)]
        default = (
            inspect.Parameter.empty
            if field_name in required
            else field_schema.get("default", None)
        )
        parameters.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=field_type,
            )
        )

    handler = make_handler(
        server["id"], server_name, server["url"], upstream_name,
        tool.description or "",
    )
    handler.__name__ = gateway_name
    handler.__signature__ = inspect.Signature(parameters)
    mcp.tool(name=gateway_name)(handler)
    registered_tools[gateway_name] = {
        "server_id": server["id"],
        "server_name": server_name,
        "url": server["url"],
        "upstream_tool": upstream_name,
    }
    print(f"Registered {gateway_name}")


def remove_tool(gateway_name: str) -> None:
    manager = mcp._tool_manager
    manager._tools.pop(gateway_name, None)
    registered_tools.pop(gateway_name, None)
    print(f"Removed {gateway_name}")


async def sync_tools() -> None:
    try:
        servers = read_registry()
    except Exception as exc:
        print(f"Registry read failed: {type(exc).__name__}")
        return

    enabled_servers = {
        server["id"]: server for server in servers
        if server.get("enabled", False) and server.get("id")
    }
    health_status = read_health_status()
    current_server_ids = {server["id"] for server in servers if server.get("id")}

    for server_id in list(health_status):
        if server_id not in current_server_ids:
            del health_status[server_id]

    for server in servers:
        if not server.get("enabled", False) and server.get("id"):
            update_server_health(health_status, server, status="disabled")

    desired_tools: dict[str, tuple[dict, Any]] = {}
    successfully_discovered_ids: set[str] = set()

    for server in servers:
        if not server.get("enabled", False):
            continue
        server_name = server.get("name", "unknown")
        server_id = server.get("id")
        if not server_id:
            print(f"Skipping registry entry without an ID: {server_name}")
            continue
        try:
            tools = await fetch_tools(server)
            successfully_discovered_ids.add(server_id)
            update_server_health(
                health_status, server, status="healthy",
                discovered_tools_count=len(tools),
            )
            for tool in tools:
                desired_tools[f"{server_name}__{tool.name}"] = (server, tool)
            print(f"Discovered {len(tools)} tools from {server_name}")
        except Exception as exc:
            update_server_health(
                health_status, server, status="unhealthy",
                error=type(exc).__name__,
            )
            print(
                f"Health check failed for {server_name}; "
                f"preserving existing tools ({type(exc).__name__})"
            )

    for name, existing in list(registered_tools.items()):
        server_id = existing["server_id"]
        current_server = enabled_servers.get(server_id)
        if current_server is None:
            remove_tool(name)
            continue
        if (
            existing["server_name"] != current_server["name"]
            or existing["url"] != current_server["url"]
        ):
            remove_tool(name)
            continue
        if server_id not in successfully_discovered_ids:
            continue
        if name not in desired_tools:
            remove_tool(name)
            continue
        desired_server, desired_tool = desired_tools[name]
        if (
            existing["server_id"] != desired_server["id"]
            or existing["url"] != desired_server["url"]
            or existing["upstream_tool"] != desired_tool.name
        ):
            remove_tool(name)

    for name, (server, tool) in desired_tools.items():
        if name not in registered_tools:
            try:
                register_tool(server, tool)
            except Exception as exc:
                print(f"Could not register {name}: {type(exc).__name__}")

    try:
        write_health_status(health_status)
    except Exception as exc:
        print(f"Could not save health status: {type(exc).__name__}")


async def refresh_loop() -> None:
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        try:
            await sync_tools()
        except Exception as exc:
            print(f"Gateway refresh failed: {type(exc).__name__}")


class MCPAPIKeyMiddleware:
    """Authenticate MCP requests and apply a per-API-key sliding-window limit.

    The in-memory limiter is suitable for a single Gateway process. Multiple
    worker processes/replicas need a shared limiter (for example Redis or an
    ingress-level rate limit) to enforce one global quota.
    """

    def __init__(
        self,
        app: ASGIApp,
        rate_limit: int = GATEWAY_RATE_LIMIT,
        window_seconds: int = GATEWAY_RATE_WINDOW_SECONDS,
    ):
        if rate_limit < 1 or window_seconds < 1:
            raise ValueError("Rate limit and window must be positive integers.")
        self.app = app
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._request_count = 0
        self._last_cleanup = time.monotonic()

    def _allow_request(self, api_key_id: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds) for this API key."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        timestamps = self._requests.setdefault(api_key_id, deque())

        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

        self._request_count += 1
        # Periodically remove inactive keys so old key IDs do not accumulate.
        if self._request_count % 256 == 0 or now - self._last_cleanup >= self.window_seconds:
            for key_id, key_timestamps in list(self._requests.items()):
                while key_timestamps and key_timestamps[0] <= cutoff:
                    key_timestamps.popleft()
                if not key_timestamps:
                    self._requests.pop(key_id, None)
            self._last_cleanup = now
            timestamps = self._requests.setdefault(api_key_id, deque())

        if len(timestamps) >= self.rate_limit:
            retry_after = max(1, ceil(self.window_seconds - (now - timestamps[0])))
            return False, retry_after

        timestamps.append(now)
        return True, 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "").rstrip("/")
        if path != "/mcp":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_key = headers.get(b"x-api-key", b"")
        try:
            user = authenticate_api_key(raw_key.decode("utf-8"))
        except Exception:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"ApiKey"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"detail":"A valid API key is required."}',
            })
            return

        # Authenticated API keys always have an api_key_id. Use a hash of the
        # presented key only as a safe fallback; never retain the raw key.
        api_key_id = user.get("api_key_id")
        if not api_key_id:
            import hashlib
            api_key_id = hashlib.sha256(raw_key).hexdigest()
        allowed, retry_after = self._allow_request(str(api_key_id))
        if not allowed:
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after).encode("ascii")),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"detail":"Rate limit exceeded. Try again later."}',
            })
            return

        token = current_user_context.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_context.reset(token)


def main() -> None:
    init_db()
    http_app = mcp.streamable_http_app()
    secured_app = MCPAPIKeyMiddleware(http_app)

    async def run_server() -> None:
        await sync_tools()
        refresh_task = asyncio.create_task(refresh_loop())
        server = uvicorn.Server(
            uvicorn.Config(
                secured_app,
                host=GATEWAY_HOST,
                port=GATEWAY_PORT,
                log_level="info",
            )
        )
        try:
            await server.serve()
        finally:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass

    asyncio.run(run_server())


if __name__ == "__main__":
    main()

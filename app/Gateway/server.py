
import asyncio
import inspect
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Annotated, cast

from dotenv import load_dotenv
from pydantic import Field

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

REGISTRY_FILE = BASE_DIR / "data" / "servers.json"

GATEWAY_HOST = os.getenv("GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8100"))
REFRESH_INTERVAL = 5

mcp = FastMCP(
    "woo-mcp-gateway",
    host=GATEWAY_HOST,
    port=GATEWAY_PORT,
)

# Maps gateway tool names to their upstream server details.
registered_tools: dict[str, dict[str, str]] = {}


def read_registry() -> list[dict]:
    """Read and validate the MCP server registry."""
    if not REGISTRY_FILE.exists():
        return []

    with REGISTRY_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Server registry must be a JSON list.")

    return data


def python_type_from_json_schema(schema: dict) -> type:
    """Convert a JSON Schema type to a Python type."""
    schema_type = schema.get("type")

    if isinstance(schema_type, list):
        schema_type = next(
            (item for item in schema_type if item != "null"),
            None,
        )

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
    """Discover tools exposed by an upstream MCP server."""
    async with streamablehttp_client(server["url"]) as (
        read_stream,
        write_stream,
        _,
    ):
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
    """Create a gateway tool handler that forwards calls upstream."""

    async def handler(**kwargs):
        # Check the current registry before every tool call.
        try:
            current_servers = read_registry()
        except Exception as exc:
            return {
                "is_error": True,
                "error": f"Could not read server registry: {exc}",
            }

        server = next(
            (
                item
                for item in current_servers
                if item.get("id") == server_id
            ),
            None,
        )

        if not server or not server.get("enabled", False):
            return {
                "is_error": True,
                "error": (
                    f"MCP server '{server_name}' "
                    "is disabled or removed."
                ),
            }

        if server.get("url") != server_url:
            return {
                "is_error": True,
                "error": (
                    "The server URL changed. "
                    "Refresh tool discovery."
                ),
            }

        try:
            async with streamablehttp_client(server_url) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(
                    read_stream,
                    write_stream,
                ) as client:
                    await client.initialize()
                    result = await client.call_tool(
                        upstream_tool_name,
                        arguments=kwargs,
                    )

            return {
                "upstream": server_name,
                "tool": upstream_tool_name,
                "is_error": result.isError,
                "content": [
                    getattr(item, "text", str(item))
                    for item in result.content
                ],
            }

        except Exception as exc:
            return {
                "upstream": server_name,
                "tool": upstream_tool_name,
                "is_error": True,
                "error": str(exc),
            }

    handler.__doc__ = description or (
        f"Call {upstream_tool_name} on {server_name}"
    )
    return handler


def register_tool(server: dict, tool) -> None:
    """Register one upstream tool with the gateway."""
    server_name = server["name"]
    upstream_name = tool.name
    gateway_name = f"{server_name}__{upstream_name}"

    input_schema = tool.inputSchema or {}
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))

    parameters = []

    for field_name, field_schema in properties.items():
        field_type = python_type_from_json_schema(field_schema)
        description = field_schema.get("description")

        if description:
            field_type = Annotated[
                field_type,
                Field(description=description),
            ]

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
        server["id"],
        server_name,
        server["url"],
        upstream_name,
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
    """Remove a tool managed by the registry synchronizer."""
    manager = mcp._tool_manager
    manager._tools.pop(gateway_name, None)
    registered_tools.pop(gateway_name, None)
    print(f"Removed {gateway_name}")


async def sync_tools() -> None:
    """
    Synchronize tools from all enabled MCP servers.

    Important:
    - Temporary discovery failures preserve existing tools.
    - Disabled or deleted servers have their tools removed.
    - Successful discovery removes tools absent from the new tool list.
    """
    try:
        servers = read_registry()
    except Exception as exc:
        print(f"Registry read failed: {exc}")
        return

    enabled_servers = {
        server["id"]: server
        for server in servers
        if server.get("enabled", False)
    }

    desired_tools: dict[str, tuple[dict, Any]] = {}
    successfully_discovered_ids: set[str] = set()

    # Discover each server independently.
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

            # A successful response is authoritative, even if it contains
            # zero tools.
            successfully_discovered_ids.add(server_id)

            for tool in tools:
                gateway_name = f"{server_name}__{tool.name}"
                desired_tools[gateway_name] = (server, tool)

            print(
                f"Discovered {len(tools)} tools from {server_name}"
            )

        except Exception as exc:
            # Do not treat a connection failure as tool deletion.
            print(
                f"Could not discover tools from {server_name}; "
                f"preserving existing tools: {exc}"
            )

    # Remove tools only when justified by registry state or successful
    # discovery. A failed upstream discovery preserves existing tools.
    for name, existing in list(registered_tools.items()):
        server_id = existing["server_id"]
        current_server = enabled_servers.get(server_id)

        # Server disabled or removed from the registry.
        if current_server is None:
            remove_tool(name)
            continue

        # The server's name or URL changed.
        if (
            existing["server_name"] != current_server["name"]
            or existing["url"] != current_server["url"]
        ):
            remove_tool(name)
            continue

        # This server failed discovery. Keep its previously registered tools.
        if server_id not in successfully_discovered_ids:
            continue

        # Discovery succeeded: a missing tool can now be removed.
        if name not in desired_tools:
            remove_tool(name)
            continue

        desired_server, desired_tool = desired_tools[name]

        # Check whether the upstream tool identity changed.
        if (
            existing["server_id"] != desired_server["id"]
            or existing["url"] != desired_server["url"]
            or existing["upstream_tool"] != desired_tool.name
        ):
            remove_tool(name)

    # Register tools discovered for the first time or tools that were removed.
    for name, (server, tool) in desired_tools.items():
        if name not in registered_tools:
            try:
                register_tool(server, tool)
            except Exception as exc:
                print(f"Could not register {name}: {exc}")


async def refresh_loop():
    """Refresh tool discovery periodically."""
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        await sync_tools()


@asynccontextmanager
async def gateway_lifespan():
    """Initialize tool discovery and start the refresh loop."""
    await sync_tools()
    refresh_task = asyncio.create_task(refresh_loop())

    try:
        yield {}
    finally:
        refresh_task.cancel()

        try:
            await refresh_task
        except asyncio.CancelledError:
            pass


async def main():
    async with gateway_lifespan():
        await mcp.run_streamable_http_async()


if __name__ == "__main__":
    asyncio.run(main())

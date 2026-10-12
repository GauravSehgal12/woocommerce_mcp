
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

WOOCOMMERCE_MCP_URL = os.getenv(
    "WOOCOMMERCE_MCP_URL",
    "http://127.0.0.1:8001/mcp",
)

GATEWAY_HOST = os.getenv("GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8100"))

mcp = FastMCP(
    "woo-mcp-gateway",
    host=GATEWAY_HOST,
    port=GATEWAY_PORT,
)

# Keep upstream sessions alive for the lifetime of the gateway.
upstream_context = None
upstream_read = None
upstream_write = None
upstream_session = None
upstream_tools: list[Any] = []


@asynccontextmanager
async def lifespan():
    """Connect to WooCommerce and discover its tools."""
    global upstream_context
    global upstream_read, upstream_write, upstream_session
    global upstream_tools

    try:
        async with streamablehttp_client(
            WOOCOMMERCE_MCP_URL
        ) as (read_stream, write_stream, _):
            async with ClientSession(
                read_stream, write_stream
            ) as client:
                await client.initialize()

                response = await client.list_tools()
                upstream_tools = response.tools

                print(
                    f"Connected to WooCommerce MCP: "
                    f"{len(upstream_tools)} tools discovered"
                )

                for tool in upstream_tools:
                    print(f"- woocommerce__{tool.name}")

                # Register one gateway tool per upstream tool.
                for tool in upstream_tools:
                    register_upstream_tool(tool.name)

                yield

    except Exception as exc:
        print(f"Upstream connection error: {exc}")
        raise


def register_upstream_tool(tool_name: str) -> None:
    """Register a namespaced gateway tool."""

    async def gateway_tool(**arguments: Any) -> dict[str, Any]:
        """Forward a tool call to WooCommerce."""
        async with streamablehttp_client(
            WOOCOMMERCE_MCP_URL
        ) as (read_stream, write_stream, _):
            async with ClientSession(
                read_stream, write_stream
            ) as client:
                await client.initialize()

                result = await client.call_tool(
                    tool_name,
                    arguments=arguments,
                )

                return {
                    "upstream": "woocommerce",
                    "tool": tool_name,
                    "is_error": result.isError,
                    "content": [
                        {
                            "type": item.type,
                            "text": getattr(item, "text", None),
                        }
                        for item in result.content
                    ],
                }

    gateway_tool.__name__ = f"woocommerce__{tool_name}"
    gateway_tool.__doc__ = (
        f"Forward a call to the WooCommerce {tool_name} tool."
    )

    mcp.tool(name=f"woocommerce__{tool_name}")(gateway_tool)


# Connect and discover tools before serving requests.
if __name__ == "__main__":
    async def main():
        async with lifespan():
            await mcp.run_streamable_http_async()

    asyncio.run(main())

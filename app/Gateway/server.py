
import asyncio
import inspect
import os
from contextlib import asynccontextmanager
from typing import Any, Annotated, cast

from dotenv import load_dotenv
from pydantic import Field

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


def python_type_from_json_schema(schema: dict) -> type[Any]:
    schema_type = schema.get("type")

    if isinstance(schema_type, list):
        schema_type = next(
            (item for item in schema_type if item != "null"),
            None,
        )

    type_map: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    if isinstance(schema_type, str):
        return cast(type, type_map.get(schema_type, Any))

    return cast(type[Any], Any)


async def discover_and_register_tools():
    async with streamablehttp_client(WOOCOMMERCE_MCP_URL) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            response = await client.list_tools()

            print(
                f"Connected to WooCommerce MCP: "
                f"{len(response.tools)} tools discovered"
            )

            for tool in response.tools:
                input_schema = tool.inputSchema or {}
                properties = input_schema.get("properties", {})
                required = set(input_schema.get("required", []))

                parameters = []

                for field_name, field_schema in properties.items():
                    field_type = python_type_from_json_schema(
                        field_schema
                    )

                    description = field_schema.get("description")

                    if description:
                        field_type = Annotated[
                            field_type,
                            Field(description=description),
                        ]

                    if field_name in required:
                        default = inspect.Parameter.empty
                    else:
                        default = field_schema.get("default", None)

                    parameters.append(
                        inspect.Parameter(
                            field_name,
                            inspect.Parameter.KEYWORD_ONLY,
                            default=default,
                            annotation=field_type,
                        )
                    )

                signature = inspect.Signature(parameters)

                def make_handler(upstream_name, tool_description):
                    async def handler(**kwargs):
                        try:
                            async with streamablehttp_client(
                                WOOCOMMERCE_MCP_URL
                            ) as (read, write, _):
                                async with ClientSession(
                                    read, write
                                ) as upstream:
                                    await upstream.initialize()

                                    result = await upstream.call_tool(
                                        upstream_name,
                                        arguments=kwargs,
                                    )

                            content = [
                                getattr(item, "text", str(item))
                                for item in result.content
                            ]

                            return {
                                "upstream": "woocommerce",
                                "tool": upstream_name,
                                "is_error": result.isError,
                                "content": content,
                            }

                        except Exception as exc:
                            return {
                                "upstream": "woocommerce",
                                "tool": upstream_name,
                                "is_error": True,
                                "error": str(exc),
                            }

                    handler.__doc__ = tool_description or (
                        f"Call the WooCommerce tool {upstream_name}"
                    )
                    return handler

                handler = make_handler(
                    tool.name,
                    tool.description,
                )

                handler.__name__ = f"woocommerce__{tool.name}"
                handler.__signature__ = signature

                mcp.tool(name=f"woocommerce__{tool.name}")(handler)

                print(
                    f"Registered woocommerce__{tool.name}: "
                    f"{list(properties.keys())}"
                )


@asynccontextmanager
async def gateway_lifespan():
    await discover_and_register_tools()
    yield {}


async def main():
    async with gateway_lifespan():
        await mcp.run_streamable_http_async()


if __name__ == "__main__":
    asyncio.run(main())

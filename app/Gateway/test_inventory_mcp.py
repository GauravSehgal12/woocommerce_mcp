
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


GATEWAY_URL = "http://127.0.0.1:8100/mcp"


async def main():
    async with streamablehttp_client(GATEWAY_URL) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as client:
            await client.initialize()

            response = await client.list_tools()
            tool_names = {tool.name for tool in response.tools}

            print("Tools discovered:", len(tool_names))

            expected = {
                "woocommerce__list_products",
                "inventory__get_inventory",
                "inventory__check_stock",
            }

            missing = expected - tool_names

            if missing:
                raise RuntimeError(f"Missing tools: {missing}")

            inventory_result = await client.call_tool(
                "inventory__get_inventory",
                arguments={"sku": "MOUSE-001"},
            )

            print("\nInventory result:")
            for item in inventory_result.content:
                text = getattr(item, "text", None)
                if text is not None:
                    print(text)

            if inventory_result.isError:
                raise RuntimeError("Inventory tool call failed.")

            stock_result = await client.call_tool(
                "inventory__check_stock",
                arguments={
                    "sku": "KEYBOARD-001",
                    "quantity": 5,
                },
            )

            print("\nStock check result:")
            for item in stock_result.content:
                text = getattr(item, "text", None)
                if text is not None:
                    print(text)

            if stock_result.isError:
                raise RuntimeError("Stock check failed.")

            print("\nSUCCESS: Both MCP servers are accessible.")


if __name__ == "__main__":
    asyncio.run(main())

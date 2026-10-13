import asyncio
import json
import os
import sqlite3
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

API_KEY = os.environ.get("GATEWAY_TEST_API_KEY")
GATEWAY_URL = "http://127.0.0.1:8100/mcp"
DB_FILE = Path("app/Gateway/data/security.db")

PRODUCT_ID = 25
PRODUCT_NAME = "MCP Draft Audit Test 0D448EA2"
PRODUCT_SKU = "MCP-AUDIT-0D448EA2"


def extract_products(result):
    """Parse the gateway response into product dictionaries."""
    assert not result.isError, f"MCP request failed: {result}"
    assert result.content, "MCP returned no content."

    outer = json.loads(result.content[0].text)
    assert not outer.get("is_error", False), outer

    products = []
    for item in outer.get("content", []):
        if isinstance(item, str):
            parsed = json.loads(item)
            if isinstance(parsed, dict):
                products.append(parsed)
        elif isinstance(item, dict):
            products.append(item)

    return products


@pytest.mark.skipif(
    not API_KEY,
    reason="Set GATEWAY_TEST_API_KEY to run the live test.",
)
def test_existing_draft_product_is_retrievable_and_audited():
    assert DB_FILE.exists(), f"Security database not found: {DB_FILE}"

    async def verify_product():
        api_key = API_KEY
        assert api_key is not None
        async with streamablehttp_client(
            GATEWAY_URL,
            headers={"X-API-Key": api_key},
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}

                assert "woocommerce__list_products" in tool_names

                result = await session.call_tool(
                    "woocommerce__list_products",
                    arguments={
                        "per_page": 100,
                        "page": 1,
                        "search": PRODUCT_NAME,
                    },
                )

                products = extract_products(result)

                matching = [
                    product
                    for product in products
                    if product.get("id") == PRODUCT_ID
                    and product.get("sku") == PRODUCT_SKU
                ]

                assert matching, (
                    f"Product ID {PRODUCT_ID} with SKU {PRODUCT_SKU} "
                    f"was not found. Results: {products}"
                )

                product = matching[0]
                assert product["name"] == PRODUCT_NAME
                assert product["status"] == "draft"
                assert product["regular_price"] == "1.00"

                return product

    product = asyncio.run(verify_product())

    # Confirm that a successful product-creation audit record exists.
    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row
        audit = db.execute(
            """
            SELECT id, username, server_name, tool_name,
                   outcome, details, duration_ms
            FROM audit_logs
            WHERE server_name = 'woocommerce'
              AND tool_name = 'create_product'
              AND outcome = 'success'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    assert audit is not None, (
        "No successful WooCommerce product-creation audit record found."
    )

    print("\nExisting product verification passed.")
    print("Product:", json.dumps(product, indent=2))
    print("Creation audit record:", dict(audit))

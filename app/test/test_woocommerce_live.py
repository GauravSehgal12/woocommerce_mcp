import asyncio
import os
import sqlite3
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

API_KEY = os.environ.get("GATEWAY_TEST_API_KEY")
GATEWAY_URL = "http://127.0.0.1:8100/mcp"
DB_FILE = Path("app/Gateway/data/security.db")


@pytest.mark.skipif(
    not API_KEY,
    reason="Set GATEWAY_TEST_API_KEY to run the live test.",
)
def test_woocommerce_list_products_is_audited():
    api_key = API_KEY
    assert api_key is not None

    assert DB_FILE.exists(), f"Security database not found: {DB_FILE}"

    with sqlite3.connect(DB_FILE) as db:
        previous_id = db.execute(
            "SELECT COALESCE(MAX(id), 0) FROM audit_logs"
        ).fetchone()[0]

    async def run_call():
        async with streamablehttp_client(
            GATEWAY_URL,
            headers={"X-API-Key": api_key},
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}

                assert "woocommerce__list_products" in names, (
                    "Gateway does not expose woocommerce__list_products."
                )

                return await session.call_tool(
                    "woocommerce__list_products",
                    arguments={"per_page": 5, "page": 1, "search": ""},
                )

    result = asyncio.run(run_call())

    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            """
            SELECT id, username, server_name, tool_name,
                   outcome, details, duration_ms
            FROM audit_logs
            WHERE id > ?
              AND server_name = 'woocommerce'
              AND tool_name = 'list_products'
            ORDER BY id DESC
            LIMIT 1
            """,
            (previous_id,),
        ).fetchone()

    assert row is not None, (
        "No audit record found for the WooCommerce product-list call."
    )

    print("\nWooCommerce audit record:", dict(row))
    print("\nWooCommerce tool response:", result)

    assert row["outcome"] == "success", (
        f"WooCommerce call was audited as '{row['outcome']}': "
        f"{row['details']}"
    )
    assert not result.isError, "WooCommerce returned a tool execution error."
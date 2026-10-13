"""Optional live smoke test for the running MCP gateway.

This test calls the real gateway and Inventory MCP server. It is skipped unless
GATEWAY_TEST_API_KEY is set in the environment. The API key is never printed.
"""
import asyncio
import os
import sqlite3
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


GATEWAY_URL = os.getenv("GATEWAY_TEST_URL", "http://127.0.0.1:8100/mcp")
API_KEY = os.getenv("GATEWAY_TEST_API_KEY")
DB_FILE = Path(__file__).resolve().parents[1] / "Gateway" / "data" / "security.db"


@pytest.mark.skipif(
    not API_KEY,
    reason="Set GATEWAY_TEST_API_KEY to run the live gateway smoke test.",
)
def test_live_inventory_tool_call_is_audited():
    """Call inventory__get_inventory through the live gateway and check its audit row."""
    assert API_KEY is not None
    api_key = API_KEY
    assert DB_FILE.exists(), (
        f"Security database not found at {DB_FILE}. "
        "Run the gateway/security setup before this live test."
    )

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
                tools_result = await session.list_tools()
                tool_names = {tool.name for tool in tools_result.tools}
                assert "inventory__get_inventory" in tool_names, (
                    "Gateway did not expose inventory__get_inventory. "
                    "Check Inventory service health and gateway discovery."
                )
                return await session.call_tool(
    "inventory__get_inventory",
    arguments={"sku": "MOUSE-001"},
)
                # return await session.call_tool("inventory__get_inventory", arguments={})

    result = asyncio.run(run_call())

    # The gateway wraps upstream errors in its tool response, so an MCP response
    # alone is not proof of success. Verify that the handler wrote a new audit row.
    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            """
            SELECT id, username, server_name, tool_name, outcome, details, duration_ms
            FROM audit_logs
            WHERE id > ? AND server_name = 'inventory'
              AND tool_name = 'get_inventory'
            ORDER BY id DESC
            LIMIT 1
            """,
            (previous_id,),
        ).fetchone()

    assert row is not None, (
        "The live tool call returned but no corresponding audit record was written."
    )
    assert row["outcome"] in {"success", "error", "denied"}
    assert row["duration_ms"] is None or row["duration_ms"] >= 0
    # Retain the result reference so the tool call is not accidentally optimized away.
    assert result is not None

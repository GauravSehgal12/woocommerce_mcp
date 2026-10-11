
import json
import requests

MCP_URL = "http://127.0.0.1:8000/mcp"
PROTOCOL_VERSION = "2025-03-26"

session = requests.Session()
session_id = None
request_id = 0


def post_mcp(payload):
    """Send an MCP JSON-RPC request."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }

    if session_id:
        headers["Mcp-Session-Id"] = session_id

    response = session.post(
        MCP_URL,
        json=payload,
        headers=headers,
        timeout=30,
    )

    print(f"{payload['method']}: HTTP {response.status_code}")

    if not response.ok:
        print("Response:", response.text)
        response.raise_for_status()

    return response


def parse_response(response):
    """Parse JSON or Server-Sent Events responses."""
    content_type = response.headers.get("Content-Type", "")

    if "application/json" in content_type:
        return response.json()

    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])

    raise RuntimeError(
        f"Could not parse MCP response:\n{response.text}"
    )


def call_tool(name, arguments):
    """Call an MCP tool and return its JSON-RPC response."""
    global request_id

    request_id += 1

    response = post_mcp({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
        },
    })

    result = parse_response(response)

    print(f"\n{name} result:")
    print(json.dumps(result, indent=2))

    if "error" in result:
        print(f"\nMCP request failed: {result['error']}")
        return result

    tool_result = result.get("result", {})

    if tool_result.get("isError"):
        print(f"\nTool execution failed: {name}")

    return result


def main():
    global session_id, request_id

    try:
        # 1. Initialize the MCP session
        request_id += 1

        response = post_mcp({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "woocommerce-mcp-test",
                    "version": "1.0.0",
                },
            },
        })

        session_id = response.headers.get("Mcp-Session-Id")

        if not session_id:
            raise RuntimeError(
                "MCP session ID was not returned by the server."
            )

        initialize_result = parse_response(response)

        if "error" in initialize_result:
            raise RuntimeError(str(initialize_result["error"]))

        print("MCP session created.")
        print(
            "Server:",
            initialize_result.get("result", {}).get(
                "serverInfo", {}
            ),
        )

        # 2. Complete initialization
        post_mcp({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # 3. List registered tools
        request_id += 1

        response = post_mcp({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/list",
            "params": {},
        })

        tools_result = parse_response(response)

        if "error" in tools_result:
            raise RuntimeError(str(tools_result["error"]))

        tools = tools_result.get("result", {}).get("tools", [])

        print(f"\nRegistered MCP tools: {len(tools)}")

        for tool in tools:
            print(
                f"- {tool['name']}: "
                f"{tool.get('description', '')}"
            )

        expected_tools = {
            "list_products",
            "create_product",
            "update_product",
            "list_orders",
            "get_order",
            "update_order",
        }

        actual_tools = {tool["name"] for tool in tools}

        missing_tools = expected_tools - actual_tools

        if missing_tools:
            print(f"\nMissing tools: {sorted(missing_tools)}")
        else:
            print("\nAll six expected tools are registered.")

        # 4. Test listing products
        list_result = call_tool(
            "list_products",
            {
                "per_page": 5,
                "page": 1,
                "search": "",
            },
        )

        list_tool_result = list_result.get("result", {})

        if (
            "error" not in list_result
            and not list_tool_result.get("isError")
        ):
            print("\nSUCCESS: list_products executed.")

        # 5. Create a draft product
        # Run this script only once unless you change the SKU.
        create_result = call_tool(
            "create_product",
            {
                "name": "MCP Test Product",
                "regular_price": "199",
                "description": (
                    "Draft product created to test MCP integration."
                ),
                "status": "draft",
                "sku": "MCP-TEST-001",
            },
        )

        create_tool_result = create_result.get("result", {})

        if (
            "error" not in create_result
            and not create_tool_result.get("isError")
        ):
            print("\nDraft product creation succeeded.")
        else:
            print("\nDraft product creation failed.")

    except requests.RequestException as exc:
        print(f"\nHTTP/network error: {exc}")

    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"\nTest error: {exc}")

    finally:
        session.close()


if __name__ == "__main__":
    main()

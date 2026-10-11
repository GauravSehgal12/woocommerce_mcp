
import json
import requests

MCP_URL = "http://127.0.0.1:8001/mcp"
PROTOCOL_VERSION = "2025-03-26"

session = requests.Session()
session_id = None
request_id = 0


def post_mcp(payload):
    """Send a JSON-RPC request to the Kubernetes MCP server."""
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
        f"Unable to parse MCP response:\n{response.text}"
    )


def call_tool(name, arguments):
    """Call a registered MCP tool."""
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
        return False

    tool_result = result.get("result", {})

    if tool_result.get("isError"):
        print(f"\nTool execution failed: {name}")
        return False

    return True


def main():
    global session_id, request_id

    try:
        # 1. Initialize the MCP session.
        request_id += 1

        response = post_mcp({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "woocommerce-kubernetes-test",
                    "version": "1.0.0",
                },
            },
        })

        session_id = response.headers.get("Mcp-Session-Id")

        if not session_id:
            raise RuntimeError(
                "Server did not return an MCP session ID."
            )

        initialization = parse_response(response)

        if "error" in initialization:
            raise RuntimeError(str(initialization["error"]))

        print("\nMCP session created.")
        print(
            "Server:",
            initialization.get("result", {}).get("serverInfo", {}),
        )

        # 2. Complete initialization.
        post_mcp({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # 3. Discover tools.
        request_id += 1

        response = post_mcp({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/list",
            "params": {},
        })

        tools_response = parse_response(response)

        if "error" in tools_response:
            raise RuntimeError(str(tools_response["error"]))

        tools = tools_response.get("result", {}).get("tools", [])

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

        if not expected_tools.issubset(actual_tools):
            missing = expected_tools - actual_tools
            raise RuntimeError(f"Missing MCP tools: {sorted(missing)}")

        print("\nAll six expected tools are registered.")

        # 4. Read products from WooCommerce.
        list_ok = call_tool(
            "list_products",
            {
                "per_page": 5,
                "page": 1,
                "search": "",
            },
        )

        if list_ok:
            print("\nSUCCESS: Kubernetes list_products test passed.")

        # 5. Create a draft product.
        # This operation writes to WooCommerce.
        # Run the script only once to avoid duplicate SKU errors.
        create_ok = call_tool(
            "create_product",
            {
                "name": "Kubernetes MCP Test Product",
                "regular_price": "199",
                "description": (
                    "Draft product created to test the "
                    "Kubernetes-hosted MCP server."
                ),
                "status": "draft",
                "sku": "K8S-MCP-TEST-001",
            },
        )

        if create_ok:
            print("\nSUCCESS: Draft product creation test passed.")

    except requests.RequestException as exc:
        print(f"\nHTTP/network error: {exc}")

    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"\nTest error: {exc}")

    finally:
        session.close()


if __name__ == "__main__":
    main()

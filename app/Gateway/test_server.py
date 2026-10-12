
import json
import requests

MCP_URL = "http://127.0.0.1:8100/mcp"
PROTOCOL_VERSION = "2025-11-25"

session = requests.Session()
session_id = None


def post_mcp(payload):
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
        print(response.text)
        response.raise_for_status()

    return response


def parse_response(response):
    if "application/json" in response.headers.get("Content-Type", ""):
        return response.json()

    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])

    raise RuntimeError(f"Unable to parse response: {response.text}")


try:
    
    response = post_mcp({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "gateway-test-client",
                "version": "1.0.0",
            },
        },
    })

    session_id = response.headers.get("Mcp-Session-Id")
    initialized = parse_response(response)

    if "error" in initialized:
        raise RuntimeError(initialized["error"])

    print("Gateway server:", initialized["result"]["serverInfo"])

    if not session_id:
        raise RuntimeError("Gateway did not return a session ID.")

    
    post_mcp({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })

    
    response = post_mcp({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    })

    result = parse_response(response)

    if "error" in result:
        raise RuntimeError(result["error"])

    tools = result["result"]["tools"]

    print(f"\nGateway tools discovered: {len(tools)}")
    for tool in tools:
        print("-", tool["name"])

    
    response = post_mcp({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "woocommerce__list_products",
            "arguments": {
                "per_page": 5,
                "page": 1,
                "search": "",
            },
        },
    })

    result = parse_response(response)

    print("\nGateway tool call result:")
    print(json.dumps(result, indent=2))

    if "error" in result:
        raise RuntimeError(result["error"])

    tool_result = result.get("result", {})

    if tool_result.get("isError"):
        raise RuntimeError("Gateway tool execution failed.")

    print("\nSUCCESS: Gateway forwarded the tool call.")

finally:
    session.close()

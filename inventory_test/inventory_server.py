
import asyncio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "inventory-test",
    host="0.0.0.0",
    port=8200,
)

INVENTORY = {
    "MOUSE-001": {
        "sku": "MOUSE-001",
        "name": "Wireless Mouse",
        "available": 25,
        "warehouse": "Delhi",
    },
    "KEYBOARD-001": {
        "sku": "KEYBOARD-001",
        "name": "Mechanical Keyboard",
        "available": 12,
        "warehouse": "Gurgaon",
    },
    "HEADSET-001": {
        "sku": "HEADSET-001",
        "name": "USB Headset",
        "available": 0,
        "warehouse": "Bangalore",
    },
}


@mcp.tool()
def get_inventory(sku: str) -> dict:
    """Get inventory details for a product SKU."""
    item = INVENTORY.get(sku.upper())

    if item is None:
        return {
            "found": False,
            "sku": sku,
            "message": "Product SKU not found.",
        }

    return {"found": True, **item}


@mcp.tool()
def check_stock(sku: str, quantity: int) -> dict:
    """Check whether the requested quantity is available."""
    if quantity < 1:
        return {"valid": False, "message": "Quantity must be at least 1."}

    item = INVENTORY.get(sku.upper())

    if item is None:
        return {"found": False, "sku": sku}

    return {
        "found": True,
        "sku": sku.upper(),
        "requested_quantity": quantity,
        "available_quantity": item["available"],
        "in_stock": item["available"] >= quantity,
    }


async def main():
    await mcp.run_streamable_http_async()


if __name__ == "__main__":
    asyncio.run(main())

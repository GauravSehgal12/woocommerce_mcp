import asyncio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "shipping-test",
    host="0.0.0.0",
    port=8300,
)

@mcp.tool()
def calculate_shipping(destination: str, weight_kg: float) -> dict:
    """Estimate shipping cost and delivery time."""
    if weight_kg <= 0:
        return {"error": "Weight must be greater than zero."}

    base_cost = 80
    cost = base_cost + weight_kg * 25

    return {
        "destination": destination,
        "weight_kg": weight_kg,
        "estimated_cost_inr": round(cost, 2),
        "estimated_delivery_days": 3,
        "note": "Demo estimate, not a live carrier quote.",
    }

@mcp.tool()
def track_shipment(tracking_id: str) -> dict:
    """Look up a sample shipment tracking status."""
    shipments = {
        "SHIP-1001": {
            "status": "In transit",
            "location": "Gurgaon",
            "estimated_delivery": "2026-10-20",
        },
        "SHIP-1002": {
            "status": "Delivered",
            "location": "Bangalore",
            "estimated_delivery": "2026-10-17",
        },
    }

    result = shipments.get(tracking_id.upper())
    if result is None:
        return {
            "found": False,
            "tracking_id": tracking_id,
            "message": "Tracking ID not found in demo data.",
        }

    return {"found": True, "tracking_id": tracking_id.upper(), **result}

async def main():
    await mcp.run_streamable_http_async()

if __name__ == "__main__":
    asyncio.run(main())
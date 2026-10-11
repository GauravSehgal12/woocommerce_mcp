
import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("WooCommerce MCP Server")

WOOCOMMERCE_URL = os.getenv(
    "WOOCOMMERCE_URL",
    "http://localhost:8080"
).rstrip("/")

CONSUMER_KEY = os.getenv("WOOCOMMERCE_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("WOOCOMMERCE_CONSUMER_SECRET")


def get_auth():
    if not CONSUMER_KEY or not CONSUMER_SECRET:
        raise RuntimeError(
            "WooCommerce API credentials are not configured."
        )
    return CONSUMER_KEY, CONSUMER_SECRET


@mcp.tool()
async def list_products(per_page: int = 10) -> list[dict]:
    """List products from the WooCommerce store."""
    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{WOOCOMMERCE_URL}/wp-json/wc/v3/products",
            auth=get_auth(),
            params={"per_page": per_page},
        )
        response.raise_for_status()
        products = response.json()

    return [
        {
            "id": product["id"],
            "name": product["name"],
            "price": product["price"],
            "status": product["status"],
        }
        for product in products
    ]


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

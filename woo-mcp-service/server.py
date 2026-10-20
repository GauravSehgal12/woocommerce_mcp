
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from requests_oauthlib import OAuth1
from mcp.server.fastmcp import FastMCP  
load_dotenv()

STORE_URL = os.getenv("WOOCOMMERCE_URL", "").rstrip("/")
CONSUMER_KEY = os.getenv("WOOCOMMERCE_CONSUMER_KEY", "")
CONSUMER_SECRET = os.getenv("WOOCOMMERCE_CONSUMER_SECRET", "")

mcp = FastMCP(
    "woocommerce-mcp",
    host="0.0.0.0",
    port=int(os.getenv("PORT", "8000")),
)


def validate_configuration() -> None:
    if not STORE_URL or not CONSUMER_KEY or not CONSUMER_SECRET:
        raise RuntimeError(
            "Missing WooCommerce configuration. Check the service .env file."
        )


def api_request(
    method: str,
    resource: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Send an OAuth-signed request to the WooCommerce REST API."""
    validate_configuration()

    auth = OAuth1(
        CONSUMER_KEY,
        CONSUMER_SECRET,
        signature_method="HMAC-SHA256",
        signature_type="AUTH_HEADER",
    )

    url = f"{STORE_URL}/wp-json/wc/v3/{resource.lstrip('/')}"

    try:
        response = requests.request(
            method,
            url,
            params=params,
            json=payload,
            auth=auth,
            timeout=20,
        )
    except requests.RequestException as exc:
        # Avoid including URLs or request details that could expose credentials.
        raise RuntimeError(
            f"Could not connect to WooCommerce ({type(exc).__name__})."
        ) from None

    if not response.ok:
        try:
            body = response.json()
            code = body.get("code", "woocommerce_api_error")
            message = body.get("message", "Request failed")
        except ValueError:
            code = "woocommerce_api_error"
            message = "WooCommerce returned a non-JSON error response"

        raise RuntimeError(
            f"WooCommerce API error: HTTP {response.status_code}; "
            f"{code}: {message}"
        )

    if response.status_code == 204 or not response.content:
        return {"success": True}

    return response.json()


def validate_price(price: str) -> str:
    try:
        amount = Decimal(price)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Price must be a valid non-negative number.") from None

    if not amount.is_finite() or amount < 0:
        raise ValueError("Price must be a valid non-negative number.")

    return format(amount, "f")


@mcp.tool()
def list_products(
    per_page: int = 10,
    page: int = 1,
    search: str = "",
) -> list[dict[str, Any]]:
    """List WooCommerce products, optionally searching by name."""
    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100.")
    if page < 1:
        raise ValueError("page must be at least 1.")

    params: dict[str, Any] = {"per_page": per_page, "page": page}
    if search.strip():
        params["search"] = search.strip()

    products = api_request("GET", "products", params=params)

    return [
        {
            "id": p["id"],
            "name": p["name"],
            "price": p["price"],
            "regular_price": p["regular_price"],
            "status": p["status"],
            "sku": p.get("sku", ""),
        }
        for p in products
    ]


@mcp.tool()
def create_product(
    name: str,
    regular_price: str,
    description: str = "",
    status: str = "publish",
    sku: str = "",
) -> dict[str, Any]:
    """Create a WooCommerce product. Products are published by default unless another valid status is explicitly requested."""
    if not name.strip():
        raise ValueError("Product name cannot be empty.")
    if status not in {"draft", "publish", "pending", "private"}:
        raise ValueError("Unsupported product status.")

    payload: dict[str, Any] = {
        "name": name.strip(),
        "regular_price": validate_price(regular_price),
        "description": description,
        "status": status,
    }
    if sku.strip():
        payload["sku"] = sku.strip()

    product = api_request("POST", "products", payload=payload)

    return {
        "id": product["id"],
        "name": product["name"],
        "regular_price": product["regular_price"],
        "status": product["status"],
    }


@mcp.tool()
def update_product(
    product_id: int,
    name: str | None = None,
    regular_price: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update selected fields of an existing WooCommerce product."""
    if product_id < 1:
        raise ValueError("product_id must be positive.")

    payload: dict[str, Any] = {}

    if name is not None:
        if not name.strip():
            raise ValueError("Product name cannot be empty.")
        payload["name"] = name.strip()

    if regular_price is not None:
        payload["regular_price"] = validate_price(regular_price)

    if description is not None:
        payload["description"] = description

    if status is not None:
        if status not in {"draft", "publish", "pending", "private"}:
            raise ValueError("Unsupported product status.")
        payload["status"] = status

    if not payload:
        raise ValueError("Provide at least one field to update.")

    product = api_request(
        "PUT", f"products/{product_id}", payload=payload
    )

    return {
        "id": product["id"],
        "name": product["name"],
        "regular_price": product["regular_price"],
        "status": product["status"],
    }


@mcp.tool()
def list_orders(
    per_page: int = 10,
    page: int = 1,
    status: str = "",
) -> list[dict[str, Any]]:
    """List WooCommerce orders, optionally filtering by status."""
    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100.")
    if page < 1:
        raise ValueError("page must be at least 1.")

    params: dict[str, Any] = {"per_page": per_page, "page": page}
    if status:
        allowed_statuses = {
            "pending", "processing", "on-hold", "completed",
            "cancelled", "refunded", "failed",
        }
        if status not in allowed_statuses:
            raise ValueError("Unsupported order status.")
        params["status"] = status

    orders = api_request("GET", "orders", params=params)

    return [
        {
            "id": order["id"],
            "status": order["status"],
            "total": order["total"],
            "currency": order["currency"],
            "date_created": order.get("date_created"),
        }
        for order in orders
    ]


@mcp.tool()
def get_order(order_id: int) -> dict[str, Any]:
    """Retrieve an order by its WooCommerce order ID."""
    if order_id < 1:
        raise ValueError("order_id must be positive.")

    order = api_request("GET", f"orders/{order_id}")

    return {
        "id": order["id"],
        "status": order["status"],
        "total": order["total"],
        "currency": order["currency"],
        "date_created": order.get("date_created"),
        "customer_note": order.get("customer_note", ""),
        "line_items": [
            {
                "product_id": item.get("product_id"),
                "name": item["name"],
                "quantity": item["quantity"],
                "total": item["total"],
            }
            for item in order.get("line_items", [])
        ],
    }


@mcp.tool()
def create_order(
    product_id: int,
    quantity: int,
    customer_email: str,
    customer_first_name: str,
    customer_last_name: str,
    confirm_order: bool,
    billing_address_1: str = "",
    billing_city: str = "",
    billing_postcode: str = "",
    billing_country: str = "IN",
) -> dict[str, Any]:
    """Create a WooCommerce order after the customer has explicitly confirmed the displayed order summary.

    Before calling this tool, show the customer the product, quantity, and price/total
    when available, and ask for explicit confirmation. Set confirm_order=True only
    after the customer confirms. This creates an order through the WooCommerce REST
    API; it does not complete a storefront checkout or process a payment.
    """
    if not confirm_order:
        raise ValueError(
            "Order was not created. Show the order summary and obtain explicit customer confirmation first."
        )
    if product_id < 1:
        raise ValueError("product_id must be positive.")
    if quantity < 1 or quantity > 100:
        raise ValueError("quantity must be between 1 and 100.")
    if not customer_email.strip() or "@" not in customer_email:
        raise ValueError("A valid customer email is required.")
    if not customer_first_name.strip() or not customer_last_name.strip():
        raise ValueError("Customer first and last names are required.")
    if billing_country.strip().upper() != "IN":
        raise ValueError("This order tool currently supports billing country IN only.")

    payload: dict[str, Any] = {
        "status": "pending",
        "billing": {
            "first_name": customer_first_name.strip(),
            "last_name": customer_last_name.strip(),
            "email": customer_email.strip(),
            "address_1": billing_address_1.strip(),
            "city": billing_city.strip(),
            "postcode": billing_postcode.strip(),
            "country": "IN",
        },
        "line_items": [{"product_id": product_id, "quantity": quantity}],
        "set_paid": False,
    }

    order = api_request("POST", "orders", payload=payload)
    return {
        "id": order["id"],
        "status": order["status"],
        "total": order["total"],
        "currency": order["currency"],
        "date_created": order.get("date_created"),
        "payment_processed": False,
        "message": "WooCommerce order created. Payment has not been processed.",
    }


@mcp.tool()
def update_order(
    order_id: int,
    status: str | None = None,
    customer_note: str | None = None,
) -> dict[str, Any]:
    """Update an order's status or customer note."""
    if order_id < 1:
        raise ValueError("order_id must be positive.")

    payload: dict[str, Any] = {}

    if status is not None:
        allowed_statuses = {
            "pending", "processing", "on-hold", "completed",
            "cancelled", "refunded", "failed",
        }
        if status not in allowed_statuses:
            raise ValueError("Unsupported order status.")
        payload["status"] = status

    if customer_note is not None:
        payload["customer_note"] = customer_note

    if not payload:
        raise ValueError("Provide status or customer_note to update.")

    order = api_request(
        "PUT", f"orders/{order_id}", payload=payload
    )

    return {
        "id": order["id"],
        "status": order["status"],
        "customer_note": order.get("customer_note", ""),
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

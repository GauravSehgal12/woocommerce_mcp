
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

# Load credentials from the service's .env file.
# env_file = Path(__file__).resolve().parent / ".env"
load_dotenv()

store_url = os.getenv("WOOCOMMERCE_URL", "").rstrip("/")
consumer_key = os.getenv("WOOCOMMERCE_CONSUMER_KEY", "")
consumer_secret = os.getenv("WOOCOMMERCE_CONSUMER_SECRET", "")


def main():
    if not all([store_url, consumer_key, consumer_secret]):
        print("ERROR: Missing WooCommerce configuration in .env")
        return

    # OAuth 1.0a signs the request instead of sending the secret
    # as a query parameter.
    auth = OAuth1(
        consumer_key,
        consumer_secret,
        signature_method="HMAC-SHA256",
        signature_type="AUTH_HEADER",
    )

    endpoint = f"{store_url}/wp-json/wc/v3/products"

    try:
        response = requests.get(
            endpoint,
            params={"per_page": 1},
            auth=auth,
            timeout=15,
        )

        print("HTTP status:", response.status_code)
        print("Response:", response.text[:1000])

        if response.status_code == 200:
            print("SUCCESS: WooCommerce API authentication works.")
        else:
            print("FAILED: Check the response above.")

    except requests.RequestException as exc:
        print("Connection error:", type(exc).__name__)


if __name__ == "__main__":
    main()
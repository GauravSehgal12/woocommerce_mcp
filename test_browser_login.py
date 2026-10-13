import getpass
import requests

base = "http://127.0.0.1:8101"

username = input("Admin username: ").strip()
password = getpass.getpass("Admin password: ")

session = requests.Session()
response = session.post(
    f"{base}/auth/login",
    json={"username": username, "password": password},
    timeout=10,
)

print("Login HTTP status:", response.status_code)

if response.ok:
    data = response.json()
    print("Authenticated role:", data.get("user", {}).get("role"))
    print("Session cookie received:", "woo_session" in session.cookies)
else:
    print("Login failed:", response.text)

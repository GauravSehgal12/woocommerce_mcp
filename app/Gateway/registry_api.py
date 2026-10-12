
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REGISTRY_FILE = DATA_DIR / "servers.json"

registry_lock = Lock()

app = FastAPI(
    title="MCP Gateway Server Registry",
    version="1.0.0",
    description="Register and manage upstream MCP servers.",
)


class ServerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    url: str = Field(min_length=8, max_length=500)
    description: str = Field(default="", max_length=500)


def validate_server_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=400,
            detail="URL must be a valid HTTP or HTTPS URL.",
        )

    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400,
            detail="Do not put credentials in the server URL.",
        )

    return url.rstrip("/")


def read_registry() -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not REGISTRY_FILE.exists():
        return []

    try:
        with REGISTRY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise ValueError("Registry must contain a JSON list.")

        return data

    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Registry file is invalid: {exc}",
        ) from exc


def write_registry(servers: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DATA_DIR,
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump(servers, file, indent=2)
            temp_path = file.name

        os.replace(temp_path, REGISTRY_FILE)

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def find_server(servers: list[dict], server_id: str) -> dict:
    for server in servers:
        if server["id"] == server_id:
            return server

    raise HTTPException(
        status_code=404,
        detail=f"Server '{server_id}' was not found.",
    )


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/servers")
def list_servers():
    with registry_lock:
        servers = read_registry()

    return {
        "count": len(servers),
        "servers": servers,
    }


@app.post("/servers", status_code=status.HTTP_201_CREATED)
def register_server(payload: ServerCreate):
    normalized_name = payload.name.strip()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", normalized_name):
        raise HTTPException(
            status_code=400,
            detail=(
                "Name must contain only letters, numbers, "
                "underscores, or hyphens."
            ),
        )

    normalized_url = validate_server_url(payload.url)

    with registry_lock:
        servers = read_registry()

        if any(
            server["name"].lower() == normalized_name.lower()
            for server in servers
        ):
            raise HTTPException(
                status_code=409,
                detail="A server with this name already exists.",
            )

        if any(server["url"] == normalized_url for server in servers):
            raise HTTPException(
                status_code=409,
                detail="A server with this URL is already registered.",
            )

        now = datetime.now(timezone.utc).isoformat()

        server = {
            "id": str(uuid.uuid4()),
            "name": normalized_name,
            "url": normalized_url,
            "description": payload.description.strip(),
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }

        servers.append(server)
        write_registry(servers)

    return {"message": "Server registered.", "server": server}


@app.patch("/servers/{server_id}/disable")
def disable_server(server_id: str):
    with registry_lock:
        servers = read_registry()
        server = find_server(servers, server_id)

        server["enabled"] = False
        server["updated_at"] = datetime.now(timezone.utc).isoformat()

        write_registry(servers)

    return {"message": "Server disabled.", "server": server}


@app.patch("/servers/{server_id}/enable")
def enable_server(server_id: str):
    with registry_lock:
        servers = read_registry()
        server = find_server(servers, server_id)

        server["enabled"] = True
        server["updated_at"] = datetime.now(timezone.utc).isoformat()

        write_registry(servers)

    return {"message": "Server enabled.", "server": server}


@app.delete("/servers/{server_id}")
def remove_server(server_id: str):
    with registry_lock:
        servers = read_registry()
        server = find_server(servers, server_id)

        servers = [
            item for item in servers
            if item["id"] != server_id
        ]

        write_registry(servers)

    return {
        "message": "Server removed from registry.",
        "server_id": server_id,
        "name": server["name"],
    }

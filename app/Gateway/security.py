
import hashlib
import secrets
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import Depends, Header, HTTPException, status


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_FILE = DATA_DIR / "security.db"

API_KEY_PREFIX = "mcp_live_"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db():
    """Open a SQLite connection and safely manage its transaction."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        DB_FILE,
        timeout=10,
    )
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create the security tables if they do not exist."""
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL
                    CHECK (role IN ('admin', 'member')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                key_prefix TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY (user_id)
                    REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_api_keys_user
                ON api_keys(user_id);

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                username TEXT,
                server_name TEXT,
                tool_name TEXT,
                timestamp TEXT NOT NULL,
                duration_ms INTEGER,
                outcome TEXT NOT NULL,
                details TEXT,
                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_logs(timestamp);

            CREATE INDEX IF NOT EXISTS idx_audit_user
                ON audit_logs(user_id);
            """
        )


def hash_api_key(api_key: str) -> str:
    """Hash a high-entropy API key before storing it."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def create_user(username: str, role: str) -> dict:
    """Create a user with the specified role."""
    username = username.strip()

    if not username or len(username) > 80:
        raise ValueError("Username must contain 1 to 80 characters.")

    if role not in {"admin", "member"}:
        raise ValueError("Role must be 'admin' or 'member'.")

    user_id = secrets.token_hex(16)

    with get_db() as db:
        db.execute(
            """
            INSERT INTO users (id, username, role, active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (user_id, username, role, utc_now()),
        )

    return {
        "id": user_id,
        "username": username,
        "role": role,
        "active": True,
    }


def issue_api_key(user_id: str) -> str:
    """
    Issue a new API key and return it once.

    Only its SHA-256 hash is persisted. The original key cannot
    be recovered from the database.
    """
    raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    key_id = secrets.token_hex(16)
    key_hash = hash_api_key(raw_key)
    key_prefix = raw_key[:len(API_KEY_PREFIX) + 8]

    with get_db() as db:
        user = db.execute(
            "SELECT id, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if user is None:
            raise ValueError("User was not found.")

        if not user["active"]:
            raise ValueError("Cannot issue a key to an inactive user.")

        db.execute(
            """
            INSERT INTO api_keys (
                id, user_id, key_hash, key_prefix, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                key_id,
                user_id,
                key_hash,
                key_prefix,
                utc_now(),
            ),
        )

    return raw_key


def authenticate_api_key(api_key: str | None) -> dict:
    """Validate a presented key and return its active user."""
    if not api_key or not api_key.startswith(API_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid API key is required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    key_hash = hash_api_key(api_key)

    with get_db() as db:
        row = db.execute(
            """
            SELECT
                users.id,
                users.username,
                users.role,
                users.active,
                api_keys.id AS api_key_id
            FROM api_keys
            JOIN users ON users.id = api_keys.user_id
            WHERE api_keys.key_hash = ?
              AND api_keys.revoked_at IS NULL
            """,
            (key_hash,),
        ).fetchone()

    if row is None or not row["active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, revoked, or inactive API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "api_key_id": row["api_key_id"],
    }


def get_current_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    """FastAPI dependency for API-key authentication."""
    return authenticate_api_key(x_api_key)


def require_role(*allowed_roles: str) -> Callable:
    """Build a FastAPI dependency that enforces user roles."""

    def role_checker(
        user: dict = Depends(get_current_user),
    ) -> dict:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )

        return user

    return role_checker


def revoke_api_key(key_id: str) -> bool:
    """Revoke an API key without deleting its audit history."""
    with get_db() as db:
        cursor = db.execute(
            """
            UPDATE api_keys
            SET revoked_at = ?
            WHERE id = ? AND revoked_at IS NULL
            """,
            (utc_now(), key_id),
        )

        return cursor.rowcount == 1


def list_users() -> list[dict]:
    """Return user records without exposing API keys or hashes."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, username, role, active, created_at
            FROM users
            ORDER BY created_at
            """
        ).fetchall()

    return [
        {
            **dict(row),
            "active": bool(row["active"]),
        }
        for row in rows
    ]


def list_user_keys(user_id: str) -> list[dict]:
    """List key metadata only; never return stored hashes."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, key_prefix, created_at, revoked_at
            FROM api_keys
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def record_audit_event(
    user: dict | None,
    server_name: str,
    tool_name: str,
    duration_ms: int | None,
    outcome: str,
    details: str | None = None,
) -> None:
    """Persist an audit event without recording API keys or secrets."""
    allowed_outcomes = {
        "success",
        "error",
        "denied",
    }

    if outcome not in allowed_outcomes:
        raise ValueError("Invalid audit outcome.")

    # Keep audit details bounded and avoid storing arbitrary tool inputs.
    safe_details = details[:1000] if details else None

    with get_db() as db:
        db.execute(
            """
            INSERT INTO audit_logs (
                user_id, username, server_name, tool_name,
                timestamp, duration_ms, outcome, details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.get("id") if user else None,
                user.get("username") if user else None,
                server_name[:80],
                tool_name[:160],
                utc_now(),
                duration_ms,
                outcome,
                safe_details,
            ),
        )


def bootstrap_admin() -> None:
    """Interactively create the first admin and display its key once."""
    init_db()

    username = input("Admin username: ").strip()

    with get_db() as db:
        existing_admin = db.execute(
            "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()

    if existing_admin:
        print(
            "An admin already exists. Use the admin-management "
            "workflow to issue another key."
        )
        return

    admin = create_user(username, "admin")
    api_key = issue_api_key(admin["id"])

    print("\nAdmin created successfully.")
    print(f"Username: {admin['username']}")
    print(f"User ID: {admin['id']}")
    print("\nCOPY THIS API KEY NOW. IT WILL NOT BE SHOWN AGAIN:")
    print(api_key)
    print("\nStore it securely. Do not commit it to Git.")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "init":
        init_db()
        print(f"Security database initialized: {DB_FILE}")
    elif len(sys.argv) == 2 and sys.argv[1] == "bootstrap-admin":
        bootstrap_admin()
    else:
        print(
            "Usage:\n"
            "  python security.py init\n"
            "  python security.py bootstrap-admin"
        )

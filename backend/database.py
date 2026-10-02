import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

# Load backend/.env explicitly so it works no matter which directory
# uvicorn is started from. Real environment variables take precedence.
load_dotenv(Path(__file__).resolve().parent / ".env")


def _require(name):
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(
            f"Missing environment variable {name}. "
            "Copy backend/.env.example to backend/.env and fill it in."
        )
    return value


DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": _require("DB_USER"),
    "password": _require("DB_PASSWORD"),
    "database": _require("DB_NAME"),
}


def get_connection():
    """Open a plain MySQL connection (for scripts and tests)."""
    return mysql.connector.connect(**DB_CONFIG)


def get_db():
    """FastAPI dependency: one connection per request.

    If the endpoint raises anything (including HTTPException), the open
    transaction is rolled back so its row locks are released immediately.
    The connection is always closed, on success and on failure.
    """
    db = get_connection()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

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


def get_db():
    return mysql.connector.connect(**DB_CONFIG)

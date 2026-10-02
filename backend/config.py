import os
from pathlib import Path

from dotenv import load_dotenv

# All settings come from environment variables. Load backend/.env explicitly
# so it works no matter which directory uvicorn is started from.
# Real environment variables take precedence over the file.
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

# Browser origins allowed to call the API (comma-separated in .env).
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500"
    ).split(",")
    if origin.strip()
]

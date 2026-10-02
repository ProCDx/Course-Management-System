import mysql.connector

from config import DB_CONFIG


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

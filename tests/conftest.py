"""Shared fixtures for the API tests.

The tests are black-box: they start the real API in a separate uvicorn
process and talk to it over HTTP, exactly like the frontend does. They use
the database configured in backend/.env (or the DB_* environment
variables), which must have backend/schema.sql loaded. Point them at a
dedicated test database, e.g.:

    DB_NAME=course_system_test pytest -v

Every test creates its own uniquely named courses and students and deletes
them afterwards, so the seed data is never touched.
"""
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from database import get_connection  # noqa: E402  (needs BACKEND on sys.path)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def running_api(extra_env=None, ready_status=200):
    """Run the real API in its own uvicorn process; yield its base URL.

    Waits until GET /courses returns `ready_status`. With the default 200
    that means the API is up AND can reach MySQL.
    """
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
        cwd=BACKEND,
        env={**os.environ, **(extra_env or {})},
    )
    url = f"http://127.0.0.1:{port}"

    try:
        deadline = time.time() + 20
        while True:
            try:
                if httpx.get(f"{url}/courses").status_code == ready_status:
                    break
            except httpx.TransportError:
                pass
            if proc.poll() is not None or time.time() > deadline:
                raise RuntimeError(
                    "API did not become ready. Is MySQL running and "
                    "backend/schema.sql loaded into the configured database?"
                )
            time.sleep(0.2)

        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def api_url():
    """One API server shared by the whole test session."""
    with running_api() as url:
        yield url


@pytest.fixture
def api_url_without_db():
    """An API server whose database is unreachable (nothing listens on DB_PORT)."""
    with running_api({"DB_PORT": str(_free_port())}, ready_status=503) as url:
        yield url


class Factory:
    """Creates test-only rows straight in MySQL and removes them afterwards."""

    def __init__(self):
        self.tag = uuid.uuid4().hex[:8]
        self.course_ids = []
        self.student_ids = []

    def course(self, capacity):
        with closing(get_connection()) as db:
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO COURSE (course_name, capacity) VALUES (%s, %s)",
                (f"Test course {self.tag}", capacity),
            )
            db.commit()
            self.course_ids.append(cursor.lastrowid)
            return cursor.lastrowid

    def students(self, count):
        ids = []
        with closing(get_connection()) as db:
            cursor = db.cursor()
            for i in range(count):
                cursor.execute(
                    "INSERT INTO STUDENT (student_name, email, department_id) VALUES (%s, %s, 1)",
                    (f"Test student {self.tag}-{i}", f"test-{self.tag}-{i}@example.test"),
                )
                ids.append(cursor.lastrowid)
            db.commit()
        self.student_ids.extend(ids)
        return ids

    def track_student(self, student_id):
        """Delete a student created through the API during cleanup too."""
        self.student_ids.append(student_id)

    def insert_enrollment(self, student_id, course_id, status, position=None):
        """Write an ENROLLMENT row directly, bypassing the API's rules."""
        with closing(get_connection()) as db:
            db.cursor().execute("""
                INSERT INTO ENROLLMENT (student_id, course_id, semester_id, status, position)
                VALUES (%s, %s, 1, %s, %s)
            """, (student_id, course_id, status, position))
            db.commit()

    def enrollment(self, course_id, semester_id=1):
        """Return (registered student ids, [(student id, position), ...] in queue order)."""
        with closing(get_connection()) as db:
            cursor = db.cursor()
            cursor.execute("""
                SELECT student_id, status, position FROM ENROLLMENT
                WHERE course_id = %s AND semester_id = %s
                ORDER BY position
            """, (course_id, semester_id))
            rows = cursor.fetchall()

        registered = sorted(sid for sid, status, _ in rows if status == "Registered")
        waitlist = [(sid, pos) for sid, status, pos in rows if status == "Waitlisted"]
        return registered, waitlist

    def cleanup(self):
        with closing(get_connection()) as db:
            cursor = db.cursor()
            if self.course_ids:
                marks = ", ".join(["%s"] * len(self.course_ids))
                cursor.execute(f"DELETE FROM ENROLLMENT WHERE course_id IN ({marks})", self.course_ids)
            if self.student_ids:
                marks = ", ".join(["%s"] * len(self.student_ids))
                cursor.execute(f"DELETE FROM ENROLLMENT WHERE student_id IN ({marks})", self.student_ids)
                cursor.execute(f"DELETE FROM STUDENT WHERE student_id IN ({marks})", self.student_ids)
            if self.course_ids:
                marks = ", ".join(["%s"] * len(self.course_ids))
                cursor.execute(f"DELETE FROM COURSE WHERE course_id IN ({marks})", self.course_ids)
            db.commit()


@pytest.fixture
def factory():
    f = Factory()
    yield f
    f.cleanup()

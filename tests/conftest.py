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
import socket
import subprocess
import sys
import time
import uuid
from contextlib import closing
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


@pytest.fixture(scope="session")
def api_url():
    """Run the real API in its own uvicorn process for the whole test session."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
        cwd=BACKEND,
    )
    url = f"http://127.0.0.1:{port}"

    try:
        # /courses only returns 200 once the API is up AND can reach MySQL
        deadline = time.time() + 20
        while True:
            try:
                if httpx.get(f"{url}/courses").status_code == 200:
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

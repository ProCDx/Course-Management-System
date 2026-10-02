import logging
import os
import re

import mysql.connector
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mysql.connector import errorcode
from pydantic import BaseModel, Field
from database import get_db
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

app = FastAPI()

# CORS: only the local frontend may call the API from a browser.
# No cookies/auth headers are used, so allow_credentials stays off.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


# ------------------ ERROR HANDLING ------------------
# Every error response has the same shape: {"detail": "<message>"}.
# HTTPException (404/409/400 raised by endpoints) already produces it.

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # FastAPI's default is 422 with a list of error objects. Return one
    # readable 400 message instead so the frontend can show it as-is.
    error = exc.errors()[0]
    field = ".".join(str(part) for part in error["loc"] if part != "body") or "request body"
    return JSONResponse(status_code=400, content={"detail": f"Invalid {field}: {error['msg']}"})


@app.exception_handler(mysql.connector.IntegrityError)
async def integrity_error_handler(request: Request, exc: mysql.connector.IntegrityError):
    if exc.errno == errorcode.ER_DUP_ENTRY:
        return JSONResponse(status_code=409, content={"detail": "This record already exists"})
    if exc.errno == errorcode.ER_NO_REFERENCED_ROW_2:
        return JSONResponse(status_code=400, content={"detail": "A referenced record does not exist"})
    return JSONResponse(status_code=400, content={"detail": "Invalid data"})


TRANSIENT_DB_ERRORS = {errorcode.ER_LOCK_WAIT_TIMEOUT, errorcode.ER_LOCK_DEADLOCK}


@app.exception_handler(mysql.connector.Error)
async def database_error_handler(request: Request, exc: mysql.connector.Error):
    # Log the real error server-side; never send SQL details to the client.
    logger.error("Database error on %s %s: %s", request.method, request.url.path, exc)
    if (
        isinstance(exc, (mysql.connector.InterfaceError, mysql.connector.OperationalError))
        or exc.errno in TRANSIENT_DB_ERRORS
    ):
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is unavailable or busy, please try again"},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ------------------ MODELS ------------------
class Data(BaseModel):
    student_id: int = Field(gt=0)
    course_id: int = Field(gt=0)
    semester_id: int = Field(default=1, gt=0)


EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


# ------------------ STUDENTS ------------------
@app.post("/add-student")
def add_student(name: str = Form(...), email: str = Form(...), db=Depends(get_db)):
    name, email = name.strip(), email.strip()

    if not 1 <= len(name) <= 100:
        raise HTTPException(status_code=400, detail="Name must be 1-100 characters")
    if len(email) > 255 or not EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=400, detail="Invalid email address")

    cursor = db.cursor()

    try:
        cursor.execute("""
            INSERT INTO STUDENT (student_name, email, department_id)
            VALUES (%s, %s, 1)
        """, (name, email))
    except mysql.connector.IntegrityError as e:
        if e.errno == errorcode.ER_DUP_ENTRY:
            raise HTTPException(
                status_code=409,
                detail="A student with this email already exists",
            )
        raise

    db.commit()

    return {"message": "Student Created", "student_id": cursor.lastrowid}


@app.get("/students")
def get_students(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT student_id, student_name FROM STUDENT")
    return cursor.fetchall()


# ------------------ REGISTER ------------------
# Any exception below (HTTPException included) makes get_db roll back the
# transaction, which also releases the course row lock.

@app.post("/register")
def register(data: Data, db=Depends(get_db)):
    cursor = db.cursor()

    # One transaction for the whole check-then-insert flow.
    # READ COMMITTED: every read below sees rows committed by whoever
    # held the course lock before us (no stale MVCC snapshot).
    db.start_transaction(isolation_level="READ COMMITTED")

    # Lock the course row. Concurrent registrations for the same course
    # block here and run one at a time until we commit or roll back.
    cursor.execute(
        "SELECT capacity FROM COURSE WHERE course_id = %s FOR UPDATE",
        (data.course_id,),
    )
    result = cursor.fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Course not found")

    capacity = result[0]

    cursor.execute("SELECT COUNT(*) FROM STUDENT WHERE student_id = %s", (data.student_id,))
    if cursor.fetchone()[0] == 0:
        raise HTTPException(status_code=404, detail="Student not found")

    # reject duplicates
    cursor.execute("""
        SELECT COUNT(*) FROM REGISTRATION
        WHERE student_id = %s AND course_id = %s
    """, (data.student_id, data.course_id))
    if cursor.fetchone()[0] > 0:
        raise HTTPException(
            status_code=409,
            detail="Student is already registered for this course",
        )

    cursor.execute("""
        SELECT COUNT(*) FROM WAITLIST
        WHERE student_id = %s AND course_id = %s
    """, (data.student_id, data.course_id))
    if cursor.fetchone()[0] > 0:
        raise HTTPException(
            status_code=409,
            detail="Student is already on the waitlist for this course",
        )

    # count registered
    cursor.execute("SELECT COUNT(*) FROM REGISTRATION WHERE course_id = %s", (data.course_id,))
    count = cursor.fetchone()[0]

    if count < capacity:
        cursor.execute("""
            INSERT INTO REGISTRATION (student_id, course_id, semester_id, status)
            VALUES (%s, %s, %s, 'Registered')
        """, (data.student_id, data.course_id, data.semester_id))
        db.commit()

        return {"message": "Registered"}

    # waitlist
    cursor.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM WAITLIST WHERE course_id = %s",
        (data.course_id,),
    )
    position = cursor.fetchone()[0]

    cursor.execute("""
        INSERT INTO WAITLIST (student_id, course_id, semester_id, position)
        VALUES (%s, %s, %s, %s)
    """, (data.student_id, data.course_id, data.semester_id, position))
    db.commit()

    return {"message": "Added to Waitlist", "position": position}


# ------------------ GET DATA ------------------
@app.get("/registrations")
def get_registrations(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT r.registration_id,
               s.student_name,
               c.course_name,
               r.status
        FROM REGISTRATION r
        JOIN STUDENT s ON r.student_id = s.student_id
        JOIN COURSE c ON r.course_id = c.course_id
    """)

    return cursor.fetchall()


@app.get("/courses")
def get_courses(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM COURSE")
    return cursor.fetchall()


@app.get("/waitlist")
def get_waitlist(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT s.student_name,
               c.course_name,
               w.position
        FROM WAITLIST w
        JOIN STUDENT s ON w.student_id = s.student_id
        JOIN COURSE c ON w.course_id = c.course_id
    """)

    return cursor.fetchall()


# ------------------ DROP ------------------
def remove_from_waitlist(cursor, student_id, course_id, position):
    """Delete one waitlist entry and move everyone behind it up one place."""
    cursor.execute("""
        DELETE FROM WAITLIST
        WHERE student_id = %s AND course_id = %s
    """, (student_id, course_id))

    cursor.execute("""
        UPDATE WAITLIST
        SET position = position - 1
        WHERE course_id = %s AND position > %s
    """, (course_id, position))


@app.delete("/drop")
def drop(data: Data, db=Depends(get_db)):
    cursor = db.cursor()

    # delete + promote + reorder succeed or fail together
    db.start_transaction(isolation_level="READ COMMITTED")

    # Lock the course row first, same as /register, so a drop and a
    # register for the same course can't interleave (and both endpoints
    # take locks in the same order, which avoids deadlocks).
    cursor.execute(
        "SELECT capacity FROM COURSE WHERE course_id = %s FOR UPDATE",
        (data.course_id,),
    )
    result = cursor.fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Course not found")

    capacity = result[0]

    # remove from registration
    cursor.execute("""
        DELETE FROM REGISTRATION
        WHERE student_id = %s AND course_id = %s
    """, (data.student_id, data.course_id))

    # Not registered: no seat was freed, so promote nobody. If the student
    # is on the waitlist, they are leaving it instead.
    if cursor.rowcount == 0:
        cursor.execute("""
            SELECT position FROM WAITLIST
            WHERE student_id = %s AND course_id = %s
        """, (data.student_id, data.course_id))
        waiting = cursor.fetchone()

        if not waiting:
            raise HTTPException(
                status_code=404,
                detail="Student is not registered or waitlisted for this course",
            )

        remove_from_waitlist(cursor, data.student_id, data.course_id, waiting[0])
        db.commit()

        return {"message": "Removed from waitlist", "promoted_student_id": None}

    # only promote if a seat is actually free now
    cursor.execute("SELECT COUNT(*) FROM REGISTRATION WHERE course_id = %s", (data.course_id,))
    count = cursor.fetchone()[0]

    next_student = None
    if count < capacity:
        # get next waitlist
        cursor.execute("""
            SELECT student_id, semester_id, position FROM WAITLIST
            WHERE course_id = %s
            ORDER BY position ASC
            LIMIT 1
        """, (data.course_id,))
        next_student = cursor.fetchone()

    if next_student:
        sid, sem, pos = next_student

        # promote
        cursor.execute("""
            INSERT INTO REGISTRATION (student_id, course_id, semester_id, status)
            VALUES (%s, %s, %s, 'Registered')
        """, (sid, data.course_id, sem))

        remove_from_waitlist(cursor, sid, data.course_id, pos)

    db.commit()

    if next_student:
        return {"message": "Dropped. Next waitlisted student promoted", "promoted_student_id": next_student[0]}
    return {"message": "Dropped", "promoted_student_id": None}

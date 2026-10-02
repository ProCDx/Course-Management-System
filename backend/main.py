import os

import mysql.connector
from fastapi import FastAPI, Form, HTTPException
from mysql.connector import errorcode
from pydantic import BaseModel
from database import get_db
from fastapi.middleware.cors import CORSMiddleware

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

# ------------------ MODELS ------------------
class Data(BaseModel):
    student_id: int
    course_id: int
    semester_id: int = 1


# ------------------ STUDENTS ------------------
@app.post("/add-student")
def add_student(name: str = Form(...), email: str = Form(...)):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO STUDENT (student_name, email, department_id)
        VALUES (%s, %s, 1)
    """, (name, email))

    db.commit()
    cursor.close()
    db.close()

    return {"message": "Student Created"}


@app.get("/students")
def get_students():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT student_id, student_name FROM STUDENT")
    data = cursor.fetchall()

    cursor.close()
    db.close()

    return data


# ------------------ REGISTER ------------------
@app.post("/register")
def register(data: Data):
    db = get_db()
    cursor = db.cursor()

    try:
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

    except mysql.connector.IntegrityError as e:
        # Second line of defence: UNIQUE (student_id, course_id) rejected it.
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            raise HTTPException(
                status_code=409,
                detail="Student is already registered or waitlisted for this course",
            )
        raise
    except Exception:
        # Rolling back also releases the course row lock.
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


# ------------------ GET DATA ------------------
@app.get("/registrations")
def get_registrations():
    db = get_db()
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

    data = cursor.fetchall()
    cursor.close()
    db.close()
    return data


@app.get("/courses")
def get_courses():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM COURSE")
    data = cursor.fetchall()

    cursor.close()
    db.close()
    return data


@app.get("/waitlist")
def get_waitlist():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT s.student_name,
               c.course_name,
               w.position
        FROM WAITLIST w
        JOIN STUDENT s ON w.student_id = s.student_id
        JOIN COURSE c ON w.course_id = c.course_id
    """)

    data = cursor.fetchall()
    cursor.close()
    db.close()
    return data


# ------------------ DROP ------------------
@app.delete("/drop")
def drop(data: Data):
    db = get_db()
    cursor = db.cursor()

    try:
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

        # nothing deleted -> no seat was freed, so promote nobody
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Student is not registered for this course",
            )

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

            # remove from waitlist
            cursor.execute("""
                DELETE FROM WAITLIST
                WHERE student_id = %s AND course_id = %s
            """, (sid, data.course_id))

            # reorder waitlist: everyone behind the promoted student moves up one
            cursor.execute("""
                UPDATE WAITLIST
                SET position = position - 1
                WHERE course_id = %s AND position > %s
            """, (data.course_id, pos))

        db.commit()

    except Exception:
        # undo the DELETE too and release the course lock
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()

    if next_student:
        return {"message": "Dropped. Next waitlisted student promoted", "promoted_student_id": next_student[0]}
    return {"message": "Dropped", "promoted_student_id": None}
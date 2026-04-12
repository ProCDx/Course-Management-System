from fastapi import FastAPI, Form
from pydantic import BaseModel
from database import get_db
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

    # get capacity
    cursor.execute("SELECT capacity FROM COURSE WHERE course_id = %s", (data.course_id,))
    result = cursor.fetchone()

    if not result:
        return {"message": "Course not found"}

    capacity = result[0]

    # count registered
    cursor.execute("SELECT COUNT(*) FROM REGISTRATION WHERE course_id = %s", (data.course_id,))
    count = cursor.fetchone()[0]

    if count < capacity:
        cursor.execute("""
            INSERT INTO REGISTRATION (student_id, course_id, semester_id, status)
            VALUES (%s, %s, %s, 'Registered')
        """, (data.student_id, data.course_id, data.semester_id))
        db.commit()

        cursor.close()
        db.close()

        return {"message": "Registered"}

    else:
        # waitlist
        cursor.execute("SELECT COUNT(*) FROM WAITLIST WHERE course_id = %s", (data.course_id,))
        position = cursor.fetchone()[0] + 1

        cursor.execute("""
            INSERT INTO WAITLIST (student_id, course_id, semester_id, position)
            VALUES (%s, %s, %s, %s)
        """, (data.student_id, data.course_id, data.semester_id, position))

        db.commit()
        cursor.close()
        db.close()

        return {"message": "Added to Waitlist"}


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

    # remove from registration
    cursor.execute("""
        DELETE FROM REGISTRATION
        WHERE student_id = %s AND course_id = %s
    """, (data.student_id, data.course_id))

    # get next waitlist
    cursor.execute("""
        SELECT student_id, semester_id FROM WAITLIST
        WHERE course_id = %s
        ORDER BY position ASC
        LIMIT 1
    """, (data.course_id,))

    next_student = cursor.fetchone()

    if next_student:
        sid, sem = next_student

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

        # reorder waitlist
        cursor.execute("SET @pos = 0")
        cursor.execute("""
            UPDATE WAITLIST
            SET position = (@pos := @pos + 1)
            WHERE course_id = %s
            ORDER BY position
        """, (data.course_id,))

    db.commit()
    cursor.close()
    db.close()

    return {"message": "Dropped + Waitlist Updated"}
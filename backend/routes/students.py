import re

import mysql.connector
from fastapi import APIRouter, Depends, Form, HTTPException
from mysql.connector import errorcode

from database import get_db

router = APIRouter(tags=["students"])

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@router.post("/add-student")
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


@router.get("/students")
def get_students(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT student_id, student_name FROM STUDENT")
    return cursor.fetchall()

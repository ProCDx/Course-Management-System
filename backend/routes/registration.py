from fastapi import APIRouter, Depends, HTTPException

from database import get_db
from models import EnrollmentRequest
from routes.courses import lock_course
from routes.waitlist import close_waitlist_gap

router = APIRouter(tags=["registration"])


# ------------------ REGISTER ------------------
# Any exception below (HTTPException included) makes get_db roll back the
# transaction, which also releases the course row lock.
# Capacity, duplicates and waitlists are all per course per semester.

@router.post("/register")
def register(data: EnrollmentRequest, db=Depends(get_db)):
    cursor = db.cursor()

    # One transaction for the whole check-then-insert flow.
    # READ COMMITTED: every read below sees rows committed by whoever
    # held the course lock before us (no stale MVCC snapshot).
    db.start_transaction(isolation_level="READ COMMITTED")

    # Concurrent registrations for the same course block here and run one
    # at a time until we commit or roll back.
    capacity = lock_course(cursor, data.course_id)

    cursor.execute("SELECT COUNT(*) FROM STUDENT WHERE student_id = %s", (data.student_id,))
    if cursor.fetchone()[0] == 0:
        raise HTTPException(status_code=404, detail="Student not found")

    cursor.execute("SELECT COUNT(*) FROM SEMESTER WHERE semester_id = %s", (data.semester_id,))
    if cursor.fetchone()[0] == 0:
        raise HTTPException(status_code=404, detail="Semester not found")

    # reject duplicates: a student has at most one ENROLLMENT row per
    # course per semester, either Registered or Waitlisted
    cursor.execute("""
        SELECT status FROM ENROLLMENT
        WHERE student_id = %s AND course_id = %s AND semester_id = %s
    """, (data.student_id, data.course_id, data.semester_id))
    existing = cursor.fetchone()

    if existing and existing[0] == "Registered":
        raise HTTPException(
            status_code=409,
            detail="Student is already registered for this course",
        )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Student is already on the waitlist for this course",
        )

    # count registered
    cursor.execute("""
        SELECT COUNT(*) FROM ENROLLMENT
        WHERE course_id = %s AND semester_id = %s AND status = 'Registered'
    """, (data.course_id, data.semester_id))
    count = cursor.fetchone()[0]

    if count < capacity:
        cursor.execute("""
            INSERT INTO ENROLLMENT (student_id, course_id, semester_id, status)
            VALUES (%s, %s, %s, 'Registered')
        """, (data.student_id, data.course_id, data.semester_id))
        db.commit()

        return {"message": "Registered"}

    # waitlist
    cursor.execute("""
        SELECT COALESCE(MAX(position), 0) + 1 FROM ENROLLMENT
        WHERE course_id = %s AND semester_id = %s AND status = 'Waitlisted'
    """, (data.course_id, data.semester_id))
    position = cursor.fetchone()[0]

    cursor.execute("""
        INSERT INTO ENROLLMENT (student_id, course_id, semester_id, status, position)
        VALUES (%s, %s, %s, 'Waitlisted', %s)
    """, (data.student_id, data.course_id, data.semester_id, position))
    db.commit()

    return {"message": "Added to Waitlist", "position": position}


# ------------------ GET DATA ------------------
@router.get("/registrations")
def get_registrations(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    # enrollment_id is returned as registration_id to keep the response shape
    cursor.execute("""
        SELECT e.enrollment_id AS registration_id,
               s.student_name,
               c.course_name,
               e.status
        FROM ENROLLMENT e
        JOIN STUDENT s ON e.student_id = s.student_id
        JOIN COURSE c ON e.course_id = c.course_id
        WHERE e.status = 'Registered'
        ORDER BY e.enrollment_id
    """)

    return cursor.fetchall()


# ------------------ DROP ------------------
@router.delete("/drop")
def drop(data: EnrollmentRequest, db=Depends(get_db)):
    cursor = db.cursor()

    # delete + promote + reorder succeed or fail together
    db.start_transaction(isolation_level="READ COMMITTED")

    # Same lock as /register, taken first, so a drop and a register for the
    # same course can't interleave.
    capacity = lock_course(cursor, data.course_id)

    # remove the registration
    cursor.execute("""
        DELETE FROM ENROLLMENT
        WHERE student_id = %s AND course_id = %s AND semester_id = %s
          AND status = 'Registered'
    """, (data.student_id, data.course_id, data.semester_id))

    # Not registered: no seat was freed, so promote nobody. If the student
    # is on the waitlist, they are leaving it instead.
    if cursor.rowcount == 0:
        cursor.execute("""
            SELECT enrollment_id, position FROM ENROLLMENT
            WHERE student_id = %s AND course_id = %s AND semester_id = %s
              AND status = 'Waitlisted'
        """, (data.student_id, data.course_id, data.semester_id))
        waiting = cursor.fetchone()

        if not waiting:
            raise HTTPException(
                status_code=404,
                detail="Student is not registered or waitlisted for this course",
            )

        enrollment_id, position = waiting
        cursor.execute("DELETE FROM ENROLLMENT WHERE enrollment_id = %s", (enrollment_id,))
        close_waitlist_gap(cursor, data.course_id, data.semester_id, position)
        db.commit()

        return {"message": "Removed from waitlist", "promoted_student_id": None}

    # only promote if a seat is actually free now
    cursor.execute("""
        SELECT COUNT(*) FROM ENROLLMENT
        WHERE course_id = %s AND semester_id = %s AND status = 'Registered'
    """, (data.course_id, data.semester_id))
    count = cursor.fetchone()[0]

    next_student = None
    if count < capacity:
        # get next waitlist
        cursor.execute("""
            SELECT enrollment_id, student_id, position FROM ENROLLMENT
            WHERE course_id = %s AND semester_id = %s AND status = 'Waitlisted'
            ORDER BY position ASC
            LIMIT 1
        """, (data.course_id, data.semester_id))
        next_student = cursor.fetchone()

    if next_student:
        enrollment_id, sid, position = next_student

        # promote: same row, new status (frees its position for the reorder)
        cursor.execute("""
            UPDATE ENROLLMENT
            SET status = 'Registered', position = NULL
            WHERE enrollment_id = %s
        """, (enrollment_id,))

        close_waitlist_gap(cursor, data.course_id, data.semester_id, position)

    db.commit()

    if next_student:
        return {"message": "Dropped. Next waitlisted student promoted", "promoted_student_id": next_student[1]}
    return {"message": "Dropped", "promoted_student_id": None}

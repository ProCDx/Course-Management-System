from fastapi import APIRouter, Depends, HTTPException

from database import get_db
from models import Data
from routes.waitlist import remove_from_waitlist

router = APIRouter(tags=["registration"])


# ------------------ REGISTER ------------------
# Any exception below (HTTPException included) makes get_db roll back the
# transaction, which also releases the course row lock.

@router.post("/register")
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
@router.get("/registrations")
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


# ------------------ DROP ------------------
@router.delete("/drop")
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

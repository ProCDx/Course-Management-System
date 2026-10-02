from fastapi import APIRouter, Depends

from database import get_db

router = APIRouter(tags=["waitlist"])


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


@router.get("/waitlist")
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

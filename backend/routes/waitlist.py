from fastapi import APIRouter, Depends

from database import get_db

router = APIRouter(tags=["waitlist"])


def close_waitlist_gap(cursor, course_id, semester_id, position):
    """Move every waitlisted student behind `position` up one place.

    ORDER BY is required: MySQL checks the UNIQUE (course_id, semester_id,
    position) key row by row, so rows must move front-to-back or 3 -> 2
    would collide with the 2 that hasn't moved yet.
    """
    cursor.execute("""
        UPDATE ENROLLMENT
        SET position = position - 1
        WHERE course_id = %s AND semester_id = %s
          AND status = 'Waitlisted' AND position > %s
        ORDER BY position
    """, (course_id, semester_id, position))


@router.get("/waitlist")
def get_waitlist(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT s.student_name,
               c.course_name,
               e.position
        FROM ENROLLMENT e
        JOIN STUDENT s ON e.student_id = s.student_id
        JOIN COURSE c ON e.course_id = c.course_id
        WHERE e.status = 'Waitlisted'
        ORDER BY c.course_name, e.semester_id, e.position
    """)

    return cursor.fetchall()

from fastapi import APIRouter, Depends, HTTPException

from database import get_db

router = APIRouter(tags=["courses"])


def lock_course(cursor, course_id):
    """Lock the course row until the transaction ends; return its capacity.

    Every write to a course's enrollments takes this lock first, so writes
    for the same course run one at a time, and all of them lock in the same
    order (course first), which avoids deadlocks.
    """
    cursor.execute(
        "SELECT capacity FROM COURSE WHERE course_id = %s FOR UPDATE",
        (course_id,),
    )
    result = cursor.fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Course not found")

    return result[0]


@router.get("/courses")
def get_courses(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM COURSE")
    return cursor.fetchall()

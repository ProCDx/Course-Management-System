from fastapi import APIRouter, Depends

from database import get_db

router = APIRouter(tags=["courses"])


@router.get("/courses")
def get_courses(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM COURSE")
    return cursor.fetchall()

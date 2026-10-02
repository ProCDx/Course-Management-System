from pydantic import BaseModel, Field


class EnrollmentRequest(BaseModel):
    """Body of POST /register and DELETE /drop."""
    student_id: int = Field(gt=0)
    course_id: int = Field(gt=0)
    semester_id: int = Field(default=1, gt=0)

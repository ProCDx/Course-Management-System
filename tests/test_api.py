"""API behaviour tests: status codes, error messages and business rules.

Every error response must be {"detail": "<string>"} so the frontend can
show it as-is.
"""
import httpx
import pytest

from config import CORS_ORIGINS  # same settings the API server loads

UNKNOWN_ID = 999999


def register(api_url, student_id, course_id, semester_id=1):
    return httpx.post(f"{api_url}/register", json={
        "student_id": student_id, "course_id": course_id, "semester_id": semester_id,
    })


def drop(api_url, student_id, course_id, semester_id=1):
    return httpx.request("DELETE", f"{api_url}/drop", json={
        "student_id": student_id, "course_id": course_id, "semester_id": semester_id,
    })


# ------------------ STUDENTS ------------------
def test_add_student_returns_new_id(api_url, factory):
    email = f"new-{factory.tag}@example.test"
    r = httpx.post(f"{api_url}/add-student", data={"name": "  New Student  ", "email": email})

    assert r.status_code == 200
    student_id = r.json()["student_id"]
    factory.track_student(student_id)
    assert r.json() == {"message": "Student Created", "student_id": student_id}
    assert {"student_id": student_id, "student_name": "New Student"} in httpx.get(f"{api_url}/students").json()


def test_add_student_with_duplicate_email_is_409(api_url, factory):
    email = f"dup-{factory.tag}@example.test"
    first = httpx.post(f"{api_url}/add-student", data={"name": "First", "email": email})
    factory.track_student(first.json()["student_id"])

    r = httpx.post(f"{api_url}/add-student", data={"name": "Second", "email": email})

    assert r.status_code == 409
    assert r.json() == {"detail": "A student with this email already exists"}


@pytest.mark.parametrize("form, detail", [
    ({"name": "   ", "email": "a@example.test"}, "Name must be 1-100 characters"),
    ({"name": "x" * 101, "email": "a@example.test"}, "Name must be 1-100 characters"),
    ({"name": "Bob", "email": "not-an-email"}, "Invalid email address"),
    ({"name": "Bob", "email": "bob@nodot"}, "Invalid email address"),
])
def test_add_student_rejects_bad_input(api_url, form, detail):
    r = httpx.post(f"{api_url}/add-student", data=form)

    assert r.status_code == 400
    assert r.json() == {"detail": detail}


def test_add_student_missing_field_is_400_with_a_string_detail(api_url):
    r = httpx.post(f"{api_url}/add-student", data={"name": "", "email": "a@example.test"})

    assert r.status_code == 400
    assert r.json()["detail"].startswith("Invalid name:")


# ------------------ REGISTER ------------------
@pytest.mark.parametrize("body, field", [
    ({"student_id": 0, "course_id": 1}, "student_id"),
    ({"student_id": -5, "course_id": 1}, "student_id"),
    ({"student_id": "abc", "course_id": 1}, "student_id"),
    ({"student_id": None, "course_id": 1}, "student_id"),   # frontend sends null for an empty select
    ({"student_id": 1}, "course_id"),
    ({"student_id": 1, "course_id": 1, "semester_id": 0}, "semester_id"),
])
def test_register_rejects_bad_input(api_url, body, field):
    r = httpx.post(f"{api_url}/register", json=body)

    assert r.status_code == 400
    assert r.json()["detail"].startswith(f"Invalid {field}:")


def test_register_without_body_is_400(api_url):
    r = httpx.post(f"{api_url}/register")

    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)


def test_register_unknown_course_student_or_semester_is_404(api_url, factory):
    course_id = factory.course(capacity=1)
    (student,) = factory.students(1)

    assert register(api_url, student, UNKNOWN_ID).json() == {"detail": "Course not found"}
    assert register(api_url, UNKNOWN_ID, course_id).json() == {"detail": "Student not found"}
    r = register(api_url, student, course_id, semester_id=UNKNOWN_ID)
    assert (r.status_code, r.json()) == (404, {"detail": "Semester not found"})


def test_register_twice_is_409(api_url, factory):
    course_id = factory.course(capacity=1)
    seated, waiting = factory.students(2)
    assert register(api_url, seated, course_id).json() == {"message": "Registered"}
    assert register(api_url, waiting, course_id).json() == {"message": "Added to Waitlist", "position": 1}

    again_seated = register(api_url, seated, course_id)
    again_waiting = register(api_url, waiting, course_id)

    assert (again_seated.status_code, again_seated.json()) == (
        409, {"detail": "Student is already registered for this course"})
    assert (again_waiting.status_code, again_waiting.json()) == (
        409, {"detail": "Student is already on the waitlist for this course"})
    assert factory.enrollment(course_id) == ([seated], [(waiting, 1)])


def test_capacity_and_waitlist_are_per_semester(api_url, factory):
    course_id = factory.course(capacity=1)
    alice, bob, carol = factory.students(3)
    assert register(api_url, alice, course_id, semester_id=1).json() == {"message": "Registered"}

    # semester 2 has its own seat, so Bob gets it and Alice may retake the course
    assert register(api_url, bob, course_id, semester_id=2).json() == {"message": "Registered"}
    assert register(api_url, alice, course_id, semester_id=2).json() == {"message": "Added to Waitlist", "position": 1}
    assert register(api_url, carol, course_id, semester_id=2).json() == {"message": "Added to Waitlist", "position": 2}

    assert factory.enrollment(course_id, semester_id=1) == ([alice], [])
    assert factory.enrollment(course_id, semester_id=2) == ([bob], [(alice, 1), (carol, 2)])


def test_failed_request_releases_the_course_lock(api_url, factory):
    # The 404 is raised *after* the course row is locked. If the transaction
    # were not rolled back, the next request would wait 50 s for that lock.
    course_id = factory.course(capacity=1)
    (student,) = factory.students(1)
    assert register(api_url, student, course_id, semester_id=UNKNOWN_ID).status_code == 404

    r = httpx.post(f"{api_url}/register", json={"student_id": student, "course_id": course_id}, timeout=5)

    assert r.json() == {"message": "Registered"}


# ------------------ DROP ------------------
def test_drop_promotes_first_in_line_and_closes_the_gap(api_url, factory):
    course_id = factory.course(capacity=1)
    seated, first, second, third = factory.students(4)
    for s in (seated, first, second, third):
        register(api_url, s, course_id)

    r = drop(api_url, seated, course_id)

    assert r.json() == {"message": "Dropped. Next waitlisted student promoted", "promoted_student_id": first}
    assert factory.enrollment(course_id) == ([first], [(second, 1), (third, 2)])


def test_drop_with_empty_waitlist_promotes_nobody(api_url, factory):
    course_id = factory.course(capacity=1)
    (student,) = factory.students(1)
    register(api_url, student, course_id)

    assert drop(api_url, student, course_id).json() == {"message": "Dropped", "promoted_student_id": None}
    assert drop(api_url, student, course_id).status_code == 404     # second drop: nothing left
    assert factory.enrollment(course_id) == ([], [])


def test_drop_from_overbooked_course_promotes_nobody(api_url, factory):
    # Legacy data from the old race: 3 students in a 2-seat course.
    course_id = factory.course(capacity=2)
    a, b, c, waiting = factory.students(4)
    for s in (a, b, c):
        factory.insert_enrollment(s, course_id, "Registered")
    factory.insert_enrollment(waiting, course_id, "Waitlisted", position=1)

    r = drop(api_url, a, course_id)

    assert r.json() == {"message": "Dropped", "promoted_student_id": None}   # 2/2: still no free seat
    assert factory.enrollment(course_id) == (sorted([b, c]), [(waiting, 1)])


def test_drop_unknown_course_is_404_and_bad_input_is_400(api_url):
    assert drop(api_url, 1, UNKNOWN_ID).json() == {"detail": "Course not found"}
    r = httpx.request("DELETE", f"{api_url}/drop", json={"student_id": 0, "course_id": 1})
    assert r.status_code == 400
    assert r.json()["detail"].startswith("Invalid student_id:")


# ------------------ READ ENDPOINTS ------------------
def test_list_endpoints_show_enrollments(api_url, factory):
    course_id = factory.course(capacity=1)
    seated, waiting = factory.students(2)
    register(api_url, seated, course_id)
    register(api_url, waiting, course_id)
    course_name = f"Test course {factory.tag}"

    courses = httpx.get(f"{api_url}/courses").json()
    registrations = httpx.get(f"{api_url}/registrations").json()
    waitlist = httpx.get(f"{api_url}/waitlist").json()

    assert {"course_id": course_id, "course_name": course_name, "capacity": 1} in courses
    mine = [r for r in registrations if r["course_name"] == course_name]
    assert [(r["student_name"], r["status"]) for r in mine] == [(f"Test student {factory.tag}-0", "Registered")]
    assert set(mine[0]) == {"registration_id", "student_name", "course_name", "status"}
    assert {"student_name": f"Test student {factory.tag}-1", "course_name": course_name, "position": 1} in waitlist


# ------------------ INFRASTRUCTURE ------------------
def test_database_down_returns_503_json(api_url_without_db):
    for r in (httpx.get(f"{api_url_without_db}/students"),
              httpx.post(f"{api_url_without_db}/register", json={"student_id": 1, "course_id": 1})):
        assert r.status_code == 503
        assert r.json() == {"detail": "Database is unavailable or busy, please try again"}


def preflight(api_url, origin):
    return httpx.options(f"{api_url}/register", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })


def test_cors_allows_the_configured_frontend_origins(api_url):
    for origin in CORS_ORIGINS:
        r = preflight(api_url, origin)
        assert r.headers.get("access-control-allow-origin") == origin
        assert "access-control-allow-credentials" not in r.headers


def test_cors_rejects_other_origins(api_url):
    r = preflight(api_url, "https://evil.example")

    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers

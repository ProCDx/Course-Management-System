"""Concurrency tests: prove the row-locking fix in /register and /drop.

Requests are fired at the same moment with asyncio.gather, each on its own
HTTP connection, so the server handles them in parallel threads with
separate MySQL connections -- the same situation as many students clicking
"Register" at once.
"""
import asyncio
from collections import Counter

import httpx
import pytest


def send_all(api_url, requests):
    """Send (method, path, json) requests concurrently; return responses in order."""
    async def run():
        async with httpx.AsyncClient(base_url=api_url, timeout=60) as client:
            return await asyncio.gather(*(
                client.request(method, path, json=body) for method, path, body in requests
            ))
    return asyncio.run(run())


def register(api_url, student_id, course_id):
    return httpx.post(f"{api_url}/register", json={"student_id": student_id, "course_id": course_id})


def drop(api_url, student_id, course_id):
    return httpx.request("DELETE", f"{api_url}/drop", json={"student_id": student_id, "course_id": course_id})


# Repeated because a race may not show up on every run.
@pytest.mark.parametrize("attempt", range(5))
def test_parallel_registrations_for_last_seat(api_url, factory, attempt):
    course_id = factory.course(capacity=1)
    students = factory.students(20)

    responses = send_all(api_url, [
        ("POST", "/register", {"student_id": s, "course_id": course_id}) for s in students
    ])

    assert [r.status_code for r in responses] == [200] * 20
    bodies = [r.json() for r in responses]
    assert Counter(b["message"] for b in bodies) == {"Registered": 1, "Added to Waitlist": 19}
    assert sorted(b["position"] for b in bodies if "position" in b) == list(range(1, 20))

    registered, waitlist = factory.enrollment(course_id)
    assert len(registered) == 1
    assert [pos for _, pos in waitlist] == list(range(1, 20))      # 1..19, no gaps or duplicates
    assert set(registered) | {sid for sid, _ in waitlist} == set(students)


def test_parallel_duplicate_registrations_by_one_student(api_url, factory):
    course_id = factory.course(capacity=5)
    (student,) = factory.students(1)

    responses = send_all(api_url, [
        ("POST", "/register", {"student_id": student, "course_id": course_id}) for _ in range(10)
    ])

    assert sorted(r.status_code for r in responses) == [200] + [409] * 9
    assert {r.json()["detail"] for r in responses if r.status_code == 409} == {
        "Student is already registered for this course"
    }
    assert factory.enrollment(course_id) == ([student], [])


def test_dropping_unregistered_student_promotes_nobody(api_url, factory):
    course_id = factory.course(capacity=1)
    seated, waiting, outsider = factory.students(3)
    assert register(api_url, seated, course_id).json() == {"message": "Registered"}
    assert register(api_url, waiting, course_id).json()["position"] == 1

    r = drop(api_url, outsider, course_id)

    assert r.status_code == 404
    assert r.json() == {"detail": "Student is not registered or waitlisted for this course"}
    assert factory.enrollment(course_id) == ([seated], [(waiting, 1)])


def test_waitlisted_student_leaving_promotes_nobody(api_url, factory):
    course_id = factory.course(capacity=1)
    seated, first, second = factory.students(3)
    for s in (seated, first, second):
        register(api_url, s, course_id)

    r = drop(api_url, first, course_id)

    assert r.status_code == 200
    assert r.json() == {"message": "Removed from waitlist", "promoted_student_id": None}
    assert factory.enrollment(course_id) == ([seated], [(second, 1)])   # second moved up 2 -> 1


@pytest.mark.parametrize("attempt", range(3))
def test_parallel_drops_and_registrations_keep_queue_order(api_url, factory, attempt):
    course_id = factory.course(capacity=3)
    students = factory.students(14)
    seated, queued, newcomers = students[:3], students[3:9], students[9:]
    for s in seated + queued:                     # sequential: deterministic queue order
        register(api_url, s, course_id)

    responses = send_all(api_url,
        [("DELETE", "/drop", {"student_id": s, "course_id": course_id}) for s in seated]
        + [("POST", "/register", {"student_id": s, "course_id": course_id}) for s in newcomers]
    )

    assert [r.status_code for r in responses] == [200] * 8
    registered, waitlist = factory.enrollment(course_id)
    assert registered == sorted(queued[:3])                        # first three in line got the seats
    assert [sid for sid, _ in waitlist][:3] == queued[3:]          # rest of the old queue still in front
    assert [pos for _, pos in waitlist] == list(range(1, 9))       # newcomers behind them, no gaps

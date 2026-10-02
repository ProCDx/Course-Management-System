# Course Management System

A course registration system with seat limits and an automatic waitlist.
Students register for a course; when it is full they join a numbered
waitlist, and when someone drops, the first student in line is promoted
automatically. It is built to stay correct when many students register for
the last seat at the same moment (see [Concurrency](#concurrency)).

**Stack:** FastAPI · MySQL 8 (InnoDB) · vanilla JavaScript · pytest · GitHub Actions

## Features

- Create students and list courses, registrations and waitlists
- **Register:** take a seat if one is free, otherwise join the waitlist and get a position
- **Drop:** free the seat and promote the first waitlisted student; a waitlisted student who drops leaves the queue and everyone behind moves up
- Capacity and waitlists are **per semester**, so a student can retake a course in a later semester
- Clear errors (`400` bad input, `404` not found, `409` duplicate, `503` database down), always as `{"detail": "..."}`, shown in the UI

## Project structure

```
backend/
  main.py             app setup: CORS, error handlers, routers
  config.py           settings from backend/.env / environment variables
  database.py         get_db(): one connection per request, rollback on error, always closed
  models.py           request body model
  routes/             students.py, courses.py, registration.py, waitlist.py
  schema.sql          tables, keys, constraints and seed data
  migrations/         upgrades for databases created before schema.sql
frontend/             index.html, script.js, style.css
tests/                test_concurrency.py, test_api.py (run against a real server + MySQL)
.github/workflows/    CI: lint + tests on Python 3.11 and 3.14 with MySQL 8.0
```

## Setup

Requirements: **Python 3.11+** and **MySQL 8.0.16+** (CHECK constraints are enforced from 8.0.16).

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt   # backend/requirements.txt is enough to only run the app
```

### 2. Create the database and an app user

As the MySQL root user, create the database and a user that can only read and
write data (no schema changes):

```sql
CREATE DATABASE course_system CHARACTER SET utf8mb4;
CREATE USER 'course_app'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT SELECT, INSERT, UPDATE, DELETE ON course_system.* TO 'course_app'@'localhost';
```

Then load the schema and seed data:

```bash
mysql -u root -p course_system < backend/schema.sql
```

> PowerShell has no `<` redirection. Use `Get-Content backend/schema.sql | mysql -u root -p course_system`,
> or run `SOURCE backend/schema.sql;` inside the `mysql` client.

`schema.sql` **drops and recreates** the tables. If you already have a database
with data from before `schema.sql` existed, back it up and run the migrations
instead (`002_enrollment.sql`, then `003_student_email_and_capacity.sql`; `001` is superseded).

### 3. Configure

```bash
cp backend/.env.example backend/.env    # Windows: copy backend\.env.example backend\.env
```

Fill in `DB_USER`, `DB_PASSWORD` and `DB_NAME`. `backend/.env` is git-ignored;
never commit it. Environment variables override the file.

### 4. Run

```bash
cd backend
uvicorn main:app --reload             # API on http://127.0.0.1:8000, docs at /docs
```

In a second terminal:

```bash
cd frontend
python -m http.server 5500            # open http://127.0.0.1:5500
```

The frontend must be served from an origin listed in `CORS_ORIGINS`
(default: `http://localhost:5500` and `http://127.0.0.1:5500`). Opening
`index.html` directly from disk will not work.

## API

All request bodies are JSON except `/add-student`, which takes form data.
`semester_id` defaults to `1`.

| Method | Path | Body | Success response | Errors |
|---|---|---|---|---|
| `POST` | `/add-student` | form: `name`, `email` | `{"message": "Student Created", "student_id": 7}` | 400, 409 duplicate email |
| `GET` | `/students` | | `[{"student_id", "student_name"}]` | |
| `GET` | `/courses` | | `[{"course_id", "course_name", "capacity"}]` | |
| `POST` | `/register` | `{"student_id", "course_id", "semester_id"}` | `{"message": "Registered"}` or `{"message": "Added to Waitlist", "position": 3}` | 400, 404 course/student/semester, 409 already registered or waitlisted |
| `DELETE` | `/drop` | `{"student_id", "course_id", "semester_id"}` | `{"message": "Dropped. Next waitlisted student promoted", "promoted_student_id": 4}`, `{"message": "Dropped", ...}` or `{"message": "Removed from waitlist", ...}` | 400, 404 course not found / not enrolled |
| `GET` | `/registrations` | | `[{"registration_id", "student_name", "course_name", "status"}]` | |
| `GET` | `/waitlist` | | `[{"student_name", "course_name", "position"}]` | |

Every error is `{"detail": "<message>"}`. Any endpoint returns `503` if the
database is unreachable or a lock wait times out.

## Data model

```
DEPARTMENT 1──* STUDENT 1──* ENROLLMENT *──1 COURSE
                                  *
                                  └──1 SEMESTER
```

`ENROLLMENT` holds one row per student, course and semester, with
`status` = `Registered` or `Waitlisted`. The database itself enforces the rules:

| Constraint | Guarantees |
|---|---|
| `UNIQUE (student_id, course_id, semester_id)` | a student is never registered *and* waitlisted, and never twice |
| `UNIQUE (course_id, semester_id, position)` | no two students share a waitlist position (registered rows have `NULL` position, and UNIQUE allows many NULLs) |
| `CHECK` on status/position | registered rows have no position; waitlisted rows have a position ≥ 1 |
| foreign keys, `UNIQUE (email)`, `CHECK (capacity >= 0)` | no orphan rows, duplicate emails or negative capacity |

## Concurrency

**The bug.** Registration used to read the number of registered students and
then insert a row, as two separate steps. Two requests arriving together could
both read "0 of 1 seats taken" and both insert. Reproduced with 20 parallel
requests on a 1-seat course: up to **20 students registered**, and waitlist
positions were duplicated. Drops had the same problem: concurrent drops all
promoted the same student.

**The fix: lock the course row.**

```sql
SELECT capacity FROM COURSE WHERE course_id = %s FOR UPDATE
```

- `/register` and `/drop` each run in **one transaction**, and their first
  statement locks the course's row. Every other write for that course waits at
  that line until the transaction commits or rolls back, so the "check seats,
  then insert" steps for one course run one request at a time. Other courses are not affected.
- The transaction uses **READ COMMITTED**, so the seat count read after
  waiting for the lock includes whatever the previous request committed.
  Under MySQL's default REPEATABLE READ, any plain `SELECT` before the lock
  freezes an old snapshot, and overbooking returns even with `FOR UPDATE`
  (demonstrated: 20 registered in a 1-seat course).
- Both endpoints take the course lock **first**, so they always lock in the
  same order and cannot deadlock with each other.
- If anything fails, the `get_db` dependency **rolls back**, which releases the
  lock immediately instead of blocking the course for the 50 s lock timeout.
- The UNIQUE and CHECK constraints above are the second line of defence: a
  bug in application code still cannot store an invalid state.

**Proof.** `tests/test_concurrency.py` fires 20 simultaneous registrations at a
1-seat course and checks MySQL for exactly 1 registered and positions 1–19
with no gaps. It also covers duplicate clicks and simultaneous drops and
registrations. Removing `FOR UPDATE` makes most of them fail (8 of 11 in a
typical run), and CI runs them on every pull request.

**Trade-off.** Writes to the *same* course are serialized. That is fine at
this scale. At high volume, an atomic conditional update on a seat counter
(`UPDATE ... SET seats_taken = seats_taken + 1 WHERE seats_taken < capacity`)
holds the lock for one statement instead of a whole transaction.

## Tests

The tests start the real API in a separate process, send real HTTP requests
and check the rows in MySQL. Use a separate database for them:

```bash
mysql -u root -p -e "CREATE DATABASE course_system_test CHARACTER SET utf8mb4;
  GRANT SELECT, INSERT, UPDATE, DELETE ON course_system_test.* TO 'course_app'@'localhost';"
mysql -u root -p course_system_test < backend/schema.sql

DB_NAME=course_system_test pytest -v      # PowerShell: $env:DB_NAME="course_system_test"; pytest -v
```

Run from the repository root. Each test creates and deletes its own courses
and students, so the seed data is never changed.

## Known limitations

- **No authentication:** anyone who can reach the API can register or drop any student.
- The frontend always uses semester 1 and calls `http://127.0.0.1:8000`.
- A course has the same capacity every semester (no separate per-semester course offerings).
- Migrations are plain SQL files, with no tool tracking which ones have run.
- One new database connection per request (no connection pool).

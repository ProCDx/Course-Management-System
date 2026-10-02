-- Migration 002: merge REGISTRATION and WAITLIST into one ENROLLMENT table.
--
-- Why: with two tables, nothing in the database stopped a student from
-- being registered AND waitlisted for the same course. One table with
-- UNIQUE (student_id, course_id, semester_id) makes that impossible.
--
-- Run once against an existing database, with the API stopped:
--   mysqldump -u root -p course_system > backup.sql      # DDL auto-commits: back up first
--   mysql -u root -p course_system < backend/migrations/002_enrollment.sql
--
-- Assumes STUDENT, COURSE and SEMESTER exist with the column names the API
-- uses. Old data is cleaned up on the way in:
--   - duplicate rows for the same student/course/semester are merged
--   - a student found in both tables keeps the registration
--   - waitlist positions are renumbered 1..n per course and semester,
--     keeping the existing order
-- Courses that the old race condition overbooked stay overbooked (the
-- migration cannot choose who loses a seat); nobody is promoted into them
-- until enough students drop. Find them with the query at the end.
--
-- The old tables are renamed, not dropped. Drop them once you are happy:
--   DROP TABLE REGISTRATION_OLD, WAITLIST_OLD;

CREATE TABLE ENROLLMENT (
    enrollment_id INT AUTO_INCREMENT PRIMARY KEY,
    student_id    INT NOT NULL,
    course_id     INT NOT NULL,
    semester_id   INT NOT NULL,
    status        ENUM('Registered', 'Waitlisted') NOT NULL,
    position      INT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_enrollment_student_course_semester
        UNIQUE (student_id, course_id, semester_id),
    CONSTRAINT uq_enrollment_waitlist_position
        UNIQUE (course_id, semester_id, position),
    CONSTRAINT chk_enrollment_position CHECK (
        (status = 'Registered' AND position IS NULL)
        OR (status = 'Waitlisted' AND position IS NOT NULL AND position >= 1)
    ),
    CONSTRAINT fk_enrollment_student
        FOREIGN KEY (student_id) REFERENCES STUDENT (student_id),
    CONSTRAINT fk_enrollment_course
        FOREIGN KEY (course_id) REFERENCES COURSE (course_id),
    CONSTRAINT fk_enrollment_semester
        FOREIGN KEY (semester_id) REFERENCES SEMESTER (semester_id)
);

-- Registrations, one per student/course/semester, oldest first.
INSERT INTO ENROLLMENT (student_id, course_id, semester_id, status, position)
SELECT student_id, course_id, semester_id, 'Registered', NULL
FROM REGISTRATION
GROUP BY student_id, course_id, semester_id
ORDER BY MIN(registration_id);

-- Waitlist entries for students who are not already registered,
-- renumbered 1..n in their existing order.
INSERT INTO ENROLLMENT (student_id, course_id, semester_id, status, position)
SELECT student_id, course_id, semester_id, 'Waitlisted',
       ROW_NUMBER() OVER (
           PARTITION BY course_id, semester_id
           ORDER BY MIN(position), student_id
       )
FROM WAITLIST w
WHERE NOT EXISTS (
    SELECT 1 FROM REGISTRATION r
    WHERE r.student_id = w.student_id
      AND r.course_id = w.course_id
      AND r.semester_id = w.semester_id
)
GROUP BY student_id, course_id, semester_id;

RENAME TABLE REGISTRATION TO REGISTRATION_OLD,
             WAITLIST TO WAITLIST_OLD;

-- Overbooked courses (registered > capacity), if any:
SELECT c.course_id, c.course_name, e.semester_id, c.capacity,
       COUNT(*) AS registered
FROM ENROLLMENT e
JOIN COURSE c ON c.course_id = e.course_id
WHERE e.status = 'Registered'
GROUP BY c.course_id, c.course_name, e.semester_id, c.capacity
HAVING COUNT(*) > c.capacity;

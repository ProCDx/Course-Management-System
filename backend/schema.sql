-- Course Management System: full schema + seed data.
--
-- Creates every table from scratch. It DROPS existing tables first, so only
-- run it on a new or throwaway database:
--   mysql -u root -p course_system < backend/schema.sql
--
-- Have an existing database with data you want to keep? Run the files in
-- backend/migrations/ instead.
--
-- Requires MySQL 8.0.16+ (CHECK constraints are enforced from 8.0.16).

SET NAMES utf8mb4;

DROP TABLE IF EXISTS ENROLLMENT;
DROP TABLE IF EXISTS WAITLIST;      -- pre-ENROLLMENT schema
DROP TABLE IF EXISTS REGISTRATION;  -- pre-ENROLLMENT schema
DROP TABLE IF EXISTS COURSE;
DROP TABLE IF EXISTS STUDENT;
DROP TABLE IF EXISTS SEMESTER;
DROP TABLE IF EXISTS DEPARTMENT;


CREATE TABLE DEPARTMENT (
    department_id   INT AUTO_INCREMENT PRIMARY KEY,
    department_name VARCHAR(100) NOT NULL,
    CONSTRAINT uq_department_name UNIQUE (department_name)
);

CREATE TABLE SEMESTER (
    semester_id   INT AUTO_INCREMENT PRIMARY KEY,
    semester_name VARCHAR(50) NOT NULL,
    CONSTRAINT uq_semester_name UNIQUE (semester_name)
);

CREATE TABLE STUDENT (
    student_id    INT AUTO_INCREMENT PRIMARY KEY,
    student_name  VARCHAR(100) NOT NULL,
    email         VARCHAR(255) NOT NULL,
    department_id INT NOT NULL,
    CONSTRAINT uq_student_email UNIQUE (email),
    CONSTRAINT fk_student_department
        FOREIGN KEY (department_id) REFERENCES DEPARTMENT (department_id)
);

CREATE TABLE COURSE (
    course_id   INT AUTO_INCREMENT PRIMARY KEY,
    course_name VARCHAR(100) NOT NULL,
    capacity    INT NOT NULL,        -- seats per semester
    CONSTRAINT chk_course_capacity CHECK (capacity >= 0)
);

-- One row per student per course per semester. A student is either
-- 'Registered' (has a seat) or 'Waitlisted' (has a queue position), never
-- both: the UNIQUE key makes that impossible at the database level.
-- Promotion from the waitlist is an UPDATE of status, not a move between
-- tables.
CREATE TABLE ENROLLMENT (
    enrollment_id INT AUTO_INCREMENT PRIMARY KEY,
    student_id    INT NOT NULL,
    course_id     INT NOT NULL,
    semester_id   INT NOT NULL,
    status        ENUM('Registered', 'Waitlisted') NOT NULL,
    position      INT NULL,          -- waitlist position (1 = next); NULL when Registered
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_enrollment_student_course_semester
        UNIQUE (student_id, course_id, semester_id),

    -- No two waitlisted students share a position in the same waitlist.
    -- Registered rows have position NULL, and UNIQUE allows many NULLs.
    CONSTRAINT uq_enrollment_waitlist_position
        UNIQUE (course_id, semester_id, position),

    -- "position IS NOT NULL" is required: a CHECK passes when its result
    -- is UNKNOWN, and NULL >= 1 is UNKNOWN.
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


-- ------------------ SEED DATA ------------------
-- POST /add-student puts new students in department 1, and the frontend
-- always registers for semester 1, so both must exist.

INSERT INTO DEPARTMENT (department_id, department_name) VALUES
    (1, 'Computer Science'),
    (2, 'Mathematics');

INSERT INTO SEMESTER (semester_id, semester_name) VALUES
    (1, 'Fall 2026'),
    (2, 'Spring 2027');

INSERT INTO STUDENT (student_id, student_name, email, department_id) VALUES
    (1, 'Alice Sharma', 'alice@example.edu', 1),
    (2, 'Bob Iyer',     'bob@example.edu',   1),
    (3, 'Carol Das',    'carol@example.edu', 2),
    (4, 'Dev Patel',    'dev@example.edu',   1),
    (5, 'Esha Rao',     'esha@example.edu',  2);

INSERT INTO COURSE (course_id, course_name, capacity) VALUES
    (1, 'Database Systems',  2),
    (2, 'Algorithms',        1),
    (3, 'Operating Systems', 3);

-- Database Systems is full (2/2) with two students waiting, so dropping
-- Alice or Bob shows a promotion straight away.
INSERT INTO ENROLLMENT (student_id, course_id, semester_id, status, position) VALUES
    (1, 1, 1, 'Registered', NULL),
    (2, 1, 1, 'Registered', NULL),
    (3, 1, 1, 'Waitlisted', 1),
    (4, 1, 1, 'Waitlisted', 2),
    (4, 2, 1, 'Registered', NULL),
    (5, 3, 1, 'Registered', NULL);

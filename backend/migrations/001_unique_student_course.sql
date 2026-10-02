-- Migration 001: a student can appear at most once per course in
-- REGISTRATION and at most once per course in WAITLIST.
--
-- This is the database-level backstop for the duplicate check in
-- POST /register: even if application code has a bug, MySQL rejects the
-- second row with error 1062 (ER_DUP_ENTRY), which the API turns into 409.
--
-- Run once against an existing database:
--   mysql -u <user> -p course_system < backend/migrations/001_unique_student_course.sql
--
-- The ALTERs fail if duplicates already exist. Find them first with:
--   SELECT student_id, course_id, COUNT(*) FROM REGISTRATION
--   GROUP BY student_id, course_id HAVING COUNT(*) > 1;
--   SELECT student_id, course_id, COUNT(*) FROM WAITLIST
--   GROUP BY student_id, course_id HAVING COUNT(*) > 1;
-- and delete the extra rows by hand before running this file.

ALTER TABLE REGISTRATION
    ADD CONSTRAINT uq_registration_student_course UNIQUE (student_id, course_id);

ALTER TABLE WAITLIST
    ADD CONSTRAINT uq_waitlist_student_course UNIQUE (student_id, course_id);

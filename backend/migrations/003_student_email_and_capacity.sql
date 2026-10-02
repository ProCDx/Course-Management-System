-- Migration 003: constraints that backend/schema.sql has and older
-- databases may lack.
--
--   mysql -u root -p course_system < backend/migrations/003_student_email_and_capacity.sql
--
-- - UNIQUE email: POST /add-student turns a duplicate email into 409.
--   Fails if duplicates already exist. Find them first with:
--     SELECT email, COUNT(*) FROM STUDENT GROUP BY email HAVING COUNT(*) > 1;
-- - capacity >= 0 (CHECK constraints need MySQL 8.0.16+).

ALTER TABLE STUDENT
    ADD CONSTRAINT uq_student_email UNIQUE (email);

ALTER TABLE COURSE
    ADD CONSTRAINT chk_course_capacity CHECK (capacity >= 0);

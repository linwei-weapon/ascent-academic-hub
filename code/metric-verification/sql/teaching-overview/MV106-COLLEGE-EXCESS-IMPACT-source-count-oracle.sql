WITH input_rows AS (
SELECT g.ID AS attempt_id,
       g.STUDENT_ID AS student_id,
       g.COURSE_ID AS course_id,
       g.SEMESTER_ID AS semester_id,
       g.SCORE AS score,
       g.GP AS gpa,
       g.PUBLISHED AS is_published,
       g.PASSED AS is_pass,
       g.GRADE_STATUS AS grade_status,
       g.RETAKE AS is_retake,
       g.PUBLISHED_DATE_TIME AS published_date_time,
       g.INPUT_DATE_TIME AS input_date_time,
       s.DEPARTMENT_ID AS organization_id,
       s.MAJOR_ID AS major_id,
       s.GRADE AS entry_grade
FROM GRADE g
JOIN STUDENT s ON s.ID = g.STUDENT_ID
WHERE 1 = 1
  AND 1 = 1
  AND 1 = 1
  AND 1 = 1
  AND g.SEMESTER_ID = :semester_id
  AND 1 = 1
)
SELECT COUNT(*) AS matched_records,
       COUNT(CASE WHEN is_published = 1 AND is_pass IN (0, 1) THEN 1 END) AS candidate_valid_attempts,
       COUNT(DISTINCT CASE WHEN is_published = 1 AND is_pass IN (0, 1) THEN student_id END) AS candidate_valid_students
FROM input_rows

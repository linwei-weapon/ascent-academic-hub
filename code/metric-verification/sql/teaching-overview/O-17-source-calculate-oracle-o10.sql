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
), valid_rows AS (
  SELECT * FROM input_rows WHERE is_published = 1 AND is_pass IN (0, 1)
), rate_rows AS (SELECT organization_id, COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END) AS failed_students, COUNT(DISTINCT student_id) AS valid_students FROM valid_rows GROUP BY organization_id), scope_total AS (SELECT COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END) AS failed_students, COUNT(DISTINCT student_id) AS valid_students FROM valid_rows), deviations AS (
SELECT r.organization_id, r.valid_students, 100.0 * r.failed_students / NULLIF(r.valid_students, 0) AS organization_value,
       100.0 * t.failed_students / NULLIF(t.valid_students, 0) AS scope_value,
       100.0 * r.failed_students / NULLIF(r.valid_students, 0) - 100.0 * t.failed_students / NULLIF(t.valid_students, 0) AS deviation_pp
FROM rate_rows r CROSS JOIN scope_total t WHERE :base_metric_id = 'O-10'), impacts AS (
SELECT deviations.*, CASE WHEN deviation_pp > 0 THEN deviation_pp * valid_students / 100.0 ELSE 0 END AS estimated_excess_students FROM deviations)
SELECT impacts.*, deviation_pp AS candidate_deviation_pp, RANK() OVER (ORDER BY estimated_excess_students DESC) AS impact_rank
FROM impacts ORDER BY estimated_excess_students DESC, organization_id

WITH input_rows AS (
SELECT g.attempt_id AS attempt_id,
       g.student_id AS student_id,
       g.course_id AS course_id,
       g.semester_id AS semester_id,
       g.score AS score,
       g.gpa AS gpa,
       g.is_published AS is_published,
       g.is_pass AS is_pass,
       g.grade_status AS grade_status,
       g.is_retake AS is_retake,
       g.published_date_time AS published_date_time,
       g.input_date_time AS input_date_time,
       s.organization_id AS organization_id,
       s.major_id AS major_id,
       s.entry_grade AS entry_grade,
       g.source_row_no AS source_row_no,
       g.batch_id AS batch_id,
       g.id AS fact_row_id,
       g.is_void AS is_void,
       g.attempt_type AS attempt_type,
       g.credits AS attempt_credits,
       g.publish_status AS publish_status,
       g.exam_status AS exam_status
FROM ACT_GRADE_ATTEMPT g
JOIN ACT_STUDENT s ON s.student_id = g.student_id
WHERE 1 = 1
  AND 1 = 1
  AND 1 = 1
  AND 1 = 1
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND g.semester_id = :semester_id
  AND 1 = 1
  AND g.batch_id = :grade_batch_id
  AND g.source = 'real'
), valid_rows AS (
  SELECT * FROM input_rows WHERE is_published = 1 AND is_pass IN (0, 1) AND is_void = 0
), rate_rows AS (SELECT organization_id, COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END) AS failed_students, COUNT(DISTINCT student_id) AS valid_students FROM valid_rows WHERE organization_id IN (SELECT organization_id FROM ACT_ORGANIZATION WHERE is_college = 1 AND source = 'real') GROUP BY organization_id), scope_total AS (SELECT COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END) AS failed_students, COUNT(DISTINCT student_id) AS valid_students FROM valid_rows), deviations AS (
SELECT r.organization_id, r.valid_students, 100.0 * r.failed_students / NULLIF(r.valid_students, 0) AS organization_value,
       100.0 * t.failed_students / NULLIF(t.valid_students, 0) AS scope_value,
       100.0 * r.failed_students / NULLIF(r.valid_students, 0) - 100.0 * t.failed_students / NULLIF(t.valid_students, 0) AS deviation_pp
FROM rate_rows r CROSS JOIN scope_total t WHERE :base_metric_id = 'O-10'), impacts AS (
SELECT deviations.*, CASE WHEN deviation_pp > 0 THEN deviation_pp * valid_students / 100.0 ELSE 0 END AS estimated_excess_students FROM deviations)
SELECT impacts.*, deviation_pp AS candidate_deviation_pp, RANK() OVER (ORDER BY estimated_excess_students DESC) AS impact_rank
FROM impacts ORDER BY estimated_excess_students DESC, organization_id

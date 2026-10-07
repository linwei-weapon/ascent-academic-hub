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
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND g.semester_id = :semester_id
  AND (:course_id IS NULL OR g.course_id = :course_id)
  AND g.batch_id = :grade_batch_id
  AND g.source = 'real'
), valid_rows AS (
  SELECT * FROM input_rows WHERE is_published = 1 AND is_pass IN (0, 1) AND is_void = 0
)
SELECT COUNT(CASE WHEN is_pass = 0 THEN 1 END) AS candidate_metric_value, COUNT(*) AS input_records FROM valid_rows

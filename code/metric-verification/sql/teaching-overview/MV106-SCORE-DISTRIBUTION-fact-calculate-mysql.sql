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
  AND g.course_id = :course_id
  AND g.batch_id = :grade_batch_id
  AND g.source = 'real'
), valid_rows AS (
  SELECT * FROM input_rows WHERE is_published = 1 AND is_pass IN (0, 1) AND is_void = 0
)
, bucket_rows AS (
  SELECT CASE WHEN score < 60 THEN '0-59' WHEN score < 70 THEN '60-69' WHEN score < 80 THEN '70-79' WHEN score < 90 THEN '80-89' ELSE '90-100' END AS bucket
  FROM valid_rows WHERE score BETWEEN 0 AND 100
)
SELECT bucket, COUNT(*) AS attempt_count,
       100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0) AS share_percent
FROM bucket_rows GROUP BY bucket ORDER BY bucket

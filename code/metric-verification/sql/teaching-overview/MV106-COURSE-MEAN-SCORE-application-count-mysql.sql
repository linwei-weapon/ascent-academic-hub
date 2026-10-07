WITH input_rows AS (
SELECT a.course_id, a.semester_id, a.avg_score, a.source
FROM AGG_COURSE_TERM a
WHERE a.course_id = :course_id
  AND a.source = 'real'
  AND a.semester_id = :semester_id
)
SELECT COUNT(*) AS matched_records FROM input_rows

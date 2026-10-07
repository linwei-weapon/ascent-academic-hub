WITH input_rows AS (
SELECT a.id, a.college_id, a.semester_id, a.student_count, a.avg_gpa, a.pass_rate, a.alert_rate, a.is_published, a.version, a.calculated_at
FROM AGG_COLLEGE_TERM a
WHERE (:college_id IS NULL OR a.college_id = :college_id)
  AND a.semester_id IN (:semester_id, :previous_semester_id)
)
SELECT * FROM input_rows
ORDER BY id
LIMIT 100

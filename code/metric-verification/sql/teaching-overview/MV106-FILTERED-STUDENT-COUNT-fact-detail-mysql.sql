WITH input_rows AS (
SELECT s.student_id AS student_id, s.organization_id AS organization_id, s.has_xue_ji AS has_xue_ji, s.in_school AS in_school, s.std_status AS student_status_name
FROM ACT_STUDENT s
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
)
SELECT * FROM input_rows
ORDER BY student_id
LIMIT 100

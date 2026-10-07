WITH input_rows AS (
SELECT e.event_id AS event_id, e.student_id AS student_id, e.status AS status, e.effective_date AS effective_date
FROM ACT_STUDENT_STATUS_EVENT e
JOIN ACT_STUDENT s ON s.student_id = e.student_id
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND e.batch_id = :event_batch_id
  AND e.source = 'real'
)
SELECT * FROM input_rows
ORDER BY student_id, effective_date, event_id
LIMIT 100

WITH input_rows AS (
SELECT f.id, f.alert_id, f.followup_type, f.followup_at, a.student_id AS student_id
FROM ACT_ALERT_FOLLOWUP f
JOIN ACT_ALERT a ON a.alert_id = f.alert_id
JOIN ACT_STUDENT s ON s.student_id = a.student_id
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND a.batch_id = :alert_batch_id
  AND a.source = 'real'
)
SELECT COUNT(*) AS matched_records FROM input_rows

WITH input_rows AS (
SELECT a.id, a.alert_id, a.student_id, a.rule_id, a.rule_code, a.semester_id, a.alert_level, a.is_active, a.is_resolved, a.workflow_status, a.created_at, a.updated_at, a.batch_id, a.metric_value, a.threshold_value, a.alert_detail
FROM ACT_ALERT a
JOIN ACT_STUDENT s ON s.student_id = a.student_id
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND a.source = 'real'
  AND a.student_id = :student_id
)
SELECT COUNT(DISTINCT rule_code) AS candidate_all_history_rules FROM input_rows

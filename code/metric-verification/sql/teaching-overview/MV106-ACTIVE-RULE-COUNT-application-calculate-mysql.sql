WITH input_rows AS (
SELECT a.alert_id, a.student_id, a.rule_id, a.rule_code, a.semester_id, a.is_active, a.is_resolved, a.alert_level, a.metric_value, a.threshold_value, a.source, a.batch_id, r.enabled, r.version AS rule_version
FROM ACT_ALERT a
JOIN ACT_STUDENT s ON s.student_id = a.student_id
LEFT JOIN SYS_ALERT_RULE r ON r.rule_code = a.rule_code
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND a.source = 'real'
  AND a.batch_id = :alert_batch_id
  AND a.semester_id = :semester_id
)
SELECT COUNT(*) AS candidate_active_records, COUNT(DISTINCT rule_id) AS candidate_active_rules FROM input_rows WHERE is_active = 1 AND enabled = 1

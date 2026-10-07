WITH input_rows AS (
SELECT a.course_id, a.semester_id, a.course_group, a.group_basis, a.retake_attempts, a.retake_pass, a.retake_pass_rate, a.rule_version, a.calculated_at, a.source
FROM AGG_COURSE_PASS_STAT a
WHERE a.semester_id = :semester_id
  AND (:course_id IS NULL OR a.course_id = :course_id)
  AND a.source = 'derived'
  AND a.rule_version = :rule_version
)
SELECT COALESCE(SUM(retake_pass), 0) AS numerator, COALESCE(SUM(retake_attempts), 0) AS denominator,
       100.0 * SUM(retake_pass) / NULLIF(SUM(retake_attempts), 0) AS candidate_metric_value FROM input_rows

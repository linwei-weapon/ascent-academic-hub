WITH input_rows AS (
SELECT a.course_id, a.semester_id, a.course_group, a.group_basis, a.first_attempts, a.first_pass, a.first_pass_rate, a.rule_version, a.calculated_at, a.source
FROM AGG_COURSE_PASS_STAT a
WHERE a.semester_id = :semester_id
  AND (:course_id IS NULL OR a.course_id = :course_id)
  AND a.source = 'derived'
  AND a.rule_version = :rule_version
)
SELECT * FROM input_rows
ORDER BY course_id, semester_id
LIMIT 100

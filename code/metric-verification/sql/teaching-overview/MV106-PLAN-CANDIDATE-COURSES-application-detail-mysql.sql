WITH input_rows AS (
SELECT a.id, a.student_id, a.course_id, a.plan_id, a.module_name, a.requirement_type, a.status, a.score, a.is_pass, a.earned_credits, a.source, a.batch_id
FROM ACT_STUDENT_PLAN_COURSE_STATUS a
JOIN ACT_STUDENT s ON s.student_id = a.student_id
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND ((:result_batch_id IS NULL AND a.batch_id IS NULL) OR a.batch_id = :result_batch_id)
  AND a.source = 'growth-v1'
)
SELECT * FROM input_rows
ORDER BY student_id, id
LIMIT 100

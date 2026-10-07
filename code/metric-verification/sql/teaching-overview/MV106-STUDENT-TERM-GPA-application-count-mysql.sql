WITH input_rows AS (
SELECT a.id, a.student_id, a.semester_id, a.term_gpa, a.cumulative_gpa, a.term_credits, a.cumulative_credits, a.pass_count, a.fail_count, a.is_published, a.version, a.calculated_at
FROM AGG_STUDENT_TERM_GROWTH a
JOIN ACT_STUDENT s ON s.student_id = a.student_id
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND a.semester_id = :semester_id
)
SELECT COUNT(*) AS matched_records FROM input_rows

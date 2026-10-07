WITH input_rows AS (
SELECT a.id, a.student_id, a.course_id, a.semester_id, a.score, a.gpa, a.is_pass, a.is_retake, a.attempt_count, a.is_published, a.version, a.calculated_at
FROM AGG_STUDENT_COURSE_OUTCOME a
JOIN ACT_STUDENT s ON s.student_id = a.student_id
WHERE (:organization_id IS NULL OR s.organization_id = :organization_id)
  AND (:major_id IS NULL OR s.major_id = :major_id)
  AND (:grade IS NULL OR s.entry_grade = :grade)
  AND (:student_id IS NULL OR s.student_id = :student_id)
  AND s.batch_id = :student_batch_id
  AND s.source = 'real'
  AND a.course_id = :course_id
  AND a.semester_id = :semester_id
)
SELECT COUNT(*) AS matched_records FROM input_rows

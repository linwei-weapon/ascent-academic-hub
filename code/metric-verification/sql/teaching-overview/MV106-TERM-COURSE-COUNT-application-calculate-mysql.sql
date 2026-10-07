WITH input_rows AS (
SELECT a.id, a.semester_id, a.organization_id, a.course_id, a.course_category, a.course_type, a.lesson_count, a.enrolled_total, a.teacher_count, a.is_published, a.version, a.calculated_at
FROM AGG_COURSE_OFFERING a
WHERE a.semester_id = :semester_id
  AND (:organization_id IS NULL OR a.organization_id = :organization_id)
)
SELECT COUNT(DISTINCT course_id) AS candidate_metric_value FROM input_rows

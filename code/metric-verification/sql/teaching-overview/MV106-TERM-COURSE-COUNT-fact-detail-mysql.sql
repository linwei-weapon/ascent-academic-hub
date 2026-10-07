WITH input_rows AS (
SELECT l.lesson_id AS lesson_id, l.course_id AS course_id, l.semester_id AS semester_id, l.open_department_id AS open_department_id
FROM ACT_TEACHING_LESSON l
WHERE l.semester_id = :semester_id
  AND (:organization_id IS NULL OR l.open_department_id = :organization_id)
  AND l.batch_id = :lesson_batch_id
  AND l.source = 'real'
)
SELECT * FROM input_rows
ORDER BY lesson_id
LIMIT 100

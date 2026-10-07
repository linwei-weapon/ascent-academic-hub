WITH input_rows AS (
SELECT l.ID AS lesson_id, l.COURSE_ID AS course_id, l.SEMESTER_ID AS semester_id, l.OPEN_DEPARTMENT_ID AS open_department_id
FROM LESSON l
WHERE l.SEMESTER_ID = :semester_id
  AND (:organization_id IS NULL OR l.OPEN_DEPARTMENT_ID = :organization_id)
)
SELECT * FROM input_rows
ORDER BY lesson_id
LIMIT 100

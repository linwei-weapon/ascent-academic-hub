WITH input_rows AS (
SELECT t.staff_id AS staff_id, t.organization_id AS organization_id, t.hire_type AS hire_type, t.teaching AS teaching, t.is_on_job AS is_on_job
FROM ACT_STAFF t
WHERE (:organization_id IS NULL OR t.organization_id = :organization_id)
  AND t.batch_id = :teacher_batch_id
  AND t.source = 'real'
)
SELECT * FROM input_rows
ORDER BY staff_id
LIMIT 100

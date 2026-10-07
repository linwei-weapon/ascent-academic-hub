WITH input_rows AS (
SELECT t.ID AS staff_id, t.DEPARTMENT_ID AS organization_id, t.HIRE_TYPE AS hire_type, t.TEACHING AS teaching, t.ZAI_ZHI AS is_on_job
FROM TEACHER t
WHERE (:organization_id IS NULL OR t.DEPARTMENT_ID = :organization_id)
)
SELECT * FROM input_rows
ORDER BY staff_id
FETCH FIRST 100 ROWS ONLY

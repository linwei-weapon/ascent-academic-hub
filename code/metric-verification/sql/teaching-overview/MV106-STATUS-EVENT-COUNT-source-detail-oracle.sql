WITH input_rows AS (
SELECT e.ID AS event_id, e.STUDENT_ID AS student_id, e.STATUS AS status, e.EFFECTIVE_DATE_TIME AS effective_date
FROM STD_ALTERATION e
JOIN STUDENT s ON s.ID = e.STUDENT_ID
WHERE (:organization_id IS NULL OR s.DEPARTMENT_ID = :organization_id)
  AND (:major_id IS NULL OR s.MAJOR_ID = :major_id)
  AND (:grade IS NULL OR s.GRADE = :grade)
  AND (:student_id IS NULL OR s.ID = :student_id)
)
SELECT * FROM input_rows
ORDER BY student_id, effective_date, event_id
FETCH FIRST 100 ROWS ONLY

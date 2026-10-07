WITH input_rows AS (
SELECT s.ID AS student_id, s.DEPARTMENT_ID AS organization_id, s.HAS_XUE_JI AS has_xue_ji, s.IN_SCHOOL AS in_school, s.ZAI_JI AS zai_ji, s.STD_STATUS_ID AS student_status_code
FROM STUDENT s
WHERE (:organization_id IS NULL OR s.DEPARTMENT_ID = :organization_id)
  AND (:major_id IS NULL OR s.MAJOR_ID = :major_id)
  AND (:grade IS NULL OR s.GRADE = :grade)
  AND (:student_id IS NULL OR s.ID = :student_id)
)
SELECT COUNT(DISTINCT student_id) AS candidate_metric_value FROM input_rows WHERE zai_ji = 1

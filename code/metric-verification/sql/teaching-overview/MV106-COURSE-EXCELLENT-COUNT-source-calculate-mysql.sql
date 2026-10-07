WITH input_rows AS (
SELECT g.ID AS attempt_id,
       g.STUDENT_ID AS student_id,
       g.COURSE_ID AS course_id,
       g.SEMESTER_ID AS semester_id,
       g.SCORE AS score,
       g.GP AS gpa,
       g.PUBLISHED AS is_published,
       g.PASSED AS is_pass,
       g.GRADE_STATUS AS grade_status,
       g.RETAKE AS is_retake,
       g.PUBLISHED_DATE_TIME AS published_date_time,
       g.INPUT_DATE_TIME AS input_date_time,
       s.DEPARTMENT_ID AS organization_id,
       s.MAJOR_ID AS major_id,
       s.GRADE AS entry_grade
FROM GRADE g
JOIN STUDENT s ON s.ID = g.STUDENT_ID
WHERE (:organization_id IS NULL OR s.DEPARTMENT_ID = :organization_id)
  AND (:major_id IS NULL OR s.MAJOR_ID = :major_id)
  AND (:grade IS NULL OR s.GRADE = :grade)
  AND (:student_id IS NULL OR s.ID = :student_id)
  AND g.SEMESTER_ID = :semester_id
  AND g.COURSE_ID = :course_id
), valid_rows AS (
  SELECT * FROM input_rows WHERE is_published = 1 AND is_pass IN (0, 1)
)
SELECT COUNT(CASE WHEN score >= 90 THEN 1 END) AS candidate_metric_value, COUNT(CASE WHEN score > 100 THEN 1 END) AS above_percentage_range FROM valid_rows

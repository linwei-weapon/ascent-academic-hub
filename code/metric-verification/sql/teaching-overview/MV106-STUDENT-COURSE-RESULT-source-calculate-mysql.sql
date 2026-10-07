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
  AND g.STUDENT_ID = :student_id
), valid_rows AS (
  SELECT * FROM input_rows WHERE is_published = 1 AND is_pass IN (0, 1)
), ranked AS (
  SELECT valid_rows.*, ROW_NUMBER() OVER (
    PARTITION BY student_id, course_id
    ORDER BY CASE WHEN published_date_time IS NULL THEN 1 ELSE 0 END, published_date_time DESC,
             CASE WHEN input_date_time IS NULL THEN 1 ELSE 0 END, input_date_time DESC, attempt_id DESC
  ) AS result_rank
  FROM valid_rows
), latest_rows AS (SELECT * FROM ranked WHERE result_rank = 1)
SELECT student_id, course_id, score AS candidate_course_score, gpa AS candidate_course_gp, attempt_id FROM latest_rows ORDER BY student_id, course_id

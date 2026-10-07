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
       s.GRADE AS entry_grade,
       c.CREDITS AS credits,
       c.CALCULATE_GP AS calculate_gp
FROM GRADE g
JOIN STUDENT s ON s.ID = g.STUDENT_ID
LEFT JOIN COURSE c ON c.ID = g.COURSE_ID
WHERE (:organization_id IS NULL OR s.DEPARTMENT_ID = :organization_id)
  AND (:major_id IS NULL OR s.MAJOR_ID = :major_id)
  AND (:grade IS NULL OR s.GRADE = :grade)
  AND (:student_id IS NULL OR s.ID = :student_id)
  AND (:course_id IS NULL OR g.COURSE_ID = :course_id)
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
), latest_rows AS (SELECT * FROM ranked WHERE result_rank = 1), passed_courses AS (SELECT student_id, course_id, MAX(credits) AS credits FROM valid_rows WHERE is_pass = 1 GROUP BY student_id, course_id), history_summary AS (SELECT student_id, SUM(credits) AS profile_ever_passed_value FROM passed_courses GROUP BY student_id), current_summary AS (SELECT student_id, SUM(credits) AS growth_current_passed_value FROM latest_rows WHERE is_pass = 1 GROUP BY student_id), students AS (SELECT DISTINCT student_id FROM valid_rows)
SELECT s.student_id, COALESCE(h.profile_ever_passed_value, 0) AS profile_ever_passed_value, COALESCE(c.growth_current_passed_value, 0) AS growth_current_passed_value
FROM students s LEFT JOIN history_summary h ON h.student_id=s.student_id LEFT JOIN current_summary c ON c.student_id=s.student_id ORDER BY s.student_id

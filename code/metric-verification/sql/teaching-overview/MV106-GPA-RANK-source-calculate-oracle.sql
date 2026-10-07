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
  AND g.SEMESTER_ID = :semester_id
  AND (:course_id IS NULL OR g.COURSE_ID = :course_id)
), valid_rows AS (
  SELECT * FROM input_rows WHERE is_published = 1 AND is_pass IN (0, 1)
), student_gpa AS (
  SELECT organization_id, student_id, SUM(gpa * credits) / NULLIF(SUM(credits), 0) AS term_gpa
  FROM valid_rows WHERE gpa IS NOT NULL AND credits > 0 GROUP BY organization_id, student_id
), college_gpa AS (
  SELECT organization_id, AVG(term_gpa) AS average_student_gpa, COUNT(*) AS students_with_gpa
  FROM student_gpa GROUP BY organization_id
)
SELECT organization_id, average_student_gpa, students_with_gpa,
       RANK() OVER (ORDER BY average_student_gpa DESC) AS candidate_rank, COUNT(*) OVER () AS comparable_colleges
FROM college_gpa ORDER BY candidate_rank, organization_id

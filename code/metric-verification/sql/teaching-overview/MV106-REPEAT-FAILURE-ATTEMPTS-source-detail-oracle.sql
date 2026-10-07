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
       cm.course_code, cm.course_name, cm.course_metadata_rows, sm.semester_name, sm.semester_start_date, sm.semester_metadata_rows, g.STATE AS source_state, mc.makeup_component_count
FROM GRADE g
JOIN STUDENT s ON s.ID = g.STUDENT_ID
LEFT JOIN (SELECT dc.ID AS course_key, CASE WHEN COUNT(DISTINCT dc.CODE) = 1 THEN MIN(dc.CODE) END AS course_code, CASE WHEN COUNT(DISTINCT dc.NAME_ZH) = 1 THEN MIN(dc.NAME_ZH) END AS course_name, COUNT(*) AS course_metadata_rows FROM COURSE dc GROUP BY dc.ID) cm ON cm.course_key = g.COURSE_ID
LEFT JOIN (SELECT tm.ID AS semester_key, CASE WHEN COUNT(DISTINCT tm.NAME_ZH) = 1 THEN MIN(tm.NAME_ZH) END AS semester_name, CASE WHEN COUNT(DISTINCT tm.START_DATE) = 1 THEN MIN(tm.START_DATE) END AS semester_start_date, COUNT(*) AS semester_metadata_rows FROM SEMESTER tm GROUP BY tm.ID) sm ON sm.semester_key = g.SEMESTER_ID
LEFT JOIN (SELECT mg.GRADE_ID AS grade_key, COUNT(*) AS makeup_component_count FROM MAKEUP_GRADE mg GROUP BY mg.GRADE_ID) mc ON mc.grade_key = g.ID
WHERE (:organization_id IS NULL OR s.DEPARTMENT_ID = :organization_id)
  AND (:major_id IS NULL OR s.MAJOR_ID = :major_id)
  AND (:grade IS NULL OR s.GRADE = :grade)
  AND (:student_id IS NULL OR s.ID = :student_id)
  AND 1 = 1
  AND g.STUDENT_ID = :student_id
)
SELECT * FROM input_rows
ORDER BY CASE WHEN semester_start_date IS NULL THEN 1 ELSE 0 END, semester_start_date DESC, CASE WHEN score IS NULL THEN 1 ELSE 0 END, score ASC, semester_id DESC, attempt_id
FETCH FIRST 100 ROWS ONLY

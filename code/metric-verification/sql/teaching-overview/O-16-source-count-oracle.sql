WITH input_rows AS (
SELECT s.ID AS student_id, s.PROGRAM_ID AS student_program_id, p.ID AS program_id, p.ENABLED AS program_enabled, p.AUDIT_STATE AS program_audit_state, cp.ID AS course_plan_id, cp.BEGIN_SEMESTER_ID AS begin_semester_id, cm.ID AS module_id, cm.PARENT_COURSE_MODULE_ID AS parent_module_id, cm.REQUIRED_CREDITS AS required_credits, cm.REQUIRED_COURSE_NUM AS required_course_num, cm.REQUIRED_SUB_MODULE_NUM AS required_sub_module_num, pc.ID AS plan_course_id, pc.COURSE_ID AS course_id, pc.COMPULSORY AS compulsory, c.CREDITS AS course_credits
FROM STUDENT s
LEFT JOIN PROGRAM p ON p.ID = s.PROGRAM_ID
LEFT JOIN COURSE_PLAN cp ON cp.ID = p.COURSE_PLAN_ID
LEFT JOIN COURSE_MODULE cm ON cm.COURSE_PLAN_ID = cp.ID
LEFT JOIN PLAN_COURSE pc ON pc.COURSE_MODULE_ID = cm.ID
LEFT JOIN COURSE c ON c.ID = pc.COURSE_ID
WHERE (:organization_id IS NULL OR s.DEPARTMENT_ID = :organization_id)
  AND (:major_id IS NULL OR s.MAJOR_ID = :major_id)
  AND (:grade IS NULL OR s.GRADE = :grade)
  AND (:student_id IS NULL OR s.ID = :student_id)
  AND s.ID = :student_id
)
SELECT COUNT(*) AS matched_records FROM input_rows

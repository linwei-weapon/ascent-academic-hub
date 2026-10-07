WITH input_rows AS (
SELECT a.id, a.semester_id, a.college_id, a.major_id, a.grade, a.gpa_min, a.gpa_max, a.gpa_avg, a.gpa_median, a.gpa_stddev, a.distribution, a.is_published, a.version, a.calculated_at
FROM AGG_GPA_DIST a
WHERE a.semester_id = :semester_id
  AND (:college_id IS NULL OR a.college_id = :college_id)
  AND (:major_id IS NULL OR a.major_id = :major_id)
  AND (:grade IS NULL OR a.grade = :grade)
)
SELECT COUNT(*) AS matched_records FROM input_rows

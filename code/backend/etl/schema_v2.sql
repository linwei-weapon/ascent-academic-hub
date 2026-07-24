PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS data_batch (
    batch_id TEXT PRIMARY KEY,
    source_code TEXT NOT NULL,
    source_file TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    collected_at TEXT,
    ingested_at TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    quality_status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(source_code, file_hash)
);

CREATE TABLE IF NOT EXISTS code_mapping (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_code TEXT NOT NULL,
    canonical_code TEXT,
    mapping_status TEXT NOT NULL DEFAULT 'pending',
    note TEXT,
    UNIQUE(domain, source_system, source_code)
);

CREATE TABLE IF NOT EXISTS dim_organization (
    organization_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    organization_type TEXT,
    status TEXT,
    valid_from TEXT,
    valid_to TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS dim_semester (
    semester_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    academic_year TEXT,
    season TEXT,
    start_date TEXT,
    end_date TEXT,
    status TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS dim_course (
    course_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    nature TEXT,
    credits REAL,
    total_hours REAL,
    theory_hours REAL,
    experiment_hours REAL,
    practice_hours REAL,
    assessment_type TEXT,
    organization_id TEXT,
    status TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS dim_student (
    student_id TEXT PRIMARY KEY,
    display_name TEXT,
    gender TEXT,
    entry_grade INTEGER,
    education_level TEXT,
    organization_id TEXT,
    major_code TEXT,
    major_name TEXT,
    class_code TEXT,
    plan_id TEXT,
    student_status TEXT,
    valid_from TEXT,
    valid_to TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS dim_staff (
    staff_id TEXT PRIMARY KEY,
    display_name TEXT,
    organization_id TEXT,
    staff_type TEXT,
    title TEXT,
    status TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS dim_building (
    building_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    campus TEXT,
    status TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS dim_room (
    room_id TEXT PRIMARY KEY,
    building_id TEXT,
    name TEXT,
    room_type TEXT,
    seats INTEGER,
    is_virtual INTEGER NOT NULL DEFAULT 0,
    is_available INTEGER NOT NULL DEFAULT 1,
    valid_from TEXT,
    valid_to TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS dim_period (
    period_id TEXT PRIMARY KEY,
    name TEXT,
    major_period TEXT,
    start_time TEXT,
    end_time TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS curriculum_plan (
    plan_id TEXT PRIMARY KEY,
    plan_name TEXT NOT NULL,
    grade INTEGER,
    major_code TEXT,
    major_name TEXT,
    total_credits REAL,
    required_min_credits REAL,
    elective_min_credits REAL,
    practice_min_credits REAL,
    degree_requirement TEXT,
    credit_rule_source_file TEXT,
    version TEXT,
    status TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS curriculum_plan_course (
    plan_course_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    module TEXT,
    requirement_type TEXT,
    credits REAL,
    suggested_term TEXT,
    offered_season TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(plan_id, course_id, module, suggested_term)
);

CREATE TABLE IF NOT EXISTS curriculum_plan_module_requirement (
    module_requirement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    parent_module TEXT,
    module_name TEXT NOT NULL,
    requirement_type TEXT,
    minimum_credits REAL NOT NULL,
    minimum_courses INTEGER,
    raw_hierarchy TEXT,
    source_file TEXT,
    source_table INTEGER,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(plan_id, module_name, minimum_credits, source_table)
);

-- 培养方案正文中的培养目标。保留原文与来源定位，避免把统计指标误作培养目标。
CREATE TABLE IF NOT EXISTS curriculum_plan_goal (
    goal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    goal_no INTEGER NOT NULL,
    goal_text TEXT NOT NULL,
    source_file TEXT,
    source_section TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(plan_id, goal_no)
);

-- 各专业方案自己的毕业要求；不同专业条数不固定，不能套用通用 12 条模板。
CREATE TABLE IF NOT EXISTS curriculum_graduation_requirement (
    requirement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    requirement_no INTEGER NOT NULL,
    requirement_title TEXT,
    requirement_text TEXT NOT NULL,
    source_file TEXT,
    source_section TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(plan_id, requirement_no)
);

-- 仅接收来源中明确给出的指标点。当前原始方案未提供时保持为空，不自动推演。
CREATE TABLE IF NOT EXISTS curriculum_requirement_indicator (
    indicator_id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL,
    indicator_code TEXT NOT NULL,
    indicator_text TEXT NOT NULL,
    source_file TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(requirement_id, indicator_code)
);

-- 课程对毕业要求/指标点的支撑关系。只有取得正式矩阵后才可计算达成度。
CREATE TABLE IF NOT EXISTS curriculum_course_requirement_mapping (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    requirement_id INTEGER NOT NULL,
    indicator_id INTEGER,
    support_level TEXT,
    weight REAL,
    source_file TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(plan_id, course_id, requirement_id, indicator_id)
);

CREATE TABLE IF NOT EXISTS student_plan_assignment (
    student_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    assignment_reason TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY(student_id, plan_id, valid_from)
);

CREATE TABLE IF NOT EXISTS teaching_lesson (
    lesson_id TEXT PRIMARY KEY,
    source_lesson_code TEXT NOT NULL,
    semester_id TEXT NOT NULL,
    course_id TEXT,
    course_name TEXT,
    organization_id TEXT,
    capacity INTEGER,
    enrolled INTEGER,
    total_hours REAL,
    theory_hours REAL,
    experiment_hours REAL,
    practice_hours REAL,
    student_grade TEXT,
    majors_text TEXT,
    classes_text TEXT,
    schedule_text TEXT,
    location_text TEXT,
    status TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(source_lesson_code, semester_id)
);

CREATE TABLE IF NOT EXISTS lesson_teacher (
    lesson_id TEXT NOT NULL,
    staff_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'teacher',
    workload_hours REAL,
    source TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY(lesson_id, staff_id, role)
);

CREATE TABLE IF NOT EXISTS course_meeting (
    meeting_id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL,
    week_no INTEGER,
    week_pattern TEXT,
    weekday INTEGER,
    period_id TEXT,
    period_start INTEGER,
    period_end INTEGER,
    room_id TEXT,
    meeting_date TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    raw_schedule TEXT,
    source TEXT NOT NULL DEFAULT 'derived'
);

CREATE TABLE IF NOT EXISTS grade_attempt (
    attempt_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    course_name TEXT,
    replaced_course_id TEXT,
    replaced_course_name TEXT,
    lesson_id TEXT,
    semester_id TEXT,
    attempt_type TEXT,
    requirement_type TEXT,
    credits REAL,
    score REAL,
    total_score REAL,
    makeup_score REAL,
    deferred_score REAL,
    bonus_score REAL,
    grade_level TEXT,
    gpa REAL,
    is_pass INTEGER,
    is_published INTEGER,
    publish_status TEXT,
    is_void INTEGER NOT NULL DEFAULT 0,
    previous_attempt_id TEXT,
    batch_id TEXT NOT NULL,
    source_row_no INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(batch_id, source_row_no)
);

CREATE TABLE IF NOT EXISTS student_course_result (
    student_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    effective_attempt_id TEXT,
    effective_score REAL,
    is_pass INTEGER,
    earned_credits REAL,
    result_basis TEXT,
    calculated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'derived',
    PRIMARY KEY(student_id, course_id, rule_version)
);

CREATE TABLE IF NOT EXISTS student_course_substitution (
    substitution_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    original_course_id TEXT,
    original_course_name TEXT,
    substitute_course_id TEXT,
    substitute_course_name TEXT,
    recognized_credits REAL,
    approval_status TEXT,
    workflow_status TEXT,
    approved_at TEXT,
    source TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS student_status_event (
    event_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    before_status TEXT,
    after_status TEXT,
    before_grade TEXT,
    after_grade TEXT,
    before_organization TEXT,
    after_organization TEXT,
    before_major_code TEXT,
    after_major_code TEXT,
    before_major_name TEXT,
    after_major_name TEXT,
    before_class_code TEXT,
    after_class_code TEXT,
    event_reason TEXT,
    event_note TEXT,
    effective_at TEXT,
    batch_id TEXT NOT NULL,
    source_row_no INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'real',
    UNIQUE(batch_id, source_row_no)
);

CREATE TABLE IF NOT EXISTS graduation_outcome (
    student_id TEXT NOT NULL,
    audit_batch TEXT NOT NULL,
    graduation_status TEXT,
    degree_status TEXT,
    education_level TEXT,
    organization_id TEXT,
    major_code TEXT,
    graduation_date TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY(student_id, audit_batch)
);

CREATE TABLE IF NOT EXISTS staff_student_scope (
    staff_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    scope_ref TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    source_system TEXT,
    source_updated_at TEXT,
    PRIMARY KEY(staff_id, student_id, relation_type, valid_from)
);

CREATE TABLE IF NOT EXISTS room_availability (
    room_id TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    available_seats INTEGER,
    is_available INTEGER NOT NULL,
    reason TEXT,
    updated_by TEXT,
    source TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY(room_id, valid_from)
);

CREATE TABLE IF NOT EXISTS metric_definition (
    metric_id TEXT NOT NULL,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    grain TEXT NOT NULL,
    formula TEXT NOT NULL,
    source_policy TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    PRIMARY KEY(metric_id, version)
);

-- M4：ETL 运行历史。与 data_batch 同库，batch_id 可空关联采集批次。
CREATE TABLE IF NOT EXISTS etl_run (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT NOT NULL,
    batch_id TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'running',
    rows_read INTEGER,
    rows_written INTEGER,
    checks_json TEXT,
    error TEXT,
    triggered_by TEXT NOT NULL DEFAULT 'manual',
    source TEXT NOT NULL DEFAULT 'etl'
);

CREATE TABLE IF NOT EXISTS student_plan_course_status (
    status_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_course_id INTEGER NOT NULL,
    course_id TEXT NOT NULL,
    module TEXT,
    requirement_type TEXT,
    suggested_term TEXT,
    completion_status TEXT NOT NULL,
    is_actionable INTEGER NOT NULL DEFAULT 0,
    is_overdue INTEGER NOT NULL DEFAULT 0,
    effective_attempt_id TEXT,
    effective_score REAL,
    earned_credits REAL,
    rule_version TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'derived',
    UNIQUE(student_id, plan_course_id, rule_version)
);

CREATE TABLE IF NOT EXISTS student_growth_indicator (
    student_id TEXT NOT NULL,
    indicator_version TEXT NOT NULL,
    passed_courses INTEGER NOT NULL DEFAULT 0,
    failed_courses INTEGER NOT NULL DEFAULT 0,
    earned_credits REAL NOT NULL DEFAULT 0,
    avg_gpa REAL,
    retake_attempts INTEGER NOT NULL DEFAULT 0,
    required_courses INTEGER NOT NULL DEFAULT 0,
    required_completed INTEGER NOT NULL DEFAULT 0,
    required_missing INTEGER NOT NULL DEFAULT 0,
    overdue_required INTEGER NOT NULL DEFAULT 0,
    status_events INTEGER NOT NULL DEFAULT 0,
    calculated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'derived',
    PRIMARY KEY(student_id, indicator_version)
);

CREATE TABLE IF NOT EXISTS student_difficulty_flag (
    student_id TEXT NOT NULL,
    flag_code TEXT NOT NULL,
    flag_version TEXT NOT NULL,
    severity TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    evidence_json TEXT,
    calculated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'derived',
    PRIMARY KEY(student_id, flag_code, flag_version)
);

CREATE TABLE IF NOT EXISTS student_timeline_event (
    event_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT,
    semester_id TEXT,
    title TEXT NOT NULL,
    detail_json TEXT,
    source_ref TEXT,
    source TEXT NOT NULL DEFAULT 'derived'
);

-- 课程通过率三分层聚合（M1）：粒度 课程×学期。
-- 口径：仅统计 grade_attempt 中 is_published=1 AND is_void=0 AND is_pass IS NOT NULL 的有效记录；
--   first=首次修读（attempt_type='regular'，含缓考 deferred 与空值，均视为首次修读链路）、
--   makeup=补考、retake=重修；三个通过率存放 0-1 小数，分母为 0 时存 NULL 不存 0。
-- course_group 推导优先级：①培养方案模块+修读要求 ②V1 dim_course.category 映射 ③其他；
-- group_basis 记录实际命中的推导来源（plan_module / v1_category / default）。
CREATE TABLE IF NOT EXISTS agg_course_pass_stat (
    course_id TEXT NOT NULL,
    semester_id TEXT NOT NULL,
    course_name TEXT,
    course_group TEXT NOT NULL DEFAULT '其他',
    group_basis TEXT,
    first_attempts INTEGER NOT NULL DEFAULT 0,
    first_pass INTEGER NOT NULL DEFAULT 0,
    makeup_attempts INTEGER NOT NULL DEFAULT 0,
    makeup_pass INTEGER NOT NULL DEFAULT 0,
    retake_attempts INTEGER NOT NULL DEFAULT 0,
    retake_pass INTEGER NOT NULL DEFAULT 0,
    first_pass_rate REAL,
    makeup_pass_rate REAL,
    retake_pass_rate REAL,
    rule_version TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'derived',
    PRIMARY KEY(course_id, semester_id)
);

CREATE TABLE IF NOT EXISTS agg_course_offering (
    semester_id TEXT NOT NULL, course_id TEXT NOT NULL, lesson_count INTEGER NOT NULL,
    teacher_count INTEGER NOT NULL, enrolled INTEGER NOT NULL DEFAULT 0,
    total_hours REAL NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'derived',
    PRIMARY KEY(semester_id, course_id)
);

CREATE TABLE IF NOT EXISTS agg_course_team (
    semester_id TEXT NOT NULL, course_id TEXT NOT NULL, teacher_count INTEGER NOT NULL,
    professor_count INTEGER NOT NULL DEFAULT 0, associate_professor_count INTEGER NOT NULL DEFAULT 0,
    lecturer_count INTEGER NOT NULL DEFAULT 0, unknown_title_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'derived', PRIMARY KEY(semester_id, course_id)
);

CREATE TABLE IF NOT EXISTS agg_teacher_schedule_preference (
    semester_id TEXT NOT NULL, staff_id TEXT NOT NULL, weekday INTEGER NOT NULL,
    day_part TEXT NOT NULL, meeting_count INTEGER NOT NULL, course_count INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'derived', PRIMARY KEY(semester_id, staff_id, weekday, day_part)
);

CREATE TABLE IF NOT EXISTS access_scope_mapping (
    role_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    source_scope_id TEXT NOT NULL,
    organization_id TEXT,
    major_code TEXT,
    class_code TEXT,
    mapping_status TEXT NOT NULL,
    note TEXT,
    PRIMARY KEY(role_id, source_scope_id)
);

CREATE INDEX IF NOT EXISTS idx_grade_attempt_student_course ON grade_attempt(student_id, course_id);
CREATE INDEX IF NOT EXISTS idx_grade_attempt_student_term_valid
    ON grade_attempt(student_id, semester_id, is_published, is_void, is_pass);
-- 课程结果专题按课程×学期统计去重学生；没有该索引会在每次查询时全表分组。
CREATE INDEX IF NOT EXISTS idx_grade_attempt_course_term_valid_student
    ON grade_attempt(course_id, semester_id, is_published, is_void, is_pass, student_id);
CREATE INDEX IF NOT EXISTS idx_student_plan ON dim_student(plan_id, student_id);
CREATE INDEX IF NOT EXISTS idx_student_org_major_grade
    ON dim_student(organization_id, major_code, entry_grade, student_id);
CREATE INDEX IF NOT EXISTS idx_plan_course_plan ON curriculum_plan_course(plan_id, plan_course_id);
CREATE INDEX IF NOT EXISTS idx_plan_requirement_plan ON curriculum_graduation_requirement(plan_id, requirement_id);
CREATE INDEX IF NOT EXISTS idx_plan_module_plan ON curriculum_plan_module_requirement(plan_id, module_requirement_id);
CREATE INDEX IF NOT EXISTS idx_lesson_semester_course ON teaching_lesson(semester_id, course_id);
CREATE INDEX IF NOT EXISTS idx_meeting_lesson ON course_meeting(lesson_id);
CREATE INDEX IF NOT EXISTS idx_status_event_student ON student_status_event(student_id, effective_at);
CREATE INDEX IF NOT EXISTS idx_scope_student ON staff_student_scope(student_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_plan_status_student ON student_plan_course_status(student_id, completion_status);
CREATE INDEX IF NOT EXISTS idx_plan_status_rule_student
    ON student_plan_course_status(rule_version, student_id, plan_id, requirement_type, completion_status, is_overdue);
CREATE INDEX IF NOT EXISTS idx_plan_status_rule_course
    ON student_plan_course_status(rule_version, course_id, requirement_type, completion_status, is_overdue, student_id);
CREATE INDEX IF NOT EXISTS idx_lesson_course_supply ON teaching_lesson(course_id, lesson_id);
CREATE INDEX IF NOT EXISTS idx_lesson_teacher_lesson ON lesson_teacher(lesson_id, staff_id);
CREATE INDEX IF NOT EXISTS idx_substitution_original ON student_course_substitution(original_course_id, substitution_id);
CREATE INDEX IF NOT EXISTS idx_difficulty_student ON student_difficulty_flag(student_id, severity);
CREATE INDEX IF NOT EXISTS idx_timeline_student ON student_timeline_event(student_id, event_date);
CREATE INDEX IF NOT EXISTS idx_course_pass_stat_semester ON agg_course_pass_stat(semester_id, course_group);
CREATE INDEX IF NOT EXISTS idx_etl_run_task_started ON etl_run(task, started_at);
-- 同一任务同一时刻至多一条 running 记录（并发保护的硬约束）。
CREATE UNIQUE INDEX IF NOT EXISTS uq_etl_run_running_task
    ON etl_run(task) WHERE status='running';

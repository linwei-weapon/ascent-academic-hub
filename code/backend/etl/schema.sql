-- =====================================================================
-- 平台管理端 BI · 分析库 Schema (SQLite)
-- 对齐 技术方案.md §4 / 数据字典.md 真实字段。命名：dim_/fact_/agg_/sys_
-- 所有业务表带 source(real/sim) 便于回溯，前端不暴露。
-- 阶段2 ETL 重建用：先 DROP 再 CREATE（幂等）。
-- =====================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;   -- 完整性由 ETL 校验把关，不靠 DB 硬约束（避免跨学期孤儿）

-- ---------------------------------------------------------------------
-- 维表 dim_
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS dim_college;
CREATE TABLE dim_college (
    college_id   TEXT PRIMARY KEY,   -- 编码（成绩表"管理部门"派生）
    name         TEXT NOT NULL,      -- 学院名（如"安全与海洋工程学院"）
    source_name  TEXT,               -- 成绩表"管理部门"原值
    source       TEXT NOT NULL DEFAULT 'real'
);

DROP TABLE IF EXISTS dim_major;
CREATE TABLE dim_major (
    major_id     TEXT PRIMARY KEY,
    college_id   TEXT,               -- → dim_college
    name         TEXT NOT NULL,      -- 成绩表"专业"
    source       TEXT NOT NULL DEFAULT 'real'
);

DROP TABLE IF EXISTS dim_class;
CREATE TABLE dim_class (
    class_id     TEXT PRIMARY KEY,
    major_id     TEXT,               -- → dim_major
    grade        TEXT,               -- 年级，如"2022"
    name         TEXT NOT NULL,      -- 成绩表"行政班"
    source       TEXT NOT NULL DEFAULT 'real'
);

DROP TABLE IF EXISTS dim_course;
CREATE TABLE dim_course (
    course_id      TEXT PRIMARY KEY, -- 课程代码
    name           TEXT,             -- 课程名称（成绩+教学任务补全，课程信息表残缺）
    credits        REAL,             -- 学分
    category       TEXT,             -- 课程类别（教学任务.课程类别，如"本科"）
    course_nature  TEXT,             -- 课程性质（必修/选修）
    is_required    INTEGER,          -- 1=必修 0=选修（成绩表"是否必修"）
    dept           TEXT,             -- 开课部门
    source         TEXT NOT NULL DEFAULT 'real'
);

DROP TABLE IF EXISTS dim_teacher;
CREATE TABLE dim_teacher (
    teacher_id   TEXT PRIMARY KEY,   -- 教师工号（解析"姓名(工号)"）
    name         TEXT,               -- 脱敏姓名"李**"
    dept         TEXT,               -- 教师所属部门
    title        TEXT,               -- 职称
    source       TEXT NOT NULL DEFAULT 'real'
);

DROP TABLE IF EXISTS dim_semester;
CREATE TABLE dim_semester (
    semester_id  TEXT PRIMARY KEY,   -- 如"2025-2026-2"
    year         TEXT,               -- 学年"2025-2026"
    term         INTEGER,            -- 1/2/3（3=短学期）
    is_current   INTEGER DEFAULT 0,  -- 当前学期标记
    source       TEXT NOT NULL DEFAULT 'real'
);

DROP TABLE IF EXISTS dim_student;
CREATE TABLE dim_student (
    student_id   TEXT PRIMARY KEY,   -- 学号
    name         TEXT,               -- 脱敏姓名"余**"
    college_id   TEXT,               -- → dim_college
    major_id     TEXT,               -- → dim_major
    class_id     TEXT,               -- → dim_class
    grade        TEXT,               -- 年级
    enroll_on    TEXT,               -- 入学日期（暂无→NULL）
    status       TEXT DEFAULT '在籍', -- 学籍状态
    source       TEXT NOT NULL DEFAULT 'real'
);

-- ---------------------------------------------------------------------
-- 事实表 fact_
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS fact_grade;
CREATE TABLE fact_grade (
    grade_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT NOT NULL,      -- → dim_student
    course_id    TEXT,               -- → dim_course（课程代码）
    lesson_id    TEXT,               -- 教学班代码（软引用 fact_lesson）
    semester_id  TEXT,               -- → dim_semester
    score        REAL,               -- 得分（非数值→NULL）
    level        TEXT,               -- 等级（等级制：优秀/良好/…）
    gpa          REAL,               -- 绩点（已预算）
    is_pass      INTEGER,            -- 1=通过 0=未通过 NULL=空
    is_required  INTEGER,            -- 1=必修 0=选修
    is_retake    INTEGER,            -- 1=重修
    credits      REAL,               -- 学分
    exam_status  TEXT,               -- 考试情况（发布状态/补考标记派生）
    source       TEXT NOT NULL DEFAULT 'real'
);

DROP TABLE IF EXISTS fact_lesson;
CREATE TABLE fact_lesson (
    lesson_id        TEXT NOT NULL,  -- 教学班代码
    semester_id      TEXT,           -- → dim_semester
    course_id        TEXT,           -- → dim_course
    teacher_id       TEXT,           -- 主讲（首位）→ dim_teacher
    teacher_ids      TEXT,           -- 全部工号（分隔）
    capacity         INTEGER,        -- 选课人数上限
    enrolled         INTEGER,        -- 已选学生数
    retake_count     INTEGER,        -- 重修人数
    total_hours      REAL,           -- 总学时
    theory_hours     REAL,           -- 理论学时
    exp_hours        REAL,           -- 实验学时
    practice_hours   REAL,           -- 实践学时
    lab_hours        REAL,           -- 上机学时
    classroom        TEXT,           -- 解析"日期时间地点人员"主教室
    utilization      REAL,           -- 解析"四教206(67%)"→0.67
    campus           TEXT,           -- 授课校区
    class_names      TEXT,           -- 上课行政班（合班判定用）
    source           TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (lesson_id, semester_id)
);

DROP TABLE IF EXISTS fact_plan_course;
CREATE TABLE fact_plan_course (
    plan_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    major_id     TEXT,               -- 仅安全工程/海洋油气 2 专业
    grade        TEXT,               -- 培养方案年级
    course_id    TEXT,               -- 计划课程代码
    course_name  TEXT,
    module       TEXT,               -- 课程模块
    credits      REAL,
    term         TEXT,               -- 建议修读学期
    is_core      INTEGER,            -- ★核心课
    source       TEXT NOT NULL DEFAULT 'real'
);

DROP TABLE IF EXISTS fact_plan_meta;
CREATE TABLE fact_plan_meta (
    major_id          TEXT,          -- 仅 2 专业
    grade             TEXT,
    major_name        TEXT,
    total_credits     REAL,          -- 最低总学分
    required_credits  REAL,          -- 必修课学分
    elective_credits  REAL,          -- 选修课学分
    practice_credits  REAL,          -- 单独设置的实践教学环节
    degree_req        TEXT,          -- 学位授予要求文本
    grad_reqs_json    TEXT,          -- 12 条毕业要求（JSON 数组）
    source            TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (major_id, grade)
);

DROP TABLE IF EXISTS fact_plan_module_rule;
CREATE TABLE fact_plan_module_rule (
    major_id       TEXT,
    grade          TEXT,
    module         TEXT,
    course_nature  TEXT NOT NULL CHECK(course_nature IN ('required','elective')),
    min_credits    REAL NOT NULL DEFAULT 0,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    source         TEXT NOT NULL DEFAULT 'derived',
    PRIMARY KEY (major_id, grade, module)
);

DROP TABLE IF EXISTS fact_grad_req_support;
CREATE TABLE fact_grad_req_support (
    major_id      TEXT,
    grade         TEXT,
    module        TEXT,
    requirement_no INTEGER,
    requirement_name TEXT,
    weight        INTEGER NOT NULL DEFAULT 0 CHECK(weight BETWEEN 0 AND 3),
    source        TEXT NOT NULL DEFAULT 'prototype',
    PRIMARY KEY (major_id, grade, module, requirement_no)
);

DROP TABLE IF EXISTS fact_course_equivalence;
CREATE TABLE fact_course_equivalence (
    equivalence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    major_id TEXT NOT NULL, grade TEXT NOT NULL,
    target_course_id TEXT NOT NULL, substitute_course_id TEXT NOT NULL,
    valid_from TEXT, valid_to TEXT, status TEXT NOT NULL DEFAULT 'active',
    approval_ref TEXT, source TEXT NOT NULL DEFAULT 'manual',
    UNIQUE (major_id, grade, target_course_id, substitute_course_id)
);

DROP TABLE IF EXISTS fact_student_credit_recognition;
CREATE TABLE fact_student_credit_recognition (
    recognition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL, recognition_type TEXT NOT NULL,
    target_course_id TEXT, module TEXT, credits REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', approval_ref TEXT,
    approved_at TEXT, source TEXT NOT NULL DEFAULT 'manual'
);

DROP TABLE IF EXISTS fact_plan_course_group;
CREATE TABLE fact_plan_course_group (
    group_id TEXT, major_id TEXT, grade TEXT, group_name TEXT,
    module TEXT, min_courses INTEGER NOT NULL DEFAULT 0,
    min_credits REAL NOT NULL DEFAULT 0, course_ids_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'manual', PRIMARY KEY (group_id,major_id,grade)
);

DROP TABLE IF EXISTS curriculum_rule_change;
CREATE TABLE curriculum_rule_change (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL, payload_json TEXT NOT NULL,
    reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL, created_at TEXT NOT NULL,
    reviewed_by TEXT, reviewed_at TEXT, review_comment TEXT,
    activated_by TEXT, activated_at TEXT
);

DROP TABLE IF EXISTS curriculum_rule_audit;
CREATE TABLE curriculum_rule_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id INTEGER NOT NULL, action TEXT NOT NULL,
    operator TEXT NOT NULL, operated_at TEXT NOT NULL, detail TEXT
);

DROP TABLE IF EXISTS fact_alert;
CREATE TABLE fact_alert (
    alert_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     TEXT NOT NULL,    -- → dim_student
    rule_id        TEXT,             -- → sys_alert_rule
    type           TEXT,             -- 预警类型
    level          TEXT,             -- 严重/警告/提醒
    trigger_detail TEXT,             -- 触发链文本（真实，如"近2学期GPA 2.8→2.4"）
    status         TEXT DEFAULT '待处理',  -- 处理状态（模拟流转）
    created_at     TEXT,             -- 生成时间
    semester_id    TEXT,             -- → dim_semester
    source         TEXT NOT NULL DEFAULT 'real', -- 预警记录本身真实，status 为模拟
    is_active      INTEGER NOT NULL DEFAULT 1,
    rule_version   TEXT,
    activation_batch_id TEXT,
    closed_at      TEXT,
    close_reason   TEXT
);

-- 预警处理闭环（平台应用数据，不回写教务源库）
DROP TABLE IF EXISTS alert_event;
CREATE TABLE alert_event (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id        INTEGER UNIQUE,       -- 对应 fact_alert 初始计算结果
    student_id      TEXT NOT NULL,
    rule_id         TEXT,
    workflow_status TEXT NOT NULL DEFAULT 'new',
    first_detected_at TEXT,
    last_detected_at  TEXT,
    updated_at      TEXT,
    source          TEXT NOT NULL DEFAULT 'engine'
);

DROP TABLE IF EXISTS alert_assignee;
CREATE TABLE alert_assignee (
    event_id        INTEGER NOT NULL,
    username        TEXT NOT NULL,
    role_id         TEXT,
    assignment_reason TEXT,
    assigned_at     TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (event_id, username)
);

DROP TABLE IF EXISTS alert_followup;
CREATE TABLE alert_followup (
    followup_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL,
    operator        TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    content         TEXT NOT NULL,
    next_action_at  TEXT,
    created_at      TEXT NOT NULL
);

DROP TABLE IF EXISTS alert_status_history;
CREATE TABLE alert_status_history (
    history_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL,
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    operator        TEXT NOT NULL,
    reason          TEXT,
    changed_at      TEXT NOT NULL
);

CREATE INDEX idx_alert_event_student ON alert_event(student_id);
CREATE INDEX idx_alert_event_status ON alert_event(workflow_status);
CREATE INDEX idx_alert_followup_event ON alert_followup(event_id, created_at);

-- ---------------------------------------------------------------------
-- 预聚合表 agg_（性能核心，ETL 算好直读）
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS agg_college_term;
CREATE TABLE agg_college_term (
    college_id   TEXT,
    semester_id  TEXT,
    students     INTEGER,
    avg_score    REAL,
    fail_rate    REAL,
    gpa_avg      REAL,
    alert_rate   REAL,
    credit_done  REAL,
    source       TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (college_id, semester_id)
);

DROP TABLE IF EXISTS agg_major_term;
CREATE TABLE agg_major_term (
    major_id     TEXT,
    semester_id  TEXT,
    grade        TEXT,
    students     INTEGER,
    avg_score    REAL,
    fail_rate    REAL,
    gpa_avg      REAL,
    alert_count  INTEGER,
    credit_done  REAL,
    source       TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (major_id, semester_id, grade)
);

DROP TABLE IF EXISTS agg_course_term;
CREATE TABLE agg_course_term (
    course_id       TEXT,
    semester_id     TEXT,
    avg_score       REAL,
    fail_rate       REAL,
    total           INTEGER,
    excellent_rate  REAL,
    retake_rate     REAL,
    first_pass_rate REAL,
    final_pass_rate REAL,
    source          TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (course_id, semester_id)
);

DROP TABLE IF EXISTS agg_gpa_dist;
CREATE TABLE agg_gpa_dist (
    scope_type   TEXT,   -- 'all' / 'college'
    scope_id     TEXT,   -- 全校='ALL' 或 college_id
    semester_id  TEXT,
    bucket       TEXT,   -- 5 档（优秀/良好/中等/及格/不及格）
    count        INTEGER,
    percent      REAL,
    source       TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (scope_type, scope_id, semester_id, bucket)
);

DROP TABLE IF EXISTS agg_teacher_load;
CREATE TABLE agg_teacher_load (
    teacher_id   TEXT,
    semester_id  TEXT,
    title        TEXT,
    hours        REAL,
    courses      INTEGER,
    classes      INTEGER,
    source       TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (teacher_id, semester_id)
);

DROP TABLE IF EXISTS agg_classroom_util;
CREATE TABLE agg_classroom_util (
    building     TEXT,
    room_type    TEXT,
    semester_id  TEXT,
    day          INTEGER,   -- 1-5
    period       TEXT,      -- p12/p34/p56/p78
    utilization  REAL,
    source       TEXT NOT NULL DEFAULT 'sim', -- 星期/节次为固定种子情景模拟
    PRIMARY KEY (building, room_type, semester_id, day, period)
);

DROP TABLE IF EXISTS agg_course_category_term;
CREATE TABLE agg_course_category_term (
    category       TEXT,               -- dim_course.category（专业必修课/通识必修课/体育课/…）
    semester_id    TEXT,
    course_count   INTEGER,            -- 去重课程门数
    lesson_count   INTEGER,            -- 教学班数
    total_hours    REAL,               -- 总学时
    theory_hours   REAL,
    exp_hours      REAL,
    practice_hours REAL,
    lab_hours      REAL,
    avg_enrolled   REAL,               -- 平均班额
    small_count    INTEGER,            -- <30人
    medium_count   INTEGER,            -- 30-60人
    large_count    INTEGER,            -- 60-120人
    xlarge_count   INTEGER,            -- >120人
    source         TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (category, semester_id)
);

DROP TABLE IF EXISTS data_quality_issue;
CREATE TABLE data_quality_issue (
    issue_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    semester_id TEXT,
    entity_type TEXT,
    entity_id TEXT,
    affected_rows INTEGER NOT NULL DEFAULT 0,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    detail TEXT,
    recommendation TEXT,
    detected_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'derived'
);

-- ---------------------------------------------------------------------
-- 系统 / RBAC / 规则元数据 sys_
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS sys_user;
CREATE TABLE sys_user (
    user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT UNIQUE NOT NULL,
    password_hash  TEXT NOT NULL,
    name           TEXT,
    role_id        TEXT,            -- → sys_role
    status         TEXT DEFAULT 'active'
);

DROP TABLE IF EXISTS sys_role;
CREATE TABLE sys_role (
    role_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    data_scope_type TEXT             -- all/college/major/grade/class
);

DROP TABLE IF EXISTS sys_role_scope;
CREATE TABLE sys_role_scope (
    role_id   TEXT,                  -- → sys_role
    scope_id  TEXT,                  -- 具体范围 id（院长→college_id 等）
    PRIMARY KEY (role_id, scope_id)
);

DROP TABLE IF EXISTS sys_menu;
CREATE TABLE sys_menu (
    menu_id    TEXT PRIMARY KEY,
    parent_id  TEXT,
    title      TEXT NOT NULL,
    path       TEXT,
    icon       TEXT,
    sort_order INTEGER DEFAULT 0
);

DROP TABLE IF EXISTS sys_role_menu;
CREATE TABLE sys_role_menu (
    role_id   TEXT,                  -- → sys_role
    menu_id   TEXT,                  -- → sys_menu
    PRIMARY KEY (role_id, menu_id)
);

DROP TABLE IF EXISTS sys_alert_rule;
CREATE TABLE sys_alert_rule (
    rule_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    level         TEXT,              -- 严重/警告/提醒
    trigger_type  TEXT,              -- threshold/discovered
    params        TEXT,              -- JSON 阈值参数
    enabled       INTEGER DEFAULT 1
);

DROP TABLE IF EXISTS sys_discovered_rule;
CREATE TABLE sys_discovered_rule (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    semester_id   TEXT NOT NULL,     -- 分析数据所在学期
    name          TEXT NOT NULL,     -- 规则名称
    conditions    TEXT NOT NULL,     -- JSON 条件数组
    level         TEXT,              -- 建议预警等级
    confidence    REAL,              -- 置信度 0-1
    risk_ratio    REAL,              -- 风险倍数
    sample_size   INTEGER,           -- 样本量
    detail_json   TEXT,              -- JSON 详细分析数据
    status        TEXT DEFAULT 'pending',  -- pending/approved/rejected
    source        TEXT DEFAULT 'ml', -- ml / llm（规则来源引擎）
    created_at    TEXT DEFAULT (datetime('now','localtime')),
    approved_at   TEXT
);

DROP TABLE IF EXISTS sys_config;
CREATE TABLE sys_config (
    config_key    TEXT PRIMARY KEY,
    config_value  TEXT NOT NULL,      -- JSON 配置值
    updated_at    TEXT DEFAULT (datetime('now','localtime')),
    updated_by    TEXT                -- 更新人 username
);

DROP TABLE IF EXISTS sys_kpi_config;
CREATE TABLE sys_kpi_config (
    kpi_id           TEXT PRIMARY KEY,
    module           TEXT NOT NULL,       -- 所属模块
    label            TEXT NOT NULL,       -- 展示名称
    enabled          INTEGER DEFAULT 1,   -- 1=展示 0=隐藏
    sort_order       INTEGER DEFAULT 0,   -- 排序
    calc_type        TEXT,                -- 计算口径 key
    formula          TEXT,                -- 预设口径 key
    unit             TEXT,                -- 单位
    color_rule       TEXT,                -- 着色逻辑 JSON
    threshold_warn   REAL,                -- 警告阈值
    threshold_danger REAL,                -- 危险阈值
    scope_applicable TEXT DEFAULT 'all',  -- 适用数据范围
    updated_at       TEXT DEFAULT (datetime('now','localtime'))
);

-- ---------------------------------------------------------------------
-- 索引（§4.5）
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_grade_student   ON fact_grade(student_id);
CREATE INDEX IF NOT EXISTS idx_grade_course_sem ON fact_grade(course_id, semester_id);
CREATE INDEX IF NOT EXISTS idx_grade_semester  ON fact_grade(semester_id);
CREATE INDEX IF NOT EXISTS idx_grade_lesson    ON fact_grade(lesson_id, semester_id);
CREATE INDEX IF NOT EXISTS idx_alert_student   ON fact_alert(student_id);
CREATE INDEX IF NOT EXISTS idx_alert_level_st  ON fact_alert(level, status);
CREATE INDEX IF NOT EXISTS idx_lesson_course   ON fact_lesson(course_id, semester_id);
CREATE INDEX IF NOT EXISTS idx_lesson_teacher  ON fact_lesson(teacher_id, semester_id);

-- ---------------------------------------------------------------------
-- 合成业务事实表（R3）：真实学业源缺失的业务域，按真实学业数据派生，
-- 固定种子可复现，source='sim'，不加演示标识，前端不暴露 source。
-- 用途：毕业去向/学籍异动/考纪/校外考试/出勤/培养方案学分要求。
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS fact_graduation;
CREATE TABLE fact_graduation (
    student_id    TEXT NOT NULL,      -- → dim_student
    grade         TEXT,               -- 年级
    major_id      TEXT,               -- → dim_major
    college_id    TEXT,               -- → dim_college
    earned_credits REAL,              -- 已修学分（真实派生）
    req_credits   REAL,               -- 应修学分（fact_major_req 派生）
    graduated     INTEGER,            -- 1=按期毕业 0=结业/延期
    degree        INTEGER,            -- 1=授予学位 0=未授予
    grad_status   TEXT,               -- 按期毕业/结业/延期毕业
    goal          TEXT,               -- 就业去向：升学读研/签约就业/灵活就业/待业
    semester_id   TEXT,               -- 毕业学期
    source        TEXT NOT NULL DEFAULT 'sim'
);

DROP TABLE IF EXISTS fact_attrition;
CREATE TABLE fact_attrition (
    student_id    TEXT NOT NULL,
    grade         TEXT,
    major_id      TEXT,
    college_id    TEXT,
    kind          TEXT,               -- 休学/复学/退学/转专业
    reason        TEXT,               -- 异动原因
    semester_id   TEXT,
    source        TEXT NOT NULL DEFAULT 'sim'
);

DROP TABLE IF EXISTS fact_discipline;
CREATE TABLE fact_discipline (
    record_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT,
    college_id    TEXT,
    kind          TEXT,               -- 违纪/作弊
    detail        TEXT,
    punish        TEXT,               -- 警告/严重警告/记过/留校察看
    semester_id   TEXT,
    source        TEXT NOT NULL DEFAULT 'sim'
);

DROP TABLE IF EXISTS fact_exam_cert;
CREATE TABLE fact_exam_cert (
    student_id    TEXT NOT NULL,
    college_id    TEXT,
    cet4          INTEGER,            -- 1=通过 0=未过
    cet6          INTEGER,
    ncre2         INTEGER,            -- 计算机二级
    ncre3         INTEGER,            -- 计算机三级
    source        TEXT NOT NULL DEFAULT 'sim'
);

DROP TABLE IF EXISTS fact_attend;
CREATE TABLE fact_attend (
    course_id     TEXT,               -- → dim_course
    college_id    TEXT,
    semester_id   TEXT,
    attend_rate   REAL,               -- 出勤率 0-1
    absent_gt3    INTEGER,            -- 旷课>3次人数
    absent_gt3_pct REAL,              -- 旷课>3占比
    trend         TEXT,               -- up/down/stable
    source        TEXT NOT NULL DEFAULT 'sim'
);

DROP TABLE IF EXISTS fact_major_req;
CREATE TABLE fact_major_req (
    major_id      TEXT PRIMARY KEY,   -- → dim_major
    grade         TEXT,
    total_req     REAL,               -- 毕业最低总学分
    general_req   REAL,               -- 通识必修学分
    major_req     REAL,               -- 专业必修学分
    practice_req  REAL,               -- 实践学分
    source        TEXT NOT NULL DEFAULT 'sim'  -- M017/M031 用真实方案→real
);

CREATE INDEX IF NOT EXISTS idx_grad_student   ON fact_graduation(student_id);
CREATE INDEX IF NOT EXISTS idx_grad_major     ON fact_graduation(major_id);
CREATE INDEX IF NOT EXISTS idx_attr_college   ON fact_attrition(college_id);
CREATE INDEX IF NOT EXISTS idx_examcert_stu   ON fact_exam_cert(student_id);
CREATE INDEX IF NOT EXISTS idx_attend_course  ON fact_attend(course_id, semester_id);

DROP TABLE IF EXISTS fact_teacher_profile;
CREATE TABLE fact_teacher_profile (
    teacher_id    TEXT PRIMARY KEY,   -- → dim_teacher
    norm_title    TEXT,               -- 规范职称（教授/副教授/讲师/助教/其他）
    education     TEXT,               -- 学历（博士研究生/硕士研究生/大学本科）
    degree        TEXT,               -- 学位（博士/硕士/学士）
    age           INTEGER,            -- 年龄
    age_band      TEXT,               -- 年龄段（35岁以下/36-45岁/46-55岁/56岁以上）
    origin        TEXT,               -- 学缘（本校毕业/外校(境内)/境外高校）
    school        TEXT,               -- 毕业院校
    teach_years   INTEGER,            -- 教龄
    source        TEXT NOT NULL DEFAULT 'sim'
);

DROP TABLE IF EXISTS fact_schedule_change;
CREATE TABLE fact_schedule_change (
    change_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id    TEXT,               -- → dim_teacher
    college_id    TEXT,               -- → dim_college
    kind          TEXT,               -- 调课/停课
    reason        TEXT,               -- 病假/事假/公差/教学调整/其他
    month         INTEGER,            -- 月份（3-6 春季学期）
    hours         INTEGER,            -- 调停学时
    affected      INTEGER,            -- 受影响学生数
    auto_approved INTEGER,            -- 1=院系自动审核(≤4学时) 0=教务审核
    review_days   REAL,               -- 审核耗时（天）
    semester_id   TEXT,
    source        TEXT NOT NULL DEFAULT 'sim'
);

CREATE INDEX IF NOT EXISTS idx_schedchg_college ON fact_schedule_change(college_id);
CREATE INDEX IF NOT EXISTS idx_schedchg_teacher ON fact_schedule_change(teacher_id);

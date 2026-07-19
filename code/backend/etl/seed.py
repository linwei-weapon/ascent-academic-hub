"""种子 seed：写入 sys_* 元数据（RBAC + 预警规则）。
来源：原型 src/config/permissions.ts + src/store/role.ts + settings 6 规则。
G12 决策：隐藏 学校管理/数据同步，菜单不含 school/sync。
密码：stdlib pbkdf2（'pbkdf2_sha256$iter$salt$hex'），阶段3 鉴权据此校验。
"""
import hashlib
import json
import os
import pandas as pd

# ---- 5 条预警规则（全部阈值触发）----
# params 中除 text 外的数值字段即引擎 alert_engine.py 实际消费的阈值；
# 每条规则仅保留引擎真正读取的阈值，避免"参数存了但不生效"的错配。
# text 由阈值现拼，纯阈值措辞、与引擎逻辑一致。
ALERT_RULES = [
    {"rule_id": "R1", "name": "GPA持续下降", "level": "严重", "trigger_type": "threshold",
     "params": {"gpa_drop": 0.3, "text": "近2~3学期GPA连续下降，累计降幅>0.3"}, "enabled": 1},
    {"rule_id": "R2", "name": "未解决挂科累积", "level": "严重", "trigger_type": "threshold",
     "params": {"fail_courses": 3, "text": "近2学期不同且尚未通过的课程≥3门"}, "enabled": 1},
    {"rule_id": "R2W", "name": "未解决挂科关注", "level": "警告", "trigger_type": "threshold",
     "params": {"fail_courses": 2, "upper_exclusive": 3,
                "text": "近2学期不同且尚未通过的课程=2门"}, "enabled": 1},
    {"rule_id": "R3", "name": "学分缺口过大", "level": "警告", "trigger_type": "threshold",
     "params": {"credit_gap": 10, "text": "已修学分较期望进度缺口>10学分"}, "enabled": 1},
    {"rule_id": "R4", "name": "核心/必修课风险", "level": "提醒", "trigger_type": "threshold",
     "params": {"core_fail": 2, "text": "有培养方案时核心课、无方案时必修课，近2学期未解决≥2门"}, "enabled": 1},
    {"rule_id": "R6", "name": "退学风险", "level": "严重", "trigger_type": "threshold",
     "params": {"gpa_below": 1.8, "fail_courses": 2,
                "text": "本学期GPA<1.8 且近2学期未解决课程≥2门"}, "enabled": 1},
]

# ---- 11 角色（key, 中文名, 数据范围类型）----
ROLES = [
    ("school_leader", "校领导", "all"),
    ("dean", "教务处处长", "all"),
    ("dept_operation", "教务处·运行科", "all"),
    ("dept_research", "教务处·教研科", "all"),
    ("dept_practice", "教务处·实践科", "all"),
    ("quality_office", "质量办/评估中心", "all"),
    ("college_dean", "二级学院·院长", "college"),
    ("college_secretary", "二级学院·教学秘书", "college"),
    ("counselor", "辅导员", "class"),
    ("dept_director", "系主任", "major"),
    ("teacher", "任课教师", "teacher"),  # V1.1新增
]

# ---- 菜单（三个一级分组；业务模块内部使用页内Tab，不形成三级导航）----
# 格式: (menu_id, title, icon, sort_order, parent_id)
MENUS = [
    ("/admin/analysis", "教学管理分析", "DataAnalysis", 1, None),
    ("/admin/decision", "AI管理决策", "MagicStick", 2, None),
    ("/admin/system", "系统管理", "Setting", 3, None),

    ("/admin/dashboard", "教学数据总览", "Odometer", 101, "/admin/analysis"),
    ("/admin/alert", "学业预警监控", "Warning", 102, "/admin/analysis"),
    ("/admin/operation/courses", "教学运行分析", "Calendar", 103, "/admin/analysis"),
    ("/admin/curriculum", "培养质量分析", "Reading", 104, "/admin/analysis"),
    ("/admin/faculty", "师资保障分析", "User", 105, "/admin/analysis"),
    ("/admin/students/analysis", "学生成长与学业分析", "DataLine", 106, "/admin/analysis"),

    ("/admin/reports/management-briefing", "管理要情", "Bell", 201, "/admin/decision"),
    ("/admin/reports/decision-simulation", "决策研判", "Opportunity", 202, "/admin/decision"),

    ("/admin/system/accounts", "账号管理", "User", 301, "/admin/system"),
    ("/admin/system/roles", "角色与功能权限", "UserFilled", 302, "/admin/system"),
    ("/admin/system/menus", "菜单管理", "Menu", 303, "/admin/system"),
    ("/admin/system/kpis", "指标与口径管理", "DataAnalysis", 304, "/admin/system"),
    ("/admin/system/audit", "审计日志", "Document", 305, "/admin/system"),
    ("/admin/settings", "系统参数", "Setting", 306, "/admin/system"),
]

# ---- 角色→菜单可见性（优化后）----
ROLE_MENU = {
    # 数据大屏（9 角色，counselor 除外）
    "/admin/dashboard": [
        "school_leader", "dean", "dept_operation", "dept_research",
        "dept_practice", "quality_office", "college_dean",
        "college_secretary", "dept_director",
    ],
    # 预警中心（6 角色）
    "/admin/alert": [
        "school_leader", "dean", "dept_research",
        "college_dean", "college_secretary", "counselor", "teacher",
    ],
    # 教学运行（模块内部以Tab组织）
    "/admin/operation/courses": [
        "dean", "dept_operation", "college_dean", "college_secretary",
    ],
    # 培养质量（7 角色，校领导负责例外规则最终激活）
    "/admin/curriculum": [
        "school_leader", "dean", "dept_research", "quality_office",
        "college_dean", "college_secretary", "dept_director",
    ],
    # 师资结构（4 角色）
    "/admin/faculty": [
        "dean", "dept_research", "college_dean", "dept_director",
    ],
    # 学生成长与学业
    "/admin/students/analysis": [
        "dean", "college_dean", "college_secretary",
        "counselor", "dept_director",
    ],
    # AI管理决策
    "/admin/reports/management-briefing": [
        "school_leader", "dean", "dept_research", "dept_practice", "quality_office",
        "college_dean", "college_secretary",
    ],
    "/admin/reports/decision-simulation": [
        "school_leader", "dean", "dept_research", "dept_practice", "quality_office",
        "college_dean", "college_secretary",
    ],
    # 系统管理（仅 dean；父菜单由登录接口自动补齐）
    "/admin/system/accounts": ["dean"],
    "/admin/system/roles":    ["dean"],
    "/admin/system/menus":    ["dean"],
    "/admin/system/audit":    ["dean"],
    "/admin/system/kpis":     ["dean"],
    "/admin/settings": ["dean"],
}

DEMO_PASSWORD = "Demo@2026"
ADMIN_PASSWORD = "admin123"  # 管理员 admin 专用登录密码


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    iters = 310_000
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iters)
    return f"pbkdf2_sha256${iters}${salt.hex()}${dk.hex()}"


def build_rules_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "rule_id": r["rule_id"], "name": r["name"], "level": r["level"],
        "trigger_type": r["trigger_type"],
        "params": json.dumps(r["params"], ensure_ascii=False),
        "enabled": r["enabled"],
    } for r in ALERT_RULES])


def load_discovered_rules() -> pd.DataFrame:
    """加载已采纳的自发现规则，保留当前生产配置中的启用状态。
    与 build_rules_df 输出结构一致，用于合并进规则集。"""
    import sqlite3
    from . import config
    db_path = str(config.DB_PATH)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""SELECT d.*,
            COALESCE((SELECT enabled FROM sys_alert_rule ar
                      WHERE ar.rule_id='DR' || d.id),
                     CASE WHEN d.status='approved' THEN 1 ELSE 0 END) current_enabled
            FROM sys_discovered_rule d WHERE d.status IN ('approved','adopted')""").fetchall()
        conn.close()
    except Exception:
        return pd.DataFrame()

    records = []
    for r in rows:
        try:
            conds = json.loads(r["conditions"])
        except Exception:
            conds = []
        params = {}
        for c in conds:
            params[c["key"]] = c.get("engineValue", c.get("value"))
        params["text"] = r["name"]
        records.append({
            "rule_id": f"DR{r['id']}",
            "name": r["name"],
            "level": r["level"] or "警告",
            "trigger_type": "discovered",
            "params": json.dumps(params, ensure_ascii=False),
            "enabled": int(r["current_enabled"] or 0),
        })
    return pd.DataFrame(records)


def build_roles_df() -> pd.DataFrame:
    return pd.DataFrame([{"role_id": k, "name": n, "data_scope_type": s}
                         for k, n, s in ROLES])


def build_menus_df() -> pd.DataFrame:
    return pd.DataFrame([{"menu_id": p, "parent_id": pid, "title": t,
                          "path": p, "icon": ic, "sort_order": o}
                         for p, t, ic, o, pid in MENUS])


def build_role_menu_df() -> pd.DataFrame:
    rows = []
    for menu_id, roles in ROLE_MENU.items():
        for r in roles:
            rows.append({"role_id": r, "menu_id": menu_id})
    return pd.DataFrame(rows)


def build_users_df() -> pd.DataFrame:
    """每角色 1 个演示账号，用户名=角色 key，统一演示密码。"""
    rows = []
    for k, n, _ in ROLES:
        rows.append({"username": k, "password_hash": hash_password(DEMO_PASSWORD),
                     "name": n, "role_id": k, "status": "active"})
    # 额外管理员
    rows.append({"username": "admin", "password_hash": hash_password(ADMIN_PASSWORD),
                 "name": "系统管理员", "role_id": "dean", "status": "active"})
    return pd.DataFrame(rows)


def build_role_scope_df(dims: dict) -> pd.DataFrame:
    """演示数据范围：给院级/系/辅导员/任课教师角色绑定真实 id。
    college_dean/secretary → 选一个真实学院；dept_director → 一个真实专业；
    counselor → 该学院若干真实班级；teacher → 选一个真实教师工号。"""
    rows = []
    # 选一个有数据的真实学院（取第一个二级学院）
    colleges = dims["dim_college"]
    teach_colleges = colleges[~colleges["name"].str.contains("研究生院|本科生院", na=False)]
    demo_college = teach_colleges.iloc[0]["college_id"] if len(teach_colleges) else colleges.iloc[0]["college_id"]
    for r in ("college_dean", "college_secretary"):
        rows.append({"role_id": r, "scope_id": demo_college})
    # dept_director → 该学院下一个专业
    majors = dims["dim_major"]
    dm = majors[majors["college_id"] == demo_college]
    if len(dm):
        rows.append({"role_id": "dept_director", "scope_id": dm.iloc[0]["major_id"]})
    # counselor → 该学院若干班级
    classes = dims["dim_class"]
    major_ids = set(dm["major_id"]) if len(dm) else set()
    cc = classes[classes["major_id"].isin(major_ids)].head(3)
    for _, c in cc.iterrows():
        rows.append({"role_id": "counselor", "scope_id": c["class_id"]})
    # V1.1: teacher → 选第一个有排课记录的教师
    teachers = dims.get("dim_teacher")
    if teachers is not None and len(teachers):
        rows.append({"role_id": "teacher", "scope_id": teachers.iloc[0]["teacher_id"]})
    return pd.DataFrame(rows)


def build_sys_config_df() -> pd.DataFrame:
    """sys_config 初始配置（规则自发现的数据范围/LLM/采样）。"""
    import json
    return pd.DataFrame([
        {"config_key": "discovery.data_sources",
         "config_value": json.dumps({
             "core": ["fact_grade", "dim_student", "fact_alert",
                      "fact_attrition", "fact_major_req"],
             "plan_majors": ["M017", "M031"],
             "optional": ["fact_exam_cert", "fact_schedule_change"],
             "available_not_connected": ["attend", "library", "card",
                                         "network", "counselor", "enrollment"],
         }, ensure_ascii=False)},
        {"config_key": "discovery.llm",
         "config_value": json.dumps({
             "mode": "off",
             "local_model": None,
             "cloud_provider": None,
             "cloud_api_key": None,
             "anonymization": "standard",
         }, ensure_ascii=False)},
        {"config_key": "discovery.sampling",
         "config_value": json.dumps({
             "positive_samples": 150,
             "negative_samples": 150,
         }, ensure_ascii=False)},
    ])


def build_kpi_config_df() -> pd.DataFrame:
    """sys_kpi_config 初始数据（V1.1 指标体系配置）。"""
    return pd.DataFrame([
        # 数据大屏 — 在校生指标
        {"kpi_id":"student_count","module":"dashboard","label":"在籍学生数","enabled":1,"sort_order":1,"calc_type":"count","formula":"count_all","unit":"人","scope_applicable":"all"},
        {"kpi_id":"course_count","module":"dashboard","label":"本学期开课门数","enabled":1,"sort_order":2,"calc_type":"count","formula":"distinct_course","unit":"门","scope_applicable":"all"},
        {"kpi_id":"teacher_count","module":"dashboard","label":"专任教师数","enabled":1,"sort_order":3,"calc_type":"count","formula":"count_all","unit":"人","scope_applicable":"all"},
        {"kpi_id":"alert_count","module":"dashboard","label":"当前预警学生数","enabled":1,"sort_order":4,"calc_type":"count","formula":"distinct_student","unit":"人","scope_applicable":"all"},
        {"kpi_id":"current_fail_rate","module":"dashboard","label":"当前挂科率","enabled":1,"sort_order":5,"calc_type":"rate","formula":"fail_current","unit":"%","color_rule":"{\"green\":{\"op\":\"<=\",\"value\":5},\"orange\":{\"op\":\"<=\",\"value\":15},\"red\":{\"op\":\">\",\"value\":15}}","scope_applicable":"all"},
        {"kpi_id":"history_fail_rate","module":"dashboard","label":"历史挂科率","enabled":1,"sort_order":6,"calc_type":"rate","formula":"fail_history","unit":"%","scope_applicable":"all"},
        # 数据大屏 — 毕业质量指标
        {"kpi_id":"grad_rate","module":"dashboard","label":"应届毕业率","enabled":1,"sort_order":7,"calc_type":"rate","formula":"grad_ontime","unit":"%","color_rule":"{\"green\":{\"op\":\">=\",\"value\":90},\"orange\":{\"op\":\">=\",\"value\":80},\"red\":{\"op\":\"<\",\"value\":80}}","scope_applicable":"all"},
        {"kpi_id":"degree_rate","module":"dashboard","label":"学位授予率","enabled":1,"sort_order":8,"calc_type":"rate","formula":"degree_all","unit":"%","scope_applicable":"all"},
        # 师资结构
        {"kpi_id":"faculty_count","module":"faculty","label":"专任教师总数","enabled":1,"sort_order":1,"calc_type":"count","formula":"count_all","unit":"人","scope_applicable":"all"},
        {"kpi_id":"doctor_rate","module":"faculty","label":"博士学位比","enabled":1,"sort_order":2,"calc_type":"rate","formula":"doctor_all","unit":"%","scope_applicable":"all"},
        {"kpi_id":"prof_teach_rate","module":"faculty","label":"教授上课率","enabled":1,"sort_order":3,"calc_type":"rate","formula":"teach_ug","unit":"%","color_rule":"{\"green\":{\"op\":\">=\",\"value\":85},\"red\":{\"op\":\"<\",\"value\":85}}","threshold_warn":85,"scope_applicable":"all"},
        {"kpi_id":"st_ratio","module":"faculty","label":"生师比","enabled":1,"sort_order":4,"calc_type":"rate","formula":"ug_teacher","unit":":1","scope_applicable":"all"},
        # 教学运行
        {"kpi_id":"operation_course_count","module":"operation","label":"开课门数","enabled":1,"sort_order":1,"scope_applicable":"all"},
        {"kpi_id":"operation_merged_rate","module":"operation","label":"合班率","enabled":1,"sort_order":4,"scope_applicable":"all"},
    ])


def build_sys_tables(dims: dict) -> dict:
    """汇总所有 sys_ 表（role_scope 需 dims）。"""
    return {
        "sys_alert_rule": build_rules_df(),
        "sys_role": build_roles_df(),
        "sys_menu": build_menus_df(),
        "sys_role_menu": build_role_menu_df(),
        "sys_user": build_users_df(),
        "sys_role_scope": build_role_scope_df(dims),
        "sys_config": build_sys_config_df(),
        "sys_kpi_config": build_kpi_config_df(),
    }

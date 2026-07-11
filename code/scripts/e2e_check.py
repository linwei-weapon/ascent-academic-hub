"""阶段5 · 端到端自动核对脚本（无第三方依赖，仅 stdlib）。

对【正在运行的后端 :8000】逐接口请求，并把返回值与 analytics.sqlite 现算的基线逐一比对，
任何不一致即判 FAIL。基线全部从数据库动态计算（不写死），因此换库/重跑 ETL 后仍然有效。

用法（需先启动后端）：
    PYTHONIOENCODING=utf-8 python -X utf8 scripts/e2e_check.py
    PYTHONIOENCODING=utf-8 python -X utf8 scripts/e2e_check.py --base http://localhost:8000

退出码 0=全部通过，1=有失败项。
"""
import argparse
import json
import sqlite3
import sys
import urllib.request
import urllib.parse

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入
from backend.etl.config import DB_PATH  # noqa: E402
from backend.api.settings import CURRENT_SEMESTER as CUR  # noqa: E402
from backend.api.settings import LATEST_REAL_SEMESTER as REAL  # noqa: E402

DEMO_PASSWORD = "Demo@2026"
_PASS, _FAIL = 0, 0
_TOKEN = None


def _conn():
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def scalar(c, sql, *a):
    return c.execute(sql, a).fetchone()[0]


def http(base, path, method="GET", body=None, token=None):
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    # 登录成功后，后续业务接口默认复用全局测试 Token。
    # 显式传入 token 时仍以调用方参数为准，便于测试失效/越权 Token。
    auth_token = _TOKEN if token is None else token
    if auth_token:
        req.add_header("Authorization", f"Bearer {auth_token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:  # 业务错误(401 等)也返回 JSON 包络
        return json.loads(e.read().decode())


def check(name, expected, actual):
    global _PASS, _FAIL
    ok = expected == actual
    _PASS += ok
    _FAIL += not ok
    flag = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  期望={expected!r} 实际={actual!r}"
    print(f"  [{flag}] {name}{extra}")


def kpi_val(payload, label):
    for key in ("kpi", "kpis", "facultyKpis", "studentKpis"):
        for k in payload.get(key, []):
            if k.get("label") == label:
                return k.get("value")
    return None


def main():
    global _TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    base = ap.parse_args().base
    c = _conn()

    print(f"== 端到端核对 @ {base}  （当前模拟学期 {CUR}）==")

    # 1. 健康检查
    print("\n[1] 健康检查")
    h = http(base, "/api/health")
    check("health.status", "up", h["data"]["status"])

    # 2. 登录 + 菜单权限（按 sys_role_menu 动态比对）
    print("\n[2] 登录与菜单权限")
    for role in ("dean", "counselor", "college_dean"):
        r = http(base, "/api/auth/login", "POST", {"username": role, "password": DEMO_PASSWORD})
        exp_menus = scalar(c, "SELECT COUNT(*) FROM sys_role_menu WHERE role_id=?", role)
        check(f"login {role}.code", 0, r["code"])
        check(f"login {role}.menus", exp_menus, len(r["data"]["user"]["menus"]))
    bad = http(base, "/api/auth/login", "POST", {"username": "dean", "password": "wrong"})
    check("login 错误密码.code", 401, bad["code"])
    token = http(base, "/api/auth/login", "POST",
                 {"username": "dean", "password": DEMO_PASSWORD})["data"]["token"]
    _TOKEN = token
    me = http(base, "/api/auth/me", token=token)
    check("auth/me.role", "dean", me["data"]["role"])
    check("业务接口缺少 Token.code", 401,
          http(base, "/api/admin/dashboard", token=False)["code"])

    # 3. 数据大屏 KPI（学生/教师/预警 与全库一致）
    print("\n[3] 数据大屏")
    d = http(base, "/api/admin/dashboard")["data"]
    check("在籍学生数", f"{scalar(c, 'SELECT COUNT(*) FROM dim_student'):,}", kpi_val(d, "在籍学生数"))
    check("专任教师数", f"{scalar(c, 'SELECT COUNT(*) FROM dim_teacher'):,}", kpi_val(d, "专任教师数"))
    exp_alert = scalar(c, "SELECT COUNT(DISTINCT student_id) FROM fact_alert WHERE COALESCE(is_active,1)=1")
    check("当前预警", f"{exp_alert}人", kpi_val(d, "当前预警"))
    # 毕业率/学位率：现算自合成真表 fact_graduation（不再是估算）
    grad_total = scalar(c, "SELECT COUNT(*) FROM fact_graduation")
    grad_count = scalar(c, "SELECT SUM(graduated) FROM fact_graduation")
    degree_count = scalar(c, "SELECT SUM(degree) FROM fact_graduation")
    exp_grad = f"{round(grad_count / grad_total * 100, 1)}%（{grad_count}/{grad_total}）"
    exp_deg = f"{round(degree_count / grad_total * 100, 1)}%（{degree_count}/{grad_total}）"
    check("应届毕业率", exp_grad, kpi_val(d, "应届毕业率"))
    check("学位授予率", exp_deg, kpi_val(d, "学位授予率"))

    # 4. 学院详情 C01
    print("\n[4] 学院详情 C01")
    col = http(base, "/api/admin/college/C01")["data"]
    exp_stu = scalar(c, "SELECT COUNT(*) FROM dim_student WHERE college_id='C01'")
    check("C01 本院学生", str(exp_stu), kpi_val(col, "本院学生"))
    exp_majors = scalar(c, "SELECT COUNT(DISTINCT major_id) FROM dim_student WHERE college_id='C01'")
    check("C01 专业数", exp_majors, len(col["majors"]))

    # 5. 专业详情 M051
    print("\n[5] 专业详情 M051")
    mj = http(base, "/api/admin/major/M051")["data"]
    check("M051 在校生", str(scalar(c, "SELECT COUNT(*) FROM dim_student WHERE major_id='M051'")),
          kpi_val(mj, "在校生"))
    exp_m_alert = scalar(c, """SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
        JOIN dim_student s ON a.student_id=s.student_id WHERE s.major_id='M051'
        AND COALESCE(a.is_active,1)=1""")
    check("M051 预警学生", str(exp_m_alert), kpi_val(mj, "预警学生"))
    # 就业去向：合成真表 fact_graduation 现算（四类之和 == 该专业毕业届人数）
    exp_goal_total = scalar(c, "SELECT COUNT(*) FROM fact_graduation WHERE major_id='M051'")
    check("M051 就业去向合计", exp_goal_total, sum(mj["goalDistribution"].values()))

    # 6. 课程详情（取当前学期修读人数最多的真实课程）
    print("\n[6] 课程详情")
    cid, exp_total = c.execute(
        "SELECT course_id, COUNT(*) n FROM fact_grade WHERE semester_id=? "
        "GROUP BY course_id ORDER BY n DESC LIMIT 1", (CUR,)).fetchone()
    co = http(base, f"/api/admin/course/{cid}")["data"]
    check(f"{cid} 修读人数", str(exp_total), kpi_val(co, "修读人数"))
    check(f"{cid} 成绩分布合计", exp_total, sum(b["count"] for b in co["scoreDistribution"]))

    # 7. 学生明细（取预警条数最多的学生）
    print("\n[7] 学生明细")
    sid, exp_ac = c.execute(
        "SELECT student_id, COUNT(*) n FROM fact_alert WHERE COALESCE(is_active,1)=1 GROUP BY student_id "
        "ORDER BY n DESC LIMIT 1").fetchone()
    st = http(base, f"/api/admin/student/{sid}")["data"]
    exp_scores = scalar(c, "SELECT COUNT(*) FROM fact_grade WHERE student_id=?", sid)
    check(f"{sid} 成绩条数", exp_scores, len(st["scores"]))
    check(f"{sid} 预警历史条数", exp_ac, len(st["alertHistory"]))

    # 8. 预警总览（列表条数 == 全库预警条数）
    print("\n[8] 预警总览")
    al = http(base, "/api/admin/alerts")["data"]
    check("预警列表条数", scalar(c, "SELECT COUNT(*) FROM fact_alert WHERE COALESCE(is_active,1)=1"), len(al["list"]))
    s = al["summary"]
    check("预警分级合计", len(al["list"]), s["critical"] + s["warning"] + s["info"])

    # 9. 培养方案（别名 me_safety→安全工程，学分与 DB 一致；major_id 随源数据重排，按专业名核对）
    print("\n[9] 培养方案 me_safety")
    pl = http(base, "/api/admin/curriculum/plan/me_safety")["data"]
    m = c.execute("""SELECT p.total_credits, p.required_credits FROM fact_plan_meta p
        JOIN dim_major mj ON p.major_id=mj.major_id WHERE mj.name='安全工程'""").fetchone()
    check("安全工程 总学分", m["total_credits"], pl["totalCredits"])
    check("安全工程 必修学分", m["required_credits"], pl["requiredCredits"])

    # 10. 报表中心
    print("\n[10] 报表中心")
    pg = http(base, "/api/admin/curriculum/progress/me_safety")["data"]
    check("curriculum progress version", "M014-2022", pg["planVersion"])
    exp_students = scalar(c, "SELECT COUNT(*) FROM dim_student WHERE major_id='M014' AND CAST(grade AS TEXT)='2022'")
    check("curriculum exact applicable students", exp_students, len(pg["progress"]))
    check("curriculum gap formula", True, all(
        abs(x["gapCredits"] - x["requiredGapCredits"] - x["electiveGapCredits"]) < 0.01
        for x in pg["progress"]))
    check("curriculum compliance fields", True, all(
        x["complianceStatus"] in ("合规", "不合规") and isinstance(x["complianceIssues"], list)
        for x in pg["progress"]))
    gr = http(base, "/api/admin/curriculum/graduate-requirements/me_safety")["data"]
    check("curriculum support matrix rows", 12 * len(gr["planModules"]),
          sum(len(v) for v in gr["supportMatrix"].values()))
    check("curriculum support matrix single source", "培养方案支撑矩阵数据表", gr["matrixSource"])
    check("curriculum module rule coverage", len(pg["planCourses"]), scalar(c, """SELECT COUNT(*)
        FROM fact_plan_course pc JOIN fact_plan_module_rule mr ON pc.major_id=mr.major_id
        AND CAST(pc.grade AS TEXT)=CAST(mr.grade AS TEXT) AND pc.module=mr.module
        WHERE pc.major_id='M014' AND CAST(pc.grade AS TEXT)='2022'"""))
    check("curriculum exceptions approval only", True,
          pg["exceptionRuleSummary"]["studentRecognitionsAreApprovalOnly"])
    check("curriculum exception fields", True, all(
        isinstance(x["appliedExceptions"], list) and x["recognizedCredits"] >= 0 and
        isinstance(x["courseGroupChecks"], list)
        for x in pg["progress"]))
    pg_high = http(base, "/api/admin/curriculum/progress/me_safety?" + urllib.parse.urlencode({"risk_level": "高"}))["data"]
    check("curriculum risk filter", True, all(x["riskLevel"] == "高" for x in pg_high["progress"]))
    first_student = pg["progress"][0]["studentId"] if pg["progress"] else ""
    pg_search = http(base, f"/api/admin/curriculum/progress/me_safety?keyword={first_student}")["data"]
    check("curriculum student search", first_student, pg_search["progress"][0]["studentId"])

    score = http(base, "/api/admin/reports?type=score")["data"]
    check("score 条数<=40", True, 0 < len(score) <= 40)
    exp_pr = scalar(c, """SELECT COUNT(*) FROM (SELECT course_id FROM fact_grade
        WHERE source='real' GROUP BY course_id HAVING COUNT(*)>=50)""")
    pr = http(base, "/api/admin/reports?type=passrank")["data"]
    check("passrank 条数", exp_pr, len(pr))
    attr = http(base, "/api/admin/reports?type=attrition")["data"]
    check("attrition 演示样例非空", True, len(attr) > 0)
    # 六类合成业务报表：均现算自合成真表（条数与 DB 聚合一致）
    exp_disc = scalar(c, "SELECT COUNT(DISTINCT college_id) FROM fact_discipline")
    disc = http(base, "/api/admin/reports?type=discipline")["data"]
    check("discipline 学院数", exp_disc, len(disc))
    exp_grad = scalar(c, """SELECT COUNT(*) FROM (SELECT major_id FROM fact_graduation
        GROUP BY major_id HAVING COUNT(*)>=20)""")
    grad = http(base, "/api/admin/reports?type=graduate")["data"]
    check("graduate 专业数(>=20)", exp_grad, len(grad))
    exp_exam = scalar(c, """SELECT COUNT(*) FROM (SELECT college_id FROM fact_exam_cert
        GROUP BY college_id HAVING COUNT(*)>=20)""")
    exam = http(base, "/api/admin/reports?type=exam")["data"]
    check("exam 学院数(>=20)", exp_exam, len(exam))
    exp_att = scalar(c, "SELECT COUNT(*) FROM fact_attend")
    att = http(base, "/api/admin/reports?type=attend")["data"]
    check("attend 课程数", exp_att, len(att))
    credit = http(base, "/api/admin/reports?type=credit")["data"]
    check("credit 非空", True, len(credit) > 0)
    # 边界：未知报表类型 -> 400；不存在专业培养方案 -> 404
    check("未知报表类型.code", 400, http(base, "/api/admin/reports?type=zzz")["code"])
    check("不存在培养方案.code", 404,
          http(base, "/api/admin/curriculum/plan/nonexist")["code"])

    # 11. 教学运行分析（开课/教室/调停课/教师负荷）—— 现算自真实排课+预聚合+合成调停课
    print(f"\n[11] 教学运行分析（真实学期 {REAL}）")
    co = http(base, "/api/admin/operation/courses")["data"]
    # 与接口一致：排除单学期教学班数>200的异常教师（源库通识课拆分缺陷）。
    exp_lessons = scalar(c, """SELECT COUNT(*) FROM fact_lesson l JOIN dim_course co
        ON l.course_id=co.course_id WHERE l.semester_id=? AND l.teacher_id NOT IN (
        SELECT teacher_id FROM fact_lesson WHERE semester_id=?
        GROUP BY teacher_id HAVING COUNT(*)>200)""", REAL, REAL)
    check("courses 班额分布合计==教学班数", exp_lessons, sum(x["count"] for x in co["sizeDist"]))
    exp_courses = scalar(c, """SELECT COUNT(DISTINCT l.course_id) FROM fact_lesson l
        JOIN dim_course co ON l.course_id=co.course_id WHERE l.semester_id=?
        AND l.teacher_id NOT IN (SELECT teacher_id FROM fact_lesson WHERE semester_id=?
        GROUP BY teacher_id HAVING COUNT(*)>200)""", REAL, REAL)
    check("courses 开课门数", exp_courses, co["totalCourses"])
    check("courses data quality visible", True,
          co["dataQuality"]["excludedTeachers"] >= 0 and co["dataQuality"]["excludedLessons"] >= 0)
    dq = http(base, "/api/admin/operation/data-quality?status=open")["data"]
    check("operation quality issue count", scalar(c, "SELECT COUNT(*) FROM data_quality_issue WHERE domain='operation' AND status='open'"), len(dq["list"]))
    check("operation quality affected rows", sum(x["affected_rows"] for x in dq["list"]), dq["summary"]["affectedRows"])
    first_course = co["courseList"][0]["courseId"]
    co_one = http(base, "/api/admin/operation/courses?keyword=" + urllib.parse.quote(first_course))["data"]
    check("courses single course filter", True,
          len(co_one["courseList"]) > 0 and all(first_course in x["courseId"] for x in co_one["courseList"]))

    cl = http(base, "/api/admin/operation/classroom")["data"]
    exp_bld = scalar(c, "SELECT COUNT(DISTINCT building) FROM agg_classroom_util")
    check("classroom 教学楼数", exp_bld, len(cl["buildings"]))
    check("classroom 教学楼数KPI", f"{exp_bld}栋", kpi_val(cl, "教学楼数"))
    check("classroom removed low-util KPI", True,
          all(x["label"] != "低利用率教学楼" for x in cl["kpis"]))
    check("classroom evidence level", "scenario_simulation", cl["evidenceLevel"])
    check("classroom source rows marked sim", 0,
          scalar(c, "SELECT COUNT(*) FROM agg_classroom_util WHERE source<>'sim'"))
    cap = http(base, "/api/admin/operation/capacity-slots?day=1&period=2")["data"]
    check("capacity slot filter", True,
          all(x["day"] == 1 and x["period"] == 2 for x in cap["slots"]))
    check("capacity remaining formula", True,
          all(abs(x["usedPct"] + x["remainingPct"] - 100) < 0.01 for x in cap["slots"]))
    check("capacity limitation disclosed", True, "座位" in cap["dataLimitation"])
    cap_all = http(base, "/api/admin/operation/capacity-slots")["data"]
    if cap_all["slots"]:
        target_slot = cap_all["slots"][0]
        target_building = target_slot["building"]
        rc = http(base, "/api/admin/operation/reschedule-candidates?" + urllib.parse.urlencode(
            {"day": target_slot["day"], "period": target_slot["period"], "building": target_building}))["data"]
        check("reschedule target echoed", target_building, rc["target"]["building"])
        check("reschedule decision boundary", "情景模拟辅助筛选", rc["decisionLevel"])
        check("reschedule evidence level", "scenario_simulation", rc["evidenceLevel"])
        check("reschedule unverified constraints", True, all(
            "教师目标时段空闲" in x["unverifiedConstraints"] and x["readiness"] == "待人工核验"
            for x in rc["candidates"]))

    sc = http(base, "/api/admin/operation/schedule-changes")["data"]
    check("schedule 调课次数", str(scalar(c, "SELECT COUNT(*) FROM fact_schedule_change WHERE kind='调课' AND semester_id=?", REAL)),
          kpi_val(sc, "调课次数"))
    check("schedule 原因分布合计", scalar(c, "SELECT COUNT(*) FROM fact_schedule_change WHERE semester_id=?", REAL),
          sum(x["count"] for x in sc["reasonDist"]))

    tl = http(base, "/api/admin/operation/teacher-load")["data"]
    check("teacher-load 职称分组合计==教师总数", scalar(c, "SELECT COUNT(*) FROM dim_teacher"),
          sum(x["count"] for x in tl["titleLoad"]))
    check("teacher-load 负荷分布合计==授课教师数",
          scalar(c, "SELECT COUNT(DISTINCT teacher_id) FROM agg_teacher_load WHERE semester_id=?", REAL),
          sum(x["count"] for x in tl["loadDist"]))

    # 12. 师资结构 + 教师明细
    print("\n[12] 师资结构与教师明细")
    fc = http(base, "/api/admin/faculty/structure")["data"]
    exp_prof_total = scalar(c, "SELECT COUNT(*) FROM fact_teacher_profile")
    check("faculty 专任教师总数", f"{exp_prof_total:,}人", kpi_val(fc, "专任教师总数"))
    title_card = next(x for x in fc["structure"] if x["title"] == "职称分布")
    check("faculty 职称分布合计", exp_prof_total, sum(i["value"] for i in title_card["items"]))
    tid = c.execute("SELECT teacher_id FROM fact_lesson WHERE semester_id=? AND teacher_id IS NOT NULL "
                    "GROUP BY teacher_id ORDER BY COUNT(*) DESC LIMIT 1", (CUR,)).fetchone()[0]
    fd = http(base, f"/api/admin/faculty/{tid}")["data"]
    check(f"faculty {tid} 本学期课程数",
          scalar(c, "SELECT COUNT(*) FROM fact_lesson WHERE teacher_id=? AND semester_id=?", tid, CUR),
          len(fd["currentCourses"]))
    check("faculty 不存在教师.code", 404, http(base, "/api/admin/faculty/NOEXIST")["code"])

    # 13. 学生学业分析
    print("\n[13] 学生学业分析")
    sa = http(base, "/api/admin/students/analysis")["data"]
    check("students 在籍学生", f"{scalar(c, 'SELECT COUNT(*) FROM dim_student'):,}",
          kpi_val(sa, "在籍学生"))
    check("students 群体聚类合计==有绩点学生",
          scalar(c, "SELECT COUNT(DISTINCT student_id) FROM fact_grade WHERE gpa IS NOT NULL"),
          sum(x["count"] for x in sa["clusters"]))
    check("students 挂科集中课程 0<n<=10", True, 0 < len(sa["failCourses"]) <= 10)

    # 14. 系统设置（预警规则 + 角色权限）
    print("\n[14] 系统设置")
    se = http(base, "/api/admin/settings")["data"]
    check("settings 预警规则数", scalar(c, "SELECT COUNT(*) FROM sys_alert_rule"), len(se["rules"]))
    check("settings 角色数", scalar(c, "SELECT COUNT(*) FROM sys_role"), len(se["roleData"]))
    changes = http(base, "/api/admin/settings/rule-changes")["data"]
    check("规则变更治理列表可访问", True, isinstance(changes, list))
    legacy_update = http(base, "/api/admin/settings/rules/R1", "PUT",
                         {"values": {"gpa_drop": 0.3}})
    check("旧规则直改接口已关闭", 410, legacy_update["code"])

    # 15. 成绩与预警数据质量约束
    print("\n[15] 成绩与预警数据质量")
    duplicate_grade_rows = scalar(c, """SELECT COALESCE(SUM(n-1),0) FROM (
        SELECT student_id, course_id, semester_id, lesson_id, COUNT(*) n
        FROM fact_grade WHERE source='real'
        GROUP BY student_id, course_id, semester_id, lesson_id HAVING COUNT(*)>1)""")
    check("真实成绩同键重复行", 0, duplicate_grade_rows)
    duplicate_alerts = scalar(c, """SELECT COUNT(*) FROM (
        SELECT student_id, rule_id, COUNT(*) n FROM fact_alert
        GROUP BY student_id, rule_id HAVING COUNT(*)>1)""")
    check("同一学生同一规则重复预警", 0, duplicate_alerts)
    non_enrolled_alerts = scalar(c, """SELECT COUNT(DISTINCT a.student_id)
        FROM fact_alert a JOIN dim_student s ON a.student_id=s.student_id
        WHERE s.status<>'在籍' OR s.status IS NULL""")
    check("预警仅覆盖在籍学生", 0, non_enrolled_alerts)
    unknown_rules = scalar(c, """SELECT COUNT(*) FROM fact_alert a
        LEFT JOIN sys_alert_rule r ON a.rule_id=r.rule_id WHERE r.rule_id IS NULL""")
    check("预警规则均可追溯", 0, unknown_rules)

    # 16. 预警处理闭环（查询基线；写操作由专项接口测试/浏览器回归覆盖）
    print("\n[16] 预警处理闭环")
    check("预警事件已完成初始化",
          scalar(c, "SELECT COUNT(*) FROM fact_alert"),
          scalar(c, "SELECT COUNT(*) FROM alert_event"))
    event_id = scalar(c, "SELECT MIN(event_id) FROM alert_event")
    event = http(base, f"/api/admin/alert-events/{event_id}")["data"]
    check("事件详情 eventId", event_id, event["eventId"])
    check("事件状态有效", True, event["workflowStatus"] in {
        "new", "assigned", "notified", "contacted", "supporting",
        "review_pending", "resolved", "closed"})
    check("事件已分派主责任人", True, len(event["assignees"]) > 0)
    counselor_token = http(base, "/api/auth/login", "POST",
        {"username": "counselor", "password": DEMO_PASSWORD})["data"]["token"]
    inbox = http(base, "/api/admin/alert-inbox", token=counselor_token)["data"]
    check("辅导员我的待办可用", True, inbox["total"] >= 0)
    resolved_event = scalar(c,
        "SELECT MIN(event_id) FROM alert_event WHERE workflow_status='resolved'")
    if resolved_event:
        invalid = http(base, f"/api/admin/alert-events/{resolved_event}/status",
                       "PUT", {"status": "new", "reason": "自动化非法流转测试"})
        check("已解决事件不可直接回退", 400, invalid["code"])

    print("\n[17] R2 两级候选规则")
    latest_batch = scalar(c, "SELECT MAX(batch_id) FROM alert_rule_candidate")
    candidate_total = scalar(c,
        "SELECT COUNT(*) FROM alert_rule_candidate WHERE batch_id=?", latest_batch)
    check("R2/R2W候选非空", True, candidate_total > 0)
    candidate_overlap = scalar(c, """SELECT COUNT(*) FROM (
        SELECT student_id,COUNT(DISTINCT rule_id) n FROM alert_rule_candidate
        WHERE batch_id=? GROUP BY student_id HAVING n>1)""", latest_batch)
    check("R2警告与严重互斥", 0, candidate_overlap)

    print(f"\n== 结果：通过 {_PASS} · 失败 {_FAIL} ==")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

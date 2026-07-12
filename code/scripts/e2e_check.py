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
    exp_gpa_students = scalar(c, """SELECT COUNT(*) FROM (
        SELECT student_id FROM fact_grade WHERE source='real' AND semester_id=?
        AND gpa IS NOT NULL GROUP BY student_id)""", CUR)
    check("大屏 GPA 分布覆盖当前学期有GPA学生", exp_gpa_students,
          sum(x["count"] for x in d["gpaDist"]))
    check("大屏 GPA 最高档使用开放区间", "≥3.5", d["gpaDist"][-1]["label"])
    check("大屏 学院人数合计", scalar(c, "SELECT COUNT(*) FROM dim_student"),
          sum(x["students"] for x in d["colleges"]))
    check("大屏 模拟毕业证据可见", True,
          "毕业结果" in "、".join(d["evidence"]["simulated"]))
    # 毕业率/学位率：现算自合成真表 fact_graduation（不再是估算）
    grad_total = scalar(c, "SELECT COUNT(*) FROM fact_graduation")
    grad_count = scalar(c, "SELECT SUM(graduated) FROM fact_graduation")
    degree_count = scalar(c, "SELECT SUM(degree) FROM fact_graduation")
    exp_grad = f"{round(grad_count / grad_total * 100, 1)}%（{grad_count}/{grad_total}）"
    exp_deg = f"{round(degree_count / grad_total * 100, 1)}%（{degree_count}/{grad_total}）"
    check("应届毕业率", exp_grad, kpi_val(d, "应届毕业率"))
    check("学位授予率", exp_deg, kpi_val(d, "学位授予率"))
    dashboard_college_token = http(base, "/api/auth/login", "POST",
        {"username": "college_dean", "password": DEMO_PASSWORD})["data"]["token"]
    scoped_cid_dash = scalar(c,
        "SELECT scope_id FROM sys_role_scope WHERE role_id='college_dean' LIMIT 1")
    scoped_dash = http(base, "/api/admin/dashboard", token=dashboard_college_token)["data"]
    scoped_students_dash = scalar(c, "SELECT COUNT(*) FROM dim_student WHERE college_id=?",
                                  scoped_cid_dash)
    check("大屏 学院角色学生范围", f"{scoped_students_dash:,}",
          kpi_val(scoped_dash, "在籍学生数"))
    check("大屏 学院角色范围标记", True, scoped_dash["scope"]["restricted"])
    check("大屏 学院角色仅返回本院", [scoped_cid_dash],
          [x["id"] for x in scoped_dash["colleges"]])
    scoped_gpa_students = scalar(c, """SELECT COUNT(*) FROM (
        SELECT g.student_id FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.semester_id=? AND g.gpa IS NOT NULL AND s.college_id=?
        GROUP BY g.student_id)""", CUR, scoped_cid_dash)
    check("大屏 学院角色GPA范围", scoped_gpa_students,
          sum(x["count"] for x in scoped_dash["gpaDist"]))
    scoped_course_totals_ok = all(row["totalCount"] == scalar(c, """SELECT COUNT(*)
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.is_pass IS NOT NULL AND g.semester_id=?
          AND s.college_id=? AND g.course_id=?""", CUR, scoped_cid_dash, row["id"])
        for row in scoped_dash["failCourses"])
    check("大屏 学院角色课程范围", True, scoped_course_totals_ok)
    check("大屏 拒绝无效学期", 400,
          http(base, "/api/admin/dashboard?semester=invalid")["code"])

    # 4. 学院详情 C01
    print("\n[4] 学院详情 C01")
    col = http(base, "/api/admin/college/C01")["data"]
    exp_stu = scalar(c, "SELECT COUNT(*) FROM dim_student WHERE college_id='C01'")
    check("C01 本院学生", str(exp_stu), kpi_val(col, "本院学生"))
    exp_majors = scalar(c, "SELECT COUNT(DISTINCT major_id) FROM dim_student WHERE college_id='C01'")
    check("C01 专业数", exp_majors, len(col["majors"]))
    director_token = http(base, "/api/auth/login", "POST",
        {"username": "dept_director", "password": DEMO_PASSWORD})["data"]["token"]
    director_major = scalar(c,
        "SELECT scope_id FROM sys_role_scope WHERE role_id='dept_director' LIMIT 1")
    director_college = scalar(c, "SELECT college_id FROM dim_major WHERE major_id=?", director_major)
    director_col = http(base, f"/api/admin/college/{director_college}",
                        token=director_token)["data"]
    director_students = scalar(c, "SELECT COUNT(*) FROM dim_student WHERE major_id=?",
                               director_major)
    check("学院详情 系主任学生范围", str(director_students),
          kpi_val(director_col, "范围内学生"))
    check("学院详情 系主任仅本专业", [director_major],
          [x["id"] for x in director_col["majors"]])
    other_college = scalar(c, "SELECT college_id FROM dim_college WHERE college_id<>? LIMIT 1",
                           director_college)
    check("学院详情 系主任禁止跨院", 403,
          http(base, f"/api/admin/college/{other_college}", token=director_token)["code"])

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
    counselor_scope_token = http(base, "/api/auth/login", "POST",
        {"username": "counselor", "password": DEMO_PASSWORD})["data"]["token"]
    counselor_classes = [r[0] for r in c.execute(
        "SELECT scope_id FROM sys_role_scope WHERE role_id='counselor' ORDER BY scope_id")]
    counselor_major = scalar(c, "SELECT major_id FROM dim_student WHERE class_id=? LIMIT 1",
                             counselor_classes[0])
    class_ph = ",".join("?" * len(counselor_classes))
    counselor_students = scalar(c, f"""SELECT COUNT(*) FROM dim_student
        WHERE major_id=? AND class_id IN ({class_ph})""", counselor_major, *counselor_classes)
    counselor_major_data = http(base, f"/api/admin/major/{counselor_major}",
                                token=counselor_scope_token)["data"]
    check("专业详情 辅导员班级范围", str(counselor_students),
          kpi_val(counselor_major_data, "范围内学生"))
    check("专业详情 返回正确学院编码",
          scalar(c, "SELECT college_id FROM dim_major WHERE major_id=?", counselor_major),
          counselor_major_data["collegeId"])
    counselor_college = counselor_major_data["collegeId"]
    inaccessible_major = scalar(c, f"""SELECT m.major_id FROM dim_major m
        WHERE m.college_id=? AND NOT EXISTS (SELECT 1 FROM dim_student s
          WHERE s.major_id=m.major_id AND s.class_id IN ({class_ph})) LIMIT 1""",
        counselor_college, *counselor_classes)
    if inaccessible_major:
        check("专业详情 辅导员禁止同院其他专业", 403,
              http(base, f"/api/admin/major/{inaccessible_major}",
                   token=counselor_scope_token)["code"])

    # 6. 课程详情（取当前学期修读人数最多的真实课程）
    print("\n[6] 课程详情")
    cid, exp_total = c.execute(
        "SELECT course_id, COUNT(*) n FROM fact_grade WHERE semester_id=? "
        "GROUP BY course_id ORDER BY n DESC LIMIT 1", (CUR,)).fetchone()
    co = http(base, f"/api/admin/course/{cid}")["data"]
    check(f"{cid} 修读人数", str(exp_total), kpi_val(co, "修读人数"))
    check(f"{cid} 成绩分布合计", exp_total, sum(b["count"] for b in co["scoreDistribution"]))
    scoped_course_id = scalar(c, """SELECT g.course_id FROM fact_grade g
        JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.semester_id=? AND s.college_id=?
        GROUP BY g.course_id ORDER BY COUNT(*) DESC LIMIT 1""", CUR, scoped_cid_dash)
    scoped_course_total = scalar(c, """SELECT COUNT(*) FROM fact_grade g
        JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.course_id=? AND g.semester_id=? AND s.college_id=?""",
        scoped_course_id, CUR, scoped_cid_dash)
    scoped_course = http(base, f"/api/admin/course/{scoped_course_id}",
                         token=dashboard_college_token)["data"]
    check("课程详情 学院角色修读范围", str(scoped_course_total),
          kpi_val(scoped_course, "修读人数"))
    check("课程详情 学院角色成绩分布范围", scoped_course_total,
          sum(x["count"] for x in scoped_course["scoreDistribution"]))
    check("课程详情 学院角色范围标记", True, scoped_course["scope"]["restricted"])
    outside_course = scalar(c, """SELECT co.course_id FROM dim_course co
        WHERE NOT EXISTS (SELECT 1 FROM fact_grade g JOIN dim_student s
          ON g.student_id=s.student_id WHERE g.course_id=co.course_id AND s.college_id=?)
        LIMIT 1""", scoped_cid_dash)
    if outside_course:
        check("课程详情 学院角色禁止无修读关系课程", 403,
              http(base, f"/api/admin/course/{outside_course}",
                   token=dashboard_college_token)["code"])

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

    score_payload = http(base, "/api/admin/reports?type=score")["data"]
    score = score_payload["rows"]
    check("score 条数<=40", True, 0 < len(score) <= 40)
    check("score 真实证据", "real", score_payload["evidence"]["level"])
    exp_pr = scalar(c, """SELECT COUNT(*) FROM (SELECT course_id FROM fact_grade
        WHERE source='real' GROUP BY course_id HAVING COUNT(*)>=50)""")
    pr = http(base, "/api/admin/reports?type=passrank")["data"]["rows"]
    check("passrank 条数", exp_pr, len(pr))
    attr_payload = http(base, "/api/admin/reports?type=attrition")["data"]
    attr = attr_payload["rows"]
    check("attrition 真实数据非空", True, len(attr) > 0)
    check("attrition 真实证据", "real", attr_payload["evidence"]["level"])
    # 业务报表均按事实表动态聚合，且显式返回真实/模拟证据边界。
    exp_disc = scalar(c, """SELECT COUNT(DISTINCT s.college_id) FROM fact_discipline d
        JOIN dim_student s ON d.student_id=s.student_id""")
    disc_payload = http(base, "/api/admin/reports?type=discipline")["data"]
    disc = disc_payload["rows"]
    check("discipline 学院数", exp_disc, len(disc))
    check("discipline 模拟证据", "simulated", disc_payload["evidence"]["level"])
    exp_grad = scalar(c, """SELECT COUNT(*) FROM (SELECT g.major_id FROM fact_graduation g
        JOIN dim_student s ON g.student_id=s.student_id GROUP BY g.major_id HAVING COUNT(*)>=20)""")
    grad = http(base, "/api/admin/reports?type=graduate")["data"]["rows"]
    check("graduate 专业数(>=20)", exp_grad, len(grad))
    exp_exam = scalar(c, """SELECT COUNT(*) FROM (SELECT s.college_id FROM fact_exam_cert e
        JOIN dim_student s ON e.student_id=s.student_id GROUP BY s.college_id HAVING COUNT(*)>=20)""")
    exam_payload = http(base, "/api/admin/reports?type=exam")["data"]
    exam = exam_payload["rows"]
    check("exam 学院数(>=20)", exp_exam, len(exam))
    check("exam 真实证据", "real", exam_payload["evidence"]["level"])
    exp_att = scalar(c, "SELECT COUNT(*) FROM fact_attend")
    att = http(base, "/api/admin/reports?type=attend")["data"]["rows"]
    check("attend 课程数", exp_att, len(att))
    credit_payload = http(base, "/api/admin/reports?type=credit")["data"]
    credit = credit_payload["rows"]
    check("credit 非空", True, len(credit) > 0)
    check("credit 混合证据", "mixed", credit_payload["evidence"]["level"])
    scoped_alert = http(base, "/api/admin/reports?type=alert",
                        token=counselor_scope_token)["data"]
    check("reports 辅导员预警范围", True, all(
        scalar(c, f"SELECT COUNT(*) FROM dim_student WHERE student_id=? AND class_id IN ({class_ph})",
               x["sid"], *counselor_classes) == 1 for x in scoped_alert["rows"]))
    scoped_attend = http(base, "/api/admin/reports?type=attend",
                         token=counselor_scope_token)["data"]
    check("reports 窄范围出勤不越权", [], scoped_attend["rows"])
    check("reports 窄范围出勤限制可见", True,
          bool(scoped_attend["evidence"]["limitation"]))
    check("reports 拒绝越权学院", 403,
          http(base, f"/api/admin/reports?type=score&college={other_college}",
               token=dashboard_college_token)["code"])
    check("reports 拒绝无效学期", 400,
          http(base, "/api/admin/reports?type=score&semester=invalid")["code"])
    check("reports 拒绝不适用筛选", 400,
          http(base, f"/api/admin/reports?type=credit&semester={CUR}")["code"])
    custom = http(base, "/api/admin/reports/custom?" + urllib.parse.urlencode({
        "metrics": "K001,K002,K003,K004", "dimension": "college",
        "semester": CUR,
    }))["data"]
    check("custom report 学院维度", scalar(c, "SELECT COUNT(*) FROM dim_college"),
          len(custom["rows"]))
    check("custom report 学生合计", scalar(c, "SELECT COUNT(*) FROM dim_student"),
          sum(x["students"] for x in custom["rows"]))
    check("custom report 真实证据", "real", custom["evidence"]["level"])
    custom_scoped = http(base, "/api/admin/reports/custom?metrics=K001&dimension=college",
                         token=dashboard_college_token)["data"]
    check("custom report 学院角色范围", [scoped_cid_dash],
          [x["dimensionId"] for x in custom_scoped["rows"]])
    check("custom report 拒绝未知指标", 400,
          http(base, "/api/admin/reports/custom?metrics=K999&dimension=college")["code"])
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
    check(f"faculty {tid} 本学期去重课程数",
          f"{scalar(c, 'SELECT COUNT(DISTINCT course_id) FROM fact_lesson WHERE teacher_id=? AND semester_id=?', tid, CUR)}门",
          kpi_val(fd, "本学期授课门数"))
    check(f"faculty {tid} 教学班记录总数",
          scalar(c, "SELECT COUNT(*) FROM fact_lesson WHERE teacher_id=? AND semester_id=?", tid, CUR),
          fd["currentCourseTotal"])
    check("faculty 教学班明细限制", True, len(fd["currentCourses"]) <= 100)
    check("faculty 异常教师质量问题可见", True, fd["dataQuality"] is not None)
    check("faculty 历史排课偏好样本数",
          scalar(c, "SELECT COUNT(*) FROM fact_lesson WHERE teacher_id=?", tid),
          fd["schedulePattern"]["sampleCount"])
    check("faculty 不使用模拟时段推断偏好", True,
          "不分析时段偏好" in fd["schedulePattern"]["limitation"] and
          fd["schedulePattern"]["evidenceLevel"] == "real_derived")
    check("faculty 画像模拟字段已披露", True,
          "学历学位、年龄、学缘、毕业院校、教龄" in "、".join(fc["evidence"]["simulated"]))
    team_course = c.execute("""SELECT l.course_id,c.name FROM fact_lesson l JOIN dim_course c
        ON l.course_id=c.course_id WHERE c.name IS NOT NULL GROUP BY l.course_id
        HAVING COUNT(DISTINCT l.teacher_id)>0 ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
    team_search = http(base, "/api/admin/faculty/team/search?q=" +
                       urllib.parse.quote(team_course["name"]))["data"]
    check("faculty 团队课程搜索", True,
          any(x["id"] == team_course["course_id"] for x in team_search))
    ft = http(base, f"/api/admin/faculty/team/{team_course['course_id']}")["data"]
    check("faculty 团队成员数量", len(ft["team"]), ft["totalMembers"])
    check("faculty 团队风险证据等级", "scenario_simulation", ft["evidence"]["level"])
    check("faculty 历史教室倾向标明行为推断", True,
          "历史行为统计" in ft["evidence"]["limitation"])
    check("faculty 团队建议非个人评价", True,
          "不构成个人评价" in ft["decisionBoundary"] and
          len(ft["supportSuggestions"]) > 0)
    check("faculty 团队建议均需核验", True,
          all(x["readiness"].startswith("待") for x in ft["supportSuggestions"]))
    college_token = http(base, "/api/auth/login", "POST",
        {"username": "college_dean", "password": DEMO_PASSWORD})["data"]["token"]
    scoped_college = scalar(c, """SELECT name FROM dim_college WHERE college_id=(
        SELECT scope_id FROM sys_role_scope WHERE role_id='college_dean' LIMIT 1)""")
    scoped_course = c.execute("""SELECT c.course_id,c.name FROM dim_course c JOIN fact_lesson l
        ON c.course_id=l.course_id WHERE c.dept=? AND c.name IS NOT NULL
        GROUP BY c.course_id ORDER BY COUNT(*) DESC LIMIT 1""", (scoped_college,)).fetchone()
    other_course = c.execute("""SELECT c.course_id FROM dim_course c JOIN fact_lesson l
        ON c.course_id=l.course_id WHERE c.dept<>? AND c.dept IN (SELECT name FROM dim_college)
        GROUP BY c.course_id ORDER BY COUNT(*) DESC LIMIT 1""", (scoped_college,)).fetchone()
    scoped_search = http(base, "/api/admin/faculty/team/search?q=" +
        urllib.parse.quote(scoped_course["name"]), token=college_token)["data"]
    check("faculty 学院角色可搜索本院课程", True,
          any(x["id"] == scoped_course["course_id"] for x in scoped_search))
    check("faculty 学院角色禁止跨院团队", 403,
          http(base, f"/api/admin/faculty/team/{other_course['course_id']}",
               token=college_token)["code"])
    check("faculty 不存在教师.code", 404, http(base, "/api/admin/faculty/NOEXIST")["code"])

    # 13. 学生学业分析
    print("\n[13] 学生学业分析")
    sa = http(base, "/api/admin/students/analysis")["data"]
    check("students 在籍学生", f"{scalar(c, 'SELECT COUNT(*) FROM dim_student'):,}",
          kpi_val(sa, "在籍学生"))
    check("students GPA分层合计==有绩点学生",
          scalar(c, "SELECT COUNT(DISTINCT student_id) FROM fact_grade WHERE gpa IS NOT NULL"),
          sum(x["count"] for x in sa["clusters"]))
    check("students 挂科集中课程 0<n<=10", True, 0 < len(sa["failCourses"]) <= 10)
    check("students 模拟指标边界可见", True,
          "毕业结果" in "、".join(sa["evidence"]["simulated"]))
    college_token2 = http(base, "/api/auth/login", "POST",
        {"username": "college_dean", "password": DEMO_PASSWORD})["data"]["token"]
    scoped_sa = http(base, "/api/admin/students/analysis", token=college_token2)["data"]
    scoped_cid = scalar(c, "SELECT scope_id FROM sys_role_scope WHERE role_id='college_dean' LIMIT 1")
    check("students 学院角色分析范围",
          f"{scalar(c, 'SELECT COUNT(*) FROM dim_student WHERE college_id=?', scoped_cid):,}",
          kpi_val(scoped_sa, "在籍学生"))
    scoped_students = scalar(c, "SELECT COUNT(*) FROM dim_student WHERE college_id=?", scoped_cid)
    check("students 学院角色迁移范围",
          scoped_students,
          scoped_sa["migration"]["compared"] + scoped_sa["migration"]["insufficient"])
    check("students 学院角色年级人数不越界",
          scoped_students, sum(x["students"] for x in scoped_sa["gradeGpa"]))
    migration = sa["migration"]
    check("students 迁移分类合计",
          migration["compared"],
          migration["improved"] + migration["stable"] + migration["declined"])
    check("students 迁移覆盖完整学生范围",
          scalar(c, "SELECT COUNT(*) FROM dim_student"),
          migration["compared"] + migration["insufficient"])
    fail_patterns = {x["key"]: x for x in sa["failPatterns"]}
    expected_repeat = scalar(c, """SELECT COUNT(DISTINCT student_id) FROM (
        SELECT student_id,course_id FROM fact_grade
        WHERE source='real' AND is_pass=0
        GROUP BY student_id,course_id HAVING COUNT(*)>=2)""")
    expected_retake_failed = scalar(c, """SELECT COUNT(DISTINCT student_id)
        FROM fact_grade WHERE source='real' AND is_pass=0 AND is_retake=1""")
    check("students 同课重复挂科模式口径", expected_repeat,
          fail_patterns["repeat_course"]["count"])
    check("students 重修仍未通过模式口径", expected_retake_failed,
          fail_patterns["retake_failed"]["count"])
    for pattern_key, pattern_row in fail_patterns.items():
        pattern_list = http(base, "/api/admin/students/list?pattern=" +
            urllib.parse.quote(pattern_key) + "&page=1&page_size=20")["data"]
        check(f"students 挂科模式下钻 {pattern_key}", pattern_row["count"],
              pattern_list["total"])
    scoped_patterns = {x["key"]: x["count"] for x in scoped_sa["failPatterns"]}
    scoped_repeat = http(base, "/api/admin/students/list?pattern=repeat_course&page=1&page_size=20",
                         token=college_token2)["data"]
    check("students 学院角色挂科模式下钻范围", scoped_patterns["repeat_course"],
          scoped_repeat["total"])
    if migration["fromSemester"] and migration["toSemester"]:
        for migration_key in ("improved", "stable", "declined", "insufficient"):
            query = urllib.parse.urlencode({
                "migration": migration_key,
                "from_semester": migration["fromSemester"],
                "to_semester": migration["toSemester"],
                "page": 1, "page_size": 20,
            })
            migration_list = http(base, "/api/admin/students/list?" + query)["data"]
            check(f"students 画像迁移下钻 {migration_key}", migration[migration_key],
                  migration_list["total"])
    invalid_pattern = http(base, "/api/admin/students/list?pattern=unknown")
    check("students 拒绝无效挂科模式", 400, invalid_pattern["code"])
    sl = http(base, "/api/admin/students/list?page=1&page_size=20")["data"]
    expected_list_gpa = scalar(c, """SELECT ROUND(AVG(g),2) FROM (
        SELECT student_id,AVG(gpa) g FROM fact_grade WHERE gpa IS NOT NULL GROUP BY student_id)""")
    check("students 清单均值使用完整筛选群体", expected_list_gpa, sl["summary"]["avgGpa"])
    required_list = http(base, "/api/admin/students/list?required=" +
        urllib.parse.quote("必修") + "&page=1&page_size=20")["data"]
    expected_required_gpa = scalar(c, """SELECT ROUND(AVG(g),2) FROM (
        SELECT student_id,AVG(gpa) g FROM fact_grade WHERE gpa IS NOT NULL AND is_required=1
        GROUP BY student_id)""")
    check("students 清单必修筛选进入GPA口径", expected_required_gpa,
          required_list["summary"]["avgGpa"])

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

    print("\n[17] R2 两级候选规则与规则自发现")
    latest_batch = scalar(c, "SELECT MAX(batch_id) FROM alert_rule_candidate")
    candidate_total = scalar(c,
        "SELECT COUNT(*) FROM alert_rule_candidate WHERE batch_id=?", latest_batch)
    check("R2/R2W候选非空", True, candidate_total > 0)
    candidate_overlap = scalar(c, """SELECT COUNT(*) FROM (
        SELECT student_id,COUNT(DISTINCT rule_id) n FROM alert_rule_candidate
        WHERE batch_id=? GROUP BY student_id HAVING n>1)""", latest_batch)
    check("R2警告与严重互斥", 0, candidate_overlap)
    discovered = http(base, "/api/admin/settings/rules/discovered")["data"]
    check("规则自发现真实派生证据", "real-derived", discovered["evidence"]["level"])
    check("规则自发现候选非空", True, len(discovered["pending"]) > 0)
    supported_features = {"gpa_trend", "gpa_drop_count", "total_fail", "core_fail",
                          "credit_ratio", "freshman_fail", "repeat_fail", "consecutive_drop"}
    check("规则自发现仅输出引擎可执行特征", True, all(
        c["key"] in supported_features
        for rule in discovered["pending"] for c in rule["conditions"]))
    check("规则自发现 GPA 下降方向", True, all(
        c["value"] < 0 and c["op"] == "≤"
        for rule in discovered["pending"] for c in rule["conditions"]
        if c["key"] == "gpa_trend"))
    check("规则自发现学分百分比展示与引擎值分离", True, all(
        c["value"] > 1 and 0 <= c["engineValue"] <= 1
        for rule in discovered["pending"] for c in rule["conditions"]
        if c["key"] == "credit_ratio"))
    discovery_config = http(base, "/api/admin/settings/discovery/config")["data"]
    check("规则发现配置不回传模型密钥", False,
          "cloud_api_key" in discovery_config["llm"])

    print(f"\n== 结果：通过 {_PASS} · 失败 {_FAIL} ==")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

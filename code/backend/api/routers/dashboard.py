"""数据大屏组：dashboard / college / major / course。
学籍、成绩、课程、教师与预警来自分析库真实数据；毕业、学位与就业去向来自
固定种子合成业务表并在接口和页面显式披露。默认学期为 CURRENT_SEMESTER。
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user, student_data_scope
from ..envelope import ok, ApiError
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin", tags=["dashboard"])

CUR = CURRENT_SEMESTER
# 数据为 5 分制绩点，当前真实记录最大值 4.5；最高档使用开放区间，避免“3.5-4.0”误导。
_GPA_BANDS = [("<2.0", "<2.0", 0.0), ("2.0-2.5", "2.0-2.5", 2.0),
              ("2.5-3.0", "2.5-3.0", 2.5), ("3.0-3.5", "3.0-3.5", 3.0),
              ("3.5-4.0", "≥3.5", 3.5)]


def _pct(x, nd=1):
    return f"{round((x or 0) * 100, nd)}%"


def _gpa_bucket(value: float) -> str:
    for bucket, _, lower in reversed(_GPA_BANDS):
        if value >= lower:
            return bucket
    return "<2.0"


def _rate(passed, attempts):
    """百分数通过率（1位小数）；分母为0或None时返回None，不落0。"""
    return round(passed * 100.0 / attempts, 1) if attempts else None


def _v2_pass_stats():
    """读取 V2 agg_course_pass_stat（M1 课程通过率三分层，全学期累计加权）。

    V2 库或聚合表缺失时返回 None：总览其余指标仍走 V1 正常输出，
    三分层字段输出 None 并在 coursePassRates.source 中说明，不静默混用口径。
    """
    try:
        conn = dbm.get_v2_conn()
    except Exception:
        return None
    try:
        if not dbm.scalar(conn, """SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='agg_course_pass_stat'"""):
            return None
        courses = {r["course_id"]: r for r in dbm.query(conn, """
            SELECT course_id, MAX(course_group) course_group,
              SUM(first_attempts) fa, SUM(first_pass) fp,
              SUM(makeup_attempts) ma, SUM(makeup_pass) mp,
              SUM(retake_attempts) ra, SUM(retake_pass) rp
            FROM agg_course_pass_stat GROUP BY course_id""")}
        overall = dbm.query_one(conn, """
            SELECT SUM(first_attempts) fa, SUM(first_pass) fp,
              SUM(makeup_attempts) ma, SUM(makeup_pass) mp,
              SUM(retake_attempts) ra, SUM(retake_pass) rp
            FROM agg_course_pass_stat""") or {}
        public = dbm.query_one(conn, """
            SELECT SUM(first_attempts) fa, SUM(first_pass) fp
            FROM agg_course_pass_stat WHERE course_group='公共必修'""") or {}
        return {"courses": courses, "overall": overall, "public_required": public}
    except Exception:
        return None
    finally:
        conn.close()


def _apply_kpi_config(conn: sqlite3.Connection, kpis: list[dict]) -> tuple[list[dict], bool]:
    """Apply display-only governance to registered dashboard KPIs.

    Missing rows keep their built-in defaults so a partial or legacy database never
    makes a valid KPI disappear unexpectedly.
    """
    exists = dbm.scalar(conn, """SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='sys_kpi_config'""")
    if not exists:
        return kpis, False
    rows = dbm.query(conn, """SELECT kpi_id,enabled,sort_order,color_rule,
        threshold_warn,threshold_danger FROM sys_kpi_config
        WHERE module='dashboard'""")
    config = {row["kpi_id"]: row for row in rows}
    shaped = []
    for default_order, item in enumerate(kpis, start=1):
        row = config.get(item["id"])
        if row and not bool(row["enabled"]):
            continue
        current = dict(item)
        current["sortOrder"] = row["sort_order"] if row else default_order
        if row:
            current["colorRule"] = row["color_rule"]
            current["thresholdWarn"] = row["threshold_warn"]
            current["thresholdDanger"] = row["threshold_danger"]
        shaped.append(current)
    shaped.sort(key=lambda item: (item["sortOrder"], item["id"]))
    return shaped, True


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
def dashboard(semester: Optional[str] = None,
              conn: sqlite3.Connection = Depends(get_db),
              user: dict = Depends(get_current_user)):
    cur = semester or CUR
    if not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)):
        raise ApiError("学期不存在", code=400, status_code=400)

    # 所有大屏指标统一使用同一学生授权范围，避免院级/专业/班级角色看到全校聚合。
    student_scope, scope_params = student_data_scope(user, conn, "s")
    student_where = f" WHERE {student_scope}" if student_scope else ""
    student_and = f" AND {student_scope}" if student_scope else ""
    restricted = bool(student_scope)

    students = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student s{student_where}", scope_params) or 0
    if restricted:
        courses_cur = dbm.scalar(conn, f"""SELECT COUNT(DISTINCT g.course_id)
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.semester_id=?{student_and}""", tuple([cur] + scope_params)) or 0
        teachers = dbm.scalar(conn, f"""SELECT COUNT(DISTINCT l.teacher_id)
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            JOIN fact_lesson l ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
            WHERE g.semester_id=? AND l.teacher_id IS NOT NULL{student_and}""",
            tuple([cur] + scope_params)) or 0
    else:
        courses_cur = dbm.scalar(conn,
            "SELECT COUNT(DISTINCT course_id) FROM fact_lesson WHERE semester_id=?", (cur,)) or 0
        teachers = dbm.scalar(conn, "SELECT COUNT(*) FROM dim_teacher") or 0

    alert_scope = f" AND {student_scope}" if student_scope else ""
    alert_stu = dbm.scalar(conn,
        f"SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a "
        f"JOIN dim_student s ON a.student_id=s.student_id "
        f"WHERE COALESCE(a.is_active,1)=1{alert_scope}", scope_params) or 0

    grad = dbm.query_one(conn, f"""SELECT COUNT(*) total,
        SUM(CASE WHEN f.graduated=1 THEN 1 ELSE 0 END) grad_count,
        SUM(CASE WHEN f.degree=1 THEN 1 ELSE 0 END) degree_count,
        AVG(CASE WHEN f.graduated=1 THEN 1.0 ELSE 0 END) grad_rate,
        AVG(CASE WHEN f.degree=1 THEN 1.0 ELSE 0 END) degree_rate
        FROM fact_graduation f JOIN dim_student s ON f.student_id=s.student_id
        {student_where}""", tuple(scope_params)) or {}
    grad_rate = grad.get("grad_rate") or 0
    degree_rate = grad.get("degree_rate") or 0
    teacher_label = "相关授课教师数" if restricted else "专任教师数"

    kpi = [
        {"id": "student_count", "label": "在籍学生数", "value": f"{students:,}", "formula": "当前在校本科生总数（含大一至大四）", "trend": "", "up": True, "group": "在校生"},
        {"id": "course_count", "label": "本学期开课门数", "value": f"{courses_cur:,}", "formula": "当前学期授权学生范围内修读课程去重；全校视角按教学任务去重", "trend": "", "up": True, "group": "在校生"},
        {"id": "teacher_count", "label": teacher_label, "value": f"{teachers:,}", "formula": "授权学生范围内有授课关系的教师去重；全校视角为教师维表去重", "trend": "", "up": True, "group": "在校生"},
        {"id": "alert_count", "label": "当前预警", "value": f"{alert_stu}人", "formula": "处于预警状态的学生数", "trend": "", "up": False, "group": "在校生"},
        {"id": "current_fail_rate", "label": "当前挂科率", "value": "—", "formula": "当前学期有未通过课程的去重学生数÷在籍学生数", "trend": "", "up": False, "group": "在校生"},
        {"id": "history_fail_rate", "label": "历史挂科经历率", "value": "—", "formula": "在校期间曾出现过未通过记录的去重学生数÷在籍学生数（包含后续补考或重修通过）", "trend": "", "up": False, "group": "在校生"},
        {"id": "grad_rate", "label": "应届毕业率", "value": f"{_pct(grad_rate)}（{grad.get('grad_count') or 0}/{grad.get('total') or 0}）",
         "formula": "合成毕业业务表：按期毕业生÷毕业届总数", "trend": "", "up": True, "group": "毕业生", "sub": "2022级毕业届（合成）"},
        {"id": "degree_rate", "label": "学位授予率", "value": f"{_pct(degree_rate)}（{grad.get('degree_count') or 0}/{grad.get('total') or 0}）",
         "formula": "合成毕业业务表：授予学位人数÷毕业届总数", "trend": "", "up": True, "group": "毕业生", "sub": "2022级毕业届（合成）"},
    ]

    rows = dbm.query(conn, f"""SELECT c.college_id,c.name,COUNT(s.student_id) students
        FROM dim_college c JOIN dim_student s ON s.college_id=c.college_id
        {student_where} GROUP BY c.college_id,c.name ORDER BY students DESC""", tuple(scope_params))
    term_by_col = {r["college_id"]: r for r in dbm.query(conn, f"""
        SELECT s.college_id,
            SUM(CASE WHEN g.score IS NOT NULL AND g.credits>0 THEN g.score*g.credits END)
              / NULLIF(SUM(CASE WHEN g.score IS NOT NULL AND g.credits>0 THEN g.credits END),0) avg_score,
            SUM(CASE WHEN g.is_pass=1 THEN COALESCE(g.credits,0) ELSE 0 END) passed_credits,
            SUM(COALESCE(g.credits,0)) attempted_credits
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.semester_id=? AND g.is_pass IS NOT NULL{student_and}
        GROUP BY s.college_id""", tuple([cur] + scope_params))}
    gpa_by_col = {r["college_id"]: r["avg_gpa"] for r in dbm.query(conn, f"""
        WITH student_gpa AS (
          SELECT s.college_id,g.student_id,AVG(g.gpa) student_gpa
          FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
          WHERE g.source='real' AND g.semester_id=? AND g.gpa IS NOT NULL{student_and}
          GROUP BY s.college_id,g.student_id)
        SELECT college_id,AVG(student_gpa) avg_gpa FROM student_gpa GROUP BY college_id
    """, tuple([cur] + scope_params))}
    alert_by_col = {r["college_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.college_id, COUNT(DISTINCT a.student_id) AS n
        FROM fact_alert a JOIN dim_student s ON a.student_id=s.student_id
        WHERE COALESCE(a.is_active,1)=1{student_and}
        GROUP BY s.college_id""", tuple(scope_params))}
    cur_fail_by_col = {r["college_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.college_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real' AND g.semester_id=?{student_and}
        GROUP BY s.college_id""", tuple([cur] + scope_params))}
    hist_fail_by_col = {r["college_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.college_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real'{student_and}
        GROUP BY s.college_id""", tuple(scope_params))}
    colleges = []
    for r in rows:
        a = term_by_col.get(r["college_id"], {})
        attempted = a.get("attempted_credits") or 0
        colleges.append({
            "id": r["college_id"], "name": r["name"], "students": r["students"],
            "avgScore": round(a.get("avg_score"), 1) if a.get("avg_score") is not None else None,
            "avgGpa": round(gpa_by_col.get(r["college_id"]), 2) if gpa_by_col.get(r["college_id"]) is not None else None,
            "failRate": _pct(hist_fail_by_col.get(r["college_id"], 0) / r["students"]),
            "currentFailRate": _pct(cur_fail_by_col.get(r["college_id"], 0) / r["students"]),
            "alertRate": _pct(alert_by_col.get(r["college_id"], 0) / r["students"]),
            "creditDone": round((a.get("passed_credits") or 0) / attempted * 100) if attempted else None,
        })
    scope_label = "全校"
    if restricted:
        if (
            (user.get("permission_context") or {}).get("detailScope", {}).get("type")
            == "college"
            and len(rows) == 1
        ):
            scope_label = rows[0]["name"]
        else:
            scope_label = "当前角色授权范围"

    gpa_rows = dbm.query(conn, f"""SELECT g.student_id,s.college_id,AVG(g.gpa) gpa
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.semester_id=? AND g.gpa IS NOT NULL{student_and}
        GROUP BY g.student_id,s.college_id""", tuple([cur] + scope_params))
    def _shape_gpa(values):
        counts = {bucket: 0 for bucket, _, _ in _GPA_BANDS}
        for value in values:
            counts[_gpa_bucket(value)] += 1
        total = len(values)
        return [{"range": label, "label": label, "count": counts[bucket],
                 "percent": round(counts[bucket] / total * 100) if total else 0}
                for bucket, label, _ in _GPA_BANDS]
    gpaDist = _shape_gpa([r["gpa"] for r in gpa_rows])
    gpaDistByCollege = {}
    for college_id in {r["college_id"] for r in gpa_rows}:
        gpaDistByCollege[college_id] = _shape_gpa(
            [r["gpa"] for r in gpa_rows if r["college_id"] == college_id])

    failCourses = []
    rate_map = {r["course_id"]: r for r in dbm.query(conn, """SELECT course_id,
        first_pass_rate,final_pass_rate FROM agg_course_term WHERE semester_id=?""", (cur,))}
    # M1：首次通过率改读 V2 agg_course_pass_stat（attempt_type 三分层，全学期累计加权）；
    # finalPassRate 仍取 V1 agg_course_term（deprecated，保留一个版本周期）。
    v2pass = _v2_pass_stats()
    v2_courses = (v2pass or {}).get("courses", {})
    for r in dbm.query(conn, f"""SELECT g.course_id,co.name,co.dept,COUNT(*) total,
        SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fail_count,
        AVG(g.score) avg_score,
        AVG(CASE WHEN g.score>=90 THEN 1.0 ELSE 0 END) excellent_rate
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        LEFT JOIN dim_course co ON g.course_id=co.course_id
        WHERE g.source='real' AND g.is_pass IS NOT NULL AND g.semester_id=?{student_and}
        GROUP BY g.course_id HAVING total>=30
        ORDER BY (fail_count*1.0/total) DESC LIMIT 8""", tuple([cur] + scope_params)):
        rates = rate_map.get(r["course_id"], {})
        v2c = v2_courses.get(r["course_id"]) or {}
        failCourses.append({
            "id": r["course_id"], "name": r["name"] or r["course_id"],
            "college": r["dept"] or "—",
            "failCount": r["fail_count"], "totalCount": r["total"],
            "failRate": str(round(r["fail_count"] / r["total"] * 100, 1)),
            "avgScore": round(r["avg_score"] or 0, 1),
            "excellentRate": str(round((r["excellent_rate"] or 0) * 100, 1)),
            "firstPassRate": None if restricted else _rate(v2c.get("fp"), v2c.get("fa")),
            "makeupPassRate": None if restricted else _rate(v2c.get("mp"), v2c.get("ma")),
            "retakePassRate": None if restricted else _rate(v2c.get("rp"), v2c.get("ra")),
            "courseGroup": None if restricted else v2c.get("course_group"),
            # deprecated：V1 末次通过率口径，保留一个版本周期后移除。
            "finalPassRate": None if restricted else round((rates.get("final_pass_rate") or 0) * 100, 1),
        })

    course_pass_rates = None
    if not restricted:
        overall, public = (v2pass or {}).get("overall") or {}, (v2pass or {}).get("public_required") or {}
        final_v1 = dbm.scalar(conn, """SELECT SUM(final_pass_rate*total)/SUM(total)
            FROM agg_course_term WHERE total>0""")
        course_pass_rates = {
            "firstPassRate": _rate(overall.get("fp"), overall.get("fa")),
            "makeupPassRate": _rate(overall.get("mp"), overall.get("ma")),
            "retakePassRate": _rate(overall.get("rp"), overall.get("ra")),
            "publicRequiredFirstPassRate": _rate(public.get("fp"), public.get("fa")),
            "attempts": {"first": overall.get("fa") or 0, "makeup": overall.get("ma") or 0,
                         "retake": overall.get("ra") or 0},
            # deprecated：V1 agg_course_term 末次通过率，保留一个版本周期。
            "finalPassRate": round(final_v1 * 100, 1) if final_v1 is not None else None,
            "source": ("V2 agg_course_pass_stat（grade_attempt attempt_type 三分层，"
                       "全学期累计加权，SUM(pass)/SUM(attempts)）"
                       if v2pass else "V2 agg_course_pass_stat 未构建，三分层指标暂缺"),
            "deprecatedFields": ["finalPassRate"],
        }

    total_cur = sum(cur_fail_by_col.values()) if cur_fail_by_col else 0
    total_hist = sum(hist_fail_by_col.values()) if hist_fail_by_col else 0
    kpi[4]["value"] = _pct(total_cur / students if students else 0)
    kpi[5]["value"] = _pct(total_hist / students if students else 0)
    kpi, kpi_config_applied = _apply_kpi_config(conn, kpi)

    return ok({"kpi": kpi, "colleges": colleges, "gpaDist": gpaDist,
               "gpaDistByCollege": gpaDistByCollege, "failCourses": failCourses,
               "coursePassRates": course_pass_rates,
               "kpiConfigApplied": kpi_config_applied,
               "scope": {"restricted": restricted,
                         "label": scope_label,
                         "studentCount": students},
               "evidence": {
                   "real": ["学籍、成绩、GPA、课程、教师授课关系、当前有效预警"],
                   "simulated": ["毕业结果、学位授予结果"],
                   "limitation": "毕业率和学位授予率来自固定种子合成业务表；课程学分通过占比是本学期已通过学分人次÷修读学分人次，不代表培养方案完成度。"
               }})


# ------------------------------------------------------------------ college
@router.get("/college/{college_id}")
def college_detail(college_id: str, semester: Optional[str] = None,
                   conn: sqlite3.Connection = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    cur = semester or CUR
    if not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)):
        raise ApiError("学期不存在", code=400, status_code=400)
    col = dbm.query_one(conn, "SELECT college_id,name FROM dim_college WHERE college_id=?", (college_id,))
    if not col:
        raise ApiError("学院不存在", code=404, status_code=404)
    student_scope, scope_params = student_data_scope(user, conn, "s")
    scope_and = f" AND {student_scope}" if student_scope else ""
    restricted = bool(student_scope)
    allowed = dbm.scalar(conn, f"SELECT 1 FROM dim_student s WHERE s.college_id=?{scope_and} LIMIT 1",
                         tuple([college_id] + scope_params))
    if not allowed:
        raise ApiError("无权限查看该学院", code=403, status_code=403)
    students = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student s WHERE s.college_id=?{scope_and}",
                          tuple([college_id] + scope_params)) or 0
    courses_cur = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT g.course_id) FROM fact_grade g
        JOIN dim_student s ON g.student_id=s.student_id
        WHERE s.college_id=? AND g.semester_id=?{scope_and}""",
        tuple([college_id, cur] + scope_params)) or 0
    teachers = dbm.scalar(conn, f"""SELECT COUNT(DISTINCT l.teacher_id)
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        JOIN fact_lesson l ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
        WHERE s.college_id=? AND g.semester_id=? AND l.teacher_id IS NOT NULL{scope_and}""",
        tuple([college_id, cur] + scope_params)) or 0
    alert_stu = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
        JOIN dim_student s ON a.student_id=s.student_id WHERE s.college_id=?
        AND COALESCE(a.is_active,1)=1{scope_and}""", tuple([college_id] + scope_params)) or 0
    degree_rate = dbm.scalar(conn, f"""SELECT AVG(CASE WHEN f.degree=1 THEN 1.0 ELSE 0 END)
        FROM fact_graduation f JOIN dim_student s ON f.student_id=s.student_id
        WHERE s.college_id=?{scope_and}""", tuple([college_id] + scope_params)) or 0
    hist_fail_college = dbm.scalar(conn, f"""
        SELECT ROUND(COUNT(DISTINCT g.student_id)*100.0/NULLIF(COUNT(DISTINCT s.student_id),0),1)
        FROM dim_student s LEFT JOIN fact_grade g
          ON s.student_id=g.student_id AND g.is_pass=0 AND g.source='real'
        WHERE s.college_id=?{scope_and}""", tuple([college_id] + scope_params)) or 0
    kpi = [
        {"label": "范围内学生" if restricted else "本院学生", "value": str(students), "formula": "学院条件与当前角色授权范围内的在籍学生数"},
        {"label": "本学期开课", "value": str(courses_cur), "formula": "当前学期开课门数"},
        {"label": "相关授课教师", "value": str(teachers) if teachers else "—", "formula": "当前学期为范围内学生授课的教师去重"},
        {"label": "预警学生", "value": str(alert_stu), "formula": "当前预警人数"},
        {"label": "历史挂科经历率", "value": f"{hist_fail_college}%", "formula": "在校期间曾出现过未通过记录的学生÷本院学生（包含后续补考或重修通过）"},
        {"label": "学位率", "value": _pct(degree_rate), "formula": "合成学位业务表：授予学位/范围内毕业届"},
    ]

    # 专业横向
    majors = []
    # 各专业当前挂科率 + 历史挂科率
    cur_fail_by_major = {r["major_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.major_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real' AND g.semester_id=?
          AND s.college_id=?{scope_and}
        GROUP BY s.major_id""", tuple([cur, college_id] + scope_params))}
    hist_fail_by_major = {r["major_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.major_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real' AND s.college_id=?{scope_and}
        GROUP BY s.major_id""", tuple([college_id] + scope_params))}
    for r in dbm.query(conn, f"""
        SELECT m.major_id, m.name,
               COUNT(DISTINCT s.student_id) AS students
        FROM dim_major m JOIN dim_student s ON s.major_id=m.major_id
        WHERE m.college_id=?{scope_and} GROUP BY m.major_id ORDER BY students DESC""",
        tuple([college_id] + scope_params)):
        mid = r["major_id"]
        stat = dbm.query_one(conn, f"""
            SELECT AVG(g.gpa) gpa, AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            WHERE s.major_id=? AND g.semester_id=?{scope_and}""",
            tuple([mid, cur] + scope_params)) or {}
        acnt = dbm.scalar(conn, f"""
            SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
            JOIN dim_student s ON a.student_id=s.student_id WHERE s.major_id=?
            AND COALESCE(a.is_active,1)=1{scope_and}""", tuple([mid] + scope_params)) or 0
        majors.append({
            "id": mid, "name": r["name"], "students": r["students"],
            "gpa": round(stat.get("gpa") or 0, 2),
            "failRate": _pct(hist_fail_by_major.get(mid, 0) / r["students"]),
            "currentFailRate": _pct(cur_fail_by_major.get(mid, 0) / r["students"]),
            "alertCount": acnt,
            "trend": "up" if (cur_fail_by_major.get(mid, 0) / max(r["students"],1)) > 0.06 else "down",
        })
    # 全院挂科率均值，修正各专业趋势
    col_avg_fail = sum(v for v in cur_fail_by_major.values()) / max(sum(m["students"] for m in majors), 1)
    for m in majors:
        m["trend"] = "up" if (cur_fail_by_major.get(m["id"], 0) / max(m["students"],1)) > col_avg_fail else "down"

    # 年级对比（按当前学期成绩）
    gradeCompare = []
    for r in dbm.query(conn, f"""
        SELECT s.grade,
               AVG(CASE WHEN g.is_pass=1 THEN g.credits ELSE 0 END)/NULLIF(AVG(g.credits),0) AS cd,
               AVG(g.gpa) gpa, AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE s.college_id=? AND g.semester_id=? AND s.grade IS NOT NULL{scope_and}
        GROUP BY s.grade ORDER BY s.grade DESC""", tuple([college_id, cur] + scope_params)):
        gradeCompare.append({
            "grade": f"{r['grade']}级", "creditDone": round((r["cd"] or 0) * 100),
            "gpaAvg": f"{round(r['gpa'] or 0, 2)}", "failRate": _pct(r["fr"]),
        })

    failCourses = _college_fail_courses(conn, college_id, cur, scope_and, scope_params, restricted=restricted)
    return ok({"name": col["name"], "kpi": kpi, "majors": majors,
               "gradeCompare": gradeCompare, "failCourses": failCourses,
               "scope": {"restricted": restricted,
                         "label": "当前角色授权范围" if restricted else "全院"},
               "evidence": {"real": ["真实学籍、成绩、课程、教师授课关系、当前有效预警"],
                            "simulated": ["学位授予结果"],
                            "limitation": "学位率来自固定种子合成业务表；年级课程学分通过占比不等同于培养方案完成度。"}})


def _college_fail_courses(conn, college_id, cur, scope_and="", scope_params=None,
                          limit=6, restricted=False):
    scope_params = scope_params or []
    cr_map = {}
    for r in dbm.query(conn,
        "SELECT course_id, first_pass_rate, final_pass_rate FROM agg_course_term "
        "WHERE semester_id=? AND first_pass_rate IS NOT NULL", (cur,)):
        cr_map[r["course_id"]] = (r["first_pass_rate"], r["final_pass_rate"])
    # M1：firstPassRate 改读 V2 agg_course_pass_stat 三分层（全学期累计加权）；
    # finalPassRate 仍取 V1（deprecated，保留一个版本周期）。
    v2_courses = (_v2_pass_stats() or {}).get("courses", {})
    out = []
    for r in dbm.query(conn, f"""
        SELECT g.course_id, co.name, co.credits,
               COUNT(*) total, SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc,
               AVG(g.score) av
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        JOIN dim_course co ON g.course_id=co.course_id
        WHERE g.source='real' AND s.college_id=? AND g.semester_id=?{scope_and}
        GROUP BY g.course_id HAVING total>=15
        ORDER BY (fc*1.0/total) DESC LIMIT ?""",
        tuple([college_id, cur] + scope_params + [limit])):
        fpr, lpr = cr_map.get(r["course_id"], (None, None))
        v2c = v2_courses.get(r["course_id"]) or {}
        out.append({
            "id": r["course_id"], "name": r["name"] or r["course_id"],
            "failCount": r["fc"], "totalCount": r["total"],
            "failRate": str(round(r["fc"] / r["total"] * 100, 1)),
            "avgScore": round(r["av"] or 0, 1), "credits": r["credits"],
            "firstPassRate": None if restricted else _rate(v2c.get("fp"), v2c.get("fa")),
            "makeupPassRate": None if restricted else _rate(v2c.get("mp"), v2c.get("ma")),
            "retakePassRate": None if restricted else _rate(v2c.get("rp"), v2c.get("ra")),
            "courseGroup": None if restricted else v2c.get("course_group"),
            # deprecated：V1 末次通过率口径，保留一个版本周期后移除。
            "finalPassRate": None if restricted else (round((lpr or 0) * 100, 1) if lpr is not None else None),
        })
    return out


# ------------------------------------------------------------------ major
@router.get("/major/{major_id}")
def major_detail(major_id: str, semester: Optional[str] = None,
                 conn: sqlite3.Connection = Depends(get_db),
                 user: dict = Depends(get_current_user)):
    cur = semester or CUR
    if not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)):
        raise ApiError("学期不存在", code=400, status_code=400)
    mj = dbm.query_one(conn, """
        SELECT m.major_id, m.name, m.college_id, c.name AS college
        FROM dim_major m LEFT JOIN dim_college c ON m.college_id=c.college_id
        WHERE m.major_id=?""", (major_id,))
    if not mj:
        raise ApiError("专业不存在", code=404, status_code=404)
    student_scope, scope_params = student_data_scope(user, conn, "s")
    scope_and = f" AND {student_scope}" if student_scope else ""
    restricted = bool(student_scope)
    students = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student s WHERE s.major_id=?{scope_and}",
                          tuple([major_id] + scope_params)) or 0
    if restricted and not students:
        raise ApiError("无权限查看该专业", code=403, status_code=403)
    alert_stu = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
        JOIN dim_student s ON a.student_id=s.student_id WHERE s.major_id=?
        AND COALESCE(a.is_active,1)=1{scope_and}""", tuple([major_id] + scope_params)) or 0
    total_req = dbm.scalar(conn, "SELECT total_req FROM fact_major_req WHERE major_id=?", (major_id,))
    earned_avg = dbm.scalar(conn, f"""SELECT AVG(f.earned_credits)
        FROM fact_graduation f JOIN dim_student s ON f.student_id=s.student_id
        WHERE s.major_id=?{scope_and}""", tuple([major_id] + scope_params)) or 0
    cd = (earned_avg / total_req) if total_req else 0
    cd = min(cd, 1.0)
    gr = dbm.query_one(conn, f"""SELECT AVG(CASE WHEN f.graduated=1 THEN 1.0 ELSE 0 END) grad_rate
        FROM fact_graduation f JOIN dim_student s ON f.student_id=s.student_id
        WHERE s.major_id=?{scope_and}""", tuple([major_id] + scope_params)) or {}
    grad_rate = gr.get("grad_rate")
    kpi = [
        {"label": "范围内学生" if restricted else "在校生", "value": str(students), "formula": "专业条件与当前角色授权范围内的学生数"},
        {"label": "培养方案完成率", "value": _pct(cd), "formula": "合成毕业业务表已修学分/真实培养方案应修总学分；无方案时不可精确解释"},
        {"label": "预警学生", "value": str(alert_stu), "formula": "当前预警人数"},
        {"label": "毕业率", "value": _pct(grad_rate) if grad_rate is not None else "—",
         "formula": "合成毕业业务表：按期毕业/范围内毕业届"},
    ]

    gradeDetail = []
    grade_rows = dbm.query(conn, f"""SELECT s.grade,COUNT(DISTINCT s.student_id) students
        FROM dim_student s WHERE s.major_id=? AND s.grade IS NOT NULL{scope_and}
        GROUP BY s.grade ORDER BY s.grade DESC""", tuple([major_id] + scope_params))
    for base in grade_rows:
        grade = base["grade"]
        r = dbm.query_one(conn, f"""SELECT AVG(g.gpa) gpa,
            COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.student_id END) failed_students,
            SUM(CASE WHEN g.is_pass=1 THEN COALESCE(g.credits,0) ELSE 0 END) passed_credits,
            SUM(COALESCE(g.credits,0)) attempted_credits
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.source='real' AND s.major_id=? AND s.grade=? AND g.semester_id=?{scope_and}""",
            tuple([major_id, grade, cur] + scope_params)) or {}
        acnt = dbm.scalar(conn, f"""
            SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
            JOIN dim_student s ON a.student_id=s.student_id
            WHERE s.major_id=? AND s.grade=? AND COALESCE(a.is_active,1)=1{scope_and}""",
            tuple([major_id, grade] + scope_params)) or 0
        courses = []
        for cr in dbm.query(conn, f"""
            SELECT g.course_id,co.name, COUNT(*) total, SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            JOIN dim_course co ON g.course_id=co.course_id
            WHERE g.source='real' AND s.major_id=? AND s.grade=? AND g.semester_id=?{scope_and}
            GROUP BY g.course_id HAVING fc>0 AND total>=8 ORDER BY (fc*1.0/total) DESC LIMIT 3""",
                tuple([major_id, grade, cur] + scope_params)):
            courses.append({"id": cr["course_id"], "name": cr["name"], "failCount": cr["fc"],
                            "totalCount": cr["total"],
                            "failRate": str(round(cr["fc"] / cr["total"] * 100, 1))})
        gradeDetail.append({
            "grade": f"{grade}级", "students": base["students"],
            "gpaAvg": f"{round(r.get('gpa') or 0, 2)}",
            "failRate": _pct((r.get("failed_students") or 0) / max(base["students"], 1)),
            "failedStudents": r.get("failed_students") or 0,
            "alertCount": acnt,
            "creditDone": round((r.get("passed_credits") or 0) * 100 / (r.get("attempted_credits") or 1)),
            "courses": courses,
        })

    goalDistribution = {"升学读研": 0, "签约就业": 0, "灵活就业": 0, "待业": 0}
    for r in dbm.query(conn, f"""SELECT f.goal, COUNT(*) n FROM fact_graduation f
        JOIN dim_student s ON f.student_id=s.student_id
        WHERE s.major_id=?{scope_and} GROUP BY f.goal""", tuple([major_id] + scope_params)):
        if r["goal"] in goalDistribution:
            goalDistribution[r["goal"]] = r["n"]
    return ok({"name": mj["name"], "college": mj["college"], "collegeId": mj["college_id"],
               "kpi": kpi, "gradeDetail": gradeDetail, "goalDistribution": goalDistribution,
               "scope": {"restricted": restricted,
                         "label": "当前角色授权范围" if restricted else "本专业"},
               "evidence": {"real": ["真实学籍、成绩、课程、当前有效预警、培养方案要求（仅覆盖专业）"],
                            "simulated": ["毕业结果、就业去向、毕业表已修学分"],
                            "limitation": "毕业率、就业去向和毕业表已修学分来自固定种子合成业务表；年级课程学分通过占比不等同于培养方案完成度。"}})


# ------------------------------------------------------------------ course
@router.get("/course/{course_id}")
def course_detail(course_id: str, semester: Optional[str] = None,
                  conn: sqlite3.Connection = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    cur = semester or CUR
    if not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)):
        raise ApiError("学期不存在", code=400, status_code=400)
    co = dbm.query_one(conn, """
        SELECT course_id, name, credits, is_required, dept FROM dim_course WHERE course_id=?""",
        (course_id,))
    if not co:
        raise ApiError("课程不存在", code=404, status_code=404)
    student_scope, scope_params = student_data_scope(user, conn, "s")
    scope_and = f" AND {student_scope}" if student_scope else ""
    restricted = bool(student_scope)
    if restricted:
        authorized = dbm.scalar(conn, f"""SELECT 1 FROM fact_grade g
            JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.course_id=?{scope_and} LIMIT 1""", tuple([course_id] + scope_params))
        if not authorized:
            raise ApiError("无权限查看该课程范围", code=403, status_code=403)
    cur_row = dbm.query_one(conn, f"""
        SELECT COUNT(*) total, AVG(g.score) av,
               SUM(CASE WHEN g.score>=90 THEN 1 ELSE 0 END) exc,
               SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.course_id=? AND g.semester_id=?{scope_and}""",
        tuple([course_id, cur] + scope_params)) or {}
    total = cur_row.get("total") or 0
    kpi = [
        {"label": "修读人数", "value": str(total), "formula": "当前学期修读学生数"},
        {"label": "平均分", "value": f"{round(cur_row.get('av') or 0, 1)}", "formula": "加权平均分", "detail": "满分100"},
        {"label": "优秀率", "value": _pct((cur_row.get("exc") or 0) / total if total else 0),
         "formula": "≥90分占比", "detail": f"{cur_row.get('exc') or 0}人≥90分"},
        {"label": "挂科率", "value": _pct((cur_row.get("fc") or 0) / total if total else 0),
         "formula": "<60分占比", "detail": f"{cur_row.get('fc') or 0}人挂科"},
    ]
    bands = [("90-100", "优秀", 90, 101), ("80-89", "良好", 80, 90), ("70-79", "中等", 70, 80),
             ("60-69", "及格", 60, 70), ("0-59", "不及格", 0, 60)]
    scoreDistribution = []
    for rng, label, lo, hi in bands:
        c = dbm.scalar(conn, f"""SELECT COUNT(*) FROM fact_grade g
            JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.source='real' AND g.course_id=? AND g.semester_id=?
            AND g.score>=? AND g.score<?{scope_and}""",
            tuple([course_id, cur, lo, hi] + scope_params)) or 0
        scoreDistribution.append({"range": rng, "label": label, "count": c,
                                  "pct": round(c / total * 100, 1) if total else 0})
    history = []
    for r in dbm.query(conn, f"""
        SELECT g.semester_id, AVG(g.score) av,
               AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr, COUNT(*) total
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.course_id=?{scope_and} GROUP BY g.semester_id
        ORDER BY g.semester_id DESC LIMIT 6""", tuple([course_id] + scope_params)):
        history.append({"semester": r["semester_id"], "avgScore": round(r["av"] or 0, 1),
                        "failRate": _pct(r["fr"]), "totalStudents": r["total"]})
    history.reverse()
    classDetail = []
    for r in dbm.query(conn, f"""
        SELECT cl.name cls, COUNT(*) total, AVG(g.score) av,
               AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr,
               GROUP_CONCAT(DISTINCT t.name) teachers
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        JOIN dim_class cl ON s.class_id=cl.class_id
        LEFT JOIN fact_lesson l ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
        LEFT JOIN dim_teacher t ON l.teacher_id=t.teacher_id
        WHERE g.source='real' AND g.course_id=? AND g.semester_id=?{scope_and}
        GROUP BY s.class_id ORDER BY total DESC LIMIT 6""",
        tuple([course_id, cur] + scope_params)):
        classDetail.append({"className": r["cls"], "students": r["total"],
                            "avgScore": round(r["av"] or 0, 1), "failRate": _pct(r["fr"]),
                            "teacher": (r["teachers"] or "—").replace(",", "、")})
    nature = "专业必修" if co["is_required"] == 1 else "选修"
    return ok({"name": co["name"], "credits": co["credits"], "type": nature,
               "college": co["dept"] or "—", "kpi": kpi,
               "scoreDistribution": scoreDistribution, "history": history,
               "classDetail": classDetail,
               "scope": {"restricted": restricted,
                         "label": "当前角色授权范围" if restricted else "全校"},
               "evidence": {"real": ["真实成绩、学籍班级、教学任务与教师"],
                            "simulated": [],
                            "limitation": "课程可跨学院修读；本页全部成绩、趋势和班级明细均按当前角色可见学生范围统计。"}})

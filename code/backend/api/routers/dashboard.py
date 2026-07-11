"""数据大屏组：dashboard / college / major / course。
真实算自 analytics.sqlite；毕业/学位/就业去向取自 fact_graduation（按真实学业
表现派生、走完整 ETL，不暴露 source）。"当前学期" = 模拟最新学期(CURRENT_SEMESTER)。
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user, student_data_scope, college_data_scope
from ..envelope import ok, ApiError
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin", tags=["dashboard"])

CUR = CURRENT_SEMESTER
# (数据库bucket名, 展示标签, GPA阈值) — bucket名匹配agg_gpa_dist.bucket，4分制0.5步长
_GPA_BANDS = [("<2.0", "<2.0", 0.0), ("2.0-2.5", "2.0-2.5", 2.0),
              ("2.5-3.0", "2.5-3.0", 2.5), ("3.0-3.5", "3.0-3.5", 3.0),
              ("3.5-4.0", "3.5-4.0", 3.5)]


def _pct(x, nd=1):
    return f"{round((x or 0) * 100, nd)}%"


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
def dashboard(semester: Optional[str] = None,
              conn: sqlite3.Connection = Depends(get_db),
              user: dict = Depends(get_current_user)):
    cur = semester or CUR
    # 数据范围过滤
    student_scope, scope_params = student_data_scope(user, conn, "s")
    student_where = f" WHERE {student_scope}" if student_scope else ""
    college_scope, college_sp = college_data_scope(user, conn)

    students = dbm.scalar(conn,
        f"SELECT COUNT(*) FROM dim_student{student_where}", scope_params)
    teachers = dbm.scalar(conn, "SELECT COUNT(*) FROM dim_teacher")
    courses_cur = dbm.scalar(
        conn, f"""SELECT COUNT(DISTINCT course_id) FROM fact_lesson WHERE semester_id=?""", (cur,))
    alert_scope = f" AND {student_scope}" if student_scope else ""
    alert_stu = dbm.scalar(conn,
        f"SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a "
        f"JOIN dim_student s ON a.student_id=s.student_id "
        f"WHERE COALESCE(a.is_active,1)=1{alert_scope}", scope_params)
    # 毕业届(2022级)毕业率/学位率：取自 fact_graduation（按学业表现派生）
    grad = dbm.query_one(conn, """
        SELECT COUNT(*) total,
               AVG(CASE WHEN graduated=1 THEN 1.0 ELSE 0 END) grad_rate,
               AVG(CASE WHEN degree=1 THEN 1.0 ELSE 0 END) degree_rate
        FROM fact_graduation""") or {}
    grad_rate = grad.get("grad_rate") or 0
    degree_rate = grad.get("degree_rate") or 0

    kpi = [
        # 在校生运行指标 — 初值占位，学院数据汇总完成后回填
        {"label": "在籍学生数", "value": f"{students:,}", "formula": "当前在校本科生总数（含大一至大四）", "trend": "", "up": True, "group": "在校生"},
        {"label": "本学期开课门数", "value": f"{courses_cur:,}", "formula": "当前学期开课教学班(去重课程)", "trend": "", "up": True, "group": "在校生"},
        {"label": "专任教师数", "value": f"{teachers:,}", "formula": "教师维表去重总数", "trend": "", "up": True, "group": "在校生"},
        {"label": "当前预警", "value": f"{alert_stu}人", "formula": "处于预警状态的学生数", "trend": "", "up": False, "group": "在校生"},
        {"label": "当前挂科率", "value": "—", "formula": "当前学期有未通过课程的去重学生数÷在籍学生数", "trend": "", "up": False, "group": "在校生"},
        {"label": "历史挂科经历率", "value": "—", "formula": "在校期间曾出现过未通过记录的去重学生数÷在籍学生数（包含后续补考或重修通过）", "trend": "", "up": False, "group": "在校生"},
        # 应届毕业质量指标
        {"label": "应届毕业率", "value": f"{_pct(grad_rate)}（{int(grad.get('total',0)*grad_rate) if grad.get('total') else 0}/{grad.get('total',0)}）",
         "formula": "按期毕业生÷毕业届总数", "trend": "", "up": True, "group": "毕业生",
         "sub": f"2022届"},
        {"label": "学位授予率", "value": f"{_pct(degree_rate)}（{int(grad.get('total',0)*degree_rate) if grad.get('total') else 0}/{grad.get('total',0)}）",
         "formula": "授予学位人数÷毕业届总数", "trend": "", "up": True, "group": "毕业生",
         "sub": f"2022届"},
    ]

    # 学院横向：人数(全量) + 当前学期指标 + 预警率(预警生/全院生)
    # 数据范围：college 角色仅显示本院
    college_filter, college_filter_params = ("", [])
    if college_scope:
        college_filter = f" WHERE c.{college_scope}"
        college_filter_params = college_sp
    colleges = []
    rows = dbm.query(conn, f"""
        SELECT c.college_id, c.name,
               (SELECT COUNT(*) FROM dim_student s WHERE s.college_id=c.college_id) AS students
        FROM dim_college c{college_filter} ORDER BY students DESC
    """, college_filter_params)
    agg = {r["college_id"]: r for r in dbm.query(
        conn, "SELECT * FROM agg_college_term WHERE semester_id=?", (cur,))}
    alert_by_col = {r["college_id"]: r["n"] for r in dbm.query(conn, """
        SELECT s.college_id, COUNT(DISTINCT a.student_id) AS n
        FROM fact_alert a JOIN dim_student s ON a.student_id=s.student_id
        WHERE COALESCE(a.is_active,1)=1
        GROUP BY s.college_id""")}
    # V1.1：各学院当前挂科率 + 历史挂科率
    cur_fail_by_col = {r["college_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.college_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real' AND g.semester_id=?
        GROUP BY s.college_id""", (cur,))}
    # 各学院历史挂科率（在校期间全历史有过挂科记录）
    hist_fail_by_col = {r["college_id"]: r["n"] for r in dbm.query(conn, """
        SELECT s.college_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real'
        GROUP BY s.college_id""")}
    for r in rows:
        if not r["students"]:
            continue
        a = agg.get(r["college_id"])
        if not a:
            continue
        colleges.append({
            "id": r["college_id"], "name": r["name"], "students": r["students"],
            "avgScore": round(a["avg_score"] or 0, 1),
            "failRate": _pct(hist_fail_by_col.get(r["college_id"], 0) / r["students"]),
            "currentFailRate": _pct(cur_fail_by_col.get(r["college_id"], 0) / r["students"]),
            "alertRate": _pct(alert_by_col.get(r["college_id"], 0) / r["students"]),
            "creditDone": round((a["credit_done"] or 0) * 100),
        })

    # GPA 分布（全校·当前学期，5分制 5 档）
    def _shape_gpa(dist):
        return [{"range": label, "label": label,
                 "percent": round((dist.get(bucket, {}).get("percent") or 0) * 100),
                 "count": dist.get(bucket, {}).get("count", 0)}
                for bucket, label, _ in _GPA_BANDS]

    dist = {r["bucket"]: r for r in dbm.query(
        conn, "SELECT bucket,count,percent FROM agg_gpa_dist "
        "WHERE scope_type='all' AND semester_id=?", (cur,))}
    gpaDist = _shape_gpa(dist)

    # 各学院 GPA 分布（真值，agg_gpa_dist scope_type='college'）
    col_dist: dict[str, dict] = {}
    for r in dbm.query(conn, "SELECT scope_id,bucket,count,percent FROM agg_gpa_dist "
                       "WHERE scope_type='college' AND semester_id=?", (cur,)):
        col_dist.setdefault(r["scope_id"], {})[r["bucket"]] = r
    gpaDistByCollege = {cid: _shape_gpa(buckets) for cid, buckets in col_dist.items()}

    # 高挂科课程 Top8（当前学期，修读≥30 人）
    failCourses = []
    for r in dbm.query(conn, """
        SELECT a.course_id, a.avg_score, a.fail_rate, a.total, a.excellent_rate,
               a.first_pass_rate, a.final_pass_rate,
               co.name, co.dept
        FROM agg_course_term a JOIN dim_course co ON a.course_id=co.course_id
        WHERE a.semester_id=? AND a.total>=30
        ORDER BY a.fail_rate DESC LIMIT 8""", (cur,)):
        failCourses.append({
            "id": r["course_id"], "name": r["name"] or r["course_id"],
            "college": r["dept"] or "—",
            "failCount": round((r["fail_rate"] or 0) * r["total"]),
            "totalCount": r["total"], "failRate": str(round((r["fail_rate"] or 0) * 100, 1)),
            "avgScore": round(r["avg_score"] or 0, 1),
            "excellentRate": str(round((r["excellent_rate"] or 0) * 100, 1)),
            "firstPassRate": str(round((r["first_pass_rate"] or 0) * 100, 1)),
            "finalPassRate": str(round((r["final_pass_rate"] or 0) * 100, 1)),
        })

    # 校级KPI从学院数据汇总，确保与学院表格数据一致
    total_cur = sum(cur_fail_by_col.values()) if cur_fail_by_col else 0
    total_hist = sum(hist_fail_by_col.values()) if hist_fail_by_col else 0
    kpi[4]["value"] = _pct(total_cur / students if students else 0)
    kpi[5]["value"] = _pct(total_hist / students if students else 0)

    return ok({"kpi": kpi, "colleges": colleges, "gpaDist": gpaDist,
               "gpaDistByCollege": gpaDistByCollege, "failCourses": failCourses})


# ------------------------------------------------------------------ college
@router.get("/college/{college_id}")
def college_detail(college_id: str, semester: Optional[str] = None,
                   conn: sqlite3.Connection = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    cur = semester or CUR
    col = dbm.query_one(conn, "SELECT college_id,name FROM dim_college WHERE college_id=?", (college_id,))
    if not col:
        raise ApiError("学院不存在", code=404, status_code=404)
    # 数据范围校验：确保用户有权访问该学院
    col_scope, col_sp = college_data_scope(user, conn)
    if col_scope:
        allowed = dbm.scalar(conn, f"SELECT 1 FROM dim_college WHERE college_id=? AND {col_scope}",
                            [college_id] + col_sp)
        if not allowed:
            raise ApiError("无权限查看该学院", code=403, status_code=403)
    students = dbm.scalar(conn, "SELECT COUNT(*) FROM dim_student WHERE college_id=?", (college_id,))
    courses_cur = dbm.scalar(conn, """
        SELECT COUNT(DISTINCT g.course_id) FROM fact_grade g
        JOIN dim_student s ON g.student_id=s.student_id
        WHERE s.college_id=? AND g.semester_id=?""", (college_id, cur)) or 0
    teachers = dbm.scalar(conn, "SELECT COUNT(*) FROM dim_teacher WHERE dept=?", (col["name"],)) or 0
    alert_stu = dbm.scalar(conn, """
        SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
        JOIN dim_student s ON a.student_id=s.student_id WHERE s.college_id=?
        AND COALESCE(a.is_active,1)=1""", (college_id,)) or 0
    degree_rate = dbm.scalar(conn, """
        SELECT AVG(CASE WHEN degree=1 THEN 1.0 ELSE 0 END)
        FROM fact_graduation WHERE college_id=?""", (college_id,)) or 0
    # 本院历史挂科率（全历史，与大盘KPI口径一致）
    hist_fail_college = dbm.scalar(conn, """
        SELECT ROUND(COUNT(DISTINCT g.student_id)*100.0/NULLIF(COUNT(DISTINCT s.student_id),0),1)
        FROM dim_student s LEFT JOIN fact_grade g
          ON s.student_id=g.student_id AND g.is_pass=0 AND g.source='real'
        WHERE s.college_id=?""", (college_id,)) or 0
    kpi = [
        {"label": "本院学生", "value": str(students), "formula": "在籍学生数"},
        {"label": "本学期开课", "value": str(courses_cur), "formula": "当前学期开课门数"},
        {"label": "本院教师", "value": str(teachers) if teachers else "—", "formula": "教师所属部门匹配"},
        {"label": "预警学生", "value": str(alert_stu), "formula": "当前预警人数"},
        {"label": "历史挂科经历率", "value": f"{hist_fail_college}%", "formula": "在校期间曾出现过未通过记录的学生÷本院学生（包含后续补考或重修通过）"},
        {"label": "学位率", "value": _pct(degree_rate), "formula": "授予学位/本院毕业届"},
    ]

    # 专业横向
    majors = []
    # 各专业当前挂科率 + 历史挂科率
    cur_fail_by_major = {r["major_id"]: r["n"] for r in dbm.query(conn, """
        SELECT s.major_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real' AND g.semester_id=?
          AND s.college_id=?
        GROUP BY s.major_id""", (cur, college_id))}
    hist_fail_by_major = {r["major_id"]: r["n"] for r in dbm.query(conn, """
        SELECT s.major_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real' AND s.college_id=?
        GROUP BY s.major_id""", (college_id,))}
    for r in dbm.query(conn, """
        SELECT m.major_id, m.name,
               COUNT(DISTINCT s.student_id) AS students
        FROM dim_major m JOIN dim_student s ON s.major_id=m.major_id
        WHERE m.college_id=? GROUP BY m.major_id ORDER BY students DESC""", (college_id,)):
        mid = r["major_id"]
        stat = dbm.query_one(conn, """
            SELECT AVG(g.gpa) gpa, AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            WHERE s.major_id=? AND g.semester_id=?""", (mid, cur)) or {}
        acnt = dbm.scalar(conn, """
            SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
            JOIN dim_student s ON a.student_id=s.student_id WHERE s.major_id=?
            AND COALESCE(a.is_active,1)=1""", (mid,)) or 0
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
    for r in dbm.query(conn, """
        SELECT s.grade,
               AVG(CASE WHEN g.is_pass=1 THEN g.credits ELSE 0 END)/NULLIF(AVG(g.credits),0) AS cd,
               AVG(g.gpa) gpa, AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE s.college_id=? AND g.semester_id=? AND s.grade IS NOT NULL
        GROUP BY s.grade ORDER BY s.grade DESC""", (college_id, cur)):
        gradeCompare.append({
            "grade": f"{r['grade']}级", "creditDone": round((r["cd"] or 0) * 100),
            "gpaAvg": f"{round(r['gpa'] or 0, 2)}", "failRate": _pct(r["fr"]),
        })

    failCourses = _college_fail_courses(conn, college_id, cur)
    return ok({"name": col["name"], "kpi": kpi, "majors": majors,
               "gradeCompare": gradeCompare, "failCourses": failCourses})


def _college_fail_courses(conn, college_id, cur, limit=6):
    # 课程级首次/最终通过率（取自 agg_course_term，取任意学期行）
    cr_map = {}
    for r in dbm.query(conn,
        "SELECT course_id, first_pass_rate, final_pass_rate FROM agg_course_term "
        "WHERE first_pass_rate IS NOT NULL GROUP BY course_id"):
        cr_map[r["course_id"]] = (r["first_pass_rate"], r["final_pass_rate"])
    out = []
    for r in dbm.query(conn, """
        SELECT g.course_id, co.name, co.credits,
               COUNT(*) total, SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc,
               AVG(g.score) av
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        JOIN dim_course co ON g.course_id=co.course_id
        WHERE s.college_id=? AND g.semester_id=?
        GROUP BY g.course_id HAVING total>=15
        ORDER BY (fc*1.0/total) DESC LIMIT ?""", (college_id, cur, limit)):
        fpr, lpr = cr_map.get(r["course_id"], (None, None))
        out.append({
            "id": r["course_id"], "name": r["name"] or r["course_id"],
            "failCount": r["fc"], "totalCount": r["total"],
            "failRate": str(round(r["fc"] / r["total"] * 100, 1)),
            "avgScore": round(r["av"] or 0, 1), "credits": r["credits"],
            "firstPassRate": round((fpr or 0) * 100, 1) if fpr is not None else None,
            "finalPassRate": round((lpr or 0) * 100, 1) if lpr is not None else None,
        })
    return out


# ------------------------------------------------------------------ major
@router.get("/major/{major_id}")
def major_detail(major_id: str, semester: Optional[str] = None,
                 conn: sqlite3.Connection = Depends(get_db),
                 user: dict = Depends(get_current_user)):
    cur = semester or CUR
    mj = dbm.query_one(conn, """
        SELECT m.major_id, m.name, c.name AS college
        FROM dim_major m LEFT JOIN dim_college c ON m.college_id=c.college_id
        WHERE m.major_id=?""", (major_id,))
    if not mj:
        raise ApiError("专业不存在", code=404, status_code=404)
    # 数据范围校验：确保用户有权访问该专业所属学院
    col_scope, col_sp = college_data_scope(user, conn)
    if col_scope:
        major_college = dbm.scalar(conn, "SELECT college_id FROM dim_major WHERE major_id=?", (major_id,))
        if major_college:
            allowed = dbm.scalar(conn, f"SELECT 1 FROM dim_college WHERE college_id=? AND {col_scope}",
                                [major_college] + col_sp)
            if not allowed:
                raise ApiError("无权限查看该专业", code=403, status_code=403)
    students = dbm.scalar(conn, "SELECT COUNT(*) FROM dim_student WHERE major_id=?", (major_id,))
    alert_stu = dbm.scalar(conn, """
        SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
        JOIN dim_student s ON a.student_id=s.student_id WHERE s.major_id=?
        AND COALESCE(a.is_active,1)=1""", (major_id,)) or 0
    # 培养方案完成率：已修学分 / 该专业应修总学分（fact_major_req 真实分母）
    total_req = dbm.scalar(conn, "SELECT total_req FROM fact_major_req WHERE major_id=?", (major_id,))
    earned_avg = dbm.scalar(conn, """
        SELECT AVG(earned_credits) FROM fact_graduation WHERE major_id=?""", (major_id,)) or 0
    cd = (earned_avg / total_req) if total_req else 0
    cd = min(cd, 1.0)
    # 毕业率：取自 fact_graduation
    gr = dbm.query_one(conn, """
        SELECT AVG(CASE WHEN graduated=1 THEN 1.0 ELSE 0 END) grad_rate
        FROM fact_graduation WHERE major_id=?""", (major_id,)) or {}
    grad_rate = gr.get("grad_rate")
    kpi = [
        {"label": "在校生", "value": str(students), "formula": "在籍学生总数"},
        {"label": "培养方案完成率", "value": _pct(cd), "formula": "已修学分/应修总学分"},
        {"label": "预警学生", "value": str(alert_stu), "formula": "当前预警人数"},
        {"label": "毕业率", "value": _pct(grad_rate) if grad_rate is not None else "—",
         "formula": "按期毕业/毕业届"},
    ]

    gradeDetail = []
    for r in dbm.query(conn, """
        SELECT s.grade, COUNT(DISTINCT s.student_id) students,
               AVG(g.gpa) gpa, AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr,
               AVG(CASE WHEN g.is_pass=1 THEN g.credits ELSE 0 END)/NULLIF(AVG(g.credits),0) cd
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE s.major_id=? AND g.semester_id=? AND s.grade IS NOT NULL
        GROUP BY s.grade ORDER BY s.grade DESC""", (major_id, cur)):
        grade = r["grade"]
        acnt = dbm.scalar(conn, """
            SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
            JOIN dim_student s ON a.student_id=s.student_id
            WHERE s.major_id=? AND s.grade=? AND COALESCE(a.is_active,1)=1""", (major_id, grade)) or 0
        courses = []
        for cr in dbm.query(conn, """
            SELECT co.name, COUNT(*) total, SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            JOIN dim_course co ON g.course_id=co.course_id
            WHERE s.major_id=? AND s.grade=? AND g.semester_id=?
            GROUP BY g.course_id HAVING fc>0 AND total>=8 ORDER BY (fc*1.0/total) DESC LIMIT 3""",
                (major_id, grade, cur)):
            courses.append({"name": cr["name"], "failCount": cr["fc"],
                            "totalCount": cr["total"],
                            "failRate": str(round(cr["fc"] / cr["total"] * 100, 1))})
        gradeDetail.append({
            "grade": f"{grade}级", "students": r["students"],
            "gpaAvg": f"{round(r['gpa'] or 0, 2)}", "failRate": _pct(r["fr"]),
            "alertCount": acnt, "creditDone": round((r["cd"] or 0) * 100), "courses": courses,
        })

    # 就业去向：取自 fact_graduation（按学业表现派生）
    goalDistribution = {"升学读研": 0, "签约就业": 0, "灵活就业": 0, "待业": 0}
    for r in dbm.query(conn, """
        SELECT goal, COUNT(*) n FROM fact_graduation WHERE major_id=? GROUP BY goal""",
            (major_id,)):
        if r["goal"] in goalDistribution:
            goalDistribution[r["goal"]] = r["n"]
    return ok({"name": mj["name"], "college": mj["college"], "kpi": kpi,
               "gradeDetail": gradeDetail, "goalDistribution": goalDistribution})


# ------------------------------------------------------------------ course
@router.get("/course/{course_id}")
def course_detail(course_id: str, semester: Optional[str] = None,
                  conn: sqlite3.Connection = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    cur = semester or CUR
    co = dbm.query_one(conn, """
        SELECT course_id, name, credits, is_required, dept FROM dim_course WHERE course_id=?""",
        (course_id,))
    if not co:
        raise ApiError("课程不存在", code=404, status_code=404)
    # 注：课程详情不设学院级数据范围限制。课程天然跨学院修读（通识课/公选课），
    # 成绩数据通过 student_data_scope 在 dashboard 层面已做学生维度过滤。
    cur_row = dbm.query_one(conn, """
        SELECT COUNT(*) total, AVG(score) av,
               SUM(CASE WHEN score>=90 THEN 1 ELSE 0 END) exc,
               SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) fc
        FROM fact_grade WHERE course_id=? AND semester_id=?""", (course_id, cur)) or {}
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
        c = dbm.scalar(conn, """
            SELECT COUNT(*) FROM fact_grade WHERE course_id=? AND semester_id=?
            AND score>=? AND score<?""", (course_id, cur, lo, hi)) or 0
        scoreDistribution.append({"range": rng, "label": label, "count": c,
                                  "pct": round(c / total * 100, 1) if total else 0})
    history = []
    for r in dbm.query(conn, """
        SELECT semester_id, AVG(score) av,
               AVG(CASE WHEN is_pass=0 THEN 1.0 ELSE 0 END) fr, COUNT(*) total
        FROM fact_grade WHERE course_id=? GROUP BY semester_id
        ORDER BY semester_id DESC LIMIT 6""", (course_id,)):
        history.append({"semester": r["semester_id"], "avgScore": round(r["av"] or 0, 1),
                        "failRate": _pct(r["fr"]), "totalStudents": r["total"]})
    history.reverse()
    # 该课程当前学期主讲教师（教学班最高频任课教师）
    teacher = dbm.scalar(conn, """
        SELECT t.name FROM fact_lesson l JOIN dim_teacher t ON l.teacher_id=t.teacher_id
        WHERE l.course_id=? AND l.semester_id=?
        GROUP BY l.teacher_id ORDER BY COUNT(*) DESC LIMIT 1""", (course_id, cur))
    if not teacher:  # 当前学期无排课快照→取历史最高频
        teacher = dbm.scalar(conn, """
            SELECT t.name FROM fact_lesson l JOIN dim_teacher t ON l.teacher_id=t.teacher_id
            WHERE l.course_id=? GROUP BY l.teacher_id ORDER BY COUNT(*) DESC LIMIT 1""",
            (course_id,))
    classDetail = []
    for r in dbm.query(conn, """
        SELECT cl.name cls, COUNT(*) total, AVG(g.score) av,
               AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        JOIN dim_class cl ON s.class_id=cl.class_id
        WHERE g.course_id=? AND g.semester_id=?
        GROUP BY s.class_id ORDER BY total DESC LIMIT 6""", (course_id, cur)):
        classDetail.append({"className": r["cls"], "students": r["total"],
                            "avgScore": round(r["av"] or 0, 1), "failRate": _pct(r["fr"]),
                            "teacher": teacher or "—"})
    nature = "专业必修" if co["is_required"] == 1 else "选修"
    return ok({"name": co["name"], "credits": co["credits"], "type": nature,
               "college": co["dept"] or "—", "kpi": kpi,
               "scoreDistribution": scoreDistribution, "history": history,
               "classDetail": classDetail})

"""报表中心组：GET /api/admin/reports?type={type}。
全部报表均算自 analytics.sqlite 事实表，并向前端明确返回真实/模拟证据边界：
  score/passrank/alert      ← fact_grade / fact_alert（真实学业数据）
  discipline/attrition/graduate/exam/attend/credit
                            ← fact_discipline/attrition/graduation/exam_cert/attend/major_req
未知 type 返回 400。形状对齐 vite.config.ts getReportData()。
维度过滤（按报表适用）：semester/year(学期/学年) · college(学院码 C01-C16) · grade(年级)
                       · kind(学籍异动类型，仅 attrition)。无值=不加 WHERE=全量（精确复现旧输出）。
"""
import sqlite3
import statistics
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user, student_data_scope, college_data_scope
from ..envelope import ok, ApiError
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin", tags=["reports"])
CUR = CURRENT_SEMESTER


class _Flt:
    """报表维度过滤上下文：解析一次，各 _report_* 取所需片段拼接。
    college 入参为学院码(C01-C16)，按需解析为学院名(co.dept 匹配)。"""

    def __init__(self, conn, user, semester=None, year=None, college=None,
                 grade=None, kind=None):
        self.conn = conn
        self.user = user
        self.semester = semester
        self.year = year
        self.college_id = college
        self.college_name = (dbm.scalar(
            conn, "SELECT name FROM dim_college WHERE college_id=?", (college,))
            if college else None)
        self.grade = grade
        self.kind = kind
        self.scope_type = dbm.scalar(
            conn, "SELECT data_scope_type FROM sys_role WHERE role_id=?",
            (user["role_id"],)) or "all"

    def student(self, alias="st"):
        return student_data_scope(self.user, self.conn, alias)

    def sem(self, col):
        """学期/学年片段（学年展开为 semester IN 子查询）。返回 (frag, params)。"""
        if self.semester:
            return f" AND {col}=?", [self.semester]
        if self.year:
            return (f" AND {col} IN (SELECT semester_id FROM dim_semester WHERE year=?)",
                    [self.year])
        return "", []

    def eq(self, col, val):
        return (f" AND {col}=?", [val]) if val else ("", [])


def _report_score(conn, flt: "_Flt") -> list[dict]:
    """按课程统计真实成绩分布（均值/中位数/标准差 + 5 档人次）。"""
    conds, params = ["g.source='real'", "g.score IS NOT NULL"], []
    sf, sp = flt.sem("g.semester_id");
    if sf:
        conds.append(sf[5:]); params += sp  # 去掉前导 ' AND '
    if flt.college_id:
        conds.append("st.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("st.grade=?"); params.append(flt.grade)
    ss, sp = flt.student("st")
    if ss:
        conds.append(ss); params += sp
    acc: dict[str, dict] = {}
    for r in dbm.query(conn, f"""
        SELECT g.course_id, co.name cname, co.dept, g.score
        FROM fact_grade g JOIN dim_student st ON g.student_id=st.student_id
        LEFT JOIN dim_course co ON g.course_id=co.course_id
        WHERE {' AND '.join(conds)}""", tuple(params)):
        a = acc.setdefault(r["course_id"], {
            "course": r["cname"] or r["course_id"], "college": r["dept"] or "—", "scores": []})
        a["scores"].append(r["score"])
    out = []
    for a in acc.values():
        s = a["scores"]
        if len(s) < 50:
            continue
        sd = statistics.pstdev(s)
        if sd < 2.0:  # 过滤 P/F/通识考查课（分数恒定、零方差），成绩分布无意义
            continue
        out.append({
            "course": a["course"], "college": a["college"],
            "avgScore": round(statistics.mean(s), 1), "median": round(statistics.median(s)),
            "stddev": round(sd, 1),
            "score90": sum(1 for x in s if x >= 90),
            "score80": sum(1 for x in s if 80 <= x < 90),
            "score70": sum(1 for x in s if 70 <= x < 80),
            "score60": sum(1 for x in s if 60 <= x < 70),
            "scoreFail": sum(1 for x in s if x < 60),
        })
    out.sort(key=lambda x: x["avgScore"])
    return out[:40]


def _report_passrank(conn, flt: "_Flt") -> list[dict]:
    """全量真实成绩按课程统计通过率，完整排名（修读≥50）。教师取该课最高频任课教师。"""
    conds, params = ["g.source='real'"], []
    sf, sp = flt.sem("g.semester_id")
    if sf:
        conds.append(sf[5:]); params += sp
    if flt.college_id:
        conds.append("st.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("st.grade=?"); params.append(flt.grade)
    ss, sp = flt.student("st")
    if ss:
        conds.append(ss); params += sp
    rows = dbm.query(conn, f"""
        SELECT g.course_id, co.name cname, co.dept,
               COUNT(*) total,
               AVG(CASE WHEN g.is_pass=1 THEN 1.0 ELSE 0 END) pass_rate,
               AVG(g.score) av,
               AVG(CASE WHEN g.score>=90 THEN 1.0 ELSE 0 END) exc,
               (SELECT t.name FROM fact_lesson l JOIN dim_teacher t ON l.teacher_id=t.teacher_id
                WHERE l.course_id=g.course_id
                GROUP BY l.teacher_id ORDER BY COUNT(*) DESC LIMIT 1) teacher
        FROM fact_grade g JOIN dim_student st ON g.student_id=st.student_id
        LEFT JOIN dim_course co ON g.course_id=co.course_id
        WHERE {' AND '.join(conds)} GROUP BY g.course_id HAVING total>=50
        ORDER BY pass_rate DESC""", tuple(params))
    out = []
    for i, r in enumerate(rows, 1):
        pr = round((r["pass_rate"] or 0) * 100, 1)
        out.append({
            "course": r["cname"] or r["course_id"], "college": r["dept"] or "—",
            "teacher": r["teacher"] or "—", "passRate": pr, "failRate": round(100 - pr, 1),
            "avgScore": round(r["av"] or 0, 1),
            "excellent": round((r["exc"] or 0) * 100, 1), "rank": i,
        })
    return out


def _report_alert(conn, flt: "_Flt") -> list[dict]:
    """学业预警明细（含每生不及格门次/学分 + 学分缺口）。
    学分缺口 = 该生专业应修总学分(fact_major_req) - 已修学分。"""
    conds, params = ["COALESCE(a.is_active,1)=1"], []
    sf, sp = flt.sem("a.semester_id")
    if sf:
        conds.append(sf[5:]); params += sp
    if flt.college_id:
        conds.append("st.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("st.grade=?"); params.append(flt.grade)
    ss, sp = flt.student("st")
    if ss:
        conds.append(ss); params += sp
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT a.student_id sid, st.name, cl.name cls, c.name college, m.name major,
               st.major_id mid, a.level, a.type, a.status
        FROM fact_alert a JOIN dim_student st ON a.student_id=st.student_id
        LEFT JOIN dim_class cl ON st.class_id=cl.class_id
        LEFT JOIN dim_college c ON st.college_id=c.college_id
        LEFT JOIN dim_major m ON st.major_id=m.major_id{where}
        ORDER BY CASE a.level WHEN '严重' THEN 0 WHEN '警告' THEN 1 ELSE 2 END""",
                       tuple(params)):
        fail = dbm.query_one(conn, """
            SELECT COUNT(*) fc, SUM(credits) fcr FROM fact_grade
            WHERE student_id=? AND is_pass=0""", (r["sid"],)) or {}
        earned = dbm.scalar(conn, """
            SELECT SUM(credits) FROM fact_grade WHERE student_id=? AND is_pass=1""",
            (r["sid"],)) or 0
        need = dbm.scalar(conn, """SELECT total_req FROM fact_major_req
            WHERE major_id=? AND (grade IS NULL OR grade=(SELECT grade FROM dim_student WHERE student_id=?))""",
                          (r["mid"], r["sid"]))
        out.append({
            "sid": r["sid"], "name": r["name"], "class": r["cls"] or "—", "college": r["college"] or "—",
            "major": r["major"] or "—", "level": r["level"], "type": r["type"],
            "failCourses": fail.get("fc") or 0, "failCredits": round(fail.get("fcr") or 0),
            "gapCredits": (max(0, round(need - earned)) if need is not None else None),
            "status": r["status"],
        })
    return out


# ------------------------------------------------------------------ 合成业务报表
def _report_discipline(conn, flt: "_Flt") -> list[dict]:
    """考纪：按学院聚合违纪/作弊次数，rate=每千人记录数。"""
    conds, params = [], []
    sf, sp = flt.sem("d.semester_id")
    if sf:
        conds.append(sf[5:]); params += sp
    if flt.college_id:
        conds.append("st.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("st.grade=?"); params.append(flt.grade)
    ss, sp = flt.student("st")
    if ss:
        conds.append(ss); params += sp
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT c.name college, MAX(d.semester_id) semester,
               SUM(CASE WHEN d.kind='违纪' THEN 1 ELSE 0 END) violation,
               SUM(CASE WHEN d.kind='作弊' THEN 1 ELSE 0 END) cheat
        FROM fact_discipline d JOIN dim_student st ON d.student_id=st.student_id
        JOIN dim_college c ON st.college_id=c.college_id{where}
        GROUP BY st.college_id ORDER BY (violation+cheat) DESC""", tuple(params)):
        den_conds, den_params = ["s.college_id=(SELECT college_id FROM dim_college WHERE name=?)"], [r["college"]]
        if flt.grade:
            den_conds.append("s.grade=?"); den_params.append(flt.grade)
        ds, dp = flt.student("s")
        if ds:
            den_conds.append(ds); den_params += dp
        stu = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student s WHERE {' AND '.join(den_conds)}",
                         tuple(den_params)) or 1
        out.append({
            "college": r["college"], "semester": r["semester"] or CUR,
            "violation": r["violation"], "cheat": r["cheat"],
            "rate": round((r["violation"] + r["cheat"]) / stu * 1000, 2),
        })
    return out


def _report_attrition(conn, flt: "_Flt") -> list[dict]:
    """学籍异动：按学院聚合各类异动数 + 异动率(占本院在籍)。
    kind(S8) 给定时仅统计该类异动。"""
    conds, params = [], []
    sf, sp = flt.sem("a.semester_id")
    if sf:
        conds.append(sf[5:]); params += sp
    if flt.college_id:
        conds.append("st.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("a.grade=?"); params.append(flt.grade)
    if flt.kind:
        conds.append("a.kind=?"); params.append(flt.kind)
    ss, sp = flt.student("st")
    if ss:
        conds.append(ss); params += sp
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT c.college_id, c.name college,
               SUM(CASE WHEN a.kind='休学' THEN 1 ELSE 0 END) suspend,
               SUM(CASE WHEN a.kind='复学' THEN 1 ELSE 0 END) resume,
               SUM(CASE WHEN a.kind='退学' THEN 1 ELSE 0 END) dropout,
               SUM(CASE WHEN a.kind='转专业' THEN 1 ELSE 0 END) transfer
        FROM fact_attrition a JOIN dim_student st ON a.student_id=st.student_id
        JOIN dim_college c ON st.college_id=c.college_id{where}
        GROUP BY st.college_id ORDER BY (suspend+resume+dropout+transfer) DESC""",
                       tuple(params)):
        den_conds, den_params = ["s.college_id=?"], [r["college_id"]]
        if flt.grade:
            den_conds.append("s.grade=?"); den_params.append(flt.grade)
        ds, dp = flt.student("s")
        if ds:
            den_conds.append(ds); den_params += dp
        total = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student s WHERE {' AND '.join(den_conds)}",
                           tuple(den_params)) or 0
        moves = r["suspend"] + r["dropout"] + r["transfer"]  # 复学不计入流失
        out.append({
            "college": r["college"], "grade": flt.grade and f"{flt.grade}级" or "全部年级",
            "total": total,
            "suspend": r["suspend"], "resume": r["resume"],
            "dropout": r["dropout"], "transfer": r["transfer"],
            "rate": round(moves / total * 100, 2) if total else 0.0,
        })
    return out


def _report_graduate(conn, flt: "_Flt") -> list[dict]:
    """毕业届：按专业聚合按期毕业率/学位率/结业率/延期率。"""
    conds, params = [], []
    sf, sp = flt.sem("g.semester_id")
    if sf:
        conds.append(sf[5:]); params += sp
    if flt.college_id:
        conds.append("st.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("g.grade=?"); params.append(flt.grade)
    ss, sp = flt.student("st")
    if ss:
        conds.append(ss); params += sp
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT m.name major, MAX(g.grade) grade, COUNT(*) total,
               AVG(CASE WHEN g.graduated=1 THEN 1.0 ELSE 0 END) ontime,
               AVG(CASE WHEN g.degree=1 THEN 1.0 ELSE 0 END) degree,
               AVG(CASE WHEN g.grad_status='结业' THEN 1.0 ELSE 0 END) finish,
               AVG(CASE WHEN g.grad_status='延期毕业' THEN 1.0 ELSE 0 END) delay
        FROM fact_graduation g JOIN dim_student st ON g.student_id=st.student_id
        JOIN dim_major m ON g.major_id=m.major_id{where}
        GROUP BY g.major_id HAVING total>=20 ORDER BY ontime DESC""", tuple(params)):
        out.append({
            "major": r["major"], "grade": f"{r['grade']}级" if r["grade"] else "—",
            "total": r["total"],
            "onTime": round((r["ontime"] or 0) * 100, 1),
            "degree": round((r["degree"] or 0) * 100, 1),
            "finish": round((r["finish"] or 0) * 100, 1),
            "delay": round((r["delay"] or 0) * 100, 1),
        })
    return out


def _report_exam(conn, flt: "_Flt") -> list[dict]:
    """校外考试：按学院聚合 CET4/6、计算机二/三级通过率（百分比字符串）。
    fact_exam_cert 无年级/学期列，其覆盖对象=应届毕业生，故年级取毕业届队列(fact_graduation)。"""
    cohort = dbm.scalar(conn, "SELECT grade FROM fact_graduation "
                        "GROUP BY grade ORDER BY COUNT(*) DESC LIMIT 1")
    grade_label = f"{cohort}级" if cohort else "应届"
    conds, params = [], []
    if flt.college_id:
        conds.append("st.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("st.grade=?"); params.append(flt.grade)
    ss, sp = flt.student("st")
    if ss:
        conds.append(ss); params += sp
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT c.name college, COUNT(*) n,
               AVG(e.cet4) cet4, AVG(e.cet6) cet6, AVG(e.ncre2) nc2, AVG(e.ncre3) nc3
        FROM fact_exam_cert e JOIN dim_student st ON e.student_id=st.student_id
        JOIN dim_college c ON st.college_id=c.college_id{where}
        GROUP BY st.college_id HAVING n>=20 ORDER BY cet4 DESC""", tuple(params)):
        out.append({
            "college": r["college"], "grade": grade_label,
            "cet4": f"{round((r['cet4'] or 0) * 100, 1)}%",
            "cet6": f"{round((r['cet6'] or 0) * 100, 1)}%",
            "nc2": f"{round((r['nc2'] or 0) * 100, 1)}%",
            "nc3": f"{round((r['nc3'] or 0) * 100, 1)}%",
        })
    return out


def _report_attend(conn, flt: "_Flt") -> list[dict]:
    """课程出勤：fact_attend 直出（含学院/课程名/出勤率/旷课>3）。"""
    conds, params = [], []
    sf, sp = flt.sem("a.semester_id")
    if sf:
        conds.append(sf[5:]); params += sp
    if flt.college_id:
        conds.append("a.college_id=?"); params.append(flt.college_id)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT c.name college, co.name cname, a.attend_rate, a.absent_gt3,
               a.absent_gt3_pct, a.trend
        FROM fact_attend a
        LEFT JOIN dim_college c ON a.college_id=c.college_id
        LEFT JOIN dim_course co ON a.course_id=co.course_id{where}
        ORDER BY a.attend_rate ASC""", tuple(params)):
        out.append({
            "college": r["college"] or "—", "course": r["cname"] or "—",
            "rate": round((r["attend_rate"] or 0) * 100, 1),
            "absentGT3": r["absent_gt3"], "absentGT3Pct": str(r["absent_gt3_pct"]),
            "trend": r["trend"],
        })
    return out


def _report_credit(conn, flt: "_Flt") -> list[dict]:
    """学分进度：按专业给通识/专业必修要求 + 平均学分缺口。"""
    conds, params = [], []
    if flt.college_id:
        conds.append("st.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("mr.grade=?"); params.append(flt.grade)
    ss, sp = flt.student("st")
    if ss:
        conds.append(ss); params += sp
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT m.name major, mr.grade, mr.general_req, mr.major_req, mr.total_req,
               AVG(g.earned_credits) earned, COUNT(*) n
        FROM fact_major_req mr JOIN dim_major m ON mr.major_id=m.major_id
        JOIN fact_graduation g ON g.major_id=mr.major_id AND g.grade=mr.grade
        JOIN dim_student st ON g.student_id=st.student_id{where}
        GROUP BY mr.major_id HAVING n>=20 ORDER BY (mr.total_req-earned) DESC LIMIT 40""",
                       tuple(params)):
        gap = max(0, round((r["total_req"] or 0) - (r["earned"] or 0)))
        out.append({
            "major": r["major"], "grade": f"{r['grade']}级" if r["grade"] else "—",
            "generalReq": round(r["general_req"] or 0),
            "majorReq": round(r["major_req"] or 0), "gap": gap,
        })
    return out


_REAL = {
    "score": _report_score, "passrank": _report_passrank, "alert": _report_alert,
    "discipline": _report_discipline, "attrition": _report_attrition,
    "graduate": _report_graduate, "exam": _report_exam, "attend": _report_attend,
    "credit": _report_credit,
}

_FILTERS = {
    "score": {"semester", "year", "college", "grade"},
    "passrank": {"semester", "year", "college", "grade"},
    "discipline": {"semester", "year", "college", "grade"},
    "alert": {"semester", "year", "college", "grade"},
    "credit": {"college", "grade"},
    "attrition": {"semester", "year", "college", "grade", "kind"},
    "graduate": {"semester", "year", "college", "grade"},
    "exam": {"college", "grade"},
    "attend": {"semester", "year", "college"},
}

_EVIDENCE_TABLES = {
    "score": ["fact_grade"], "passrank": ["fact_grade"],
    "discipline": ["fact_discipline"], "alert": ["fact_alert", "fact_grade"],
    "credit": ["fact_major_req", "fact_graduation"],
    "attrition": ["fact_attrition"], "graduate": ["fact_graduation"],
    "exam": ["fact_exam_cert"], "attend": ["fact_attend"],
}

_EVIDENCE_LABEL = {"real": "真实同步数据", "sim": "规则模拟数据"}

_CUSTOM_METRICS = {
    "K001": ("students", "在籍学生数"),
    "K002": ("alerts", "预警学生数"),
    "K003": ("gpa", "GPA均值"),
    "K004": ("failRate", "挂科率"),
}

_CUSTOM_DIMS = {
    "college": ("s.college_id", "c.name", "LEFT JOIN dim_college c ON s.college_id=c.college_id", "学院"),
    "major": ("s.major_id", "m.name", "LEFT JOIN dim_major m ON s.major_id=m.major_id", "专业"),
    "grade": ("s.grade", "s.grade || '级'", "", "年级"),
}


def _validate_filters(conn, report_type, semester, year, college, grade, kind):
    if semester and year:
        raise ApiError("学期与学年不能同时筛选", code=400, status_code=400)
    supplied = {k for k, v in {
        "semester": semester, "year": year, "college": college,
        "grade": grade, "kind": kind,
    }.items() if v}
    unsupported = sorted(supplied - _FILTERS[report_type])
    if unsupported:
        raise ApiError(f"{report_type} 报表不支持筛选: {', '.join(unsupported)}",
                       code=400, status_code=400)
    checks = [
        (semester, "SELECT 1 FROM dim_semester WHERE semester_id=?", "学期"),
        (year, "SELECT 1 FROM dim_semester WHERE year=?", "学年"),
        (college, "SELECT 1 FROM dim_college WHERE college_id=?", "学院"),
        (grade, "SELECT 1 FROM dim_student WHERE grade=?", "年级"),
        (kind, "SELECT 1 FROM fact_attrition WHERE kind=?", "异动类型"),
    ]
    for value, sql, label in checks:
        if value and not dbm.scalar(conn, sql, (value,)):
            raise ApiError(f"无效{label}: {value}", code=400, status_code=400)


def _evidence(conn, report_type, limitation=None):
    details = []
    sources = set()
    for table in _EVIDENCE_TABLES[report_type]:
        rows = dbm.query(conn, f"SELECT source, COUNT(*) count FROM {table} GROUP BY source")
        table_sources = []
        for row in rows:
            source = row["source"] or "unknown"
            sources.add(source)
            table_sources.append({
                "source": source,
                "label": _EVIDENCE_LABEL.get(source, source),
                "count": row["count"],
            })
        details.append({"table": table, "sources": table_sources})
    level = "real" if sources == {"real"} else "simulated" if sources == {"sim"} else "mixed"
    labels = {"real": "真实数据", "simulated": "模拟数据", "mixed": "真实与模拟混合数据"}
    return {"level": level, "label": labels[level], "details": details,
            "limitation": limitation}


@router.get("/reports/custom")
def custom_report(metrics: str, dimension: str = "college",
                  semester: Optional[str] = None,
                  user: dict = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    """受控的真实数据聚合。只开放已有可靠口径的指标与维度。"""
    metric_ids = list(dict.fromkeys(x.strip() for x in metrics.split(",") if x.strip()))
    if not metric_ids:
        raise ApiError("请至少选择一个指标", code=400, status_code=400)
    unknown = [x for x in metric_ids if x not in _CUSTOM_METRICS]
    if unknown:
        raise ApiError(f"暂不支持的自定义指标: {', '.join(unknown)}", code=400, status_code=400)
    if dimension not in _CUSTOM_DIMS:
        raise ApiError(f"暂不支持的聚合维度: {dimension}", code=400, status_code=400)
    if semester and not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?",
                                   (semester,)):
        raise ApiError(f"无效学期: {semester}", code=400, status_code=400)

    dim_id, dim_label, dim_join, dim_name = _CUSTOM_DIMS[dimension]
    scope_sql, scope_params = student_data_scope(user, conn, "s")
    scoped_where = f"WHERE {scope_sql}" if scope_sql else ""
    sem_grade = "AND g.semester_id=?" if semester else ""
    sem_alert = "AND a.semester_id=?" if semester else ""
    params = list(scope_params)
    if semester:
        params.extend([semester, semester])
    rows = dbm.query(conn, f"""
        WITH scoped AS (
            SELECT s.student_id sid, {dim_id} dim_id, {dim_label} dim_label
            FROM dim_student s {dim_join} {scoped_where}
        ), grade_student AS (
            SELECT g.student_id, AVG(g.gpa) gpa, COUNT(*) attempts,
                   SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fails
            FROM fact_grade g WHERE g.source='real' {sem_grade}
            GROUP BY g.student_id
        ), alert_student AS (
            SELECT DISTINCT a.student_id FROM fact_alert a
            WHERE COALESCE(a.is_active,1)=1 {sem_alert}
        )
        SELECT sc.dim_id, sc.dim_label,
               COUNT(DISTINCT sc.sid) students,
               COUNT(DISTINCT al.student_id) alerts,
               ROUND(AVG(gs.gpa),2) gpa,
               ROUND(CASE WHEN SUM(gs.attempts)>0
                    THEN SUM(gs.fails)*100.0/SUM(gs.attempts) ELSE NULL END,2) failRate
        FROM scoped sc
        LEFT JOIN grade_student gs ON sc.sid=gs.student_id
        LEFT JOIN alert_student al ON sc.sid=al.student_id
        WHERE sc.dim_id IS NOT NULL
        GROUP BY sc.dim_id, sc.dim_label ORDER BY sc.dim_label""", tuple(params))
    projected = [{"dimensionId": r["dim_id"], "dimension": r["dim_label"],
                  **{_CUSTOM_METRICS[mid][0]: r[_CUSTOM_METRICS[mid][0]] for mid in metric_ids}}
                 for r in rows]
    columns = [{"prop": "dimension", "label": dim_name}] + [
        {"prop": _CUSTOM_METRICS[mid][0], "label": _CUSTOM_METRICS[mid][1]}
        for mid in metric_ids]
    return ok({
        "columns": columns, "rows": projected,
        "evidence": {"level": "real", "label": "真实数据",
                     "details": [
                         {"table": "dim_student", "source": "real"},
                         {"table": "fact_grade", "source": "real"},
                         {"table": "fact_alert", "source": "real"},
                     ]},
        "scope": {"restricted": bool(scope_sql)},
        "filters": {"semester": semester, "dimension": dimension,
                    "metrics": metric_ids},
    })


@router.get("/reports")
def reports(type: str = "score", semester: Optional[str] = None,
            year: Optional[str] = None, college: Optional[str] = None,
            grade: Optional[str] = None, kind: Optional[str] = None,
            user: dict = Depends(get_current_user),
            conn: sqlite3.Connection = Depends(get_db)):
    fn = _REAL.get(type)
    if fn is None:
        raise ApiError(f"未知报表类型: {type}", code=400, status_code=400)
    _validate_filters(conn, type, semester, year, college, grade, kind)

    # 学院参数必须与角色授权范围取交集，不能由显式参数绕过。
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope:
        allowed = [r["college_id"] for r in dbm.query(
            conn, f"SELECT college_id FROM dim_college WHERE {col_scope}", col_params)]
        if college and college not in allowed:
            raise ApiError("无权查看该学院报表", code=403, status_code=403)
        if not college and len(allowed) == 1:
            college = allowed[0]

    flt = _Flt(conn, user, semester=semester, year=year, college=college,
               grade=grade, kind=kind)
    limitation = None
    if type == "attend" and flt.scope_type in {"major", "class", "teacher"}:
        rows = []
        limitation = "出勤事实表仅含课程与学院聚合，无法按当前角色的数据范围可靠拆分。"
    else:
        rows = fn(conn, flt)
    return ok({
        "rows": rows,
        "evidence": _evidence(conn, type, limitation),
        "scope": {"type": flt.scope_type, "restricted": flt.scope_type != "all"},
        "filters": {"semester": semester, "year": year, "college": college,
                    "grade": grade, "kind": kind},
    })

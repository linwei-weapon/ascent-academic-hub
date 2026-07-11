"""报表中心组：GET /api/admin/reports?type={type}。
全部报表均算自 analytics.sqlite 真实/合成业务表（走完整 ETL，不暴露 source）：
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

    def __init__(self, conn, semester=None, year=None, college=None,
                 grade=None, kind=None):
        self.semester = semester
        self.year = year
        self.college_id = college
        self.college_name = (dbm.scalar(
            conn, "SELECT name FROM dim_college WHERE college_id=?", (college,))
            if college else None)
        self.grade = grade
        self.kind = kind

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
    if flt.college_name:
        conds.append("co.dept=?"); params.append(flt.college_name)
    if flt.grade:
        conds.append("g.student_id IN (SELECT student_id FROM dim_student WHERE grade=?)")
        params.append(flt.grade)
    acc: dict[str, dict] = {}
    for r in dbm.query(conn, f"""
        SELECT g.course_id, co.name cname, co.dept, g.score
        FROM fact_grade g LEFT JOIN dim_course co ON g.course_id=co.course_id
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
    if flt.college_name:
        conds.append("co.dept=?"); params.append(flt.college_name)
    if flt.grade:
        conds.append("g.student_id IN (SELECT student_id FROM dim_student WHERE grade=?)")
        params.append(flt.grade)
    rows = dbm.query(conn, f"""
        SELECT g.course_id, co.name cname, co.dept,
               COUNT(*) total,
               AVG(CASE WHEN g.is_pass=1 THEN 1.0 ELSE 0 END) pass_rate,
               AVG(g.score) av,
               AVG(CASE WHEN g.score>=90 THEN 1.0 ELSE 0 END) exc,
               (SELECT t.name FROM fact_lesson l JOIN dim_teacher t ON l.teacher_id=t.teacher_id
                WHERE l.course_id=g.course_id
                GROUP BY l.teacher_id ORDER BY COUNT(*) DESC LIMIT 1) teacher
        FROM fact_grade g LEFT JOIN dim_course co ON g.course_id=co.course_id
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
        need = dbm.scalar(conn, "SELECT total_req FROM fact_major_req WHERE major_id=?",
                          (r["mid"],)) or 165
        out.append({
            "name": r["name"], "class": r["cls"] or "—", "college": r["college"] or "—",
            "major": r["major"] or "—", "level": r["level"], "type": r["type"],
            "failCourses": fail.get("fc") or 0, "failCredits": round(fail.get("fcr") or 0),
            "gapCredits": max(0, round(need - earned)), "status": r["status"],
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
        conds.append("d.college_id=?"); params.append(flt.college_id)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT c.name college, MAX(d.semester_id) semester,
               SUM(CASE WHEN d.kind='违纪' THEN 1 ELSE 0 END) violation,
               SUM(CASE WHEN d.kind='作弊' THEN 1 ELSE 0 END) cheat,
               (SELECT COUNT(*) FROM dim_student s WHERE s.college_id=d.college_id) stu
        FROM fact_discipline d JOIN dim_college c ON d.college_id=c.college_id{where}
        GROUP BY d.college_id ORDER BY (violation+cheat) DESC""", tuple(params)):
        stu = r["stu"] or 1
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
        conds.append("a.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("a.grade=?"); params.append(flt.grade)
    if flt.kind:
        conds.append("a.kind=?"); params.append(flt.kind)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT c.college_id, c.name college,
               SUM(CASE WHEN a.kind='休学' THEN 1 ELSE 0 END) suspend,
               SUM(CASE WHEN a.kind='复学' THEN 1 ELSE 0 END) resume,
               SUM(CASE WHEN a.kind='退学' THEN 1 ELSE 0 END) dropout,
               SUM(CASE WHEN a.kind='转专业' THEN 1 ELSE 0 END) transfer
        FROM fact_attrition a JOIN dim_college c ON a.college_id=c.college_id{where}
        GROUP BY a.college_id ORDER BY (suspend+resume+dropout+transfer) DESC""",
                       tuple(params)):
        total = dbm.scalar(conn, "SELECT COUNT(*) FROM dim_student WHERE college_id=?",
                           (r["college_id"],)) or 0
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
        conds.append("g.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("g.grade=?"); params.append(flt.grade)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT m.name major, MAX(g.grade) grade, COUNT(*) total,
               AVG(CASE WHEN g.graduated=1 THEN 1.0 ELSE 0 END) ontime,
               AVG(CASE WHEN g.degree=1 THEN 1.0 ELSE 0 END) degree,
               AVG(CASE WHEN g.grad_status='结业' THEN 1.0 ELSE 0 END) finish,
               AVG(CASE WHEN g.grad_status='延期毕业' THEN 1.0 ELSE 0 END) delay
        FROM fact_graduation g JOIN dim_major m ON g.major_id=m.major_id{where}
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
        conds.append("e.college_id=?"); params.append(flt.college_id)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT c.name college, COUNT(*) n,
               AVG(e.cet4) cet4, AVG(e.cet6) cet6, AVG(e.ncre2) nc2, AVG(e.ncre3) nc3
        FROM fact_exam_cert e JOIN dim_college c ON e.college_id=c.college_id{where}
        GROUP BY e.college_id HAVING n>=20 ORDER BY cet4 DESC""", tuple(params)):
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
        conds.append("m.college_id=?"); params.append(flt.college_id)
    if flt.grade:
        conds.append("mr.grade=?"); params.append(flt.grade)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    out = []
    for r in dbm.query(conn, f"""
        SELECT m.name major, mr.grade, mr.general_req, mr.major_req, mr.total_req,
               AVG(g.earned_credits) earned, COUNT(*) n
        FROM fact_major_req mr JOIN dim_major m ON mr.major_id=m.major_id
        LEFT JOIN fact_graduation g ON g.major_id=mr.major_id{where}
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


@router.get("/reports")
def reports(type: str = "score", semester: Optional[str] = None,
            year: Optional[str] = None, college: Optional[str] = None,
            grade: Optional[str] = None, kind: Optional[str] = None,
            user: dict = Depends(get_current_user),
            conn: sqlite3.Connection = Depends(get_db)):
    # 数据范围：受限角色仅可见被授权学院的报表数据
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope and not college:
        scoped = dbm.query_one(
            conn, f"SELECT college_id FROM dim_college WHERE {col_scope}", col_params)
        if scoped:
            college = scoped["college_id"]
    fn = _REAL.get(type)
    if fn is None:
        raise ApiError(f"未知报表类型: {type}", code=400, status_code=400)
    flt = _Flt(conn, semester=semester, year=year, college=college,
               grade=grade, kind=kind)
    return ok(fn(conn, flt))

"""师资结构组：师资画像分布 + 教师明细。
画像分布算自 fact_teacher_profile（合成，按真实职称派生），上课率/趋势算自
真实排课 fact_lesson + 真实成绩 fact_grade。学院下钻用真实 college_id（C01-C16）。
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user, student_data_scope, college_data_scope
from ..envelope import ok, ApiError
from ..util import normalize_title, clean_dept
from ..settings import LATEST_REAL_SEMESTER, CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin/faculty", tags=["faculty"])
REAL = LATEST_REAL_SEMESTER
CUR = CURRENT_SEMESTER
# 本科教学学院（排除研究生院/本科生院等非授课建制）
_NON_TEACHING_COLLEGE = ("本科生院", "研究生院")


def _teaching_set(conn, sem) -> set:
    """指定学期承担排课的教师工号集合（含合讲：teacher_ids 拆分）。"""
    s = set()
    for r in dbm.query(conn,
                       "SELECT teacher_id, teacher_ids FROM fact_lesson WHERE semester_id=?",
                       (sem,)):
        if r["teacher_id"]:
            s.add(str(r["teacher_id"]))
        for tid in str(r["teacher_ids"] or "").replace("；", ";").replace(",", ";").split(";"):
            tid = tid.strip()
            if tid:
                s.add(tid)
    return s


@router.get("/structure")
def structure(college: Optional[str] = None, semester: Optional[str] = None,
              title: Optional[str] = None,
              user: dict = Depends(get_current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    # 数据范围：受限角色仅可见被授权学院的师资结构
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope and not college:
        scoped = dbm.query_one(
            conn, f"SELECT college_id FROM dim_college WHERE {col_scope}", col_params)
        if scoped:
            college = scoped["college_id"]
    sem = semester or REAL
    cname_filter = dbm.scalar(
        conn, "SELECT name FROM dim_college WHERE college_id=?", (college,)) if college else None
    profiles = dbm.query(conn, """
        SELECT p.teacher_id, p.norm_title, p.education, p.age_band, p.origin, p.degree,
               t.dept FROM fact_teacher_profile p
        JOIN dim_teacher t ON p.teacher_id=t.teacher_id""")
    if cname_filter:
        profiles = [p for p in profiles if clean_dept(p["dept"]) == cname_filter]
    if title:
        profiles = [p for p in profiles if p["norm_title"] == title]
    total = len(profiles) or 1
    teaching = _teaching_set(conn, sem)

    def _dist(key, order):
        cnt: dict = {}
        for p in profiles:
            cnt[p[key]] = cnt.get(p[key], 0) + 1
        keys = [k for k in order if k in cnt] + [k for k in cnt if k not in order]
        return [{"label": k, "value": cnt[k], "pct": round(cnt[k] / total * 100)}
                for k in keys]

    structure_cards = [
        {"title": "职称分布", "items": _dist("norm_title", ["教授", "副教授", "讲师", "助教", "其他"])},
        {"title": "学历分布", "items": _dist("education", ["博士研究生", "硕士研究生", "大学本科"])},
        {"title": "年龄分布", "items": _dist("age_band", ["35岁以下", "36-45岁", "46-55岁", "56岁以上"])},
        {"title": "学缘结构", "items": _dist("origin", ["本校毕业", "外校(境内)", "境外高校"])},
    ]

    # KPI
    doctor = sum(1 for p in profiles if p["degree"] == "博士")
    prof_ids = {p["teacher_id"] for p in profiles if p["norm_title"] == "教授"}
    prof_teach = sum(1 for tid in prof_ids if tid in teaching)
    prof_rate = round(prof_teach / len(prof_ids) * 100) if prof_ids else 0
    students = dbm.scalar(
        conn, "SELECT COUNT(*) FROM dim_student WHERE college_id=?", (college,)) if cname_filter \
        else dbm.scalar(conn, "SELECT COUNT(*) FROM dim_student") or 0
    ratio = round(students / total, 1)
    facultyKpis = [
        {"label": "专任教师总数", "value": f"{total:,}人", "color": "#1E3A5F",
         "formula": "COUNT(教职工画像)"},
        {"label": "博士学位比", "value": f"{round(doctor / total * 100)}%", "color": "#2563EB",
         "formula": "博士学位教师÷专任教师总数"},
        {"label": "教授上课率", "value": f"{prof_rate}%",
         "color": "#16A34A" if prof_rate >= 85 else "#DC2626",
         "formula": "为本科生授课教授÷教授总数·教育部要求≥85%"},
        {"label": "生师比", "value": f"{ratio}:1", "color": "#16A34A",
         "formula": "在籍学生÷专任教师"},
    ]

    # 各学院教授/副教授上课率（含"校级直属/其他"兜底分组）
    name2cid = {r["name"]: r["college_id"] for r in dbm.query(
        conn, "SELECT college_id,name FROM dim_college")}
    cid2name = {v: k for k, v in name2cid.items()}
    col_acc: dict = {}
    for p in profiles:
        cid = name2cid.get(clean_dept(p["dept"]))
        if cid and cid2name.get(cid) in _NON_TEACHING_COLLEGE:
            cid = None
        if not cid:
            cid = "_other"  # 非教学学院单位的教授归入"校级直属/其他"
        a = col_acc.setdefault(cid, {"prof": 0, "profT": 0, "assoc": 0, "assocT": 0})
        teach = p["teacher_id"] in teaching
        if p["norm_title"] == "教授":
            a["prof"] += 1
            a["profT"] += 1 if teach else 0
        elif p["norm_title"] == "副教授":
            a["assoc"] += 1
            a["assocT"] += 1 if teach else 0
    teachingRates = []
    for cid, a in col_acc.items():
        if a["prof"] < 1 and a["assoc"] < 1:
            continue
        name = "校级直属/其他" if cid == "_other" else cid2name.get(cid, cid)
        teachingRates.append({
            "id": cid, "name": name, "profTotal": a["prof"],
            "profRate": round(a["profT"] / a["prof"] * 100) if a["prof"] else 0,
            "assocTotal": a["assoc"],
            "assocRate": round(a["assocT"] / a["assoc"] * 100) if a["assoc"] else 0})
    # 教学学院在前，其他分组在最后
    teachingRates.sort(key=lambda x: (x["id"] == "_other", -x["profRate"]))
    teachingRates = teachingRates[:15]

    # 教师本学期任课均分排行（真实排课+成绩可归因的两学期仅覆盖 2025-2026，
    # 历史教学班未入库无法做跨年趋势；此处给真实学期可归因教师的均分表现，
    # trend 相对全体任课均分：高于均值=up，低于=down）
    trows = dbm.query(conn, """
        SELECT l.teacher_id, COUNT(*) n, AVG(g.score) av
        FROM fact_grade g JOIN fact_lesson l
          ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
        WHERE g.score IS NOT NULL AND l.semester_id=?
        GROUP BY l.teacher_id HAVING n>=20""", (sem,))
    if cname_filter:
        _ids = {p["teacher_id"] for p in profiles}
        trows = [r for r in trows if r["teacher_id"] in _ids]
    tmeta = {t["teacher_id"]: t for t in dbm.query(
        conn, "SELECT teacher_id, name, title, dept FROM dim_teacher")}
    overall = round(sum(r["av"] for r in trows) / len(trows), 1) if trows else 0
    teacherTrends = []
    for r in sorted(trows, key=lambda x: -x["av"])[:8]:
        meta = tmeta.get(r["teacher_id"], {})
        av = round(r["av"], 1)
        teacherTrends.append({
            "id": r["teacher_id"], "name": meta.get("name") or r["teacher_id"],
            "title": normalize_title(meta.get("title")),
            "dept": clean_dept(meta.get("dept")) or "—",
            "avgScore": av, "students": r["n"],
            "trend": "up" if av >= overall else "down"})

    # 未上课教授名单
    notTeaching = []
    for p in profiles:
        if p["norm_title"] != "教授" or p["teacher_id"] in teaching:
            continue
        meta = tmeta.get(p["teacher_id"], {})
        notTeaching.append({
            "name": meta.get("name") or p["teacher_id"], "title": "教授",
            "dept": clean_dept(p["dept"]) or "—",
            "reason": "本学期无本科教学任务（科研/行政/进修等）",
            "semesters": "本学期"})
    notTeaching = notTeaching[:12]

    return ok({"facultyKpis": facultyKpis, "structure": structure_cards,
               "teachingRates": teachingRates, "teacherTrends": teacherTrends,
               "notTeaching": notTeaching})


@router.get("/{teacher_id}")
def detail(teacher_id: str, semester: Optional[str] = None,
           user: dict = Depends(get_current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    cur = semester or CUR
    t = dbm.query_one(conn, "SELECT teacher_id, name, dept, title FROM dim_teacher WHERE teacher_id=?",
                      (teacher_id,))
    if not t:
        raise ApiError(f"教师不存在: {teacher_id}", code=404, status_code=404)
    # 数据范围校验：确保教师所属学院在用户授权范围内
    col_scope, col_sp = college_data_scope(user, conn)
    if col_scope and t.get("dept"):
        dept_name = clean_dept(t["dept"])
        if dept_name:
            allowed = dbm.scalar(conn,
                f"SELECT 1 FROM dim_college WHERE name=? AND {col_scope}",
                [dept_name] + col_sp)
            if not allowed:
                raise ApiError("无权限查看该教师", code=403, status_code=403)
    prof = dbm.query_one(conn, """
        SELECT norm_title, education, degree, age, origin, school, teach_years
        FROM fact_teacher_profile WHERE teacher_id=?""", (teacher_id,)) or {}

    # 各学期任课均分
    srows = dbm.query(conn, """
        SELECT l.semester_id, COUNT(*) n, AVG(g.score) av
        FROM fact_grade g JOIN fact_lesson l
          ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
        WHERE l.teacher_id=? AND g.score IS NOT NULL
        GROUP BY l.semester_id ORDER BY l.semester_id""", (teacher_id,))
    semesters = [r["semester_id"] for r in srows]
    scoreTrend = [round(r["av"], 1) for r in srows]
    avg_all = round(sum(scoreTrend) / len(scoreTrend), 1) if scoreTrend else 0

    # 本学期授课课程
    currentCourses = []
    cur_hours = 0.0
    for r in dbm.query(conn, """
        SELECT l.course_id, co.name cname, l.class_names, l.enrolled, l.total_hours
        FROM fact_lesson l LEFT JOIN dim_course co ON l.course_id=co.course_id
        WHERE l.teacher_id=? AND l.semester_id=?""", (teacher_id, cur)):
        cur_hours += r["total_hours"] or 0
        currentCourses.append({
            "id": r["course_id"], "courseName": r["cname"] or r["course_id"],
            "className": r["class_names"] or "—", "students": r["enrolled"] or 0,
            "hours": round(r["total_hours"] or 0)})

    # 近年授课历史（逐教学班均分/通过率）
    teachingHistory = []
    for r in dbm.query(conn, """
        SELECT l.semester_id, co.name cname, COUNT(g.grade_id) total,
               AVG(g.score) av, AVG(CASE WHEN g.is_pass=1 THEN 1.0 ELSE 0 END) pr
        FROM fact_lesson l LEFT JOIN dim_course co ON l.course_id=co.course_id
        LEFT JOIN fact_grade g ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
        WHERE l.teacher_id=?
        GROUP BY l.lesson_id, l.semester_id
        ORDER BY l.semester_id DESC""", (teacher_id,)):
        teachingHistory.append({
            "semester": r["semester_id"], "courseName": r["cname"] or "—",
            "students": r["total"] or 0,
            "avgScore": round(r["av"], 1) if r["av"] is not None else "—",
            "passRate": f"{round((r['pr'] or 0) * 100, 1)}%" if r["total"] else "—"})
    teachingHistory = teachingHistory[:12]

    kpis = [
        {"label": "本学期授课门数", "value": f"{len(currentCourses)}门",
         "formula": "当前学期承担教学班课程数"},
        {"label": "本学期总学时", "value": str(round(cur_hours)),
         "formula": "当前学期教学班学时合计"},
        {"label": "近期平均成绩", "value": str(avg_all) if scoreTrend else "—",
         "formula": "所授课程学生平均分（各学期均）"},
        {"label": "教龄", "value": f"{prof.get('teach_years', '—')}年",
         "formula": "教职工画像派生"},
        {"label": "年龄", "value": f"{prof.get('age', '—')}岁",
         "formula": "教职工画像派生"},
        {"label": "学缘", "value": prof.get("origin", "—"),
         "formula": "毕业院校来源"},
    ]
    return ok({
        "name": t["name"] or teacher_id, "code": teacher_id,
        "deptName": clean_dept(t["dept"]) or "—",
        "title": normalize_title(t["title"]),
        "education": prof.get("education", "—"), "degree": prof.get("degree", "—"),
        "school": prof.get("school", "—"), "kpis": kpis,
        "semesters": semesters, "scoreTrend": scoreTrend,
        "currentCourses": currentCourses, "teachingHistory": teachingHistory})

# -- V1.1：课程教学团队分析 --
@router.get("/team/{course_id}")
def team_analysis(course_id: str, conn: sqlite3.Connection = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    """课程教学团队画像 + 断层风险评估 + 排课偏好。"""
    co = dbm.query_one(conn, "SELECT course_id, name, credits, dept FROM dim_course WHERE course_id=?", (course_id,))
    if not co: raise ApiError("课程不存在", code=404, status_code=404)
    # 团队教师列表
    members = []
    for r in dbm.query(conn, """
        SELECT DISTINCT l.teacher_id, t.name, p.norm_title, p.education,
               p.age, p.teach_years, p.origin
        FROM fact_lesson l
        JOIN dim_teacher t ON l.teacher_id=t.teacher_id
        LEFT JOIN fact_teacher_profile p ON l.teacher_id=p.teacher_id
        WHERE l.course_id=? AND l.semester_id IN (
            SELECT semester_id FROM dim_semester ORDER BY semester_id DESC LIMIT 2)
    """, (course_id,)):
        # 排课偏好
        prefs = dbm.query(conn, """
            SELECT l.classroom, COUNT(*) cnt FROM fact_lesson l
            WHERE l.teacher_id=? AND l.course_id=?
            GROUP BY l.classroom ORDER BY cnt DESC LIMIT 1
        """, (r["teacher_id"], course_id))
        members.append({"teacherId": r["teacher_id"], "name": r["name"] or r["teacher_id"],
            "title": r["norm_title"] or "—", "education": r["education"] or "—",
            "age": r["age"], "teachYears": r["teach_years"],
            "origin": r["origin"] or "—",
            "prefClassroom": prefs[0]["classroom"] if prefs else "—"})
    total = len(members) or 1
    under_45 = sum(1 for m in members if (m["age"] or 99) < 45)
    over_55 = sum(1 for m in members if (m["age"] or 0) > 55)
    has_under_40 = any((m["age"] or 99) < 40 for m in members)
    if under_45 / total < 0.3:
        gap_level = "severe" if (over_55 / total > 0.5 and not has_under_40) else "warning"
    else:
        gap_level = "none"
    return ok({"courseName": co["name"] or course_id, "credits": co["credits"],
        "college": co["dept"] or "—", "members": members, "totalMembers": total,
        "titleDist": [{"label": t, "count": sum(1 for m in members if m["title"]==t)}
            for t in ["教授","副教授","讲师","助教","其他"]],
        "gapRisk": {"level": gap_level, "under45Pct": round(under_45/total*100),
            "over55Pct": round(over_55/total*100), "hasUnder40": has_under_40}})

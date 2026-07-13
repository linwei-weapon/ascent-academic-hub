"""师资结构组：师资画像分布 + 教师明细。
画像分布算自 fact_teacher_profile（合成，按真实职称派生），上课率/趋势算自
真实排课 fact_lesson + 真实成绩 fact_grade。学院下钻用真实 college_id（C01-C16）。
"""
import sqlite3
from collections import defaultdict
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


def _historical_schedule_pattern(conn: sqlite3.Connection, teacher_id: str) -> dict:
    """从真实教学任务归纳历史排课行为倾向；不使用模拟星期/节次数据。"""
    rows = dbm.query(conn, """SELECT l.semester_id,l.campus,l.classroom,l.enrolled,
        c.course_nature FROM fact_lesson l LEFT JOIN dim_course c ON l.course_id=c.course_id
        WHERE l.teacher_id=? ORDER BY l.semester_id""", (teacher_id,))
    total = len(rows)

    def dist(key: str, limit: int = 3) -> list:
        counts = {}
        for row in rows:
            value = str(row.get(key) or "").strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
        return [{"label": label, "count": count,
                 "pct": round(count / total * 100, 1) if total else 0}
                for label, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]]

    enrolled = [int(r["enrolled"]) for r in rows if r.get("enrolled") is not None]
    avg_size = round(sum(enrolled) / len(enrolled), 1) if enrolled else None
    if avg_size is None:
        size_label = "暂无"
    elif avg_size < 30:
        size_label = "小班（<30）"
    elif avg_size < 60:
        size_label = "中班（30-59）"
    elif avg_size < 120:
        size_label = "大班（60-119）"
    else:
        size_label = "超大班（≥120）"
    classrooms = dist("classroom")
    top_share = classrooms[0]["pct"] if classrooms else 0
    confidence = "低" if total < 5 else ("高" if top_share >= 60 else "中" if top_share >= 40 else "低")
    has_issue = bool(dbm.scalar(conn, """SELECT 1 FROM data_quality_issue
        WHERE domain='operation' AND entity_type='teacher' AND entity_id=?
        AND status IN ('open','reviewing') LIMIT 1""", (teacher_id,)))
    return {"evidenceLevel": "real_derived", "sampleCount": total,
            "semesterCount": len({r["semester_id"] for r in rows}),
            "campuses": dist("campus"), "classrooms": classrooms,
            "courseNatures": dist("course_nature"), "avgClassSize": avg_size,
            "classSizeTendency": size_label, "confidence": confidence,
            "readiness": "待数据核验" if has_issue else "可供排课参考",
            "limitation": "该结果是历史排课行为统计，不等同于教师主动表达的意愿；源数据无真实星期和节次字段，因此不分析时段偏好。"}


@router.get("/management-overview")
def management_overview(college: Optional[str] = None, semester: Optional[str] = None,
                        user: dict = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db)):
    """本科教学师资保障总览，仅使用真实教师主数据与教学任务。"""
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope and not college:
        scoped = dbm.query_one(conn, f"SELECT college_id FROM dim_college WHERE {col_scope}", col_params)
        if scoped: college = scoped["college_id"]
    sem = semester or REAL
    college_dimension = dbm.query(conn, "SELECT college_id,name FROM dim_college")
    college_ids_by_name = {clean_dept(x["name"]): x["college_id"] for x in college_dimension}
    known_college_names = set(college_ids_by_name)
    college_name = dbm.scalar(conn, "SELECT name FROM dim_college WHERE college_id=?", (college,)) if college else None
    params: list = [sem]
    college_sql = ""
    if college_name:
        college_sql = " AND TRIM(COALESCE(t.dept,''))=?"
        params.append(college_name)
    course_rows = dbm.query(conn, f"""SELECT l.course_id,COALESCE(MAX(c.name),l.course_id) course_name,
      COALESCE(MAX(c.course_nature),'未标注') course_nature,COALESCE(MAX(t.dept),'待映射学院') college_name,
      COUNT(DISTINCT l.lesson_id) lesson_count,COUNT(DISTINCT l.teacher_id) teacher_count,
      SUM(COALESCE(l.enrolled,0)) enrolled,
      COUNT(DISTINCT CASE WHEN NULLIF(TRIM(t.title),'') IS NOT NULL THEN l.teacher_id END) known_title_teachers,
      COUNT(DISTINCT CASE WHEN t.title LIKE '%教授%' THEN l.teacher_id END) senior_title_teachers
      FROM fact_lesson l LEFT JOIN dim_course c ON c.course_id=l.course_id
      LEFT JOIN dim_teacher t ON t.teacher_id=l.teacher_id
      WHERE l.semester_id=? AND NULLIF(TRIM(l.course_id),'') IS NOT NULL {college_sql}
      GROUP BY l.course_id""", tuple(params))
    lesson_team_rows = dbm.query(conn, f"""SELECT l.course_id,l.teacher_id,l.teacher_ids
      FROM fact_lesson l LEFT JOIN dim_teacher t ON t.teacher_id=l.teacher_id
      WHERE l.semester_id=? AND NULLIF(TRIM(l.course_id),'') IS NOT NULL {college_sql}""", tuple(params))
    team_sets = defaultdict(set)
    for item in lesson_team_rows:
        if item["teacher_id"]: team_sets[item["course_id"]].add(str(item["teacher_id"]).strip())
        for teacher_id in str(item["teacher_ids"] or "").replace("，", ";").replace(",", ";").split(";"):
            if teacher_id.strip(): team_sets[item["course_id"]].add(teacher_id.strip())
    if not college_name:
        course_rows = [row for row in course_rows if clean_dept(row["college_name"]) in known_college_names]
        valid_course_ids = {row["course_id"] for row in course_rows}
        team_sets = defaultdict(set, {course_id: members for course_id, members in team_sets.items() if course_id in valid_course_ids})
    teacher_meta = {x["teacher_id"]: x for x in dbm.query(conn, "SELECT teacher_id,title,dept FROM dim_teacher")}
    for row in course_rows:
        member_ids = team_sets.get(row["course_id"], set())
        row["teacher_count"] = len(member_ids)
        row["known_title_teachers"] = sum(bool(str(teacher_meta.get(x, {}).get("title") or "").strip()) for x in member_ids)
        row["senior_title_teachers"] = sum("教授" in str(teacher_meta.get(x, {}).get("title") or "") for x in member_ids)
        reasons = []
        if row["teacher_count"] == 1: reasons.append("当前学期仅1名实际授课教师")
        if row["teacher_count"] <= 2 and row["lesson_count"] >= 3: reasons.append(f"{row['lesson_count']}个教学班仅由{row['teacher_count']}名教师覆盖")
        if row["enrolled"] >= 100 and row["teacher_count"] == 1: reasons.append(f"单一教师覆盖{row['enrolled']}人次")
        if row["known_title_teachers"] < row["teacher_count"]: reasons.append("团队职称证据不完整")
        row["attention_reasons"] = reasons
        row["priority"] = "高" if row["teacher_count"] == 1 and row["enrolled"] >= 100 else ("中" if reasons else "常规")
    risk_courses = sorted([x for x in course_rows if x["attention_reasons"]],
                          key=lambda x: (x["priority"] != "高", x["priority"] != "中", -x["enrolled"]))[:30]
    teacher_params: list = [sem]
    teacher_college_sql = ""
    if college_name:
        teacher_college_sql = " AND TRIM(COALESCE(t.dept,''))=?"; teacher_params.append(college_name)
    teacher_rows = dbm.query(conn, f"""SELECT l.teacher_id,COALESCE(MAX(t.name),l.teacher_id) teacher_name,
      COALESCE(MAX(t.dept),'待映射学院') college_name,MAX(t.title) title,
      COUNT(DISTINCT l.course_id) course_count,COUNT(DISTINCT l.lesson_id) lesson_count,
      SUM(COALESCE(l.enrolled,0)) enrolled FROM fact_lesson l LEFT JOIN dim_teacher t ON t.teacher_id=l.teacher_id
      WHERE l.semester_id=? AND NULLIF(TRIM(l.teacher_id),'') IS NOT NULL {teacher_college_sql}
      GROUP BY l.teacher_id ORDER BY lesson_count DESC,enrolled DESC""", tuple(teacher_params))
    if not college_name:
        teacher_rows = [row for row in teacher_rows if clean_dept(row["college_name"]) in known_college_names]
    teachers = teacher_rows[:30]
    colleges_map = {}
    for row in course_rows:
        bucket = colleges_map.setdefault(row["college_name"], {"college_name": row["college_name"], "courses": 0,
          "lessons": 0, "enrolled": 0, "single_teacher_courses": 0, "high_impact_courses": 0})
        bucket["courses"] += 1; bucket["lessons"] += row["lesson_count"]; bucket["enrolled"] += row["enrolled"] or 0
        bucket["single_teacher_courses"] += int(row["teacher_count"] == 1)
        bucket["high_impact_courses"] += int(row["teacher_count"] == 1 and row["enrolled"] >= 100)
    for row in colleges_map.values():
        row["college_id"] = college_ids_by_name.get(clean_dept(row["college_name"]))
    college_rows = sorted([row for row in colleges_map.values() if row["college_id"]],
                          key=lambda x: (-x["high_impact_courses"], -x["single_teacher_courses"], x["college_name"]))
    active_ids = set().union(*team_sets.values()) if team_sets else set()
    title_known = sum(bool(str(teacher_meta.get(x, {}).get("title") or "").strip()) for x in active_ids)
    professor_ids = {teacher_id for teacher_id, meta in teacher_meta.items()
      if normalize_title(meta.get("title")) == "教授"
      and (clean_dept(meta.get("dept")) == college_name if college_name else clean_dept(meta.get("dept")) in known_college_names)}
    professor_active = len(professor_ids & active_ids)
    total_enrolled = sum(x["enrolled"] or 0 for x in course_rows)
    top_load = sum(x["enrolled"] or 0 for x in teacher_rows[:max(1, round(len(teacher_rows)*0.1))])
    summary = {"active_teachers": len(active_ids), "courses": len(course_rows),
      "single_teacher_courses": sum(x["teacher_count"] == 1 for x in course_rows),
      "high_impact_courses": sum(x["teacher_count"] == 1 and x["enrolled"] >= 100 for x in course_rows),
      "professor_total": len(professor_ids), "professor_active": professor_active,
      "professor_participation_rate": round(professor_active*100/len(professor_ids),1) if professor_ids else None,
      "title_completeness_rate": round(title_known*100/len(active_ids),1) if active_ids else 0,
      "top10_load_share": round(top_load*100/total_enrolled,1) if total_enrolled else 0}
    return ok({"semester": sem, "college": college_name, "summary": summary, "colleges": college_rows,
      "risk_courses": risk_courses, "teachers": teachers,
      "definition": {"active_teachers": "当前筛选学期至少承担1个本科教学班的去重教师数。",
        "single_teacher_courses": "当前学期教学任务只关联1名实际授课教师的去重课程数；只表示当期单点承担。",
        "high_impact_courses": "单一教师覆盖且选课人次不少于100的课程数；100人为原型核查阈值，不是学校定额。",
        "professor_participation": "当前教师主数据中职称含教授且承担本科教学任务的人数÷教授人数；缺岗位状态，需人工核验分母。",
        "title_completeness": "实际授课教师中职称字段非空人数÷实际授课教师人数。",
        "load_share": "按主讲教师字段覆盖选课人次排序，前10%教师的覆盖人次占比；联合授课因缺少工作量分配比例暂不拆分，仅表示任务集中度。",
        "boundary": "本页只用于核查本科教学师资供给和课程团队连续性；不评价教师个人教学质量，不使用模拟年龄、学历、教龄或学缘形成结论。"}})


@router.get("/management-course/{course_id}")
def management_course(course_id: str, semester: Optional[str] = None,
                      user: dict = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or REAL
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope:
        allowed = {x["name"] for x in dbm.query(conn, f"SELECT name FROM dim_college WHERE {col_scope}", col_params)}
        course_depts = {clean_dept(x["dept"]) for x in dbm.query(conn, """SELECT DISTINCT t.dept FROM fact_lesson l
          JOIN dim_teacher t ON t.teacher_id=l.teacher_id WHERE l.course_id=?""", (course_id,)) if x.get("dept")}
        if not (allowed & course_depts):
            raise ApiError("无权限查看该课程团队", code=403, status_code=403)
    lessons = dbm.query(conn, """SELECT lesson_id,semester_id,teacher_id,teacher_ids,enrolled,capacity
      FROM fact_lesson WHERE course_id=? AND semester_id=?""", (course_id, sem))
    if not lessons: raise ApiError("当前学期暂无该课程教学任务", code=404, status_code=404)
    member_ids = set()
    for item in lessons:
        if item["teacher_id"]: member_ids.add(str(item["teacher_id"]).strip())
        for teacher_id in str(item["teacher_ids"] or "").replace("，", ";").replace(",", ";").split(";"):
            if teacher_id.strip(): member_ids.add(teacher_id.strip())
    marks = ",".join("?" for _ in member_ids)
    members = dbm.query(conn, f"""SELECT teacher_id staff_id,name display_name,title,dept organization_id,source
      FROM dim_teacher WHERE teacher_id IN ({marks}) ORDER BY name""", tuple(member_ids)) if member_ids else []
    known = [x for x in members if str(x.get("title") or "").strip()]
    offerings = dbm.query(conn, """SELECT semester_id semesterId,COUNT(DISTINCT lesson_id) lessonCount,
      COUNT(DISTINCT teacher_id) teacherCount,SUM(COALESCE(capacity,0)) capacity,
      SUM(COALESCE(enrolled,0)) enrolled,ROUND(AVG(enrolled),1) avgClassSize
      FROM fact_lesson WHERE course_id=? GROUP BY semester_id ORDER BY semester_id DESC""", (course_id,))
    course = dbm.query_one(conn, "SELECT course_id courseId,name courseName,course_nature courseNature FROM dim_course WHERE course_id=?", (course_id,)) or {"courseId":course_id,"courseName":course_id}
    return ok({"course": course, "summary": {"semester_id": sem, "teacher_count": len(member_ids),
      "unknown_title_count": len(member_ids)-len(known),
      "professor_count": sum(normalize_title(x.get("title")) == "教授" for x in known),
      "associate_professor_count": sum(normalize_title(x.get("title")) == "副教授" for x in known),
      "lesson_count": len(lessons), "enrolled": sum(x.get("enrolled") or 0 for x in lessons)},
      "members": members, "offerings": offerings,
      "boundary": "成员来自真实教学任务的主教师及联合教师字段；历史开课只证明已接入学期曾开设，当前缺少未来开课计划、教师资格、真实年龄和完整岗位状态。"})


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
               "notTeaching": notTeaching,
               "evidence": {
                   "real": ["教师工号、姓名、所属部门、原始职称", "教学任务、授课课程、学生成绩"],
                   "simulated": ["学历学位、年龄、学缘、毕业院校、教龄"],
                   "limitation": "专任教师总数仅覆盖教学任务中出现的教师，不代表学校教职工全量名册。"
               }})


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
    lesson_rows = dbm.query(conn, """
        SELECT l.course_id, co.name cname, l.class_names, l.enrolled, l.total_hours
        FROM fact_lesson l LEFT JOIN dim_course co ON l.course_id=co.course_id
        WHERE l.teacher_id=? AND l.semester_id=? ORDER BY l.course_id,l.lesson_id""", (teacher_id, cur))
    currentCourses = []
    cur_hours = 0.0
    for r in lesson_rows[:100]:
        cur_hours += r["total_hours"] or 0
        currentCourses.append({
            "id": r["course_id"], "courseName": r["cname"] or r["course_id"],
            "className": r["class_names"] or "—", "students": r["enrolled"] or 0,
            "hours": round(r["total_hours"] or 0)})
    # 总学时必须基于全量行计算，不能被前端展示上限截断。
    cur_hours = sum((r["total_hours"] or 0) for r in lesson_rows)
    current_course_count = len({r["course_id"] for r in lesson_rows if r["course_id"]})
    current_issue = dbm.query_one(conn, """SELECT issue_id,status,detail,recommendation,affected_rows
        FROM data_quality_issue WHERE domain='operation' AND entity_type='teacher'
        AND entity_id=? AND semester_id=? AND status IN ('open','reviewing') LIMIT 1""",
        (teacher_id, cur))

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
        {"label": "本学期授课门数", "value": f"{current_course_count}门",
         "formula": "当前学期教学任务中的去重课程数"},
        {"label": "教学班记录", "value": f"{len(lesson_rows)}条",
         "formula": "当前学期教学任务记录数；异常问题未关闭时须先核验"},
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
        "currentCourses": currentCourses, "teachingHistory": teachingHistory,
        "currentCourseTotal": len(lesson_rows), "currentCourseDisplayLimit": 100,
        "dataQuality": dict(current_issue) if current_issue else None,
        "schedulePattern": _historical_schedule_pattern(conn, teacher_id),
        "evidence": {
            "real": ["教师基本标识、原始职称、教学任务、课程成绩"],
            "simulated": ["学历学位、年龄、学缘、毕业院校、教龄"],
            "limitation": "模拟画像仅用于界面和场景分析，不得作为教师评价、晋升或排课决策依据。"
        }})

# -- V1.1：课程教学团队分析 --
@router.get("/team/search")
def search_team_courses(q: str, user: dict = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db)):
    keyword = q.strip()
    if not keyword:
        return ok([])
    rows = dbm.query(conn, """SELECT DISTINCT c.course_id id,c.course_id code,c.name,c.dept
        FROM dim_course c JOIN fact_lesson l ON c.course_id=l.course_id
        WHERE c.course_id LIKE ? OR c.name LIKE ?
        ORDER BY c.name,c.course_id LIMIT 20""", (f"%{keyword}%", f"%{keyword}%"))
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope:
        allowed_names = {r["name"] for r in dbm.query(
            conn, f"SELECT name FROM dim_college WHERE {col_scope}", col_params)}
        rows = [r for r in rows if clean_dept(r.get("dept")) in allowed_names]
    return ok(rows)


@router.get("/team/{course_id}")
def team_analysis(course_id: str, conn: sqlite3.Connection = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    """课程教学团队画像 + 基于模拟年龄画像的断层风险场景。"""
    co = dbm.query_one(conn, "SELECT course_id, name, credits, dept FROM dim_course WHERE course_id=?", (course_id,))
    if not co: raise ApiError("课程不存在", code=404, status_code=404)
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope:
        allowed = dbm.scalar(conn, f"SELECT 1 FROM dim_college WHERE name=? AND {col_scope}",
                             [clean_dept(co.get("dept"))] + col_params)
        if not allowed:
            raise ApiError("无权限查看该课程教学团队", code=403, status_code=403)
    # 团队教师列表
    members = []
    for r in dbm.query(conn, """
        SELECT l.teacher_id, t.name, p.norm_title, p.education,
               p.age, p.teach_years, p.origin, COUNT(*) teaching_count
        FROM fact_lesson l
        JOIN dim_teacher t ON l.teacher_id=t.teacher_id
        LEFT JOIN fact_teacher_profile p ON l.teacher_id=p.teacher_id
        WHERE l.course_id=? AND l.semester_id IN (
            SELECT semester_id FROM dim_semester ORDER BY semester_id DESC LIMIT 2)
        GROUP BY l.teacher_id,t.name,p.norm_title,p.education,p.age,p.teach_years,p.origin
    """, (course_id,)):
        # 仅表示历史上最常使用的教室，不等同于教师主动填报的排课偏好。
        prefs = dbm.query(conn, """
            SELECT l.classroom, COUNT(*) cnt FROM fact_lesson l
            WHERE l.teacher_id=? AND l.course_id=?
            GROUP BY l.classroom ORDER BY cnt DESC LIMIT 1
        """, (r["teacher_id"], course_id))
        course_lesson_count = dbm.scalar(conn, "SELECT COUNT(*) FROM fact_lesson WHERE teacher_id=? AND course_id=?",
                                         (r["teacher_id"], course_id)) or 0
        current_courses = dbm.scalar(conn, """SELECT COUNT(DISTINCT course_id) FROM fact_lesson
            WHERE teacher_id=? AND semester_id=?""", (r["teacher_id"], CUR)) or 0
        members.append({"teacherId": r["teacher_id"], "name": r["name"] or r["teacher_id"],
            "title": r["norm_title"] or "—", "education": r["education"] or "—",
            "age": r["age"], "teachingYears": r["teach_years"],
            "origin": r["origin"] or "—",
            "teachingCount": r["teaching_count"],
            "coursesThisSemester": current_courses,
            "observedClassroom": prefs[0]["classroom"] if prefs else "—",
            "observedClassroomPct": round(prefs[0]["cnt"] / course_lesson_count * 100, 1)
                if prefs and course_lesson_count else 0})
    total = len(members) or 1
    under_45 = sum(1 for m in members if (m["age"] or 99) < 45)
    over_55 = sum(1 for m in members if (m["age"] or 0) > 55)
    has_under_40 = any((m["age"] or 99) < 40 for m in members)
    if under_45 / total < 0.3:
        gap_level = "severe" if (over_55 / total > 0.5 and not has_under_40) else "warning"
    else:
        gap_level = "none"
    level_label = {"severe": "高", "warning": "中", "none": "无"}[gap_level]
    risks = [] if gap_level == "none" else [{
        "level": level_label,
        "title": "团队年龄梯队模拟场景存在断层风险",
        "desc": f"模拟画像中45岁以下占比{round(under_45/total*100)}%、55岁以上占比{round(over_55/total*100)}%。请接入真实年龄与人员名册后再核验。"
    }]
    # 团队建设建议只使用真实授课覆盖与数据质量台账，不使用模拟画像评价个人。
    support_suggestions = []
    if len(members) == 1:
        support_suggestions.append({"level": "重点关注", "topic": "课程授课单点覆盖",
            "basis": "近两学期该课程仅识别到1名授课教师",
            "suggestion": "建议教研室核验课程接续安排，并评估是否需要设置协同备课或替补教师。",
            "readiness": "待人工核验"})
    elif len(members) == 2:
        support_suggestions.append({"level": "一般关注", "topic": "课程团队覆盖较窄",
            "basis": "近两学期该课程识别到2名授课教师",
            "suggestion": "建议结合开课规模核验团队冗余度和课程交接安排。",
            "readiness": "待人工核验"})
    issue_members = {r["entity_id"] for r in dbm.query(conn, """SELECT entity_id
        FROM data_quality_issue WHERE domain='operation' AND entity_type='teacher'
        AND status IN ('open','reviewing')""")}
    affected = [m["name"] for m in members if m["teacherId"] in issue_members]
    if affected:
        support_suggestions.append({"level": "数据核验", "topic": "教师课时数据质量",
            "basis": f"团队中{len(affected)}名教师存在未关闭的教学运行数据质量问题",
            "suggestion": "请先完成教师工号映射和教学班拆分核验，再使用工作量数据开展团队建设分析。",
            "readiness": "待数据修复"})
    if not support_suggestions:
        support_suggestions.append({"level": "信息提示", "topic": "团队覆盖",
            "basis": f"近两学期识别到{len(members)}名授课教师，未命中现有课时数据质量问题",
            "suggestion": "当前仅提供授课覆盖事实；培养计划仍需结合真实人才档案、教研任务和教师意愿人工制定。",
            "readiness": "待人工核验"})
    return ok({"course": {"id": course_id, "code": course_id,
            "name": co["name"] or course_id, "dept": co["dept"] or "—"},
        "courseName": co["name"] or course_id, "credits": co["credits"],
        "college": co["dept"] or "—", "team": members, "members": members,
        "totalMembers": len(members),
        "titleDist": [{"label": t, "count": sum(1 for m in members if m["title"]==t)}
            for t in ["教授","副教授","讲师","助教","其他"]],
        "gapRisk": {"level": gap_level, "under45Pct": round(under_45/total*100),
            "over55Pct": round(over_55/total*100), "hasUnder40": has_under_40},
        "gapRisks": risks,
        "supportSuggestions": support_suggestions,
        "decisionBoundary": "建议仅用于团队建设核验，不构成个人评价、岗位安排或晋升依据。",
        "evidence": {"level": "scenario_simulation",
            "real": ["近两学期课程授课教师、原始职称、教学班和历史教室"],
            "simulated": ["学历、年龄、教龄、学缘"],
            "limitation": "断层风险基于模拟年龄画像；教室倾向来自历史行为统计，不等同于教师主动表达的意愿。"}})

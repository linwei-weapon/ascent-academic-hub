"""教学运行分析组：开课/教室/调停课/教师负荷。
全部算自 analytics.sqlite 真实排课(fact_lesson)+预聚合(agg_classroom_util/agg_teacher_load)
+合成调停课(fact_schedule_change)。学院下钻用真实 college_id（C01-C16）。
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user, student_data_scope, college_data_scope
from ..envelope import ok
from ..util import normalize_title, clean_dept
from ..settings import LATEST_REAL_SEMESTER, CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin/operation", tags=["operation"])
REAL = LATEST_REAL_SEMESTER
_PALETTE = ["#2563EB", "#16A34A", "#EA580C", "#F59E0B", "#9333EA", "#60A5FA",
            "#DC2626", "#0891B2", "#65A30D"]
# 单学期教学班 > 阈值 → 判为源库生成缺陷，统计时排除
_TEACHER_CAP = 200


def _pct(x, nd=1):
    return round((x or 0) * 100, nd)


def _anomalous_filter(conn, sem_ids: list, alias: str = "l") -> tuple[str, list]:
    """返回 (SQL片段, 参数列表)，排除单学期教学班>200的异常教师。
    SQL片段不含前导 AND，调用方自行拼接。"""
    if not sem_ids:
        return ("", [])
    ph = ",".join("?" * len(sem_ids))
    rows = dbm.query(conn, f"""SELECT entity_id teacher_id FROM data_quality_issue
        WHERE domain='operation' AND issue_type='teacher_lesson_overflow' AND status='open'
        AND semester_id IN ({ph})""", tuple(sem_ids))
    bad = [r["teacher_id"] for r in rows]
    if not bad:
        return ("1=1", [])
    bph = ",".join("?" * len(bad))
    return (f"{alias}.teacher_id NOT IN ({bph})", bad)


def _anomaly_summary(conn, sem_ids: list) -> dict:
    if not sem_ids:
        return {"excludedTeachers": 0, "excludedLessons": 0, "threshold": _TEACHER_CAP}
    ph = ",".join("?" * len(sem_ids))
    rows = dbm.query(conn, f"""SELECT entity_id teacher_id,affected_rows lessons FROM data_quality_issue
        WHERE domain='operation' AND issue_type='teacher_lesson_overflow' AND status='open'
        AND semester_id IN ({ph})""", sem_ids)
    return {"excludedTeachers": len(rows), "excludedLessons": sum(r["lessons"] for r in rows),
            "threshold": _TEACHER_CAP, "reason": "单教师单学期教学班数超过质量阈值"}


def _college_name(conn, college_id: Optional[str]) -> Optional[str]:
    """学院码(C01-C16)→学院名；无效/缺省返回 None（=全校口径）。"""
    if not college_id:
        return None
    return dbm.scalar(
        conn, "SELECT name FROM dim_college WHERE college_id=?", (college_id,))


@router.get("/data-quality")
def operation_data_quality(semester: Optional[str] = None, status: Optional[str] = None,
                           user: dict = Depends(get_current_user),
                           conn: sqlite3.Connection = Depends(get_db)):
    conds, params = ["q.domain='operation'"], []
    if semester:
        conds.append("q.semester_id=?"); params.append(semester)
    if status:
        conds.append("q.status=?"); params.append(status)
    rows = dbm.query(conn, """SELECT q.*,t.name entity_name,t.dept entity_dept
        FROM data_quality_issue q LEFT JOIN dim_teacher t ON q.entity_type='teacher'
        AND q.entity_id=t.teacher_id WHERE """ + " AND ".join(conds) +
        " ORDER BY q.severity DESC,q.affected_rows DESC,q.issue_id", params)
    return ok({"list": rows, "summary": {"total": len(rows),
        "open": sum(1 for r in rows if r["status"] == "open"),
        "affectedRows": sum(int(r["affected_rows"] or 0) for r in rows)},
        "policy": {"statisticalAction": "open问题在教学运行统计中排除",
                   "recovery": "源数据修复并复核后可关闭问题并重新计算"}})


# ------------------------------------------------------------------ 开课与排课
_SIZE_RANGE = {  # A4 班额档（前端语义标签 → l.enrolled 区间 [lo,hi)）
    "小班(<30)": (0, 30), "中班(30-60)": (30, 60),
    "大班(60-120)": (60, 120), "超大班(>120)": (120, 100000),
}


def _sem_ids(conn, semester, year, default):
    """学期/学年解析：semester 优先单值；否则 year 展开为该学年全部 semester；
    都无则用 default 单值。返回 semester_id 列表。"""
    if semester:
        return [semester]
    if year:
        ids = [r["semester_id"] for r in dbm.query(
            conn, "SELECT semester_id FROM dim_semester WHERE year=?", (year,))]
        return ids or [default]
    return [default]


@router.get("/courses")
def courses(college: Optional[str] = None, semester: Optional[str] = None,
            campus: Optional[str] = None, course_nature: Optional[str] = None,
            category: Optional[str] = None, size: Optional[str] = None,
            year: Optional[str] = None, keyword: Optional[str] = None,
            user: dict = Depends(get_current_user),
            conn: sqlite3.Connection = Depends(get_db)):
    # 数据范围：受限角色仅可见被授权学院的开课数据
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope and not college:
        scoped = dbm.query_one(
            conn, f"SELECT college_id FROM dim_college WHERE {col_scope}", col_params)
        if scoped:
            college = scoped["college_id"]
    sem_ids = _sem_ids(conn, semester, year, REAL)
    sem_ph = ",".join("?" * len(sem_ids))
    cname = _college_name(conn, college)
    sz = _SIZE_RANGE.get(size or "")
    # 预计算异常教师黑名单（源库通识课拆分缺陷：单师单学期>200教学班）
    anom_frag, anom_params = _anomalous_filter(conn, sem_ids)
    # 维度过滤：学院(co.dept)/校区(l.campus)/课程性质(co.course_nature)/类别(co.category)/班额
    conds, bp = [f"l.semester_id IN ({sem_ph})"], list(sem_ids)
    if cname:
        conds.append("co.dept=?"); bp.append(cname)
    if campus:
        conds.append("l.campus=?"); bp.append(campus)
    if course_nature:
        conds.append("co.course_nature=?"); bp.append(course_nature)
    if category:
        conds.append("co.category=?"); bp.append(category)
    if sz:
        conds.append("l.enrolled>=? AND l.enrolled<?"); bp += [sz[0], sz[1]]
    if keyword:
        conds.append("(l.course_id LIKE ? OR co.name LIKE ?)"); bp += [f"%{keyword.strip()}%"] * 2
    conds.append(anom_frag); bp += anom_params
    base = ("FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id WHERE "
            + " AND ".join(conds))
    bp = tuple(bp)
    tot_courses = dbm.scalar(conn, f"SELECT COUNT(DISTINCT l.course_id) {base}", bp) or 0
    tot_lessons = dbm.scalar(conn, f"SELECT COUNT(*) {base}", bp) or 0
    avg_size = dbm.scalar(conn, f"SELECT AVG(l.enrolled) {base}", bp) or 0
    merged = dbm.scalar(
        conn, f"SELECT COUNT(*) {base} AND l.class_names LIKE '%;%'", bp) or 0
    kpis = [
        {"label": "开课门数", "value": f"{tot_courses:,}",
         "formula": "COUNT(DISTINCT 课程) 当前学期排课", "trend": "", "up": True},
        {"label": "教学班数", "value": f"{tot_lessons:,}",
         "formula": "教学班(排课记录)总数", "trend": "", "up": True},
        {"label": "平均班额", "value": f"{round(avg_size, 1)}人",
         "formula": "AVG(选课人数) 每教学班", "trend": "", "up": True},
        {"label": "合班率", "value": f"{_pct(merged / tot_lessons if tot_lessons else 0)}%",
         "formula": "多行政班教学班÷总教学班", "trend": "", "up": False},
    ]

    # 按学院开课（course.dept = college.name 匹配）。学院视图下仅该院一行。
    deptCourses = []
    dconds, dparams = [f"l.semester_id IN ({sem_ph})"], list(sem_ids)
    if cname:
        dconds.append("co.dept=?"); dparams.append(cname)
    if campus:
        dconds.append("l.campus=?"); dparams.append(campus)
    if course_nature:
        dconds.append("co.course_nature=?"); dparams.append(course_nature)
    if category:
        dconds.append("co.category=?"); dparams.append(category)
    if sz:
        dconds.append("l.enrolled>=? AND l.enrolled<?"); dparams += [sz[0], sz[1]]
    if keyword:
        dconds.append("(l.course_id LIKE ? OR co.name LIKE ?)"); dparams += [f"%{keyword.strip()}%"] * 2
    dconds.append(anom_frag); dparams += anom_params
    rows = dbm.query(conn, f"""
        SELECT c.college_id, c.name,
               COUNT(DISTINCT l.course_id) courseCount, COUNT(*) lessonCount
        FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id
        JOIN dim_college c ON co.dept=c.name
        WHERE {' AND '.join(dconds)}
          AND l.teacher_id IS NOT NULL
        GROUP BY c.college_id ORDER BY lessonCount DESC""",
                     tuple(dparams))
    for i, r in enumerate(rows):
        pct = round(r["lessonCount"] / tot_lessons * 100) if tot_lessons else 0
        if pct >= 12:
            level, color = "教学主力", "#E6A23C"
        elif pct >= 6:
            level, color = "常规", "#409EFF"
        else:
            level, color = "较少", "#67C23A"
        deptCourses.append({
            "id": r["college_id"], "name": r["name"],
            "courseCount": r["courseCount"], "lessonCount": r["lessonCount"],
            "pct": pct, "level": level, "levelColor": color, "barColor": color})

    # 课程类别分布（按课程性质，去重课程计数）
    typeDist = []
    trows = dbm.query(conn, f"""
        SELECT COALESCE(NULLIF(co.course_nature,''),'其他') nature, COUNT(DISTINCT l.course_id) n
        {base} GROUP BY nature ORDER BY n DESC""", bp)
    tsum = sum(r["n"] for r in trows) or 1
    for i, r in enumerate(trows):
        typeDist.append({"name": r["nature"], "count": r["n"],
                         "pct": round(r["n"] / tsum * 100), "color": _PALETTE[i % len(_PALETTE)]})

    # 班额分布
    buckets = [("小班(<30)", 0, 30, "#16A34A"), ("中班(30-60)", 30, 60, "#2563EB"),
               ("大班(60-120)", 60, 120, "#EA580C"), ("超大班(>120)", 120, 100000, "#DC2626")]
    sizeDist = []
    for label, lo, hi, color in buckets:
        c = dbm.scalar(conn, f"SELECT COUNT(*) {base} AND l.enrolled>=? AND l.enrolled<?",
                       (*bp, lo, hi)) or 0
        sizeDist.append({"label": label, "count": c,
                         "pct": round(c / tot_lessons * 100) if tot_lessons else 0, "color": color})

    # 学期趋势（真实存在的学期：真实快照 + 模拟学期）。学院视图下按该院课程收口。
    if cname:
        trend_sql = f"""
            SELECT l.semester_id, COUNT(DISTINCT l.course_id) cc, COUNT(*) lc, AVG(l.enrolled) av
            FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id
            WHERE co.dept=? AND {anom_frag}
            GROUP BY l.semester_id ORDER BY l.semester_id"""
        trend_params = (cname,) + tuple(anom_params)
    else:
        trend_sql = f"""
            SELECT l.semester_id, COUNT(DISTINCT l.course_id) cc, COUNT(*) lc, AVG(l.enrolled) av
            FROM fact_lesson l
            WHERE {anom_frag}
            GROUP BY l.semester_id ORDER BY l.semester_id"""
        trend_params = tuple(anom_params)
    trend = []
    prev = None
    for r in dbm.query(conn, trend_sql, trend_params):
        avg = round(r["av"] or 0, 1)
        change = round((r["lc"] - prev) / prev * 100, 1) if prev else 0
        trend.append({"semester": r["semester_id"], "courseCount": r["cc"],
                      "lessonCount": r["lc"], "avgSize": avg, "change": change})
        prev = r["lc"]

    course_list = dbm.query(conn, f"""SELECT l.course_id courseId,co.name courseName,
        co.dept,co.course_nature courseNature,COUNT(*) lessonCount,
        ROUND(AVG(l.enrolled),1) avgEnrolled,SUM(l.enrolled) studentCount
        {base} GROUP BY l.course_id,co.name,co.dept,co.course_nature
        ORDER BY lessonCount DESC,co.name LIMIT 100""", bp)

    return ok({
        "kpis": kpis, "deptCourses": deptCourses, "typeDist": typeDist,
        "sizeDist": sizeDist, "trend": trend, "totalCourses": tot_courses,
        "courseList": course_list, "dataQuality": _anomaly_summary(conn, sem_ids)})


# ------------------------------------------------------------------ 教室利用率
_DAYS = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五"}


def _period_index(value) -> int:
    """兼容源表 period 的数字序号或“1-2节”文本。"""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    try:
        first = int(text.split("-", 1)[0].replace("第", ""))
        return (first + 1) // 2
    except ValueError:
        return 0


def _period_label(value) -> str:
    idx = _period_index(value)
    return f"{idx*2-1}-{idx*2}节" if idx else str(value or "—")


@router.get("/classroom")
def classroom(semester: Optional[str] = None, room_type: Optional[str] = None,
              building: Optional[str] = None,
              user: dict = Depends(get_current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    # 教室利用率按学期聚合（agg_classroom_util 带 semester_id）。默认当前学期，
    # 避免把 9 学期网格平均成失真总览。room_type/building 可选过滤（agg 自带列）。
    # 注：agg_classroom_util 无 campus 列且无 dim_room，故不支持校区过滤（诚实空态）。
    sem = semester or REAL
    conds, params = ["semester_id=?"], [sem]
    if room_type:
        conds.append("room_type=?"); params.append(room_type)
    if building:
        conds.append("building=?"); params.append(building)
    rows = dbm.query(conn, "SELECT building,room_type,day,period,utilization "
                     "FROM agg_classroom_util WHERE " + " AND ".join(conds), tuple(params))
    if not rows:
        return ok({})
    # 热力图：按 day,period 取均
    cell: dict = {}
    for r in rows:
        cell.setdefault((r["day"], _period_index(r["period"])), []).append(r["utilization"])
    heatmap = {}
    peak = 0
    for (day, period), vals in cell.items():
        v = round(sum(vals) / len(vals) * 100)
        heatmap.setdefault(_DAYS.get(day, str(day)), {})[period] = v
        peak = max(peak, v)
    overall = round(sum(r["utilization"] for r in rows) / len(rows) * 100, 1)

    # 分教学楼
    bmap: dict = {}
    for r in rows:
        bmap.setdefault(r["building"], []).append(r["utilization"])
    buildings = sorted(
        [{"id": b, "name": b, "pct": round(sum(v) / len(v) * 100)} for b, v in bmap.items()],
        key=lambda x: -x["pct"])

    # 分类型
    tmap: dict = {}
    for r in rows:
        tmap.setdefault(r["room_type"], []).append(r["utilization"])
    types = sorted([{"name": t, "pct": round(sum(v) / len(v) * 100)} for t, v in tmap.items()],
                   key=lambda x: -x["pct"])

    kpis = [
        {"label": "总体利用率", "value": f"{overall}%", "color": "#1E3A5F",
         "formula": "已占用教室时段÷总可用时段", "sub": "真实排课快照"},
        {"label": "高峰时段利用率", "value": f"{peak}%", "color": "#DC2626",
         "formula": "时段网格最高利用率", "sub": "周内最忙时段"},
        {"label": "教学楼数", "value": f"{len(buildings)}栋", "color": "#16A34A",
         "formula": "排课覆盖的教学楼/场地数", "sub": "含机房/实验室/体育场地"},
    ]
    return ok({
        "kpis": kpis, "heatmap": heatmap, "buildings": buildings, "types": types,
        "evidenceLevel": "scenario_simulation",
        "dataSource": "真实楼栋利用率基线 + 固定种子模拟星期/节次分布"})


@router.get("/capacity-slots")
def capacity_slots(semester: Optional[str] = None, day: Optional[int] = None,
                   period: Optional[int] = None, building: Optional[str] = None,
                   user: dict = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    """按楼栋×时段展示排课余量。源表无教室座位总量，余量使用标准化时段比例，不伪造座位数。"""
    sem = semester or REAL
    conds, params = ["semester_id=?"], [sem]
    if day is not None:
        conds.append("day=?"); params.append(day)
    if building:
        conds.append("building=?"); params.append(building)
    rows = dbm.query(conn, """SELECT building,room_type,day,period,AVG(utilization) utilization,
        COUNT(*) sample_count FROM agg_classroom_util WHERE """ + " AND ".join(conds) +
        " GROUP BY building,room_type,day,period ORDER BY utilization,building", params)
    if period is not None:
        rows = [r for r in rows if _period_index(r["period"]) == period]
    slots = []
    for r in rows:
        used = round(float(r["utilization"] or 0) * 100, 1)
        slots.append({"building": r["building"], "roomType": r["room_type"],
                      "day": r["day"], "dayLabel": _DAYS.get(r["day"], str(r["day"])),
                      "period": _period_index(r["period"]), "periodLabel": _period_label(r["period"]),
                      "usedPct": used, "remainingPct": round(max(0, 100-used), 1),
                      "sampleCount": r["sample_count"],
                      "status": "余量充足" if used < 60 else ("可协调" if used < 80 else "紧张")})
    used_avg = round(sum(x["usedPct"] for x in slots) / len(slots), 1) if slots else 0
    return ok({"semester": sem, "slots": slots,
               "summary": {"slotCount": len(slots), "avgUsedPct": used_avg,
                           "avgRemainingPct": round(100-used_avg, 1) if slots else 0,
                           "availableCount": sum(1 for x in slots if x["usedPct"] < 60)},
               "capacityUnit": "模拟标准化教室时段比例",
               "evidenceLevel": "scenario_simulation",
               "dataSource": "真实楼栋/教室类型利用率基线 + 固定种子模拟星期/节次分布",
               "dataLimitation": "当前源数据缺少真实星期/节次课表和完整教室座位总量；结果仅用于情景分析，不能解释为真实空闲时段或可用座位数。"})


@router.get("/reschedule-candidates")
def reschedule_candidates(day: int, period: int, building: str,
                          semester: Optional[str] = None, keyword: Optional[str] = None,
                          user: dict = Depends(get_current_user),
                          conn: sqlite3.Connection = Depends(get_db)):
    """生成需人工复核的调度候选；不声称已完成教师/学生冲突校验。"""
    sem = semester or REAL
    slot_rows = dbm.query(conn, """SELECT period,utilization FROM agg_classroom_util
        WHERE semester_id=? AND day=? AND building=?""", (sem, day, building))
    slot_values = [float(r["utilization"] or 0) for r in slot_rows if _period_index(r["period"]) == period]
    used = round((sum(slot_values) / len(slot_values) if slot_values else 0) * 100, 1)
    remaining = round(max(0, 100-used), 1)
    conds, params = ["l.semester_id=?", "l.enrolled IS NOT NULL", "l.enrolled>0"], [sem]
    if keyword:
        conds.append("(l.course_id LIKE ? OR co.name LIKE ?)"); params += [f"%{keyword.strip()}%"] * 2
    anom_frag, anom_params = _anomalous_filter(conn, [sem])
    conds.append(anom_frag); params += anom_params
    rows = dbm.query(conn, """SELECT l.course_id courseId,co.name courseName,co.dept,
        co.course_nature courseNature,COUNT(*) lessonCount,ROUND(AVG(l.enrolled),1) avgEnrolled,
        MAX(l.enrolled) maxEnrolled,ROUND(AVG(COALESCE(l.capacity,l.enrolled)),1) avgDeclaredCapacity
        FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id WHERE """ +
        " AND ".join(conds) + " GROUP BY l.course_id,co.name,co.dept,co.course_nature", params)
    candidates = []
    for r in rows:
        # 仅用于排序：目标时段余量越高、小班越容易协调。不是可行性结论。
        size_score = max(0, 100 - min(100, float(r["avgEnrolled"] or 0)))
        score = round(remaining * .6 + size_score * .4, 1)
        candidates.append({**r, "targetDay": day, "targetDayLabel": _DAYS.get(day, str(day)),
            "targetPeriod": period, "targetPeriodLabel": f"{period*2-1}-{period*2}节",
            "targetBuilding": building, "targetRemainingPct": remaining, "priorityScore": score,
            "readiness": "待人工核验", "verifiedConstraints": ["目标时段余量", "教学班规模", "课程属性"],
            "unverifiedConstraints": ["教师目标时段空闲", "学生课表冲突", "具体教室座位容量", "教室设备匹配"]})
    candidates.sort(key=lambda x: (-x["priorityScore"], x["avgEnrolled"] or 0))
    return ok({"target": {"building": building, "day": day, "dayLabel": _DAYS.get(day, str(day)),
                           "period": period, "periodLabel": f"{period*2-1}-{period*2}节",
                           "usedPct": used, "remainingPct": remaining},
               "candidates": candidates[:50], "totalCandidates": len(candidates),
               "decisionLevel": "情景模拟辅助筛选", "evidenceLevel": "scenario_simulation",
               "warning": "目标星期/节次余量来自模拟分布，且候选未完成教师、学生和具体教室冲突校验，不可直接作为排课指令。"})


# ------------------------------------------------------------------ 调停课趋势
_REASON_COLOR = {"病假": "#DC2626", "事假": "#EA580C", "公差": "#F59E0B",
                 "教学调整": "#2563EB", "其他": "#94A3B8"}


@router.get("/schedule-changes")
def schedule_changes(college: Optional[str] = None, semester: Optional[str] = None,
                     user: dict = Depends(get_current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    # 数据范围：受限角色仅可见被授权学院的调停课数据
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope and not college:
        scoped = dbm.query_one(
            conn, f"SELECT college_id FROM dim_college WHERE {col_scope}", col_params)
        if scoped:
            college = scoped["college_id"]
    # 调停课表自带 college_id + semester_id。学院/学期过滤即加 WHERE；无过滤=全校。
    sem = semester or REAL
    valid = bool(_college_name(conn, college))

    def _where(alias=""):
        a = f"{alias}." if alias else ""
        conds, params = [], []
        if valid:
            conds.append(f"{a}college_id=?"); params.append(college)
        if sem:
            conds.append(f"{a}semester_id=?"); params.append(sem)
        clause = (" WHERE " + " AND ".join(conds)) if conds else ""
        return clause, tuple(params)

    w, p = _where()           # 无别名（FROM fact_schedule_change）
    sw, sp = _where("s")      # 别名 s.

    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_schedule_change{w}", p) or 0
    if not total:
        return ok({})
    chg = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_schedule_change{w}{' AND' if w else ' WHERE'} kind='调课'", p) or 0
    stop = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_schedule_change{w}{' AND' if w else ' WHERE'} kind='停课'", p) or 0
    affected = dbm.scalar(conn, f"SELECT SUM(affected) FROM fact_schedule_change{w}", p) or 0
    auto = dbm.scalar(conn, f"SELECT AVG(auto_approved) FROM fact_schedule_change{w}", p) or 0
    avg_review = dbm.scalar(conn, f"SELECT AVG(review_days) FROM fact_schedule_change{w}", p) or 0
    kpis = [
        {"label": "调课次数", "value": str(chg), "color": "#1E3A5F", "formula": "本学期调课记录数"},
        {"label": "停课次数", "value": str(stop), "color": "#DC2626", "formula": "直接停课不补课"},
        {"label": "受影响学生", "value": f"{affected:,}人次", "color": "#EA580C",
         "formula": "调停课教学班学生人次"},
        {"label": "院系自动审核", "value": f"{_pct(auto)}%", "color": "#16A34A",
         "formula": "≤4学时自动通过比例"},
        {"label": "教务审核", "value": f"{_pct(1 - auto)}%", "color": "#2563EB",
         "formula": ">4学时需教务审核比例"},
        {"label": "平均审核时间", "value": f"{round(avg_review, 1)}天", "color": "#888",
         "formula": "提交到通过平均天数"},
    ]

    # 各学院调课率：调课次数 / 该院教学班数(course.dept=college.name)
    sched_anom_frag, sched_anom_params = _anomalous_filter(conn, [sem])
    lesson_by_col = {r["college_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT c.college_id, COUNT(*) n FROM fact_lesson l
        JOIN dim_course co ON l.course_id=co.course_id
        JOIN dim_college c ON co.dept=c.name WHERE l.semester_id=? AND {sched_anom_frag}
        GROUP BY c.college_id""", (sem,) + tuple(sched_anom_params))}
    deptRanks = []
    for r in dbm.query(conn, f"""
        SELECT s.college_id, c.name, COUNT(*) cnt FROM fact_schedule_change s
        JOIN dim_college c ON s.college_id=c.college_id{sw}
        GROUP BY s.college_id ORDER BY cnt DESC""", sp):
        tl = lesson_by_col.get(r["college_id"], 0)
        pct = round(r["cnt"] / tl * 100, 1) if tl else 0.0
        deptRanks.append({"id": r["college_id"], "name": r["name"],
                          "totalLessons": tl, "changeCount": r["cnt"], "pct": pct})
    deptRanks.sort(key=lambda x: -x["pct"])

    reasonDist = []
    for r in dbm.query(conn, f"""
        SELECT reason, COUNT(*) n FROM fact_schedule_change{w}
        GROUP BY reason ORDER BY n DESC""", p):
        reasonDist.append({"name": r["reason"], "count": r["n"],
                           "pct": round(r["n"] / total * 100),
                           "color": _REASON_COLOR.get(r["reason"], "#94A3B8")})

    frequentTeachers = []
    for r in dbm.query(conn, f"""
        SELECT s.teacher_id, t.name, t.dept, COUNT(*) cnt,
               (SELECT reason FROM fact_schedule_change s2 WHERE s2.teacher_id=s.teacher_id
                GROUP BY reason ORDER BY COUNT(*) DESC LIMIT 1) top_reason
        FROM fact_schedule_change s JOIN dim_teacher t ON s.teacher_id=t.teacher_id{sw}
        GROUP BY s.teacher_id HAVING cnt>=3 ORDER BY cnt DESC LIMIT 8""", sp):
        frequentTeachers.append({
            "id": r["teacher_id"], "name": r["name"] or r["teacher_id"],
            "dept": clean_dept(r["dept"]) or "—", "count": r["cnt"],
            "reason": f"{r['top_reason']}为主"})

    mmap = {r["month"]: r["n"] for r in dbm.query(
        conn, f"SELECT month, COUNT(*) n FROM fact_schedule_change{w} GROUP BY month", p)}
    monthlyTrend = [{"month": f"{m}月", "count": mmap.get(m, 0)} for m in (3, 4, 5, 6)]

    return ok({
        "kpis": kpis, "deptRanks": deptRanks, "reasonDist": reasonDist,
        "frequentTeachers": frequentTeachers, "monthlyTrend": monthlyTrend})


# ------------------------------------------------------------------ 教师负荷
@router.get("/teacher-load")
def teacher_load(college: Optional[str] = None, semester: Optional[str] = None,
                 title: Optional[str] = None,
                 user: dict = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    # 数据范围：受限角色仅可见被授权学院教师及关联学生的负荷数据
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope and not college:
        scoped = dbm.query_one(
            conn, f"SELECT college_id FROM dim_college WHERE {col_scope}", col_params)
        if scoped:
            college = scoped["college_id"]
    # 同时获取学生视角的数据范围，用于后续生师比等学生计数查询
    stu_scope, stu_params = student_data_scope(user, conn)
    sem = semester or REAL
    cname_filter = _college_name(conn, college)
    # 教师职称（规范化） + 当前学期负荷
    prof = {r["teacher_id"]: r["norm_title"] for r in dbm.query(
        conn, "SELECT teacher_id, norm_title FROM fact_teacher_profile")}
    teachers = dbm.query(conn, "SELECT teacher_id, title, dept FROM dim_teacher")
    title_of = {t["teacher_id"]: prof.get(t["teacher_id"]) or normalize_title(t["title"])
                for t in teachers}
    dept_of = {t["teacher_id"]: clean_dept(t["dept"]) for t in teachers}
    # 学院过滤：dept 命中该院；职称过滤：norm_title 命中该档。两者求交集收口口径。
    if cname_filter or title:
        in_college = set(title_of.keys())
        if cname_filter:
            in_college &= {tid for tid, d in dept_of.items() if d == cname_filter}
        if title:
            in_college &= {tid for tid, t in title_of.items() if t == title}
    else:
        in_college = None
    load = {r["teacher_id"]: r for r in dbm.query(
        conn, "SELECT teacher_id, hours, courses, classes FROM agg_teacher_load WHERE semester_id=?",
        (sem,))
        if in_college is None or r["teacher_id"] in in_college}

    order = ["教授", "副教授", "讲师", "助教", "其他"]
    by_title: dict = {k: {"count": 0, "teach": 0, "hours": 0.0, "courses": 0.0,
                          "classes": 0.0} for k in order}
    for tid, title in title_of.items():
        if in_college is not None and tid not in in_college:
            continue
        b = by_title[title]
        b["count"] += 1
        if tid in load:
            b["teach"] += 1
            b["hours"] += load[tid]["hours"] or 0
            b["courses"] += load[tid]["courses"] or 0
            b["classes"] += load[tid]["classes"] or 0
    titleLoad = []
    for k in order:
        b = by_title[k]
        if b["count"] == 0:
            continue
        teach = b["teach"] or 1
        rate = round(b["teach"] / b["count"] * 100)
        if k == "教授":
            note, status = ("✓达标" if rate >= 85 else "↓未达标(需≥85%)"), ("ok" if rate >= 85 else "warn")
        else:
            note, status = ("✓达标" if rate >= 85 else "上课率偏低"), ("ok" if rate >= 85 else "warn")
        titleLoad.append({
            "title": k, "count": b["count"],
            "avgHours": round(b["hours"] / teach), "avgCourses": round(b["courses"] / teach, 1),
            "avgClasses": round(b["classes"] / teach, 1), "teachingRate": rate,
            "note": note, "status": status})

    # 负荷分布（按授课教师总学时）
    hrs = [load[t]["hours"] or 0 for t in load]
    dbk = [("低负荷", 0, 80, "#94A3B8"), ("正常", 80, 180, "#16A34A"),
           ("高负荷", 180, 280, "#EA580C"), ("过载", 280, 1e9, "#DC2626")]
    nload = len(hrs) or 1
    loadDist = []
    for label, lo, hi, color in dbk:
        c = sum(1 for h in hrs if lo <= h < hi)
        loadDist.append({"label": label, "count": c, "pct": round(c / nload * 100), "color": color})

    overloaded = []
    for r in dbm.query(conn, """
        SELECT a.teacher_id, t.name, t.dept, a.hours, a.courses FROM agg_teacher_load a
        JOIN dim_teacher t ON a.teacher_id=t.teacher_id
        WHERE a.semester_id=? AND (a.hours>280 OR a.courses>5)
        ORDER BY a.hours DESC LIMIT 50""", (sem,)):
        if in_college is not None and r["teacher_id"] not in in_college:
            continue
        overloaded.append({
            "id": r["teacher_id"], "name": r["name"] or r["teacher_id"],
            "title": title_of.get(r["teacher_id"], "—"),
            "dept": clean_dept(r["dept"]) or "—", "hours": round(r["hours"] or 0),
            "courses": r["courses"]})
        if len(overloaded) >= 10:
            break

    # 各学院负荷
    name2cid = {r["name"]: r["college_id"] for r in dbm.query(
        conn, "SELECT college_id,name FROM dim_college")}
    col_acc: dict = {}
    for tid, rec in load.items():
        cid = name2cid.get(dept_of.get(tid))
        if not cid:
            continue
        a = col_acc.setdefault(cid, {"teachers": 0, "hours": 0.0, "courses": 0.0})
        a["teachers"] += 1
        a["hours"] += rec["hours"] or 0
        a["courses"] += rec["courses"] or 0
    cname = {r["college_id"]: r["name"] for r in dbm.query(
        conn, "SELECT college_id,name FROM dim_college")}
    deptLoad = []
    for cid, a in col_acc.items():
        n = a["teachers"] or 1
        avg_h = round(a["hours"] / n)
        deptLoad.append({"id": cid, "dept": cname.get(cid, cid), "teacherCount": a["teachers"],
                         "avgHours": avg_h, "avgCourses": round(a["courses"] / n, 1),
                         "loadLevel": min(round(avg_h / 200 * 100), 100)})
    deptLoad.sort(key=lambda x: -x["avgHours"])

    n_teach = len(load) or 1
    sum_h = sum(load[t]["hours"] or 0 for t in load)
    sum_c = sum(load[t]["courses"] or 0 for t in load)
    sum_cl = sum(load[t]["classes"] or 0 for t in load)
    prof_rate = next((x["teachingRate"] for x in titleLoad if x["title"] == "教授"), 0)
    assoc_rate = next((x["teachingRate"] for x in titleLoad if x["title"] == "副教授"), 0)
    overload_n = sum(1 for h in hrs if h > 280)
    kpis = [
        {"label": "人均学时", "value": str(round(sum_h / n_teach)), "color": "#1E3A5F",
         "formula": "SUM(学时)÷授课教师数"},
        {"label": "人均课程门数", "value": str(round(sum_c / n_teach, 1)), "color": "#2563EB",
         "formula": "SUM(课程)÷授课教师数"},
        {"label": "人均教学班", "value": str(round(sum_cl / n_teach, 1)), "color": "#1E3A5F",
         "formula": "SUM(教学班)÷授课教师数"},
        {"label": "教授上课率", "value": f"{prof_rate}%",
         "color": "#16A34A" if prof_rate >= 85 else "#DC2626",
         "formula": "授课教授÷教授总数"},
        {"label": "副教授上课率", "value": f"{assoc_rate}%", "color": "#16A34A",
         "formula": "授课副教授÷副教授总数"},
        {"label": "过载教师", "value": f"{overload_n}人", "color": "#DC2626",
         "formula": "学时>280"},
    ]
    return ok({
        "kpis": kpis, "titleLoad": titleLoad, "loadDist": loadDist,
        "overloaded": overloaded, "deptLoad": deptLoad})


# ------------------------------------------------------------------ 课程排课分析

# 思政课识别关键词（课程名称包含任一即判为思政类）
_POLITICS_KEYS = ["马克思主义", "毛泽东", "习近平", "思想道德", "形势与政策",
                  "近代史", "中国特色", "中国共产党", "思想政治教育"]


def _is_politics(name: str) -> bool:
    if not name:
        return False
    return any(k in name for k in _POLITICS_KEYS)


def _extract_grade(class_names: str) -> str | None:
    """从班名提取年级，如 '安全22-1班' → '2022'。"""
    import re
    if not class_names:
        return None
    m = re.search(r'(\d{2})-\d+班', class_names)
    if m:
        yr = int(m.group(1))
        return f"20{yr}" if yr >= 0 else None
    return None


@router.get("/schedule-analysis")
def schedule_analysis(semester: Optional[str] = None,
                      conn: sqlite3.Connection = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    sem_ids = _sem_ids(conn, semester, None, REAL)
    sem_ph = ",".join("?" * len(sem_ids))
    sem_p = tuple(sem_ids)

    # ---- KPI 卡片 ----
    cat_count = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT category) FROM agg_course_category_term
        WHERE semester_id IN ({sem_ph})""", sem_p) or 0
    lesson_total = dbm.scalar(conn, f"""
        SELECT SUM(lesson_count) FROM agg_course_category_term
        WHERE semester_id IN ({sem_ph})""", sem_p) or 0
    avg_enrolled_all = dbm.scalar(conn, f"""
        SELECT AVG(avg_enrolled) FROM agg_course_category_term
        WHERE semester_id IN ({sem_ph})""", sem_p) or 0
    hours_total = dbm.scalar(conn, f"""
        SELECT SUM(total_hours) FROM agg_course_category_term
        WHERE semester_id IN ({sem_ph})""", sem_p) or 0
    kpis = [
        {"label": "课程类别数", "value": str(cat_count), "formula": "distinct 课程类别"},
        {"label": "教学班总数", "value": f"{lesson_total:,}", "formula": "SUM(教学班)"},
        {"label": "平均班额", "value": f"{round(avg_enrolled_all, 1)}人", "formula": "AVG(avg_enrolled)"},
        {"label": "总学时", "value": f"{hours_total:,.0f}", "formula": "SUM(total_hours)"},
    ]

    # ---- 模块1: 课程类别分布 ----
    categoryDist = []
    cat_rows = dbm.query(conn, f"""
        SELECT * FROM agg_course_category_term
        WHERE semester_id IN ({sem_ph})
        ORDER BY lesson_count DESC""", sem_p)
    for r in cat_rows:
        categoryDist.append({
            "category": r["category"],
            "courseCount": r["course_count"],
            "lessonCount": r["lesson_count"],
            "totalHours": round(r["total_hours"] or 0, 1),
            "theoryHours": round(r["theory_hours"] or 0, 1),
            "expHours": round(r["exp_hours"] or 0, 1),
            "practiceHours": round(r["practice_hours"] or 0, 1),
            "labHours": round(r["lab_hours"] or 0, 1),
            "avgEnrolled": round(r["avg_enrolled"] or 0, 1),
            "smallCount": r["small_count"],
            "mediumCount": r["medium_count"],
            "largeCount": r["large_count"],
            "xlargeCount": r["xlarge_count"],
        })

    # 均匀度指标：前3类别占比 + 变异系数
    top3_pct = 0.0
    if categoryDist:
        total_l = sum(c["lessonCount"] for c in categoryDist)
        top3_pct = round(sum(c["lessonCount"] for c in categoryDist[:3]) / total_l * 100, 1) if total_l else 0
        import math
        vals = [c["lessonCount"] for c in categoryDist]
        mean_v = sum(vals) / len(vals) if vals else 1
        std_v = math.sqrt(sum((v - mean_v) ** 2 for v in vals) / len(vals)) if vals else 0
        cv = round(std_v / mean_v, 3) if mean_v else 0
    else:
        cv = 0
    uniformity = {"top3Pct": top3_pct, "cv": cv}

    # ---- 模块2: 年级×类别交叉 ----
    gradeCross = []
    import re
    grade_rows = dbm.query(conn, f"""
        SELECT co.category, l.class_names, l.course_id, l.enrolled
        FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id
        WHERE l.semester_id IN ({sem_ph}) AND l.class_names IS NOT NULL AND l.class_names!=''
    """, sem_p)
    # 在 Python 侧按 category×grade 聚合
    from collections import defaultdict
    cross: dict[tuple[str, str], int] = defaultdict(int)
    for r in grade_rows:
        g = _extract_grade(r["class_names"] or "")
        cat = r["category"] or "未知"
        if g:
            cross[(cat, g)] += 1
    # 整理成有序列表
    categories_sorted = [c["category"] for c in categoryDist]
    grades_set = sorted(set(g for _, g in cross.keys()), reverse=True)
    gradeCross = {
        "categories": categories_sorted,
        "grades": grades_set,
        "data": [{"category": cat, "grade": grd, "count": cross.get((cat, grd), 0)}
                 for cat in categories_sorted for grd in grades_set],
    }

    # ---- 模块3: 体育/思政专项 ----
    # 体育课：category='体育课' 直接从 agg_course_category_term 取
    pe_row = next((c for c in categoryDist if c["category"] == "体育课"), None)
    # 思政课：从 fact_lesson 按课程名关键词筛选后聚合
    pol_rows = dbm.query(conn, f"""
        SELECT co.name, co.category, l.enrolled, l.total_hours, l.theory_hours,
               l.exp_hours, l.practice_hours, l.lab_hours
        FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id
        WHERE l.semester_id IN ({sem_ph})
    """, sem_p)
    pol_lessons = [r for r in pol_rows if _is_politics(r["name"] or "")]
    pol_course_ids = set()
    pol_lesson_count = len(pol_lessons)
    pol_total_h = 0.0
    pol_theory_h = 0.0
    pol_exp_h = 0.0
    pol_prac_h = 0.0
    pol_lab_h = 0.0
    pol_enrolled = []
    for r in pol_lessons:
        pol_course_ids.add(r["name"])
        pol_total_h += r["total_hours"] or 0
        pol_theory_h += r["theory_hours"] or 0
        pol_exp_h += r["exp_hours"] or 0
        pol_prac_h += r["practice_hours"] or 0
        pol_lab_h += r["lab_hours"] or 0
        if r["enrolled"] is not None:
            pol_enrolled.append(r["enrolled"])
    pol_avg_e = round(sum(pol_enrolled) / len(pol_enrolled), 1) if pol_enrolled else 0

    def _size_buckets(enrolled_list):
        buckets = {"small": 0, "medium": 0, "large": 0, "xlarge": 0}
        for e in enrolled_list:
            if e < 30: buckets["small"] += 1
            elif e < 60: buckets["medium"] += 1
            elif e < 120: buckets["large"] += 1
            else: buckets["xlarge"] += 1
        return buckets

    pePolitics = {
        "pe": {
            "courseCount": pe_row["courseCount"] if pe_row else 0,
            "lessonCount": pe_row["lessonCount"] if pe_row else 0,
            "totalHours": pe_row["totalHours"] if pe_row else 0,
            "theoryHours": pe_row["theoryHours"] if pe_row else 0,
            "practiceHours": pe_row["practiceHours"] if pe_row else 0,
            "avgEnrolled": pe_row["avgEnrolled"] if pe_row else 0,
            "sizeBuckets": {
                "small": pe_row["smallCount"] if pe_row else 0,
                "medium": pe_row["mediumCount"] if pe_row else 0,
                "large": pe_row["largeCount"] if pe_row else 0,
                "xlarge": pe_row["xlargeCount"] if pe_row else 0,
            },
        },
        "politics": {
            "courseCount": len(pol_course_ids),
            "lessonCount": pol_lesson_count,
            "totalHours": round(pol_total_h, 1),
            "theoryHours": round(pol_theory_h, 1),
            "expHours": round(pol_exp_h, 1),
            "practiceHours": round(pol_prac_h, 1),
            "labHours": round(pol_lab_h, 1),
            "avgEnrolled": pol_avg_e,
            "sizeBuckets": _size_buckets(pol_enrolled),
        },
    }

    # ---- 模块3b: 体育/思政教学楼热力图 ----
    # 从 agg_classroom_util 取体育场地 + 教学楼数据，标记是否体育相关
    heatmap_rows = dbm.query(conn, f"""
        SELECT building, room_type, day, period, utilization
        FROM agg_classroom_util WHERE semester_id IN ({sem_ph})
    """, sem_p)
    # 分类建筑：体育场地 vs 普通教学楼
    pe_buildings = set()
    normal_buildings = set()
    for r in heatmap_rows:
        if r["room_type"] == "体育场地":
            pe_buildings.add(r["building"])
        else:
            normal_buildings.add(r["building"])
    # 聚合热力图数据
    DAY_MAP = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五"}
    PERIOD_MAP = {"p12": "1-2节", "p34": "3-4节", "p56": "5-6节", "p78": "7-8节"}

    def _build_heatmap(rows, building_filter):
        """聚合 day×period → 平均利用率。"""
        cells: dict[tuple[int, str], list[float]] = defaultdict(list)
        for r in rows:
            if building_filter and r["building"] not in building_filter:
                continue
            cells[(r["day"], r["period"])].append(r["utilization"])
        result = []
        for (day, period), vals in cells.items():
            result.append({
                "day": day, "dayLabel": DAY_MAP.get(day, str(day)),
                "period": period, "periodLabel": PERIOD_MAP.get(period, period),
                "utilization": round(sum(vals) / len(vals), 3),
            })
        return result

    peHeatmap = _build_heatmap(heatmap_rows, pe_buildings)
    normalHeatmap = _build_heatmap(heatmap_rows, normal_buildings)

    # 建筑负载
    building_load_rows = dbm.query(conn, f"""
        SELECT b.building, b.room_type, AVG(b.utilization) avg_u
        FROM agg_classroom_util b WHERE b.semester_id IN ({sem_ph})
        GROUP BY b.building, b.room_type ORDER BY avg_u DESC
    """, sem_p)
    buildingLoad = []
    for r in building_load_rows:
        buildingLoad.append({
            "building": r["building"], "roomType": r["room_type"],
            "utilization": round(r["avg_u"], 3),
        })

    # ---- 模块5: 时序趋势 ----
    trends = []
    trend_rows = dbm.query(conn, """
        SELECT category, semester_id, lesson_count, total_hours, avg_enrolled
        FROM agg_course_category_term
        ORDER BY category, semester_id
    """)
    for r in trend_rows:
        trends.append({
            "category": r["category"],
            "semester": r["semester_id"],
            "lessonCount": r["lesson_count"],
            "totalHours": round(r["total_hours"] or 0, 1),
            "avgEnrolled": round(r["avg_enrolled"] or 0, 1),
        })

    # PE trends
    peTrends = [t for t in trends if t["category"] == "体育课"]

    # Politics trends (on-the-fly from fact_lesson per semester)
    pol_trend_rows = dbm.query(conn, """
        SELECT l.semester_id, co.name, l.enrolled, l.total_hours
        FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id
        ORDER BY l.semester_id
    """)
    from collections import defaultdict as dd
    pol_trend: dict[str, dict[str, float]] = dd(lambda: {"lessonCount": 0, "totalHours": 0.0, "enrolledSum": 0.0, "enrolledN": 0})
    for r in pol_trend_rows:
        if _is_politics(r["name"] or ""):
            sem = r["semester_id"]
            pol_trend[sem]["lessonCount"] += 1
            pol_trend[sem]["totalHours"] += r["total_hours"] or 0
            if r["enrolled"] is not None:
                pol_trend[sem]["enrolledSum"] += r["enrolled"]
                pol_trend[sem]["enrolledN"] += 1
    politicsTrends = []
    for sem, v in sorted(pol_trend.items()):
        politicsTrends.append({
            "semester": sem,
            "lessonCount": v["lessonCount"],
            "totalHours": round(v["totalHours"], 1),
            "avgEnrolled": round(v["enrolledSum"] / v["enrolledN"], 1) if v["enrolledN"] else 0,
        })

    return ok({
        "kpis": kpis,
        "categoryDist": categoryDist,
        "uniformity": uniformity,
        "gradeCross": gradeCross,
        "pePolitics": pePolitics,
        "heatmaps": {"pe": peHeatmap, "normal": normalHeatmap},
        "buildingLoad": buildingLoad,
        "trends": trends,
        "peTrends": peTrends,
        "politicsTrends": politicsTrends,
    })

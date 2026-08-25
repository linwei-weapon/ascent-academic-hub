"""教学运行分析组：开课/教室/调停课/教师负荷。
全部算自 analytics.sqlite 真实排课(fact_lesson)+预聚合(agg_classroom_util/agg_teacher_load)
+合成调停课(fact_schedule_change)。学院下钻用真实 college_id（C01-C16）。
"""
import sqlite3
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .. import db as dbm
from ..deps import (
    get_db, get_db_rw, get_current_user, get_v2_db,
    student_data_scope, college_data_scope,
)
from ..envelope import ok, ApiError
from ..permission_context import has_action, v2_organization_scope
from ..util import normalize_title, clean_dept
from ..settings import LATEST_REAL_SEMESTER, CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin/operation", tags=["operation"])
REAL = LATEST_REAL_SEMESTER
_PALETTE = ["#2563EB", "#16A34A", "#EA580C", "#F59E0B", "#9333EA", "#60A5FA",
            "#DC2626", "#0891B2", "#65A30D"]
# 单学期教学班 > 阈值 → 判为源库生成缺陷，统计时排除
_TEACHER_CAP = 200
_CLASSROOM_OCCUPANCY_CACHE: dict[tuple, tuple[str, float, dict]] = {}
_CLASSROOM_OCCUPANCY_CACHE_TTL = 900


class QualityStatusIn(BaseModel):
    status: str
    comment: str


def _pct(x, nd=1):
    return round((x or 0) * 100, nd)


def _anomalous_filter(conn, sem_ids: list, alias: str = "l") -> tuple[str, list]:
    """返回 (SQL片段, 参数列表)，排除单学期教学班>200的异常教师。
    SQL片段不含前导 AND，调用方自行拼接。"""
    if not sem_ids:
        return ("", [])
    ph = ",".join("?" * len(sem_ids))
    rows = dbm.query(conn, f"""SELECT entity_id teacher_id FROM data_quality_issue
        WHERE domain='operation' AND issue_type='teacher_lesson_overflow' AND status IN ('open','reviewing')
        AND semester_id IN ({ph})""", tuple(sem_ids))
    bad = [r["teacher_id"] for r in rows]
    if not bad:
        return ("1=1", [])
    bph = ",".join("?" * len(bad))
    return (f"({alias}.teacher_id IS NULL OR {alias}.teacher_id NOT IN ({bph}))", bad)


def _anomaly_summary(conn, sem_ids: list) -> dict:
    if not sem_ids:
        return {"excludedTeachers": 0, "excludedLessons": 0, "threshold": _TEACHER_CAP}
    ph = ",".join("?" * len(sem_ids))
    rows = dbm.query(conn, f"""SELECT entity_id teacher_id,affected_rows lessons FROM data_quality_issue
        WHERE domain='operation' AND issue_type='teacher_lesson_overflow' AND status IN ('open','reviewing')
        AND semester_id IN ({ph})""", sem_ids)
    return {"excludedTeachers": len(rows), "excludedLessons": sum(r["lessons"] for r in rows),
            "threshold": _TEACHER_CAP, "reason": "单教师单学期教学班数超过质量阈值"}


def _course_filter_where(
        conn: sqlite3.Connection, user: dict, college: Optional[str],
        semester: Optional[str], campus: Optional[str],
        course_nature: Optional[str], category: Optional[str],
        size: Optional[str], year: Optional[str] = None,
        keyword: Optional[str] = None, *, exclude_anomalies: bool = True,
) -> tuple[list[str], str, tuple]:
    """构造开课供给统一筛选条件，并在服务端校验显式学院范围。"""
    sem_ids = _sem_ids(conn, semester, year, REAL)
    sem_ph = ",".join("?" * len(sem_ids))
    conds, params = [f"l.semester_id IN ({sem_ph})"], list(sem_ids)

    college_scope, college_scope_params = college_data_scope(user, conn)
    visible_colleges = dbm.query(
        conn,
        "SELECT college_id,name FROM dim_college" +
        (f" WHERE {college_scope}" if college_scope else "") +
        " ORDER BY college_id",
        tuple(college_scope_params),
    )
    if college:
        selected = next(
            (row for row in visible_colleges if row["college_id"] == college), None,
        )
        if not selected:
            exists = dbm.scalar(
                conn, "SELECT 1 FROM dim_college WHERE college_id=?", (college,),
            )
            if exists and college_scope:
                raise ApiError("无权查看该学院开课供给", code=403, status_code=403)
            raise ApiError("学院不存在", code=400, status_code=400)
        conds.append("co.dept=?")
        params.append(selected["name"])
    elif college_scope:
        names = [row["name"] for row in visible_colleges]
        if not names:
            conds.append("1=0")
        else:
            conds.append(f"co.dept IN ({','.join('?' * len(names))})")
            params.extend(names)

    if campus:
        conds.append("l.campus=?")
        params.append(campus)
    if course_nature:
        conds.append("co.course_nature=?")
        params.append(course_nature)
    if category:
        conds.append("co.category=?")
        params.append(category)
    size_range = _SIZE_RANGE.get(size or "")
    if size_range:
        conds.append("l.enrolled>=? AND l.enrolled<?")
        params.extend(size_range)
    if keyword and keyword.strip():
        conds.append("(l.course_id LIKE ? OR co.name LIKE ?)")
        term = f"%{keyword.strip()}%"
        params.extend([term, term])
    if exclude_anomalies:
        anomaly_sql, anomaly_params = _anomalous_filter(conn, sem_ids)
        conds.append(anomaly_sql)
        params.extend(anomaly_params)
    return sem_ids, " AND ".join(conds), tuple(params)


def _course_quality_rows(
        conn: sqlite3.Connection, user: dict, college: Optional[str],
        semester: Optional[str], campus: Optional[str],
        course_nature: Optional[str], category: Optional[str],
        size: Optional[str], year: Optional[str] = None,
        status: Optional[str] = None,
) -> list[dict]:
    """返回当前开课筛选切片实际命中的异常教师，一名教师一条记录。"""
    _, where, params = _course_filter_where(
        conn, user, college, semester, campus, course_nature, category,
        size, year, exclude_anomalies=False,
    )
    status_sql = "q.status=?" if status else "q.status IN ('open','reviewing')"
    status_params = (status,) if status else ()
    return dbm.query(conn, f"""
        SELECT MIN(q.issue_id) issue_id,'operation' domain,
               'teacher_lesson_overflow' issue_type,q.semester_id,
               'teacher' entity_type,q.entity_id,MAX(q.severity) severity,
               MIN(q.status) status,MAX(q.detail) detail,
               MAX(q.recommendation) recommendation,
               t.name entity_name,t.dept entity_dept,
               COUNT(DISTINCT l.lesson_id) affected_rows
        FROM fact_lesson l
        JOIN dim_course co ON co.course_id=l.course_id
        JOIN data_quality_issue q
          ON q.entity_id=l.teacher_id AND q.semester_id=l.semester_id
         AND q.domain='operation' AND q.issue_type='teacher_lesson_overflow'
        LEFT JOIN dim_teacher t ON t.teacher_id=q.entity_id
        WHERE {where} AND {status_sql}
        GROUP BY q.semester_id,q.entity_id,t.name,t.dept
        ORDER BY severity DESC,affected_rows DESC,issue_id
    """, params + status_params)


def _course_quality_summary(rows: list[dict]) -> dict:
    return {
        "excludedTeachers": len(rows),
        "excludedLessons": sum(int(row.get("affected_rows") or 0) for row in rows),
        "threshold": _TEACHER_CAP,
        "reason": "单教师单学期教学班数超过质量阈值",
    }


def _course_offering_rows(conn: sqlite3.Connection, where: str,
                          params: tuple, sort: str = "attention") -> list[dict]:
    rows = dbm.query(conn, f"""
        SELECT l.semester_id,l.course_id,COALESCE(co.name,l.course_id) course_name,
               co.dept,co.category,co.course_nature nature,
               COUNT(*) lesson_count,
               COUNT(DISTINCT NULLIF(TRIM(l.teacher_id),'')) teacher_count,
               SUM(COALESCE(l.enrolled,0)) enrolled
        FROM fact_lesson l JOIN dim_course co ON co.course_id=l.course_id
        WHERE {where}
        GROUP BY l.semester_id,l.course_id,co.name,co.dept,co.category,co.course_nature
    """, params)
    for row in rows:
        lesson_count = int(row.get("lesson_count") or 0)
        enrolled = int(row.get("enrolled") or 0)
        teacher_count = int(row.get("teacher_count") or 0)
        average = enrolled / lesson_count if lesson_count else 0
        row["attention_score"] = (
            (2 if average >= 120 else 1 if average >= 80 else 0)
            + (2 if teacher_count == 1 and lesson_count >= 3 else 0)
            + (2 if lesson_count == 1 and enrolled >= 80 else 0)
        )
    if sort == "scale":
        rows.sort(key=lambda row: (
            -int(row.get("lesson_count") or 0),
            -int(row.get("enrolled") or 0), row.get("course_id") or "",
        ))
    else:
        rows.sort(key=lambda row: (
            -int(row.get("attention_score") or 0),
            -int(row.get("enrolled") or 0),
            -int(row.get("lesson_count") or 0), row.get("course_id") or "",
        ))
    return rows


def _teacher_anomaly_ids(conn: sqlite3.Connection, sem_ids: list[str]) -> set[str]:
    """统一教师负荷异常集合：已登记质量问题 + 防漏启发式阈值。"""
    if not sem_ids:
        return set()
    placeholders = ",".join("?" * len(sem_ids))
    ids = {
        row["entity_id"] for row in dbm.query(conn, f"""
            SELECT entity_id FROM data_quality_issue
            WHERE domain='operation' AND issue_type='teacher_lesson_overflow'
              AND status IN ('open','reviewing')
              AND semester_id IN ({placeholders})
        """, tuple(sem_ids))
    }
    ids.update(
        row["teacher_id"] for row in dbm.query(conn, f"""
            SELECT teacher_id FROM agg_teacher_load
            WHERE semester_id IN ({placeholders})
              AND (COALESCE(classes,0)>200 OR COALESCE(hours,0)>1000
                   OR COALESCE(courses,0)>20)
        """, tuple(sem_ids))
    )
    return ids


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + .999999) - 1))
    return float(ordered[index])


def _college_name(conn, college_id: Optional[str]) -> Optional[str]:
    """学院码(C01-C16)→学院名；无效/缺省返回 None（=全校口径）。"""
    if not college_id:
        return None
    return dbm.scalar(
        conn, "SELECT name FROM dim_college WHERE college_id=?", (college_id,))


def _period_coverage(conn: sqlite3.Connection, sql: str,
                     params: tuple = ()) -> dict:
    rows = dbm.query(conn, sql, params)
    periods = [row["semester_id"] for row in rows if row.get("semester_id")]
    return {
        "available": bool(periods),
        "periods": periods,
        "periodFrom": periods[0] if periods else None,
        "periodTo": periods[-1] if periods else None,
        "periodCount": len(periods),
    }


@router.get("/data-context")
def operation_data_context(user: dict = Depends(get_current_user),
                           conn: sqlite3.Connection = Depends(get_db),
                           v2_conn: sqlite3.Connection = Depends(get_v2_db)):
    """返回各教学运行数据域的真实覆盖、证据级别和当前身份范围。

    页面必须先读取该上下文，再决定学期控件、空状态和口径提示；没有数据、
    未接入和无权访问不得继续统一显示为0。
    """
    context = user.get("permission_context") or {}
    detail_scope = context.get("detailScope") or {}
    college_scope, college_params = college_data_scope(user, conn)
    visible_colleges = dbm.query(
        conn,
        "SELECT college_id,name FROM dim_college" +
        (f" WHERE {college_scope}" if college_scope else "") +
        " ORDER BY name",
        tuple(college_params),
    )
    college_ids = [row["college_id"] for row in visible_colleges]
    college_names = [row["name"] for row in visible_colleges]

    lesson_where, lesson_params = ["1=1"], []
    teacher_where, teacher_params = ["1=1"], []
    change_where, change_params = ["1=1"], []
    if college_scope:
        if college_names:
            placeholders = ",".join("?" * len(college_names))
            lesson_where.append(f"co.dept IN ({placeholders})")
            lesson_params.extend(college_names)
            teacher_where.append(f"t.dept IN ({placeholders})")
            teacher_params.extend(college_names)
        else:
            lesson_where.append("1=0")
            teacher_where.append("1=0")
        if college_ids:
            placeholders = ",".join("?" * len(college_ids))
            change_where.append(f"s.college_id IN ({placeholders})")
            change_params.extend(college_ids)
        else:
            change_where.append("1=0")

    lesson_coverage = _period_coverage(conn, f"""
        SELECT DISTINCT l.semester_id
        FROM fact_lesson l LEFT JOIN dim_course co ON co.course_id=l.course_id
        WHERE {' AND '.join(lesson_where)}
        ORDER BY l.semester_id
    """, tuple(lesson_params))
    room_coverage = _period_coverage(conn, """
        SELECT DISTINCT semester_id FROM fact_room_occupancy
        ORDER BY semester_id
    """) if dbm.scalar(conn, """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='fact_room_occupancy'
    """) else {"available": False, "periods": [], "periodFrom": None,
               "periodTo": None, "periodCount": 0}
    teacher_coverage = _period_coverage(conn, f"""
        SELECT DISTINCT a.semester_id FROM agg_teacher_load a
        JOIN dim_teacher t ON t.teacher_id=a.teacher_id
        WHERE {' AND '.join(teacher_where)}
        ORDER BY a.semester_id
    """, tuple(teacher_params))
    change_coverage = _period_coverage(conn, f"""
        SELECT DISTINCT s.semester_id FROM fact_schedule_change s
        WHERE {' AND '.join(change_where)}
        ORDER BY s.semester_id
    """, tuple(change_params))

    organization_scope, organization_params = v2_organization_scope(
        context, v2_conn, "l",
    )
    organization_where = (
        f"WHERE {organization_scope}" if organization_scope else ""
    )
    schedule_coverage = _period_coverage(v2_conn, f"""
        SELECT DISTINCT l.semester_id FROM teaching_lesson l
        {organization_where}
        ORDER BY l.semester_id
    """, tuple(organization_params))
    result_scope, result_params = v2_organization_scope(
        context, v2_conn, "c",
    )
    result_where = f"WHERE {result_scope}" if result_scope else ""
    result_coverage = _period_coverage(v2_conn, f"""
        SELECT DISTINCT a.semester_id FROM agg_course_pass_stat a
        LEFT JOIN dim_course c ON c.course_id=a.course_id
        {result_where}
        ORDER BY a.semester_id
    """, tuple(result_params)) if dbm.scalar(v2_conn, """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='agg_course_pass_stat'
    """) else {"available": False, "periods": [], "periodFrom": None,
               "periodTo": None, "periodCount": 0}

    domains = {
        "courseSupply": {
            **lesson_coverage,
            "source": "fact_lesson",
            "evidenceLevel": "actual_teaching_task",
            "scopeBasis": "开课学院",
            "timeControl": "single_term",
        },
        "scheduleStructure": {
            **schedule_coverage,
            "source": "teaching_lesson + course_meeting",
            "evidenceLevel": "actual_schedule_snapshot",
            "scopeBasis": "开课组织",
            "timeControl": "single_term",
        },
        "classroomOccupancy": {
            **room_coverage,
            "source": "fact_room_occupancy",
            "evidenceLevel": "actual_occupancy",
            "scopeBasis": "学校共享空间聚合",
            "timeControl": "single_term",
        },
        "teacherLoad": {
            **teacher_coverage,
            "source": "agg_teacher_load",
            "evidenceLevel": "actual_task_derived_hours",
            "scopeBasis": "教师所属学院",
            "timeControl": "single_term",
        },
        "scheduleChanges": {
            **change_coverage,
            "source": "fact_schedule_change",
            "evidenceLevel": "actual_source_event",
            "scopeBasis": "申请学院",
            "timeControl": "single_term",
        },
        "courseResults": {
            **result_coverage,
            "source": "agg_course_pass_stat + grade_attempt",
            "evidenceLevel": "actual_grade_record",
            "scopeBasis": "课程责任学院",
            "timeControl": "independent_period_window",
        },
    }
    return ok({
        "identity": {
            "roleId": context.get("activeRole") or user.get("role_id"),
            "roleName": context.get("activeRoleName"),
            "detailScope": detail_scope.get("type") or "denied",
            "visibleColleges": visible_colleges,
        },
        "domains": domains,
        "defaultSingleTerm": lesson_coverage["periodTo"],
        "rules": {
            "zeroState": "仅在数据域可用且查询成功时显示0；未接入、无权限和请求失败使用独立状态。",
            "sharedSpace": "教室占用按学校共享资源聚合展示，不提供其他学院人员或课程明细。",
            "courseResults": "课程结果使用独立多学期观察窗口，不跟随页面顶部单学期切换。",
        },
    })


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
        "policy": {"statisticalAction": "open/reviewing问题在教学运行统计中排除",
                   "recovery": "源数据修复并复核后可关闭问题并重新计算"},
        "permissions": {"manage": has_action(user, "operation.quality.manage")}})


@router.get("/data-quality/{issue_id}/audit")
def operation_quality_audit(issue_id: str, user: dict = Depends(get_current_user),
                            conn: sqlite3.Connection = Depends(get_db)):
    issue = dbm.query_one(conn, "SELECT 1 FROM data_quality_issue WHERE issue_id=?", (issue_id,))
    if not issue:
        raise ApiError("数据质量问题不存在", code=404, status_code=404)
    return ok(dbm.query(conn, """SELECT from_status,to_status,operator,comment,operated_at
        FROM data_quality_issue_audit WHERE issue_id=? ORDER BY audit_id""", (issue_id,)))


@router.put("/data-quality/{issue_id}/status")
def update_operation_quality_status(issue_id: str, body: QualityStatusIn,
                                    user: dict = Depends(get_current_user),
                                    conn: sqlite3.Connection = Depends(get_db_rw)):
    if not has_action(user, "operation.quality.manage"):
        raise ApiError("仅教务处运行科或教务处处长可处置数据质量问题", code=403, status_code=403)
    issue = dbm.query_one(conn, "SELECT status FROM data_quality_issue WHERE issue_id=?", (issue_id,))
    if not issue:
        raise ApiError("数据质量问题不存在", code=404, status_code=404)
    allowed = {"open": {"reviewing"}, "reviewing": {"open", "closed"}, "closed": {"open"}}
    if body.status not in allowed.get(issue["status"], set()):
        raise ApiError(f"不允许从 {issue['status']} 变更为 {body.status}", code=400, status_code=400)
    if not body.comment.strip():
        raise ApiError("请填写处置说明", code=400, status_code=400)
    now = datetime.now().isoformat(timespec="seconds")
    dbm.execute(conn, "UPDATE data_quality_issue SET status=? WHERE issue_id=?", (body.status, issue_id))
    dbm.execute(conn, """INSERT INTO data_quality_issue_audit
        (issue_id,from_status,to_status,operator,comment,operated_at) VALUES (?,?,?,?,?,?)""",
        (issue_id, issue["status"], body.status, user["username"], body.comment.strip(), now))
    return ok({"issueId": issue_id, "status": body.status}, msg="问题状态已更新")


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
    sem_ids, where, bp = _course_filter_where(
        conn, user, college, semester, campus, course_nature, category, size,
        year, keyword,
    )
    base = "FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id WHERE " + where
    tot_courses = dbm.scalar(conn, f"SELECT COUNT(DISTINCT l.course_id) {base}", bp) or 0
    tot_lessons = dbm.scalar(conn, f"SELECT COUNT(*) {base}", bp) or 0
    total_enrolled = dbm.scalar(conn, f"SELECT SUM(COALESCE(l.enrolled,0)) {base}", bp) or 0
    offering_rows = _course_offering_rows(conn, where, bp, "attention")
    attention_count = sum(1 for row in offering_rows if row["attention_score"] > 0)
    kpis = [
        {"label": "已关联课程", "value": f"{tot_courses}门",
         "formula": "当前筛选范围有效教学任务中的去重课程数", "tone": "primary"},
        {"label": "教学班数", "value": f"{tot_lessons:,}",
         "formula": "当前筛选范围排除异常教师后的教学班记录数", "tone": "primary"},
        {"label": "平均班额", "value": f"{round(total_enrolled / tot_lessons) if tot_lessons else 0}人",
         "formula": "当前筛选范围选课人次÷教学班数", "tone": "teal"},
        {"label": "需核查课程", "value": f"{attention_count}门",
         "formula": "触发大班额、单班集中或单一教师多班覆盖提示的课程数", "tone": "amber"},
    ]

    # 所有页面区域直接复用同一个 where/bp，避免筛选条件在卡片间漂移。
    deptCourses = []
    rows = dbm.query(conn, f"""
        SELECT c.college_id, c.name,
               COUNT(DISTINCT l.course_id) courseCount, COUNT(*) lessonCount
        FROM fact_lesson l JOIN dim_course co ON l.course_id=co.course_id
        JOIN dim_college c ON co.dept=c.name
        WHERE {where}
        GROUP BY c.college_id ORDER BY lessonCount DESC""",
                     bp)
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

    quality_issues = _course_quality_rows(
        conn, user, college, semester, campus, course_nature, category, size,
        year,
    )
    course_list = [{
        "courseId": row["course_id"],
        "courseName": row["course_name"],
        "dept": row.get("dept"),
        "courseNature": row.get("nature"),
        "lessonCount": row.get("lesson_count") or 0,
        "avgEnrolled": round(
            (row.get("enrolled") or 0) / (row.get("lesson_count") or 1), 1,
        ),
        "studentCount": row.get("enrolled") or 0,
    } for row in offering_rows[:100]]

    return ok({
        "kpis": kpis, "deptCourses": deptCourses, "typeDist": typeDist,
        "sizeDist": sizeDist, "trend": [], "totalCourses": tot_courses,
        "courseList": course_list,
        "focusCourses": offering_rows[:10],
        "courseSummary": {
            "course_count": tot_courses, "lesson_count": tot_lessons,
            "enrolled": total_enrolled, "attention_count": attention_count,
        },
        "qualityIssues": quality_issues,
        "dataQuality": _course_quality_summary(quality_issues),
        "filters": {
            "semester": sem_ids[0] if len(sem_ids) == 1 else sem_ids,
            "college": college, "campus": campus,
            "courseNature": course_nature, "category": category, "size": size,
        },
    })


@router.get("/courses/offerings")
def course_offerings(
        college: Optional[str] = None, semester: Optional[str] = None,
        campus: Optional[str] = None, course_nature: Optional[str] = None,
        category: Optional[str] = None, size: Optional[str] = None,
        keyword: Optional[str] = None,
        sort: str = Query("scale", pattern="^(scale|attention)$"),
        limit: int = Query(20, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: dict = Depends(get_current_user),
        conn: sqlite3.Connection = Depends(get_db),
):
    sem_ids, where, params = _course_filter_where(
        conn, user, college, semester, campus, course_nature, category, size,
        keyword=keyword,
    )
    rows = _course_offering_rows(conn, where, params, sort)
    return ok({
        "items": rows[offset:offset + limit],
        "total": len(rows),
        "semester": sem_ids[0] if len(sem_ids) == 1 else sem_ids,
        "sort": sort,
        "summary": {
            "lesson_count": sum(int(row.get("lesson_count") or 0) for row in rows),
            "enrolled": sum(int(row.get("enrolled") or 0) for row in rows),
            "attention_count": sum(
                1 for row in rows if int(row.get("attention_score") or 0) > 0
            ),
        },
        "definition": {
            "attention": "按大班额、单一教师多班覆盖和单班集中供给排序，不是课程质量排名",
        },
    })


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


@router.get("/classroom-occupancy")
def classroom_occupancy(semester: Optional[str] = None, building: Optional[str] = None,
                        include_evening: bool = True,
                        user: dict = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db)):
    """实际教室占用证据；分母仅为源文件中出现过的已观测教室。"""
    if not dbm.scalar(conn, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='fact_room_occupancy'"):
        return ok({"available": False, "evidenceLevel": "not_ingested"})
    cache_key = (semester, building, include_evening)
    batch_signature = str(dbm.scalar(conn, """SELECT COALESCE(MAX(imported_at),'')||':'||
        COALESCE(SUM(loaded_rows),0) FROM etl_room_occupancy_batch""") or "")
    cached = _CLASSROOM_OCCUPANCY_CACHE.get(cache_key)
    if cached and cached[0] == batch_signature and time.monotonic() - cached[1] < _CLASSROOM_OCCUPANCY_CACHE_TTL:
        return ok(cached[2])
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM fact_room_occupancy")
    fact_conds, params = ["o.semester_id=?"], [sem]
    if building:
        fact_conds.append("o.building_name=?"); params.append(building)
    conds = list(fact_conds)
    if not include_evening:
        conds.append("p.period_index<=8")
    where = " AND ".join(conds)
    fact_where = " AND ".join(fact_conds)
    if not include_evening:
        fact_where += " AND EXISTS (SELECT 1 FROM fact_room_occupancy_period fp WHERE fp.occupancy_id=o.occupancy_id AND fp.period_index<=8)"
    summary = dbm.query(conn, """SELECT COUNT(DISTINCT o.occupancy_id) occupancyRecords,
        COUNT(DISTINCT o.room_name) observedRooms,COUNT(DISTINCT o.activity_date) observedDates,
        MIN(o.activity_date) dateFrom,MAX(o.activity_date) dateTo,
        COUNT(DISTINCT CASE WHEN o.overlap_count>0 THEN o.occupancy_id END) overlapRecords,
        COUNT(DISTINCT CASE WHEN o.building_mapping_status='pending' THEN o.occupancy_id END) pendingMappingRecords,
        COUNT(DISTINCT CASE WHEN o.is_evening=1 THEN o.occupancy_id END) eveningRecords
        FROM fact_room_occupancy o WHERE """ + fact_where, params)[0]
    # 晚间记录始终返回当前学期/楼宇的总量，便于开关前后保持管理参照一致。
    summary["eveningRecords"] = dbm.scalar(conn,
        "SELECT COUNT(DISTINCT o.occupancy_id) FROM fact_room_occupancy o WHERE " +
        " AND ".join(fact_conds) + " AND o.is_evening=1", params) or 0
    heat_rows = dbm.query(conn, """SELECT o.weekday,p.period_index,
        COUNT(DISTINCT o.room_name||'|'||o.activity_date) occupiedRoomDays
        FROM fact_room_occupancy o JOIN fact_room_occupancy_period p ON p.occupancy_id=o.occupancy_id
        WHERE """ + where + " GROUP BY o.weekday,p.period_index ORDER BY o.weekday,p.period_index", params)
    day_counts = {r["weekday"]: r["days"] for r in dbm.query(conn,
        "SELECT weekday,COUNT(DISTINCT activity_date) days FROM fact_room_occupancy WHERE semester_id=? GROUP BY weekday", (sem,))}
    observed_rooms = summary["observedRooms"] or 0
    heatmap = []
    for row in heat_rows:
        opportunities = observed_rooms * day_counts.get(row["weekday"], 0)
        heatmap.append({"weekday": row["weekday"], "period": row["period_index"],
            "occupiedRoomDays": row["occupiedRoomDays"], "observedOpportunities": opportunities,
            "observedUtilizationPct": round(row["occupiedRoomDays"] * 100 / opportunities, 1) if opportunities else 0})
    buildings = dbm.query(conn, """SELECT COALESCE(o.building_name,'待映射') name,
        COUNT(DISTINCT o.room_name) observedRooms,COUNT(DISTINCT o.activity_date) observedDates,
        COUNT(DISTINCT o.occupancy_id) occupancyRecords,
        COUNT(DISTINCT o.room_name||'|'||o.activity_date||'|'||p.period_index) occupiedRoomSlots
        FROM fact_room_occupancy o LEFT JOIN fact_room_occupancy_period p ON p.occupancy_id=o.occupancy_id
        WHERE """ + where + " GROUP BY COALESCE(o.building_name,'待映射') ORDER BY occupancyRecords DESC", params)
    period_count = 12 if include_evening else 8
    for row in buildings:
        denominator = row["observedRooms"] * row["observedDates"] * period_count
        row["observedLoadPct"] = round(row["occupiedRoomSlots"] * 100 / denominator, 1) if denominator else 0
    activity_types = dbm.query(conn, """SELECT o.activity_type type,COUNT(DISTINCT o.occupancy_id) records
        FROM fact_room_occupancy o WHERE """ + fact_where +
        " GROUP BY o.activity_type ORDER BY records DESC", params)
    payload = {"available": True, "semester": sem, "includeEvening": include_evening,
        "summary": summary, "heatmap": heatmap, "buildings": buildings, "activityTypes": activity_types,
        "evidenceLevel": "actual_occupancy",
        "denominator": "observed_rooms",
        "denominatorExplanation": "利用率分母为本批数据中曾发生占用的已观测教室×实际出现的日期，不代表学校正式可用教室全集。",
        "managementBoundary": "可用于识别占用时序、晚间使用、楼宇负荷和异常重叠；不可直接解释为全校教室空闲率或可用教室数量。"}
    _CLASSROOM_OCCUPANCY_CACHE[cache_key] = (batch_signature, time.monotonic(), payload)
    return ok(payload)


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
_SEMANTIC_REASON_RULES = [
    ("教师个人安排", ("教师请假", "教师临时", "教师", "病假", "事假", "出差", "会议", "个人"), "#DC2626"),
    ("教学计划调整", ("教学计划", "教学调整", "课程冲突", "补课"), "#2563EB"),
    ("教室与设备", ("教室", "设备", "场地", "容量"), "#D97706"),
    ("学校与学生活动", ("学生活动", "学校活动", "大型活动"), "#7C3AED"),
    ("节假日与校历", ("节假日", "校历"), "#0D9488"),
    ("突发与不可抗力", ("天气", "突发", "不可抗力"), "#0891B2"),
]


def _classify_schedule_reason(reason: str) -> dict:
    text = str(reason or "").strip()
    for category, keywords, color in _SEMANTIC_REASON_RULES:
        matched = [keyword for keyword in keywords if keyword in text]
        if matched:
            return {"category": category, "matchedKeyword": matched[0], "confidence": "高",
                    "method": "keyword-rule-v1", "color": color}
    return {"category": "其他待核验", "matchedKeyword": None, "confidence": "低",
            "method": "keyword-rule-v1", "color": "#94A3B8"}


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
    teachers = dbm.scalar(conn, f"SELECT COUNT(DISTINCT teacher_id) FROM fact_schedule_change{w}", p) or 0
    reason_coverage = dbm.scalar(conn, f"""SELECT AVG(
        CASE WHEN NULLIF(TRIM(reason),'') IS NOT NULL THEN 1.0 ELSE 0 END
        ) FROM fact_schedule_change{w}""", p) or 0
    stop_share = round(stop * 100 / total, 1) if total else 0
    kpis = [
        {"label": "调课记录", "value": str(chg), "color": "#1E3A5F",
         "formula": "当前筛选学期内kind=调课的源事件记录数"},
        {"label": "停课记录", "value": str(stop), "color": "#DC2626",
         "formula": "当前筛选学期内kind=停课的源事件记录数；不推断是否已补课"},
        {"label": "停课记录占比", "value": f"{stop_share}%", "color": "#EA580C",
         "formula": "停课记录数÷全部调停课记录数"},
        {"label": "影响学生人次", "value": f"{affected:,}人次", "color": "#EA580C",
         "formula": "源事件affected字段合计；同一学生多次受影响会重复计数"},
        {"label": "涉及教师", "value": f"{teachers}人", "color": "#2563EB",
         "formula": "调停课源事件中的去重教师数"},
        {"label": "原因文本覆盖率", "value": f"{_pct(reason_coverage)}%", "color": "#16A34A",
         "formula": "原因文本非空记录数÷全部调停课记录数"},
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

    reasonDist, semantic_map = [], {}
    for r in dbm.query(conn, f"""
        SELECT reason, COUNT(*) n FROM fact_schedule_change{w}
        GROUP BY reason ORDER BY n DESC""", p):
        classified = _classify_schedule_reason(r["reason"])
        reasonDist.append({"name": r["reason"], "count": r["n"],
                           "pct": round(r["n"] / total * 100),
                           "semanticCategory": classified["category"],
                           "matchedKeyword": classified["matchedKeyword"],
                           "confidence": classified["confidence"],
                           "color": _REASON_COLOR.get(r["reason"], classified["color"])})
        item = semantic_map.setdefault(classified["category"],
            {"name": classified["category"], "count": 0, "color": classified["color"], "rawReasons": []})
        item["count"] += r["n"]
        item["rawReasons"].append({"text": r["reason"], "count": r["n"], "matchedKeyword": classified["matchedKeyword"]})
    semanticReasonDist = sorted(semantic_map.values(), key=lambda item: -item["count"])
    for item in semanticReasonDist:
        item["pct"] = round(item["count"] / total * 100, 1) if total else 0

    frequentTeachers = []
    for r in dbm.query(conn, f"""
        SELECT s.teacher_id, t.name, t.dept, COUNT(*) cnt
        FROM fact_schedule_change s JOIN dim_teacher t ON s.teacher_id=t.teacher_id{sw}
        GROUP BY s.teacher_id HAVING cnt>=3 ORDER BY cnt DESC LIMIT 10""", sp):
        teacher_reasons = dbm.query(conn, """SELECT reason,COUNT(*) count
            FROM fact_schedule_change WHERE teacher_id=? AND semester_id=?
            GROUP BY reason ORDER BY count DESC""", (r["teacher_id"], sem))
        top_reason = teacher_reasons[0]["reason"] if teacher_reasons else "其他"
        frequentTeachers.append({
            "id": r["teacher_id"], "name": r["name"] or r["teacher_id"],
            "dept": clean_dept(r["dept"]) or "—", "count": r["cnt"],
            "reason": f"{_classify_schedule_reason(top_reason)['category']}为主",
            "rawTopReason": top_reason,
            "reasonBreakdown": [{**item, "semanticCategory": _classify_schedule_reason(item["reason"])["category"]}
                                for item in teacher_reasons]})

    monthlyTrend = [
        {"month": f"{row['month']}月", "monthIndex": row["month"],
         "count": row["n"], "affected": row["affected"]}
        for row in dbm.query(conn, f"""SELECT month,COUNT(*) n,
            COALESCE(SUM(affected),0) affected
            FROM fact_schedule_change{w}
            GROUP BY month ORDER BY month""", p)
    ]

    return ok({
        "kpis": kpis, "deptRanks": deptRanks, "reasonDist": reasonDist,
        "semanticReasonDist": semanticReasonDist,
        "classification": {"method": "keyword-rule-v1", "aiEnabled": False,
            "classifiedRecords": sum(item["count"] for item in semanticReasonDist if item["name"] != "其他待核验"),
            "unclassifiedRecords": semantic_map.get("其他待核验", {}).get("count", 0),
            "explanation": "先按可解释关键词规则对原因文本预分类并保留原文；未调用外部AI，生产环境可在匿名化和审核机制明确后替换为受控模型。"},
        "frequentTeachers": frequentTeachers, "monthlyTrend": monthlyTrend,
        "evidenceLevel": "actual_source_event",
        "derivedFieldsExcluded": ["auto_approved", "review_days"],
        "dataSource": "历史调停课源事件及原始原因文本",
        "dataLimitation": "当前事件可用于统计调课、停课、原因、月份、涉及教师和影响人次；审批层级、审核时长、补课安排与学生通知证据未接入，不输出相关结论。"})


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
    anomaly_ids = _teacher_anomaly_ids(conn, [sem])
    scoped_anomaly_ids = {
        teacher_id for teacher_id in anomaly_ids
        if in_college is None or teacher_id in in_college
    }
    load = {r["teacher_id"]: r for r in dbm.query(
        conn, "SELECT teacher_id, hours, courses, classes FROM agg_teacher_load WHERE semester_id=?",
        (sem,))
        if (in_college is None or r["teacher_id"] in in_college)
        and r["teacher_id"] not in anomaly_ids}

    order = ["教授", "副教授", "讲师", "助教", "其他"]
    by_title: dict = {k: {"count": 0, "hours": 0.0, "hourValues": [],
                          "courses": 0.0, "classes": 0.0} for k in order}
    for tid, rec in load.items():
        title = title_of.get(tid, "其他")
        b = by_title[title]
        b["count"] += 1
        b["hours"] += rec["hours"] or 0
        b["hourValues"].append(float(rec["hours"] or 0))
        b["courses"] += rec["courses"] or 0
        b["classes"] += rec["classes"] or 0
    titleLoad = []
    for k in order:
        b = by_title[k]
        if b["count"] == 0:
            continue
        count = b["count"] or 1
        titleLoad.append({
            "title": k, "count": b["count"],
            "avgHours": round(b["hours"] / count),
            "medianHours": round(_nearest_rank(b["hourValues"], .5), 1),
            "p90Hours": round(_nearest_rank(b["hourValues"], .9), 1),
            "avgCourses": round(b["courses"] / count, 1),
            "avgClasses": round(b["classes"] / count, 1),
            "note": "仅统计有教学任务教师", "status": "info"})

    # 学时分布仅描述数据区间，不套用未经学校确认的正常/过载结论。
    hrs = [load[t]["hours"] or 0 for t in load]
    dbk = [("<80学时", 0, 80, "#94A3B8"), ("80—179学时", 80, 180, "#16A34A"),
           ("180—279学时", 180, 280, "#EA580C"), ("≥280学时", 280, 1e9, "#DC2626")]
    nload = len(hrs) or 1
    loadDist = []
    for label, lo, hi, color in dbk:
        c = sum(1 for h in hrs if lo <= h < hi)
        loadDist.append({"label": label, "count": c, "pct": round(c / nload * 100), "color": color})

    p90_hours = round(_nearest_rank([float(h) for h in hrs], .9), 1)
    median_hours = round(_nearest_rank([float(h) for h in hrs], .5), 1)

    # 负荷核查队列：按当前范围P90形成有限统计线索，不直接认定“超负荷”。
    # 学生覆盖人次、教学班数、课程数与平均班额作为管理核查证据。
    teacher_load_rows = dbm.query(conn, """
        SELECT l.teacher_id, COALESCE(MAX(t.name), l.teacher_id) name,
               MAX(t.dept) dept,
               COUNT(DISTINCT l.course_id) course_count,
               COUNT(DISTINCT l.lesson_id) lesson_count,
               ROUND(SUM(COALESCE(l.total_hours, 0)), 1) total_hours,
               SUM(COALESCE(l.enrolled, 0)) student_visits,
               ROUND(AVG(NULLIF(l.enrolled, 0)), 1) avg_class_size
        FROM fact_lesson l
        LEFT JOIN dim_teacher t ON t.teacher_id=l.teacher_id
        WHERE l.semester_id=? AND NULLIF(TRIM(l.teacher_id), '') IS NOT NULL
        GROUP BY l.teacher_id
        ORDER BY total_hours DESC, student_visits DESC, lesson_count DESC
    """, (sem,))
    teacher_load_rows = [
        r for r in teacher_load_rows
        if (in_college is None or r["teacher_id"] in in_college)
        and r["teacher_id"] not in anomaly_ids
        and float(r["total_hours"] or 0) >= p90_hours
    ][:10]
    topTeachers = []
    for rank, r in enumerate(teacher_load_rows, 1):
        courses = dbm.query(conn, """
            SELECT l.course_id, COALESCE(MAX(c.name), l.course_id) course_name,
                   COUNT(DISTINCT l.lesson_id) lesson_count,
                   ROUND(SUM(COALESCE(l.total_hours, 0)), 1) total_hours,
                   SUM(COALESCE(l.enrolled, 0)) student_visits,
                   ROUND(AVG(NULLIF(l.enrolled, 0)), 1) avg_class_size
            FROM fact_lesson l
            LEFT JOIN dim_course c ON c.course_id=l.course_id
            WHERE l.semester_id=? AND l.teacher_id=?
            GROUP BY l.course_id
            ORDER BY total_hours DESC, student_visits DESC
        """, (sem, r["teacher_id"]))
        topTeachers.append({
            "rank": rank, "id": r["teacher_id"], "name": r["name"],
            "title": title_of.get(r["teacher_id"], "其他"),
            "dept": clean_dept(r["dept"]) or "未归属",
            "hours": r["total_hours"] or 0,
            "courses": r["course_count"] or 0,
            "lessons": r["lesson_count"] or 0,
            "studentVisits": r["student_visits"] or 0,
            "avgClassSize": r["avg_class_size"] or 0,
            "reviewReason": (
                f"总学时不低于当前范围P90（{p90_hours:g}学时），"
                "需结合教学班、学生覆盖与课程构成核查"
            ),
            "courseBreakdown": [{
                "courseId": x["course_id"], "courseName": x["course_name"],
                "lessons": x["lesson_count"], "hours": x["total_hours"] or 0,
                "studentVisits": x["student_visits"] or 0,
                "avgClassSize": x["avg_class_size"] or 0,
            } for x in courses],
        })

    # 各学院负荷
    name2cid = {r["name"]: r["college_id"] for r in dbm.query(
        conn, "SELECT college_id,name FROM dim_college")}
    col_acc: dict = {}
    for tid, rec in load.items():
        cid = name2cid.get(dept_of.get(tid))
        if not cid:
            continue
        a = col_acc.setdefault(cid, {"teachers": 0, "hours": 0.0, "hourValues": [],
                                     "courses": 0.0})
        a["teachers"] += 1
        a["hours"] += rec["hours"] or 0
        a["hourValues"].append(float(rec["hours"] or 0))
        a["courses"] += rec["courses"] or 0
    cname = {r["college_id"]: r["name"] for r in dbm.query(
        conn, "SELECT college_id,name FROM dim_college")}
    deptLoad = []
    for cid, a in col_acc.items():
        n = a["teachers"] or 1
        avg_h = round(a["hours"] / n)
        deptLoad.append({"id": cid, "dept": cname.get(cid, cid), "teacherCount": a["teachers"],
                         "avgHours": avg_h,
                         "medianHours": round(_nearest_rank(a["hourValues"], .5), 1),
                         "p90Hours": round(_nearest_rank(a["hourValues"], .9), 1),
                         "avgCourses": round(a["courses"] / n, 1)})
    deptLoad.sort(key=lambda x: (-x["p90Hours"], -x["medianHours"]))
    max_dept_hours = max((row["p90Hours"] for row in deptLoad), default=0)
    for row in deptLoad:
        row["loadLevel"] = (
            round(row["p90Hours"] * 100 / max_dept_hours)
            if max_dept_hours else 0
        )

    n_teach = len(load)
    sum_h = sum(load[t]["hours"] or 0 for t in load)
    sum_c = sum(load[t]["courses"] or 0 for t in load)
    kpis = [
        {"label": "有效授课教师", "value": f"{n_teach}人", "color": "#1E3A5F",
         "formula": "排除当前开放/复核中数据质量问题后，有有效教学任务的去重教师数"},
        {"label": "人均学时", "value": str(round(sum_h / n_teach) if n_teach else 0), "color": "#1E3A5F",
         "formula": "有效教学任务总学时÷有效授课教师数；不是学校正式工作量"},
        {"label": "中位学时", "value": f"{median_hours:g}", "color": "#2563EB",
         "formula": "有效授课教师学时的第50百分位，降低极端值对均值的影响"},
        {"label": "P90学时", "value": f"{p90_hours:g}", "color": "#EA580C",
         "formula": "有效授课教师学时的第90百分位，仅用于形成有限核查队列"},
        {"label": "人均课程门数", "value": str(round(sum_c / n_teach, 1) if n_teach else 0), "color": "#2563EB",
         "formula": "有效教学任务课程门数合计÷有效授课教师数"},
        {"label": "已排除异常教师", "value": f"{len(scoped_anomaly_ids)}人", "color": "#DC2626",
         "formula": "命中教学班>200、学时>1000、课程>20或已登记质量问题的教师数"},
    ]
    return ok({
        "kpis": kpis, "titleLoad": titleLoad, "loadDist": loadDist,
        "reviewCandidates": topTeachers, "topTeachers": topTeachers,
        "deptLoad": deptLoad,
        "dataQuality": {
            "excludedTeachers": len(scoped_anomaly_ids),
            "excludedTeacherIds": sorted(scoped_anomaly_ids),
            "policy": "开放或复核中的质量问题以及启发式异常不进入统计、排名和AI研判",
        },
        "workloadPolicy": {
            "configured": False,
            "statement": "尚未配置学校正式工作量办法，本页不输出达标、未达标或超负荷认定。",
        },
        "evidenceLevel": "actual_task_derived_hours",
        "topTeacherPolicy": {
            "title": "负荷核查队列",
            "ranking": f"仅纳入当前范围总学时不低于P90（{p90_hours:g}学时）的教师，最多10人；同学时按学生覆盖人次、教学班数排序",
            "boundary": "这是统计分布形成的核查顺序，不等同于教师超负荷认定；最终结论需结合学校工作量办法、合讲拆分及减免规则。"
        }})


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

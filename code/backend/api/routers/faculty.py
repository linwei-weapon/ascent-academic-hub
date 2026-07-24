"""师资结构组：师资画像分布 + 教师明细。
画像分布算自 fact_teacher_profile（合成，按真实职称派生），上课率/趋势算自
真实排课 fact_lesson + 真实成绩 fact_grade。学院下钻用真实 college_id（C01-C16）。
"""
import sqlite3
import threading
import time
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
FACULTY_RULE_VERSION = "FACULTY-ASSURANCE-2026.07.1"
_IMPORTANT_COURSE_KEYWORDS = (
    "必修", "主干", "核心", "基础", "思想", "政治", "形势与政策",
    "体育", "数学", "英语",
)
_ANALYSIS_CACHE_TTL_SECONDS = 180
_analysis_cache: dict[tuple[str, Optional[str]], tuple[float, dict]] = {}
_analysis_cache_lock = threading.Lock()


def _member_ids(row: dict) -> set[str]:
    """从主讲及联合教师字段提取去重教师编号。"""
    members: set[str] = set()
    if row.get("teacher_id"):
        members.add(str(row["teacher_id"]).strip())
    raw = str(row.get("teacher_ids") or "")
    for teacher_id in raw.replace("，", ";").replace("；", ";").replace(",", ";").split(";"):
        if teacher_id.strip():
            members.add(teacher_id.strip())
    return members


def _excluded_teacher_ids(conn: sqlite3.Connection, semester: str) -> set[str]:
    """返回分析期内需从正式师资指标排除的教师任务。"""
    return {
        str(row["entity_id"]).strip()
        for row in dbm.query(conn, """
            SELECT DISTINCT entity_id
            FROM data_quality_issue
            WHERE domain='operation'
              AND entity_type='teacher'
              AND semester_id=?
              AND status IN ('open','reviewing')
              AND severity IN ('high','critical')
              AND NULLIF(TRIM(entity_id),'') IS NOT NULL
        """, (semester,))
    }


def _is_important_course(row: dict) -> bool:
    """原型阶段的重点保障课程判定；正式系统由学校规则配置替换。"""
    if int(row.get("is_required") or 0) == 1:
        return True
    text = " ".join(str(row.get(key) or "") for key in (
        "course_name", "course_nature", "category",
    ))
    return any(keyword in text for keyword in _IMPORTANT_COURSE_KEYWORDS)


def _scale_band(enrolled: int) -> str:
    if enrolled < 60:
        return "small"
    if enrolled < 200:
        return "medium"
    return "large"


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]


def _priority_classification(row: dict) -> tuple[str, list[str], str]:
    """以可解释规则形成课程核查类型；单教师事实不会单独触发风险。"""
    reasons: list[str] = []
    important = bool(row.get("important_course"))
    scale_reached = int(row.get("lesson_count") or 0) >= 4 or int(row.get("enrolled") or 0) >= 100
    data_candidate = bool(row.get("data_candidate"))
    high_impact_single = (
        important and scale_reached and int(row.get("teacher_count") or 0) == 1
    )
    continuous_single = bool(row.get("continuous_single")) and important and scale_reached
    high_concentration = bool(row.get("high_concentration")) and important and scale_reached
    structure_review = (
        important
        and int(row.get("teacher_count") or 0) >= 2
        and float(row.get("title_completeness_rate") or 0) >= 90
        and int(row.get("senior_title_teachers") or 0) == 0
        and scale_reached
    )

    if high_impact_single:
        reasons.append(
            f"重点保障课程，本期由1名教师承担{row.get('lesson_count', 0)}个教学班、"
            f"覆盖{row.get('enrolled', 0)}人次"
        )
    if continuous_single:
        reasons.append(
            f"最近{row.get('continuity_observations', 0)}次实际开课持续由同一教师单点承担"
        )
    if high_concentration:
        reasons.append(
            f"重点课程最大主讲教师教学班占比{row.get('max_lesson_share', 0):g}%、"
            f"覆盖人次占比{row.get('max_enrolled_share', 0):g}%，均达到可比组P90"
        )
    if structure_review:
        reasons.append(
            f"团队职称证据率{row.get('title_completeness_rate', 0):g}%，"
            "但当前实际授课团队未体现高级职称教师"
        )
    if data_candidate:
        reasons.extend(row.get("data_candidate_reasons") or [])

    row["high_impact_single"] = high_impact_single
    row["structure_review"] = structure_review
    if data_candidate:
        return "data_candidate", reasons, "数据候选"
    if high_impact_single or continuous_single or high_concentration:
        return "priority_review", reasons, "优先核查"
    if structure_review:
        return "structure_review", reasons, "结构核查"
    return "general_observation", [], "一般观察"


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


def _resolve_faculty_college(user: dict, conn: sqlite3.Connection,
                             college_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """解析课程责任学院范围；受限身份不能通过参数越权访问其他学院。"""
    scope_sql, scope_params = college_data_scope(user, conn)
    allowed_rows = (
        dbm.query(conn, f"SELECT college_id,name FROM dim_college WHERE {scope_sql}", scope_params)
        if scope_sql else []
    )
    if scope_sql:
        allowed_ids = {row["college_id"] for row in allowed_rows}
        if college_id and college_id not in allowed_ids:
            raise ApiError("无权限查看该学院师资保障明细", code=403, status_code=403)
        if not college_id:
            if not allowed_rows:
                raise ApiError("当前身份没有师资保障数据范围", code=403, status_code=403)
            college_id = allowed_rows[0]["college_id"]
    college_name = (
        dbm.scalar(conn, "SELECT name FROM dim_college WHERE college_id=?", (college_id,))
        if college_id else None
    )
    if college_id and not college_name:
        raise ApiError("学院不存在", code=404, status_code=404)
    return college_id, clean_dept(college_name) if college_name else None


def _faculty_analysis(conn: sqlite3.Connection, semester: str,
                      college_name: Optional[str] = None) -> dict:
    """构建课程保障分析事实，所有页面和下钻复用同一套规则。"""
    college_dimension = dbm.query(conn, "SELECT college_id,name FROM dim_college")
    college_ids_by_name = {clean_dept(row["name"]): row["college_id"] for row in college_dimension}
    teacher_meta = {
        str(row["teacher_id"]): row
        for row in dbm.query(conn, "SELECT teacher_id,name,title,dept,source FROM dim_teacher")
    }
    excluded_ids = _excluded_teacher_ids(conn, semester)
    raw_lessons = dbm.query(conn, f"""
        SELECT l.lesson_id,l.semester_id,l.course_id,l.teacher_id,l.teacher_ids,
               l.enrolled,l.capacity,l.total_hours,
               c.name course_name,c.course_nature,c.category,c.is_required,c.dept course_dept
        FROM fact_lesson l
        LEFT JOIN dim_course c ON c.course_id=l.course_id
        WHERE l.semester_id=?
          AND NULLIF(TRIM(l.course_id),'') IS NOT NULL
    """, (semester,))

    courses: dict[str, dict] = {}
    excluded_lesson_count = 0
    excluded_course_ids: set[str] = set()
    for lesson in raw_lessons:
        course_id = str(lesson["course_id"])
        responsibility = clean_dept(lesson.get("course_dept")) or "待映射学院"
        row = courses.setdefault(course_id, {
            "course_id": course_id,
            "course_name": lesson.get("course_name") or course_id,
            "course_nature": lesson.get("course_nature") or "未标注",
            "category": lesson.get("category") or "未标注",
            "is_required": int(lesson.get("is_required") or 0),
            "college_name": responsibility,
            "college_id": college_ids_by_name.get(responsibility),
            "lesson_count": 0,
            "enrolled": 0,
            "capacity": 0,
            "members": set(),
            "primary_lesson_counts": defaultdict(int),
            "primary_enrolled_counts": defaultdict(int),
            "excluded_lesson_count": 0,
            "excluded_teacher_ids": set(),
        })
        primary_id = str(lesson.get("teacher_id") or "").strip()
        if primary_id and primary_id in excluded_ids:
            excluded_lesson_count += 1
            excluded_course_ids.add(course_id)
            row["excluded_lesson_count"] += 1
            row["excluded_teacher_ids"].add(primary_id)
            continue
        valid_members = _member_ids(lesson) - excluded_ids
        row["lesson_count"] += 1
        row["enrolled"] += int(lesson.get("enrolled") or 0)
        row["capacity"] += int(lesson.get("capacity") or 0)
        row["members"].update(valid_members)
        if primary_id and primary_id not in excluded_ids:
            row["primary_lesson_counts"][primary_id] += 1
            row["primary_enrolled_counts"][primary_id] += int(lesson.get("enrolled") or 0)

    # 批量构建历史实际开课团队，用于“最近3次实际开课”的连续性判断。
    history: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    history_excluded = {
        (str(row["semester_id"]), str(row["entity_id"]))
        for row in dbm.query(conn, """
            SELECT semester_id,entity_id
            FROM data_quality_issue
            WHERE domain='operation' AND entity_type='teacher'
              AND status IN ('open','reviewing') AND severity IN ('high','critical')
              AND NULLIF(TRIM(semester_id),'') IS NOT NULL
              AND NULLIF(TRIM(entity_id),'') IS NOT NULL
        """)
    }
    scoped_course_ids = set(courses)
    for lesson in dbm.query(conn, """
        SELECT course_id,semester_id,teacher_id,teacher_ids
        FROM fact_lesson
        WHERE NULLIF(TRIM(course_id),'') IS NOT NULL
        ORDER BY semester_id DESC
    """):
        course_id = str(lesson["course_id"])
        if course_id not in scoped_course_ids:
            continue
        sem = str(lesson["semester_id"])
        primary_id = str(lesson.get("teacher_id") or "").strip()
        if primary_id and (sem, primary_id) in history_excluded:
            continue
        valid_members = {
            member for member in _member_ids(lesson)
            if (sem, member) not in history_excluded
        }
        history[course_id][sem].update(valid_members)

    rows = []
    for row in courses.values():
        members = row.pop("members")
        primary_lesson_counts = row.pop("primary_lesson_counts")
        primary_enrolled_counts = row.pop("primary_enrolled_counts")
        row["teacher_count"] = len(members)
        row["member_ids"] = sorted(members)
        row["known_title_teachers"] = sum(
            bool(str(teacher_meta.get(member, {}).get("title") or "").strip())
            for member in members
        )
        row["senior_title_teachers"] = sum(
            normalize_title(teacher_meta.get(member, {}).get("title")) in ("教授", "副教授")
            for member in members
        )
        row["title_completeness_rate"] = (
            round(row["known_title_teachers"] * 100 / row["teacher_count"], 1)
            if row["teacher_count"] else 0
        )
        row["max_lesson_share"] = (
            round(max(primary_lesson_counts.values(), default=0) * 100 / row["lesson_count"], 1)
            if row["lesson_count"] else 0
        )
        row["max_enrolled_share"] = (
            round(max(primary_enrolled_counts.values(), default=0) * 100 / row["enrolled"], 1)
            if row["enrolled"] else 0
        )
        row["important_course"] = _is_important_course(row)
        row["scale_band"] = _scale_band(row["enrolled"])
        observed = [
            (sem, team) for sem, team in sorted(
                history.get(row["course_id"], {}).items(), reverse=True
            ) if team
        ][:3]
        single_teachers = [next(iter(team)) for _, team in observed if len(team) == 1]
        row["continuity_observations"] = len(observed)
        row["continuous_single"] = (
            len(observed) >= 3
            and len(single_teachers) == len(observed)
            and max((single_teachers.count(member) for member in set(single_teachers)), default=0)
            >= len(observed) - 1
        )
        row["continuity_semesters"] = [sem for sem, _ in observed]
        row["data_candidate_reasons"] = []
        if not row["college_id"]:
            row["data_candidate_reasons"].append("课程责任组织未能映射到教学学院")
        if not row["teacher_count"]:
            row["data_candidate_reasons"].append("有效授课教师证据为空")
        if row["excluded_lesson_count"]:
            row["data_candidate_reasons"].append(
                f"{row['excluded_lesson_count']}条教学任务命中已登记异常并从正式指标排除"
            )
        missing_titles = row["teacher_count"] - row["known_title_teachers"]
        if missing_titles:
            row["data_candidate_reasons"].append(
                f"{missing_titles}名实际授课教师职称证据缺失"
            )
        row["data_candidate"] = bool(row["data_candidate_reasons"])
        row["evaluable"] = (
            row["lesson_count"] > 0
            and row["teacher_count"] > 0
            and bool(row["college_id"])
            and row["excluded_lesson_count"] == 0
        )
        rows.append(row)

    # 在同类、同规模课程中计算当期集中阈值；样本不足时不作正式判断。
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if row["evaluable"]:
            groups[(row["important_course"], row["scale_band"])].append(row)
    thresholds: dict[tuple, tuple[float, float, int]] = {}
    for key, members in groups.items():
        thresholds[key] = (
            _p90([row["max_lesson_share"] for row in members]),
            _p90([row["max_enrolled_share"] for row in members]),
            len(members),
        )
    for row in rows:
        lesson_cutoff, enrolled_cutoff, sample_count = thresholds.get(
            (row["important_course"], row["scale_band"]), (0, 0, 0)
        )
        row["comparison_sample_count"] = sample_count
        row["lesson_share_cutoff"] = lesson_cutoff
        row["enrolled_share_cutoff"] = enrolled_cutoff
        row["high_concentration"] = (
            row["evaluable"]
            and sample_count >= 10
            and row["lesson_count"] >= 4
            and row["enrolled"] >= 100
            and row["max_lesson_share"] >= lesson_cutoff
            and row["max_enrolled_share"] >= enrolled_cutoff
        )
        review_type, reasons, priority_label = _priority_classification(row)
        row["review_type"] = review_type
        row["attention_reasons"] = reasons
        row["priority"] = priority_label
        row["rule_version"] = FACULTY_RULE_VERSION
        # 避免把内部教师编号集合暴露给概览接口。
        row.pop("member_ids", None)

    # 先以全校可比组形成稳定阈值和分类，再按课程责任学院裁剪结果。
    if college_name:
        rows = [row for row in rows if row["college_name"] == college_name]

    priority_order = {
        "priority_review": 0,
        "structure_review": 1,
        "data_candidate": 2,
        "general_observation": 3,
    }
    rows.sort(key=lambda row: (
        priority_order[row["review_type"]],
        -int(row["important_course"]),
        -row["enrolled"],
        row["course_name"],
    ))
    evaluable_rows = [row for row in rows if row["evaluable"]]
    review_rows = [row for row in rows if row["review_type"] != "general_observation"]
    active_ids: set[str] = set()
    for row in evaluable_rows:
        # 重新从当期有效课表提取仅用于范围说明的实际教师数。
        course_id = row["course_id"]
        for lesson in raw_lessons:
            if str(lesson["course_id"]) == course_id:
                primary_id = str(lesson.get("teacher_id") or "").strip()
                if not primary_id or primary_id not in excluded_ids:
                    active_ids.update(_member_ids(lesson) - excluded_ids)
    title_known = sum(
        bool(str(teacher_meta.get(member, {}).get("title") or "").strip())
        for member in active_ids
    )
    scoped_excluded_ids: set[str] = set()
    for row in rows:
        scoped_excluded_ids.update(row.pop("excluded_teacher_ids", set()))
    excluded_lesson_count = sum(row["excluded_lesson_count"] for row in rows)
    excluded_course_ids = {
        row["course_id"] for row in rows if row["excluded_lesson_count"]
    }
    summary = {
        "evaluable_courses": len(evaluable_rows),
        "priority_review_courses": sum(
            row["review_type"] == "priority_review" for row in rows
        ),
        "continuous_single_courses": sum(
            row["continuous_single"] and row["important_course"]
            and (row["lesson_count"] >= 4 or row["enrolled"] >= 100)
            and row["evaluable"]
            for row in rows
        ),
        "structure_review_courses": sum(
            row["review_type"] == "structure_review" for row in rows
        ),
        "data_candidate_courses": sum(
            row["review_type"] == "data_candidate" for row in rows
        ),
        "active_teachers": len(active_ids),
        "courses": len(rows),
        "single_teacher_courses": sum(row["teacher_count"] == 1 for row in rows),
        "title_completeness_rate": (
            round(title_known * 100 / len(active_ids), 1) if active_ids else 0
        ),
        "excluded_lesson_count": excluded_lesson_count,
        "excluded_teacher_count": len(scoped_excluded_ids),
        # 兼容旧前端字段，语义已改为真正需要优先核查的课程。
        "high_impact_courses": sum(
            row["review_type"] == "priority_review" for row in rows
        ),
    }

    colleges_map: dict[str, dict] = {}
    for row in rows:
        if not row["college_id"]:
            continue
        bucket = colleges_map.setdefault(row["college_name"], {
            "college_name": row["college_name"],
            "college_id": row["college_id"],
            "evaluable_courses": 0,
            "priority_review_courses": 0,
            "continuous_single_courses": 0,
            "structure_review_courses": 0,
            "data_candidate_courses": 0,
            "courses": 0,
            "lessons": 0,
            "enrolled": 0,
        })
        bucket["courses"] += 1
        bucket["lessons"] += row["lesson_count"]
        bucket["enrolled"] += row["enrolled"]
        bucket["evaluable_courses"] += int(row["evaluable"])
        bucket["priority_review_courses"] += int(row["review_type"] == "priority_review")
        bucket["continuous_single_courses"] += int(
            row["continuous_single"] and row["important_course"]
            and (row["lesson_count"] >= 4 or row["enrolled"] >= 100)
            and row["evaluable"]
        )
        bucket["structure_review_courses"] += int(row["review_type"] == "structure_review")
        bucket["data_candidate_courses"] += int(row["review_type"] == "data_candidate")
    college_rows = sorted(
        colleges_map.values(),
        key=lambda row: (
            -row["priority_review_courses"],
            -row["structure_review_courses"],
            -row["data_candidate_courses"],
            row["college_name"],
        ),
    )
    affected_colleges = sum(row["priority_review_courses"] > 0 for row in college_rows)
    if college_name:
        management_statement = (
            f"本院本期识别{summary['priority_review_courses']}门优先核查课程、"
            f"{summary['structure_review_courses']}门结构待核实课程；"
            f"另有{summary['data_candidate_courses']}门仅因证据不足进入数据候选。"
            f"分析已排除{excluded_lesson_count}条异常教师任务。"
        )
    else:
        management_statement = (
            f"本期识别{summary['priority_review_courses']}门优先核查课程，"
            f"涉及{affected_colleges}个学院；另有{summary['structure_review_courses']}门结构待核实、"
            f"{summary['data_candidate_courses']}门仅因证据不足进入数据候选。"
            f"分析已排除{excluded_lesson_count}条异常教师任务。"
        )
    return {
        "summary": summary,
        "colleges": college_rows,
        "courses": rows,
        "review_courses": review_rows,
        "management_statement": management_statement,
        "affected_college_count": affected_colleges,
        "evidence_readiness": [
            {"key": "course_org", "label": "课程责任组织", "status": "ready",
             "value": f"{sum(bool(row['college_id']) for row in rows)}/{len(rows)}门",
             "note": "原型暂以课程维表所属部门代理开设责任组织"},
            {"key": "teacher_title", "label": "教师职称", "status": "ready",
             "value": f"{summary['title_completeness_rate']}%",
             "note": "按实际授课教师职称非空率计算"},
            {"key": "official_team", "label": "正式课程团队", "status": "missing",
             "value": "未接入", "note": "当前仅能识别实际授课团队"},
            {"key": "age", "label": "年龄/临退休", "status": "missing",
             "value": "未接入", "note": "不使用模拟年龄形成结论"},
            {"key": "future_plan", "label": "后续开课计划", "status": "missing",
             "value": "未接入", "note": "当前历史证据不代表未来安排"},
        ],
        "quality_gate": {
            "excluded_lesson_count": excluded_lesson_count,
            "excluded_teacher_count": len(scoped_excluded_ids),
            "affected_course_count": len(excluded_course_ids),
            "rule": "分析期内已登记为高/严重且状态为待处理或核验中的教师任务异常",
        },
    }


def _cached_faculty_analysis(conn: sqlite3.Connection, semester: str,
                             college_name: Optional[str] = None) -> dict:
    """短时复用同一学期和责任范围结果，避免首页、队列和抽屉重复全量计算。"""
    key = (semester, college_name)
    now = time.monotonic()
    with _analysis_cache_lock:
        cached = _analysis_cache.get(key)
        if cached and now - cached[0] < _ANALYSIS_CACHE_TTL_SECONDS:
            return cached[1]
    result = _faculty_analysis(conn, semester, college_name)
    with _analysis_cache_lock:
        _analysis_cache[key] = (time.monotonic(), result)
        # 只保留少量近期范围，防止长期切换学期/学院导致进程内缓存增长。
        if len(_analysis_cache) > 48:
            oldest = min(_analysis_cache, key=lambda item: _analysis_cache[item][0])
            _analysis_cache.pop(oldest, None)
    return result


@router.get("/management-overview")
def management_overview(college: Optional[str] = None, semester: Optional[str] = None,
                        user: dict = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db)):
    """本科教学师资保障总览：课程保障优先级、证据状态与学院责任范围。"""
    college_id, college_name = _resolve_faculty_college(user, conn, college)
    sem = semester or REAL
    analysis = _cached_faculty_analysis(conn, sem, college_name)
    return ok({
        "semester": sem,
        "college": college_name,
        "college_id": college_id,
        "scope_mode": "college" if college_name else "school",
        "summary": analysis["summary"],
        "colleges": analysis["colleges"],
        "risk_courses": analysis["review_courses"][:30],
        "management_statement": analysis["management_statement"],
        "affected_college_count": analysis["affected_college_count"],
        "evidence_readiness": analysis["evidence_readiness"],
        "quality_gate": analysis["quality_gate"],
        "rule_version": FACULTY_RULE_VERSION,
        "definition": {
            "evaluable_courses": "通过数据质量门禁，且具有课程责任组织、有效教学任务和可识别实际授课教师的去重课程数。",
            "priority_review_courses": "重点保障课程中，同时命中规模条件与高影响单点、连续单点或当期任务高度集中规则的课程数；单教师事实不会单独触发。",
            "continuous_single_courses": "重点保障课程最近3次实际开课均为单教师承担，且至少2次为同一教师，同时达到4个教学班或100人次规模的课程数。",
            "structure_review_courses": "重点保障课程实际团队不少于2人、职称证据率不低于90%、达到规模条件且未体现高级职称教师的课程数。",
            "data_candidate_courses": "因课程组织、授课教师、职称或异常任务证据不足，暂不形成正式保障判断的课程数。",
            "title_completeness": "实际授课教师中职称字段非空人数÷实际授课教师人数。",
            "boundary": "本页用于课程师资供给连续性与团队保障核查，不评价教师个人教学质量；教师负荷排名归属教学运行分析，未接入的年龄、临退休、正式团队和未来计划不形成正式结论。",
        },
    })


@router.get("/management-courses")
def management_courses(college: Optional[str] = None, semester: Optional[str] = None,
                       review_type: Optional[str] = None, keyword: Optional[str] = None,
                       page: int = 1, page_size: int = 20,
                       user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db)):
    """师资保障课程队列，服务端分页并复用首页正式口径。"""
    _, college_name = _resolve_faculty_college(user, conn, college)
    analysis = _cached_faculty_analysis(conn, semester or REAL, college_name)
    rows = analysis["courses"]
    if review_type == "continuous_single":
        rows = [
            row for row in rows
            if row["continuous_single"] and row["important_course"]
            and (row["lesson_count"] >= 4 or row["enrolled"] >= 100)
        ]
    elif review_type:
        rows = [row for row in rows if row["review_type"] == review_type]
    if keyword and keyword.strip():
        needle = keyword.strip().lower()
        rows = [
            row for row in rows
            if needle in str(row["course_name"]).lower()
            or needle in str(row["course_id"]).lower()
        ]
    page = max(1, page)
    page_size = min(100, max(10, page_size))
    total = len(rows)
    start = (page - 1) * page_size
    return ok({
        "items": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "rule_version": FACULTY_RULE_VERSION,
    })


@router.get("/management-course/{course_id}")
def management_course(course_id: str, semester: Optional[str] = None,
                      user: dict = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or REAL
    course = dbm.query_one(conn, """
        SELECT course_id courseId,name courseName,course_nature courseNature,
               category,is_required,dept
        FROM dim_course WHERE course_id=?
    """, (course_id,)) or {
        "courseId": course_id, "courseName": course_id, "dept": None,
    }
    course_college = clean_dept(course.get("dept"))
    course_college_id = (
        dbm.scalar(conn, "SELECT college_id FROM dim_college WHERE TRIM(name)=?",
                   (course_college,))
        if course_college else None
    )
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope:
        allowed_ids = {
            row["college_id"]
            for row in dbm.query(
                conn, f"SELECT college_id FROM dim_college WHERE {col_scope}", col_params
            )
        }
        if not course_college_id or course_college_id not in allowed_ids:
            raise ApiError("无权限查看该课程团队", code=403, status_code=403)
    excluded_ids = _excluded_teacher_ids(conn, sem)
    raw_lessons = dbm.query(conn, """
        SELECT lesson_id,semester_id,teacher_id,teacher_ids,enrolled,capacity,total_hours
        FROM fact_lesson WHERE course_id=? AND semester_id=?
    """, (course_id, sem))
    lessons = [
        row for row in raw_lessons
        if not row.get("teacher_id")
        or str(row["teacher_id"]).strip() not in excluded_ids
    ]
    if not raw_lessons:
        raise ApiError("当前学期暂无该课程教学任务", code=404, status_code=404)
    member_ids = set()
    member_lessons: dict[str, int] = defaultdict(int)
    member_enrolled: dict[str, int] = defaultdict(int)
    primary_ids: set[str] = set()
    for item in lessons:
        primary_id = str(item.get("teacher_id") or "").strip()
        if primary_id:
            primary_ids.add(primary_id)
        for teacher_id in _member_ids(item) - excluded_ids:
            member_ids.add(teacher_id)
            member_lessons[teacher_id] += 1
            member_enrolled[teacher_id] += int(item.get("enrolled") or 0)
    marks = ",".join("?" for _ in member_ids)
    members = dbm.query(conn, f"""SELECT teacher_id staff_id,name display_name,title,dept organization_id,source
      FROM dim_teacher WHERE teacher_id IN ({marks}) ORDER BY name""", tuple(member_ids)) if member_ids else []
    known_member_ids = {str(row["staff_id"]) for row in members}
    for member in members:
        teacher_id = str(member["staff_id"])
        member["team_role"] = "主讲" if teacher_id in primary_ids else "联合授课"
        member["lesson_count"] = member_lessons.get(teacher_id, 0)
        member["enrolled"] = member_enrolled.get(teacher_id, 0)
        member["lesson_share"] = (
            round(member["lesson_count"] * 100 / len(lessons), 1) if lessons else 0
        )
    for teacher_id in sorted(member_ids - known_member_ids):
        members.append({
            "staff_id": teacher_id,
            "display_name": teacher_id,
            "title": None,
            "organization_id": None,
            "source": "missing",
            "team_role": "主讲" if teacher_id in primary_ids else "联合授课",
            "lesson_count": member_lessons.get(teacher_id, 0),
            "enrolled": member_enrolled.get(teacher_id, 0),
            "lesson_share": (
                round(member_lessons.get(teacher_id, 0) * 100 / len(lessons), 1)
                if lessons else 0
            ),
        })
    known = [x for x in members if str(x.get("title") or "").strip()]
    historical_lessons = dbm.query(conn, """
        SELECT lesson_id,semester_id,teacher_id,teacher_ids,enrolled,capacity
        FROM fact_lesson WHERE course_id=? ORDER BY semester_id DESC
    """, (course_id,))
    historical_excluded = {
        (str(row["semester_id"]), str(row["entity_id"]))
        for row in dbm.query(conn, """
            SELECT semester_id,entity_id
            FROM data_quality_issue
            WHERE domain='operation' AND entity_type='teacher'
              AND status IN ('open','reviewing') AND severity IN ('high','critical')
        """)
    }
    offering_map: dict[str, dict] = {}
    for lesson in historical_lessons:
        offering_semester = str(lesson["semester_id"])
        primary_id = str(lesson.get("teacher_id") or "").strip()
        if primary_id and (offering_semester, primary_id) in historical_excluded:
            continue
        bucket = offering_map.setdefault(offering_semester, {
            "semesterId": offering_semester, "lessonIds": set(), "teacherIds": set(),
            "capacity": 0, "enrolled": 0,
        })
        bucket["lessonIds"].add(str(lesson["lesson_id"]))
        bucket["teacherIds"].update({
            teacher_id for teacher_id in _member_ids(lesson)
            if (offering_semester, teacher_id) not in historical_excluded
        })
        bucket["capacity"] += int(lesson.get("capacity") or 0)
        bucket["enrolled"] += int(lesson.get("enrolled") or 0)
    offerings = []
    for bucket in sorted(offering_map.values(), key=lambda row: row["semesterId"], reverse=True):
        lesson_count = len(bucket.pop("lessonIds"))
        teacher_count = len(bucket.pop("teacherIds"))
        bucket["lessonCount"] = lesson_count
        bucket["teacherCount"] = teacher_count
        bucket["avgClassSize"] = round(bucket["enrolled"] / lesson_count, 1) if lesson_count else 0
        offerings.append(bucket)

    analysis = _cached_faculty_analysis(conn, sem, course_college)
    review = next(
        (row for row in analysis["courses"] if row["course_id"] == course_id),
        None,
    ) or {
        "review_type": "data_candidate",
        "priority": "数据候选",
        "attention_reasons": ["当前课程缺少可形成正式判断的有效任务证据"],
        "rule_version": FACULTY_RULE_VERSION,
        "continuity_observations": 0,
        "continuous_single": False,
    }
    action_by_type = {
        "priority_review": "核实下期是否继续开设、是否已有共同授课或备份安排，以及教学任务拆分是否准确。",
        "structure_review": "核实正式课程团队、课程负责人及梯队安排；当前结果不评价现有教师能力。",
        "data_candidate": "先核实课程责任组织、教师映射、职称或异常任务，数据确认前不形成保障结论。",
        "general_observation": "保留常规观察，无需作为本期优先管理事项。",
    }
    recent = offerings[:3]
    return ok({"course": course, "summary": {"semester_id": sem, "teacher_count": len(member_ids),
      "unknown_title_count": len(member_ids)-len(known),
      "professor_count": sum(normalize_title(x.get("title")) == "教授" for x in known),
      "associate_professor_count": sum(normalize_title(x.get("title")) == "副教授" for x in known),
      "lesson_count": len(lessons), "enrolled": sum(x.get("enrolled") or 0 for x in lessons),
      "excluded_lesson_count": len(raw_lessons) - len(lessons)},
      "review": {
          "type": review["review_type"],
          "label": review["priority"],
          "reasons": review["attention_reasons"],
          "suggested_check": action_by_type[review["review_type"]],
          "rule_version": review["rule_version"],
          "comparison": {
              "sample_count": review.get("comparison_sample_count", 0),
              "lesson_share": review.get("max_lesson_share", 0),
              "lesson_share_cutoff": review.get("lesson_share_cutoff", 0),
              "enrolled_share": review.get("max_enrolled_share", 0),
              "enrolled_share_cutoff": review.get("enrolled_share_cutoff", 0),
          },
      },
      "continuity": {
          "observed_offerings": len(recent),
          "continuous_single": bool(review.get("continuous_single")),
          "summary": (
              f"最近{len(recent)}次实际开课"
              + ("持续呈现单点承担" if review.get("continuous_single") else "未形成连续单点承担结论")
          ),
          "recent": recent,
      },
      "members": members, "offerings": offerings,
      "sources": [
          {"name": "教学任务", "table": "fact_lesson", "time": sem},
          {"name": "课程信息", "table": "dim_course", "time": "当前接入批次"},
          {"name": "教师职称", "table": "dim_teacher", "time": "当前接入批次"},
          {"name": "数据质量问题", "table": "data_quality_issue", "time": sem},
      ],
      "boundary": "成员来自真实教学任务的主讲及联合教师字段；历史开课只证明已接入学期曾开设。当前缺少正式课程团队、未来开课计划、教师资格、合规年龄段和完整岗位状态，不据此评价教师个人或自动认定未来断供风险。"})


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


@router.get("/management-teacher/{teacher_id}")
def management_teacher(teacher_id: str, semester: Optional[str] = None,
                       course_id: Optional[str] = None,
                       user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db)):
    """课程保障上下文中的教师教学经历，不返回成绩评价或模拟个人画像。"""
    sem = semester or CUR
    teacher = dbm.query_one(
        conn, "SELECT teacher_id,name,dept,title,source FROM dim_teacher WHERE teacher_id=?",
        (teacher_id,),
    )
    if not teacher:
        raise ApiError(f"教师不存在: {teacher_id}", code=404, status_code=404)

    scope_sql, scope_params = college_data_scope(user, conn)
    if scope_sql:
        allowed_names = {
            clean_dept(row["name"])
            for row in dbm.query(
                conn, f"SELECT name FROM dim_college WHERE {scope_sql}", scope_params
            )
        }
        teacher_allowed = clean_dept(teacher.get("dept")) in allowed_names
        course_allowed = False
        if course_id:
            course_row = dbm.query_one(
                conn, "SELECT dept FROM dim_course WHERE course_id=?", (course_id,)
            )
            course_allowed = (
                bool(course_row)
                and clean_dept(course_row.get("dept")) in allowed_names
                and bool(dbm.scalar(conn, """
                    SELECT 1 FROM fact_lesson
                    WHERE course_id=? AND semester_id=?
                      AND (teacher_id=? OR teacher_ids LIKE ?)
                    LIMIT 1
                """, (course_id, sem, teacher_id, f"%{teacher_id}%")))
            )
        if not teacher_allowed and not course_allowed:
            raise ApiError("无权限查看该教师教学经历", code=403, status_code=403)

    current_issue = dbm.query_one(conn, """
        SELECT issue_id,status,detail,recommendation,affected_rows
        FROM data_quality_issue
        WHERE domain='operation' AND entity_type='teacher'
          AND entity_id=? AND semester_id=?
          AND status IN ('open','reviewing')
        ORDER BY severity DESC LIMIT 1
    """, (teacher_id, sem))
    current_lessons = dbm.query(conn, """
        SELECT l.lesson_id,l.course_id,c.name course_name,c.dept course_dept,
               l.class_names,l.enrolled,l.total_hours,
               CASE WHEN l.teacher_id=? THEN '主讲' ELSE '联合授课' END team_role
        FROM fact_lesson l
        LEFT JOIN dim_course c ON c.course_id=l.course_id
        WHERE l.semester_id=?
          AND (l.teacher_id=? OR l.teacher_ids LIKE ?)
        ORDER BY c.name,l.lesson_id
    """, (teacher_id, sem, teacher_id, f"%{teacher_id}%"))
    current_course_count = len({
        row["course_id"] for row in current_lessons if row.get("course_id")
    })
    total_enrolled = sum(int(row.get("enrolled") or 0) for row in current_lessons)
    total_hours = sum(float(row.get("total_hours") or 0) for row in current_lessons)
    current_courses = [{
        "id": row["course_id"],
        "courseName": row.get("course_name") or row["course_id"],
        "courseDept": clean_dept(row.get("course_dept")) or "—",
        "className": row.get("class_names") or "—",
        "students": int(row.get("enrolled") or 0),
        "hours": round(float(row.get("total_hours") or 0), 1),
        "teamRole": row["team_role"],
    } for row in current_lessons[:100]]

    history = dbm.query(conn, """
        SELECT l.semester_id semester,l.course_id,c.name course_name,c.dept course_dept,
               COUNT(DISTINCT l.lesson_id) lesson_count,
               SUM(COALESCE(l.enrolled,0)) enrolled,
               SUM(COALESCE(l.total_hours,0)) hours,
               MAX(CASE WHEN l.teacher_id=? THEN 1 ELSE 0 END) is_primary
        FROM fact_lesson l
        LEFT JOIN dim_course c ON c.course_id=l.course_id
        WHERE l.teacher_id=? OR l.teacher_ids LIKE ?
        GROUP BY l.semester_id,l.course_id,c.name,c.dept
        ORDER BY l.semester_id DESC,c.name
        LIMIT 40
    """, (teacher_id, teacher_id, f"%{teacher_id}%"))
    teaching_history = [{
        "semester": row["semester"],
        "courseId": row["course_id"],
        "courseName": row.get("course_name") or row["course_id"],
        "courseDept": clean_dept(row.get("course_dept")) or "—",
        "lessonCount": int(row.get("lesson_count") or 0),
        "students": int(row.get("enrolled") or 0),
        "hours": round(float(row.get("hours") or 0), 1),
        "teamRole": "主讲" if row.get("is_primary") else "联合授课",
    } for row in history]

    return ok({
        "name": teacher.get("name") or teacher_id,
        "code": teacher_id,
        "deptName": clean_dept(teacher.get("dept")) or "—",
        "title": normalize_title(teacher.get("title")),
        "kpis": [
            {"label": "本学期授课门数", "value": f"{current_course_count}门",
             "formula": "当前学期主讲或联合授课的去重课程数"},
            {"label": "本学期教学班", "value": f"{len(current_lessons)}个",
             "formula": "当前学期主讲或联合授课教学班记录数"},
            {"label": "覆盖学生人次", "value": f"{total_enrolled}人次",
             "formula": "当前学期相关教学班选课人次合计；联合授课不拆分贡献比例"},
            {"label": "任务记录学时", "value": f"{round(total_hours, 1):g}",
             "formula": "当前学期相关教学班学时合计；不等同于人事核定工作量"},
        ],
        "currentCourses": current_courses,
        "currentCourseTotal": len(current_lessons),
        "currentCourseDisplayLimit": 100,
        "teachingHistory": teaching_history,
        "dataQuality": dict(current_issue) if current_issue else None,
        "sources": [
            {"name": "教师主数据", "table": "dim_teacher"},
            {"name": "教学任务", "table": "fact_lesson"},
            {"name": "课程信息", "table": "dim_course"},
            {"name": "数据质量问题", "table": "data_quality_issue"},
        ],
        "boundary": "本抽屉仅为课程师资保障核查提供教学经历证据，不展示学生成绩、通过率或模拟年龄学历，不用于教师绩效评价。",
    })


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

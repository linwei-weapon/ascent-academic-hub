"""V2真实数据验证接口。全部只读，响应继续使用{code,msg,data}。"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from .. import db as dbm
from ..deps import get_current_user, get_v2_db
from ..envelope import ApiError, ok

router = APIRouter(prefix="/api/v2", tags=["v2"])

V2_ALL_SCOPE_ROLES = {"school_leader", "dean", "dept_operation", "dept_research", "dept_practice", "quality_office"}
V2_MAPPED_SCOPE_ROLES = {"college_dean", "college_secretary", "counselor", "dept_director"}


def require_v2_reader(user: dict = Depends(get_current_user)) -> dict:
    """允许全校角色及已建立显式V2范围映射的角色。"""
    if user.get("role_id") not in V2_ALL_SCOPE_ROLES | V2_MAPPED_SCOPE_ROLES:
        raise ApiError("当前角色没有V2访问范围", code=403, status_code=403)
    return user


def require_v2_all_reader(user: dict = Depends(get_current_user)) -> dict:
    """课程、教师和空间全校聚合在范围过滤完成前仅开放全校角色。"""
    if user.get("role_id") not in V2_ALL_SCOPE_ROLES:
        raise ApiError("当前接口仅对全校范围角色开放", code=403, status_code=403)
    return user


def _student_scope(user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    role = user.get("role_id")
    if role in V2_ALL_SCOPE_ROLES:
        return "", []
    mappings = dbm.query(conn, "SELECT * FROM access_scope_mapping WHERE role_id=? AND mapping_status='mapped'", (role,))
    if not mappings:
        raise ApiError("V2数据范围未映射", code=403, status_code=403)
    scope_type = mappings[0]["scope_type"]
    if scope_type == "college":
        values = [x["organization_id"] for x in mappings if x.get("organization_id")]
        field = "organization_id"
    elif scope_type == "major":
        values = [x["major_code"] for x in mappings if x.get("major_code")]
        field = "major_code"
    elif scope_type == "class":
        values = [x["class_code"] for x in mappings if x.get("class_code")]
        field = "class_code"
    else:
        raise ApiError("不支持的数据范围类型", code=403, status_code=403)
    if not values:
        raise ApiError("V2数据范围为空", code=403, status_code=403)
    return f"{alias}.{field} IN ({','.join('?' for _ in values)})", values


def _assert_student_access(student_id: str, user: dict, conn: sqlite3.Connection) -> None:
    fragment, params = _student_scope(user, conn, "s")
    sql = "SELECT 1 FROM dim_student s WHERE s.student_id=?" + (f" AND {fragment}" if fragment else "")
    if not dbm.query_one(conn, sql, tuple([student_id] + params)):
        raise ApiError("学生不存在或无权访问", code=404, status_code=404)


@router.get("/health")
def health(conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    batches = dbm.scalar(conn, "SELECT COUNT(*) FROM data_batch") or 0
    return ok({"status": "up", "batches": batches, "mode": "read-only"})


@router.get("/meta/teaching-semesters")
def teaching_semesters(conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    rows = dbm.query(conn, """SELECT s.semester_id,s.name,s.academic_year,s.season,COUNT(DISTINCT l.lesson_id) lesson_count
        FROM dim_semester s JOIN teaching_lesson l ON l.semester_id=s.semester_id
        GROUP BY s.semester_id,s.name,s.academic_year,s.season ORDER BY s.semester_id DESC""")
    return ok({"items": rows, "current": rows[0]["semester_id"] if rows else None,
               "scope": "仅返回已接入真实教学任务的学期"})


@router.get("/students/difficult")
def difficult_students(flag: Optional[str] = None, severity: Optional[str] = None,
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    cond, params = ["1=1"], []
    scope, scope_params = _student_scope(user, conn, "s")
    if scope:
        cond.append(scope); params.extend(scope_params)
    if flag:
        cond.append("f.flag_code=?"); params.append(flag)
    if severity:
        cond.append("f.severity=?"); params.append(severity)
    where = " AND ".join(cond)
    total = dbm.scalar(conn, f"SELECT COUNT(DISTINCT f.student_id) FROM student_difficulty_flag f JOIN dim_student s ON s.student_id=f.student_id WHERE {where}", tuple(params)) or 0
    rows = dbm.query(conn, f"""SELECT f.student_id,s.display_name,s.entry_grade,s.organization_id,s.major_code,s.class_code,
        COUNT(*) flag_count,MAX(CASE f.severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END) severity_rank,
        GROUP_CONCAT(f.flag_code) flags,g.failed_courses,g.required_missing,g.retake_attempts
        FROM student_difficulty_flag f JOIN dim_student s ON s.student_id=f.student_id
        LEFT JOIN student_growth_indicator g ON g.student_id=f.student_id AND g.indicator_version='growth-v1'
        WHERE {where} GROUP BY f.student_id ORDER BY severity_rank DESC,flag_count DESC,f.student_id LIMIT ? OFFSET ?""",
        tuple(params + [limit, offset]))
    return ok({"items": rows, "total": total, "limit": limit, "offset": offset})


@router.get("/students/{student_id}/growth")
def student_growth(student_id: str, timeline_limit: int = Query(100, ge=1, le=500),
                   conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    _assert_student_access(student_id, user, conn)
    student = dbm.query_one(conn, """SELECT s.*,p.plan_name FROM dim_student s
        LEFT JOIN curriculum_plan p ON p.plan_id=s.plan_id WHERE s.student_id=?""", (student_id,))
    if not student:
        raise ApiError("学生不存在", code=404, status_code=404)
    indicator = dbm.query_one(conn, "SELECT * FROM student_growth_indicator WHERE student_id=? AND indicator_version='growth-v1'", (student_id,))
    flags = dbm.query(conn, "SELECT flag_code,severity,evidence_count,evidence_json FROM student_difficulty_flag WHERE student_id=? AND flag_version='growth-v1' ORDER BY severity DESC,flag_code", (student_id,))
    timeline = dbm.query(conn, "SELECT event_type,event_date,semester_id,title,detail_json,source_ref,source FROM student_timeline_event WHERE student_id=? ORDER BY COALESCE(event_date,semester_id) DESC LIMIT ?", (student_id, timeline_limit))
    graduation = dbm.query(conn, "SELECT graduation_status,degree_status,graduation_date,education_level FROM graduation_outcome WHERE student_id=? ORDER BY graduation_date DESC", (student_id,))
    return ok({"student": student, "indicator": indicator, "flags": flags,
               "timeline": timeline, "graduation": graduation})


@router.get("/students/{student_id}/plan-courses")
def student_plan_courses(student_id: str, status: Optional[str] = None,
                         actionable: Optional[bool] = None,
                         limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                         conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    _assert_student_access(student_id, user, conn)
    cond, params = ["x.student_id=?", "x.rule_version='growth-v1'"], [student_id]
    if status:
        cond.append("x.completion_status=?"); params.append(status)
    if actionable is not None:
        cond.append("x.is_actionable=?"); params.append(int(actionable))
    where = " AND ".join(cond)
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM student_plan_course_status x WHERE {where}", tuple(params)) or 0
    rows = dbm.query(conn, f"""SELECT x.course_id,COALESCE(c.name,pc.course_id) course_name,x.module,x.requirement_type,
        x.suggested_term,x.completion_status,x.is_actionable,x.is_overdue,x.effective_score,x.earned_credits
        FROM student_plan_course_status x LEFT JOIN dim_course c ON c.course_id=x.course_id
        LEFT JOIN curriculum_plan_course pc ON pc.plan_course_id=x.plan_course_id
        WHERE {where} ORDER BY x.is_actionable DESC,x.is_overdue DESC,x.suggested_term,x.course_id LIMIT ? OFFSET ?""",
        tuple(params + [limit, offset]))
    return ok({"items": rows, "total": total, "limit": limit, "offset": offset,
               "wording": "not_completed表示截至当前成绩和认定记录尚无完成证据，不等同于漏选"})


@router.get("/students/{student_id}/advice")
def student_advice(student_id: str, conn: sqlite3.Connection = Depends(get_v2_db),
                   user: dict = Depends(require_v2_reader)):
    """确定性建议证据包；不调用大模型，不产生毕业结论或心理推断。"""
    _assert_student_access(student_id, user, conn)
    student = dbm.query_one(conn, "SELECT student_id,display_name,entry_grade,major_code,class_code,student_status FROM dim_student WHERE student_id=?", (student_id,)) or {}
    indicator = dbm.query_one(conn, "SELECT * FROM student_growth_indicator WHERE student_id=? AND indicator_version='growth-v1'", (student_id,)) or {}
    audiences = ["student", "counselor", "class_adviser", "college", "academic_affairs"]
    cards = []

    actionable = dbm.query(conn, """SELECT x.course_id,COALESCE(c.name,x.course_id) course_name,x.effective_score
        FROM student_plan_course_status x LEFT JOIN dim_course c ON c.course_id=x.course_id
        WHERE x.student_id=? AND x.is_actionable=1 ORDER BY x.is_overdue DESC,x.suggested_term LIMIT 5""", (student_id,))
    for row in actionable:
        course = row["course_name"]
        cards.append({"advice_id": f"ADV-PLAN-FAILED-REQUIRED:{row['course_id']}", "priority": "high", "topic": "培养方案",
            "title": f"优先核对《{course}》后续修读安排",
            "evidence": f"培养方案课程存在明确未通过记录，有效成绩为{row['effective_score'] if row['effective_score'] is not None else '未记录'}",
            "evidence_ids": [f"plan-course:{row['course_id']}"], "confidence": "high",
            "messages": {"student": "建议尽早核对下一次开课或重修安排，并确认该课程是否影响后续课程衔接。",
                "counselor": "建议确认学生是否了解该必修课程状态，并持续关注后续修读安排。",
                "class_adviser": "建议关注该课程对应的专业基础及后续课程衔接，必要时提供学习指导。",
                "college": "建议核查该课程重修或跟班修读资源，并关注同类学生规模。",
                "academic_affairs": "建议关注该课程跨学院开课与重修资源；正式安排以教务系统为准。"},
            "verification": "当前数据未包含完整重修班容量与报名条件"})

    semester_gpa = dbm.query(conn, """SELECT semester_id,AVG(gpa) gpa FROM grade_attempt
        WHERE student_id=? AND is_void=0 AND gpa IS NOT NULL GROUP BY semester_id ORDER BY semester_id DESC LIMIT 2""", (student_id,))
    if len(semester_gpa) == 2:
        delta = (semester_gpa[0]["gpa"] or 0) - (semester_gpa[1]["gpa"] or 0)
        if abs(delta) >= 0.3:
            improved = delta > 0
            cards.append({"advice_id": "ADV-GPA-RECOVERY" if improved else "ADV-GPA-DECLINE",
                "priority": "positive" if improved else "medium", "topic": "积极进展" if improved else "成绩趋势",
                "title": "近期 GPA 有明显改善" if improved else "近期 GPA 出现下降",
                "evidence": f"{semester_gpa[1]['semester_id']}至{semester_gpa[0]['semester_id']}平均绩点变化{delta:+.2f}",
                "evidence_ids": [f"semester:{semester_gpa[1]['semester_id']}", f"semester:{semester_gpa[0]['semester_id']}"], "confidence": "high",
                "messages": {a: ("近期学习结果出现改善，建议保持有效的学习节奏，并继续关注尚未解决的课程。" if improved else
                    {"student": "建议回顾近期低分课程和学习负荷，优先安排基础薄弱课程的学习时间。",
                     "counselor": "建议关注下降是否持续，并结合课程负荷和学籍背景与学生核实。",
                     "class_adviser": "建议分析下降是否集中在专业基础课程，提供课程衔接建议。",
                     "college": "建议结合该专业同年级情况判断是否存在共性困难课程。",
                     "academic_affairs": "建议仅在形成跨学院共性时进入校级课程资源分析。"}[a]) for a in audiences},
                "verification": "GPA变化为结果事实，不用于推断具体原因"})

    latest_semester = dbm.scalar(conn, "SELECT MAX(semester_id) FROM grade_attempt WHERE student_id=? AND is_void=0", (student_id,))
    if latest_semester:
        difficult = dbm.query(conn, """WITH history AS (
            SELECT course_id,COUNT(*) attempts,SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) failures
            FROM grade_attempt WHERE is_void=0 AND semester_id<? AND is_pass IS NOT NULL GROUP BY course_id
            HAVING COUNT(*)>=30 AND SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END)*1.0/COUNT(*)>=0.15)
            SELECT DISTINCT a.course_id,COALESCE(a.course_name,c.name,a.course_id) course_name,h.attempts,h.failures
            FROM grade_attempt a JOIN history h ON h.course_id=a.course_id LEFT JOIN dim_course c ON c.course_id=a.course_id
            WHERE a.student_id=? AND a.semester_id=? AND a.is_void=0 LIMIT 5""", (latest_semester, student_id, latest_semester))
        for row in difficult:
            rate = round(row["failures"] * 100.0 / row["attempts"], 1); course = row["course_name"]
            cards.append({"advice_id": f"ADV-HIGH-FAIL-COURSE:{row['course_id']}", "priority": "medium", "topic": "课程难度",
                "title": f"关注《{course}》的历史学习难度", "confidence": "medium",
                "evidence": f"最近修读记录为{latest_semester}；此前历史样本{row['attempts']}人次，未通过率{rate}%",
                "evidence_ids": [f"recent-course:{latest_semester}:{row['course_id']}", f"course-history:{row['course_id']}"],
                "messages": {"student": "该课程历史未通过率相对较高，建议尽早安排学习时间、复习先修知识并关注课程答疑资源。",
                    "counselor": "建议关注学生是否同时修读多门历史高难度课程，避免学习负荷过度集中。",
                    "class_adviser": "建议关注先修知识和专业课程衔接，为学生提供针对性的学习指导。",
                    "college": "建议核查该课程答疑、助教、课程团队和重修资源是否充足。",
                    "academic_affairs": "建议关注该课程是否形成跨专业、跨学院的共同学习压力。"},
                "verification": "历史群体结果不预测个人结果；原型缺当前选课状态，仅按最近学期修读记录提示"})

    order = {"high": 0, "medium": 1, "positive": 2}; cards.sort(key=lambda x: (order.get(x["priority"], 9), x["advice_id"]))
    return ok({"student": student, "indicator": indicator, "cards": cards[:12], "audiences": audiences,
        "generated_by": "deterministic-template-v1", "ai_enabled": False,
        "wording": "建议基于确定性证据生成；尚无完成证据不等同漏选，历史课程难度不预测个人结果"})


@router.get("/courses/offerings")
def course_offerings(semester: str = "2023-2024-1", category: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                     conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    cond, params = ["a.semester_id=?"], [semester]
    if category:
        cond.append("c.category=?"); params.append(category)
    where = " AND ".join(cond)
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM agg_course_offering a LEFT JOIN dim_course c ON c.course_id=a.course_id WHERE {where}", tuple(params)) or 0
    rows = dbm.query(conn, f"""SELECT a.*,c.name course_name,c.category,c.nature,c.organization_id
        FROM agg_course_offering a LEFT JOIN dim_course c ON c.course_id=a.course_id WHERE {where}
        ORDER BY a.lesson_count DESC,a.enrolled DESC LIMIT ? OFFSET ?""", tuple(params + [limit, offset]))
    return ok({"items": rows, "total": total, "semester": semester})


@router.get("/courses/schedule-distribution")
def course_schedule_distribution(semester: str = "2023-2024-1", focus: str = Query("all", pattern="^(all|pe|politics)$"),
                                 conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    conditions = ["l.semester_id=?"]
    params: list = [semester]
    if focus == "pe":
        conditions.append("(COALESCE(c.category,'') LIKE '%体育%' OR COALESCE(c.nature,'') LIKE '%体育%' OR COALESCE(c.name,l.course_name,'') LIKE '%体育%')")
    elif focus == "politics":
        conditions.append("(COALESCE(c.category,'') LIKE '%思政%' OR COALESCE(c.nature,'') LIKE '%思政%' OR COALESCE(c.name,l.course_name,'') LIKE '%思想政治%' OR COALESCE(c.name,l.course_name,'') LIKE '%马克思%' OR COALESCE(c.name,l.course_name,'') LIKE '%毛泽东%')")
    where = " AND ".join(conditions)
    cells = dbm.query(conn, f"""SELECT m.weekday,
        CASE WHEN m.period_start<=4 THEN 'morning' WHEN m.period_start<=8 THEN 'afternoon' ELSE 'evening' END day_part,
        COUNT(DISTINCT m.meeting_id) meeting_count,COUNT(DISTINCT l.course_id) course_count,
        COUNT(DISTINCT l.lesson_id) lesson_count
        FROM course_meeting m JOIN teaching_lesson l ON l.lesson_id=m.lesson_id
        LEFT JOIN dim_course c ON c.course_id=l.course_id WHERE {where}
        GROUP BY m.weekday,CASE WHEN m.period_start<=4 THEN 'morning' WHEN m.period_start<=8 THEN 'afternoon' ELSE 'evening' END
        ORDER BY m.weekday,day_part""", tuple(params))
    return ok({"semester": semester, "focus": focus, "cells": cells,
               "classification": "体育/思政专项按课程类别、性质与课程名称关键词识别，生产系统应由课程标签主数据替代"})


@router.get("/courses/{course_id}/team")
def course_team(course_id: str, semester: str = "2023-2024-1",
                conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    summary = dbm.query_one(conn, "SELECT * FROM agg_course_team WHERE semester_id=? AND course_id=?", (semester, course_id))
    if not summary:
        raise ApiError("暂无课程团队数据", code=404, status_code=404)
    members = dbm.query(conn, """SELECT DISTINCT s.staff_id,s.display_name,s.title,s.organization_id,s.source
        FROM teaching_lesson l JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        LEFT JOIN dim_staff s ON s.staff_id=lt.staff_id WHERE l.semester_id=? AND l.course_id=? ORDER BY s.title,s.staff_id""", (semester, course_id))
    return ok({"summary": summary, "members": members})


@router.get("/teachers/{staff_id}/schedule-preference")
def teacher_preference(staff_id: str, semester: str = "2023-2024-1",
                       conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    teacher = dbm.query_one(conn, "SELECT staff_id,display_name,title,organization_id,source FROM dim_staff WHERE staff_id=?", (staff_id,))
    if not teacher:
        raise ApiError("教师不存在", code=404, status_code=404)
    cells = dbm.query(conn, "SELECT weekday,day_part,meeting_count,course_count FROM agg_teacher_schedule_preference WHERE semester_id=? AND staff_id=? ORDER BY weekday,day_part", (semester, staff_id))
    return ok({"teacher": teacher, "semester": semester, "cells": cells,
               "scope": "历史实际排课分布，不是教师主动填报偏好"})


@router.get("/rooms/summary")
def room_summary(conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    totals = dbm.query_one(conn, """SELECT COUNT(*) total_rooms,SUM(is_available) marked_available,
        SUM(CASE WHEN is_available=1 AND is_virtual=0 AND seats>0 THEN 1 ELSE 0 END) usable_rooms,
        SUM(CASE WHEN is_available=1 AND is_virtual=0 AND seats>0 THEN seats ELSE 0 END) usable_seats FROM dim_room""")
    buildings = dbm.query(conn, """SELECT COALESCE(b.name,'待映射楼宇') building,COUNT(*) total_rooms,
        SUM(CASE WHEN r.is_available=1 AND r.is_virtual=0 AND r.seats>0 THEN 1 ELSE 0 END) usable_rooms,
        SUM(CASE WHEN r.is_available=1 AND r.is_virtual=0 AND r.seats>0 THEN r.seats ELSE 0 END) usable_seats
        FROM dim_room r LEFT JOIN dim_building b ON b.building_id=r.building_id GROUP BY COALESCE(b.name,'待映射楼宇') ORDER BY usable_rooms DESC""")
    return ok({"summary": totals, "buildings": buildings,
               "denominator": "可用、非虚拟、座位数大于0；可用数量由上游主数据提供，本系统只消费和分析"})

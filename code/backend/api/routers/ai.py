"""AI insight endpoints.

The prototype uses a hybrid strategy:
- a small set of representative records is returned as AI-enhanced samples;
- all other records are handled by deterministic, evidence-based rules.

This keeps demos stable while making the AI value visible on real school data.
"""
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import college_data_scope, get_current_user, get_db, get_v2_db, student_data_scope
from ..envelope import ApiError, ok
from ..util import clean_dept, normalize_title

router = APIRouter(prefix="/api/admin/ai", tags=["ai"])

LEVEL_ORDER = {"严重": 0, "警告": 1, "提醒": 2}
RISK_LABEL = {"critical": "高风险", "warning": "中风险", "info": "关注", "low": "低风险"}
TONE = {"critical": "danger", "warning": "warning", "info": "info", "low": "success"}
AI_SAMPLE_LIMIT = 5
WORKFLOW_BY_LABEL = {
    "待处理": "new",
    "已分派": "assigned",
    "已通知": "notified",
    "已联系": "contacted",
    "帮扶中": "supporting",
    "待复核": "review_pending",
    "已解决": "resolved",
    "已关闭": "closed",
}
V2_ALL_SCOPE_ROLES = {"school_leader", "dean", "dept_operation", "dept_research", "dept_practice", "quality_office"}
V2_MAPPED_SCOPE_ROLES = {"college_dean", "college_secretary", "counselor", "dept_director"}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _student_scope_sql(user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    frag, params = student_data_scope(user, conn, alias)
    return (f" AND {frag}" if frag else "", params)


def _v2_student_scope(user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    role = user.get("role_id")
    if role in V2_ALL_SCOPE_ROLES:
        return "", []
    if role not in V2_MAPPED_SCOPE_ROLES:
        raise ApiError("当前角色没有V2访问范围", code=403, status_code=403)
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
        raise ApiError("不支持的V2数据范围类型", code=403, status_code=403)
    if not values:
        raise ApiError("V2数据范围为空", code=403, status_code=403)
    return f"{alias}.{field} IN ({','.join('?' for _ in values)})", values


def _v2_student_access(conn: sqlite3.Connection, student_id: str, user: dict) -> dict:
    scope, params = _v2_student_scope(user, conn, "s")
    row = dbm.query_one(conn, f"""
        SELECT s.student_id,s.display_name,s.entry_grade,s.organization_id,s.major_code,
               s.major_name,s.class_code,p.plan_name,p.version
        FROM dim_student s
        LEFT JOIN curriculum_plan p ON p.plan_id=s.plan_id
        WHERE s.student_id=?{(' AND ' + scope) if scope else ''}
    """, tuple([student_id] + params))
    if not row:
        raise ApiError("学生不存在或无权访问", code=404, status_code=404)
    return row


def _gpa_history(conn: sqlite3.Connection, student_id: str) -> list[dict]:
    return dbm.query(conn, """
        SELECT semester_id, ROUND(AVG(gpa), 2) AS gpa
        FROM fact_grade
        WHERE student_id=? AND gpa IS NOT NULL
        GROUP BY semester_id
        ORDER BY semester_id
    """, (student_id,))


def _student_base(conn: sqlite3.Connection, student_id: str, user: dict) -> dict:
    scope_sql, scope_params = _student_scope_sql(user, conn, "s")
    row = dbm.query_one(conn, f"""
        SELECT s.student_id, s.name, s.grade, s.status,
               c.name AS college_name, m.name AS major_name, cl.name AS class_name
        FROM dim_student s
        LEFT JOIN dim_college c ON c.college_id=s.college_id
        LEFT JOIN dim_major m ON m.major_id=s.major_id
        LEFT JOIN dim_class cl ON cl.class_id=s.class_id
        WHERE s.student_id=?{scope_sql}
    """, [student_id] + scope_params)
    if not row:
        raise ApiError("学生不存在或无权访问", code=404, status_code=404)
    return row


def _student_alerts(conn: sqlite3.Connection, student_id: str) -> list[dict]:
    return dbm.query(conn, """
        SELECT a.alert_id, a.level, a.type, a.trigger_detail, a.status,
               a.created_at, a.semester_id, a.is_active,
               e.event_id, e.workflow_status
        FROM fact_alert a
        LEFT JOIN alert_event e ON e.alert_id=a.alert_id
        WHERE a.student_id=?
        ORDER BY COALESCE(a.created_at, '') DESC, a.alert_id DESC
    """, (student_id,))


def _student_grade_stats(conn: sqlite3.Connection, student_id: str) -> dict:
    stats = dbm.query_one(conn, """
        SELECT COUNT(*) AS grade_rows,
               COUNT(DISTINCT CASE WHEN is_pass=0 THEN course_id END) AS failed_courses,
               COUNT(DISTINCT CASE WHEN is_pass=0 AND COALESCE(is_required,0)=1 THEN course_id END) AS failed_required_courses,
               ROUND(AVG(CASE WHEN gpa IS NOT NULL THEN gpa END), 2) AS avg_gpa,
               ROUND(SUM(CASE WHEN is_pass=1 THEN COALESCE(credits,0) ELSE 0 END), 1) AS earned_credits,
               ROUND(SUM(CASE WHEN is_pass=0 THEN COALESCE(credits,0) ELSE 0 END), 1) AS failed_credits,
               SUM(CASE WHEN is_retake=1 THEN 1 ELSE 0 END) AS retake_attempts
        FROM fact_grade
        WHERE student_id=?
    """, (student_id,)) or {}
    history = _gpa_history(conn, student_id)
    stats["gpa_history"] = history
    if len(history) >= 2:
        stats["gpa_delta"] = round((history[-1]["gpa"] or 0) - (history[-2]["gpa"] or 0), 2)
    else:
        stats["gpa_delta"] = None
    return stats


def _failed_courses(conn: sqlite3.Connection, student_id: str, limit: int = 5) -> list[dict]:
    rows = dbm.query(conn, """
        SELECT g.course_id, COALESCE(c.name, g.course_id) AS course_name,
               COUNT(*) AS fail_count,
               MAX(g.semester_id) AS last_semester,
               ROUND(MIN(g.score), 1) AS min_score,
               MAX(COALESCE(g.is_required, c.is_required, 0)) AS is_required
        FROM fact_grade g
        LEFT JOIN dim_course c ON c.course_id=g.course_id
        WHERE g.student_id=? AND g.is_pass=0
        GROUP BY g.course_id, COALESCE(c.name, g.course_id)
        ORDER BY fail_count DESC, last_semester DESC
        LIMIT ?
    """, (student_id, limit))
    for row in rows:
        total = dbm.scalar(conn, "SELECT COUNT(*) FROM fact_grade WHERE course_id=? AND is_pass IS NOT NULL", (row["course_id"],)) or 0
        failed = dbm.scalar(conn, "SELECT COUNT(*) FROM fact_grade WHERE course_id=? AND is_pass=0", (row["course_id"],)) or 0
        row["historical_fail_rate"] = round(failed / total * 100, 1) if total else None
    return rows


def _sample_student_ids(conn: sqlite3.Connection, user: dict) -> set[str]:
    scope_sql, scope_params = _student_scope_sql(user, conn, "s")
    rows = dbm.query(conn, f"""
        SELECT a.student_id,
               MAX(CASE a.level WHEN '严重' THEN 3 WHEN '警告' THEN 2 ELSE 1 END) AS max_level,
               COUNT(DISTINCT a.alert_id) AS alert_count,
               COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.course_id END) AS fail_courses,
               ROUND(AVG(g.gpa), 2) AS avg_gpa
        FROM fact_alert a
        JOIN dim_student s ON s.student_id=a.student_id
        LEFT JOIN fact_grade g ON g.student_id=a.student_id
        WHERE COALESCE(a.is_active,1)=1{scope_sql}
        GROUP BY a.student_id
        ORDER BY max_level DESC, fail_courses DESC, alert_count DESC, avg_gpa ASC
        LIMIT ?
    """, scope_params + [AI_SAMPLE_LIMIT])
    return {r["student_id"] for r in rows}


def _risk_level(alerts: list[dict], stats: dict) -> str:
    active = [a for a in alerts if a.get("is_active") == 1]
    if any(a.get("level") == "严重" for a in active):
        return "critical"
    if (stats.get("failed_required_courses") or 0) >= 2 or (stats.get("failed_courses") or 0) >= 3:
        return "critical"
    if any(a.get("level") == "警告" for a in active):
        return "warning"
    if (stats.get("failed_courses") or 0) > 0 or (stats.get("gpa_delta") or 0) < -0.3:
        return "warning"
    return "info" if active else "low"


def _evidence(base: dict, alerts: list[dict], stats: dict, failed: list[dict]) -> list[dict]:
    active = [a for a in alerts if a.get("is_active") == 1]
    latest = alerts[0] if alerts else {}
    evidence = [
        {"label": "当前有效预警", "value": f"{len(active)} 条", "detail": latest.get("trigger_detail") or "来自已启用预警规则", "tone": "danger" if active else "success"},
        {"label": "未通过课程", "value": f"{stats.get('failed_courses') or 0} 门", "detail": f"其中必修 {stats.get('failed_required_courses') or 0} 门", "tone": "danger" if (stats.get("failed_courses") or 0) else "success"},
        {"label": "平均 GPA", "value": stats.get("avg_gpa") if stats.get("avg_gpa") is not None else "暂无", "detail": _gpa_detail(stats), "tone": "warning" if (stats.get("avg_gpa") or 9) < 2.3 else "info"},
        {"label": "已获学分", "value": f"{stats.get('earned_credits') or 0}", "detail": f"未通过学分 {stats.get('failed_credits') or 0}", "tone": "info"},
    ]
    if failed:
        top = failed[0]
        rate = top.get("historical_fail_rate")
        evidence.append({
            "label": "重点课程",
            "value": top["course_name"],
            "detail": f"历史未通过率 {rate}%" if rate is not None else "存在未通过记录",
            "tone": "danger" if rate and rate >= 20 else "warning",
        })
    return evidence


def _gpa_detail(stats: dict) -> str:
    delta = stats.get("gpa_delta")
    if delta is None:
        return "暂未形成连续学期趋势"
    if delta < -0.3:
        return f"较上一学期下降 {abs(delta)}"
    if delta > 0.2:
        return f"较上一学期提升 {delta}"
    return "较上一学期基本稳定"


def _reasons(base: dict, alerts: list[dict], stats: dict, failed: list[dict], enhanced: bool) -> list[str]:
    reasons: list[str] = []
    if alerts:
        a = alerts[0]
        reasons.append(f"最近一次预警为“{a.get('level')} / {a.get('type')}”，触发依据是：{a.get('trigger_detail') or '规则命中'}。")
    if (stats.get("failed_required_courses") or 0) > 0:
        reasons.append(f"该生仍有 {stats.get('failed_required_courses')} 门必修课程未通过，毕业准备和后续选课需要优先核查。")
    elif (stats.get("failed_courses") or 0) > 0:
        reasons.append(f"该生存在 {stats.get('failed_courses')} 门课程未通过，建议区分必修、选修和重修资源后处理。")
    if stats.get("gpa_delta") is not None and stats["gpa_delta"] < -0.3:
        reasons.append(f"GPA 相邻学期下降 {abs(stats['gpa_delta'])}，需要确认是否由单门关键课程、学习状态或课程负荷变化造成。")
    high_rate = [c for c in failed if c.get("historical_fail_rate") and c["historical_fail_rate"] >= 20]
    if high_rate:
        names = "、".join(c["course_name"] for c in high_rate[:2])
        reasons.append(f"未通过课程中包含历史未通过率较高课程：{names}，学生需要提前获得课程难度提醒和学习资源建议。")
    if enhanced:
        reasons.append("该对象命中本轮演示的 AI 精研样本，研判文本在规则证据基础上进行了管理视角增强。")
    return reasons or ["当前证据未显示明显恶化，但仍建议结合最近成绩、选课和学生访谈进行常规观察。"]


def _suggestions(base: dict, alerts: list[dict], stats: dict, failed: list[dict], enhanced: bool) -> list[dict]:
    failed_names = "、".join(c["course_name"] for c in failed[:3]) or "未通过课程"
    items = [
        {
            "role": "辅导员",
            "priority": "high" if alerts or (stats.get("failed_courses") or 0) >= 2 else "medium",
            "action": "优先完成一次学业状态沟通",
            "detail": f"围绕 {failed_names}、近期学习投入和心理受挫情况进行访谈，确认是否需要持续跟踪。",
        },
        {
            "role": "班主任/导师",
            "priority": "high" if (stats.get("failed_required_courses") or 0) else "medium",
            "action": "核查课程学习路径",
            "detail": "判断未通过课程是否属于基础先修链条，必要时建议学生调整后续选课顺序。",
        },
        {
            "role": "学院",
            "priority": "high" if (stats.get("failed_required_courses") or 0) >= 2 else "medium",
            "action": "核查重修与补修资源",
            "detail": "确认相关课程近期是否有教学班、重修班或替代认定路径，避免风险延后到毕业审核阶段暴露。",
        },
    ]
    if enhanced:
        items.append({
            "role": "学生本人",
            "priority": "medium",
            "action": "制定下一学期课程优先级",
            "detail": "优先处理必修缺口和历史难度较高课程，避免同时叠加多门高风险课程。",
        })
    return items


def _next_actions(base: dict, alerts: list[dict], stats: dict, failed: list[dict]) -> list[str]:
    actions = ["查看学生完整档案中的成长轨迹、历史预警和人工干预记录。"]
    if failed:
        actions.append("核查未通过课程是否已有下学期开课、重修班或课程替代资源。")
    if alerts:
        actions.append("在预警闭环中补充本次沟通记录，并约定下一次复核时间。")
    if (stats.get("failed_required_courses") or 0) > 0:
        actions.append("将必修未通过课程纳入学院毕业准备风险清单。")
    return actions


def _student_insight(conn: sqlite3.Connection, student_id: str, user: dict, scenario: str) -> dict:
    base = _student_base(conn, student_id, user)
    alerts = _student_alerts(conn, student_id)
    stats = _student_grade_stats(conn, student_id)
    failed = _failed_courses(conn, student_id)
    enhanced = student_id in _sample_student_ids(conn, user)
    risk = _risk_level(alerts, stats)
    source = "ai_sample" if enhanced else "rule"
    latest = alerts[0] if alerts else {}
    fail_courses = stats.get("failed_courses") or 0
    required_fail = stats.get("failed_required_courses") or 0

    if enhanced:
        summary = (
            f"{base['name']}属于需要优先跟进的复合型学业风险学生：当前预警等级为"
            f"{latest.get('level') or '关注'}，未通过课程 {fail_courses} 门，其中必修 {required_fail} 门。"
            "建议把该生放入本轮学院帮扶核查名单，先确认课程缺口和重修资源，再安排辅导员沟通。"
        )
        confidence = "高"
    else:
        summary = (
            f"{base['name']}当前研判为{RISK_LABEL[risk]}，主要依据为有效预警、未通过课程、GPA 趋势和历史课程难度。"
        )
        confidence = "中"

    return {
        "targetType": "student",
        "targetId": student_id,
        "targetName": base["name"],
        "scenario": scenario,
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": source,
        "sourceLabel": "AI增强研判样本" if enhanced else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if enhanced else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": confidence,
        "profile": {
            "college": base.get("college_name"),
            "major": base.get("major_name"),
            "className": base.get("class_name"),
            "grade": base.get("grade"),
        },
        "evidence": _evidence(base, alerts, stats, failed),
        "reasons": _reasons(base, alerts, stats, failed, enhanced),
        "suggestions": _suggestions(base, alerts, stats, failed, enhanced),
        "nextActions": _next_actions(base, alerts, stats, failed),
        "limitations": [
            "本结果用于管理研判和核查提示，不替代学校正式毕业审核、成绩认定或处分结论。",
            "原型阶段优先使用结构化数据摘要；生产环境可经学校允许后接入云端或私有化大模型。",
        ],
    }


@router.get("/insight/student/{student_id}")
def student_insight(student_id: str, scenario: str = "alert",
                    user: dict = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)):
    return ok(_student_insight(conn, student_id, user, scenario))


@router.get("/insight/alert-summary")
def alert_summary(level: Optional[str] = None, type: Optional[str] = None,
                  status: Optional[str] = None, college: Optional[str] = None,
                  user: dict = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    conds = ["COALESCE(a.is_active,1)=1"]
    params: list = []
    if level:
        conds.append("a.level=?"); params.append(level)
    if type:
        conds.append("a.type=?"); params.append(type)
    if status:
        mapped_status = WORKFLOW_BY_LABEL.get(status, status)
        conds.append("(e.workflow_status=? OR a.status=?)"); params += [mapped_status, status]
    if college:
        conds.append("c.name=?"); params.append(college)
    scope_sql, scope_params = _student_scope_sql(user, conn, "s")
    if scope_sql:
        conds.append(scope_sql.replace(" AND ", "", 1)); params += scope_params
    where = " WHERE " + " AND ".join(conds)
    rows = dbm.query(conn, f"""
        SELECT a.student_id, s.name, c.name AS college, a.level, a.type,
               a.trigger_detail, e.workflow_status,
               COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.course_id END) AS failed_courses,
               ROUND(AVG(g.gpa), 2) AS avg_gpa
        FROM fact_alert a
        JOIN dim_student s ON s.student_id=a.student_id
        LEFT JOIN dim_college c ON c.college_id=s.college_id
        LEFT JOIN alert_event e ON e.alert_id=a.alert_id
        LEFT JOIN fact_grade g ON g.student_id=a.student_id
        {where}
        GROUP BY a.alert_id
        ORDER BY CASE a.level WHEN '严重' THEN 0 WHEN '警告' THEN 1 ELSE 2 END,
                 failed_courses DESC
        LIMIT 50
    """, params)
    total = len(rows)
    critical = sum(1 for r in rows if r.get("level") == "严重")
    warning = sum(1 for r in rows if r.get("level") == "警告")
    top = rows[:3]
    summary = (
        f"当前切片共识别 {total} 条有效预警，其中严重 {critical} 条、警告 {warning} 条。"
        "建议优先查看严重预警且未通过课程较多的学生，再核查是否存在课程供给或帮扶资源不足。"
    )
    return ok({
        "targetType": "alertGroup",
        "targetId": "current-alert-filter",
        "targetName": "当前预警切片",
        "scenario": "alert_monitor",
        "riskLevel": "critical" if critical else "warning" if warning else "info",
        "riskLabel": "高风险" if critical else "中风险" if warning else "关注",
        "riskTone": "danger" if critical else "warning" if warning else "info",
        "source": "rule",
        "sourceLabel": "规则研判兜底",
        "generatedBy": "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中",
        "evidence": [
            {"label": "有效预警", "value": f"{total} 条", "detail": "当前筛选条件下的预警记录", "tone": "info"},
            {"label": "严重预警", "value": f"{critical} 条", "detail": "应优先进入人工核查", "tone": "danger" if critical else "success"},
            {"label": "警告预警", "value": f"{warning} 条", "detail": "建议按课程缺口和 GPA 变化分层处理", "tone": "warning" if warning else "success"},
        ],
        "reasons": [
            "预警切片用于帮助管理者判断本轮应先处理哪些学生，而不是仅按列表顺序逐条查看。",
            "严重等级、未通过课程数量和 GPA 偏低是本次排序的核心依据。",
        ],
        "suggestions": [
            {"role": "教务处", "priority": "high", "action": "按学院分派核查任务", "detail": "先推动严重预警学生所在学院确认课程缺口和重修资源。"},
            {"role": "二级学院", "priority": "high", "action": "建立本周重点学生清单", "detail": "优先处理严重预警、持续预警和必修未通过课程较多的学生。"},
            {"role": "辅导员", "priority": "medium", "action": "完成学生访谈和跟进记录", "detail": "将访谈结论写入预警闭环，便于后续比较历史预警变化。"},
        ],
        "nextActions": [
            "打开前 3 名重点学生的 AI 研判，确认是否进入本轮帮扶名单。",
            "对同一课程集中触发的学生，进一步查看课程质量与重修资源。",
        ],
        "focusItems": top,
        "limitations": ["当前统计基于已接入预警和成绩数据，未包含心理、出勤等暂未接入数据。"],
    })


@router.get("/insight/graduation-readiness/student/{student_id}")
def graduation_readiness_student_insight(student_id: str,
                                         user: dict = Depends(get_current_user),
                                         conn: sqlite3.Connection = Depends(get_v2_db)):
    student = _v2_student_access(conn, student_id, user)
    rows = dbm.query(conn, """
        SELECT x.course_id,COALESCE(c.name,x.course_id) course_name,x.suggested_term,
               x.completion_status,x.effective_score,pc.credits required_credits,
               (SELECT COUNT(DISTINCT l.lesson_id) FROM teaching_lesson l WHERE l.course_id=x.course_id) lesson_count,
               (SELECT COUNT(DISTINCT lt.staff_id) FROM teaching_lesson l
                  LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id WHERE l.course_id=x.course_id) teacher_count,
               (SELECT COUNT(DISTINCT scs.substitution_id) FROM student_course_substitution scs
                  WHERE scs.student_id=x.student_id AND scs.original_course_id=x.course_id) substitution_count
        FROM student_plan_course_status x
        LEFT JOIN dim_course c ON c.course_id=x.course_id
        LEFT JOIN curriculum_plan_course pc ON pc.plan_course_id=x.plan_course_id
        WHERE x.student_id=? AND x.rule_version='growth-v1' AND x.requirement_type='必修'
          AND (x.completion_status='failed' OR (x.completion_status IN ('not_completed','unknown') AND x.is_overdue=1))
        ORDER BY CASE WHEN x.completion_status='failed' THEN 0 ELSE 1 END,x.suggested_term,x.course_id
    """, (student_id,))
    failed = [r for r in rows if r["completion_status"] == "failed"]
    candidates = [r for r in rows if r["completion_status"] != "failed"]
    no_offering = [r for r in rows if not r["lesson_count"]]
    risk = "critical" if failed else "warning" if candidates else "low"
    enhanced = len(failed) >= 2 or (failed and no_offering)
    top_names = "、".join(r["course_name"] for r in rows[:3]) or "暂无明确课程缺口"
    summary = (
        f"{student['display_name']}当前毕业准备核查重点为：{top_names}。"
        f"其中明确未通过 {len(failed)} 门，到期缺结果候选 {len(candidates)} 门。"
        "建议先核查必修未通过课程的重修、补考、替代认定和近期教学班供给。"
    )
    return ok({
        "targetType": "graduationStudent",
        "targetId": student_id,
        "targetName": student["display_name"],
        "scenario": "graduation_readiness",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if enhanced else "rule",
        "sourceLabel": "AI增强研判样本" if enhanced else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if enhanced else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "高" if rows else "中",
        "profile": {"college": student.get("organization_id"), "major": student.get("major_name"),
                    "className": student.get("class_code"), "grade": student.get("entry_grade")},
        "evidence": [
            {"label": "明确未通过", "value": f"{len(failed)} 门", "detail": "已发布成绩中存在必修课未通过记录", "tone": "danger" if failed else "success"},
            {"label": "缺结果候选", "value": f"{len(candidates)} 门", "detail": "到建议学期仍缺完成证据，需先核验选课与认定", "tone": "warning" if candidates else "success"},
            {"label": "无开课证据", "value": f"{len(no_offering)} 门", "detail": "历史教学任务中暂未发现该课程教学班", "tone": "danger" if no_offering else "info"},
            {"label": "培养方案", "value": student.get("plan_name") or "未绑定", "detail": student.get("version") or "当前学生绑定方案", "tone": "info"},
        ],
        "reasons": [
            "毕业准备核查关注的是学生是否存在必修课程完成证据缺口，不直接等同毕业审核结论。",
            "明确未通过课程可优先进入重修、补考、替代认定和课程保障核查。",
            "缺结果候选必须先核验选课、免修认定、课程替代和个人方案适用范围，不能直接认定学生缺修。",
        ],
        "suggestions": [
            {"role": "学院", "priority": "high" if failed else "medium", "action": "确认学生课程缺口清单", "detail": "逐门核查必修未通过课程是否有近期补修、重修或替代认定路径。"},
            {"role": "教务处", "priority": "high" if no_offering else "medium", "action": "核查课程供给和保障资源", "detail": "对无开课证据或影响学生较多的课程，确认下学期开课计划、教师容量和教学班资源。"},
            {"role": "辅导员/班主任", "priority": "medium", "action": "提醒学生制定毕业准备计划", "detail": "让学生明确优先处理哪些必修课程，避免毕业审核前集中暴露问题。"},
        ],
        "nextActions": [
            "查看核查证据弹窗中的明确未通过课程和缺结果候选课程。",
            "对无开课证据课程进入课程保障证据核查。",
            "必要时把学生加入学院毕业准备重点跟踪名单。",
        ],
        "limitations": ["本研判仅用于毕业准备管理核查，不替代学校正式毕业资格审核。"],
    })


@router.get("/insight/graduation-readiness/course/{course_id}")
def graduation_readiness_course_insight(course_id: str,
                                        user: dict = Depends(get_current_user),
                                        conn: sqlite3.Connection = Depends(get_v2_db)):
    scope, scope_params = _v2_student_scope(user, conn, "s")
    scope_sql = f" AND {scope}" if scope else ""
    course = dbm.query_one(conn, "SELECT course_id,name,category,nature,organization_id FROM dim_course WHERE course_id=?", (course_id,)) or {"course_id": course_id, "name": course_id}
    affected = dbm.query_one(conn, f"""
        SELECT COUNT(DISTINCT CASE WHEN x.requirement_type='必修' AND x.completion_status='failed' THEN x.student_id END) failed_students,
               COUNT(DISTINCT CASE WHEN x.requirement_type='必修' AND x.completion_status IN ('not_completed','unknown') AND x.is_overdue=1 THEN x.student_id END) candidate_students,
               COUNT(DISTINCT s.major_code) major_count
        FROM student_plan_course_status x
        JOIN dim_student s ON s.student_id=x.student_id
        WHERE x.course_id=? AND x.rule_version='growth-v1'{scope_sql}
    """, tuple([course_id] + scope_params)) or {}
    supply = dbm.query_one(conn, """
        SELECT COUNT(DISTINCT l.lesson_id) lesson_count,
               COUNT(DISTINCT lt.staff_id) teacher_count,
               SUM(COALESCE(l.capacity,0)) capacity,
               SUM(COALESCE(l.enrolled,0)) enrolled,
               GROUP_CONCAT(DISTINCT l.semester_id) semesters
        FROM teaching_lesson l
        LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        WHERE l.course_id=?
    """, (course_id,)) or {}
    substitutions = dbm.scalar(conn, """
        SELECT COUNT(DISTINCT substitution_id) FROM student_course_substitution
        WHERE original_course_id=? OR substitute_course_id=?
    """, (course_id, course_id)) or 0
    failed = affected.get("failed_students") or 0
    candidates = affected.get("candidate_students") or 0
    lesson_count = supply.get("lesson_count") or 0
    teacher_count = supply.get("teacher_count") or 0
    risk = "critical" if failed >= 10 or not lesson_count else "warning" if failed or candidates else "info"
    reasons = []
    if failed:
        reasons.append(f"该课程当前关联 {failed} 名明确未通过学生，是毕业准备核查中的可行动问题。")
    if candidates:
        reasons.append(f"另有 {candidates} 名学生属于缺结果候选，需要先核验选课、认定或方案适用范围。")
    if not lesson_count:
        reasons.append("当前历史教学任务中未发现教学班证据，需优先确认是否存在课程代码映射、替代课程或未来开课计划。")
    elif teacher_count <= 1:
        reasons.append("历史教学证据中教师覆盖较少，若下期开重修或补修班，需要提前确认师资容量。")
    if substitutions:
        reasons.append(f"已发现 {substitutions} 条课程替代关系，可作为学生个体核查时的重要证据。")
    return ok({
        "targetType": "graduationCourse",
        "targetId": course_id,
        "targetName": course.get("name") or course_id,
        "scenario": "graduation_course_supply",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk == "critical" else "rule",
        "sourceLabel": "AI增强研判样本" if risk == "critical" else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk == "critical" else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": f"{course.get('name') or course_id}建议作为毕业准备课程保障对象核查：明确未通过 {failed} 人，缺结果候选 {candidates} 人，涉及 {affected.get('major_count') or 0} 个专业。",
        "confidence": "高" if failed or candidates else "中",
        "profile": {"college": course.get("organization_id"), "major": f"{affected.get('major_count') or 0} 个专业"},
        "evidence": [
            {"label": "明确未通过学生", "value": f"{failed} 人", "detail": "可优先进入重修/补考/替代路径核查", "tone": "danger" if failed else "success"},
            {"label": "缺结果候选", "value": f"{candidates} 人", "detail": "需先核验选课与认定数据", "tone": "warning" if candidates else "success"},
            {"label": "历史教学班", "value": f"{lesson_count} 个", "detail": f"教师 {teacher_count} 人；容量 {supply.get('capacity') or 0}", "tone": "danger" if not lesson_count else "info"},
            {"label": "替代关系", "value": f"{substitutions} 条", "detail": "可用于学生个体课程替代核查", "tone": "info"},
        ],
        "reasons": reasons or ["当前未显示明显课程保障风险，可作为常规观察对象。"],
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "确认课程供给策略", "detail": "结合下学期开课计划、教师容量和重修资源，判断是否需要保障该课程。"},
            {"role": "二级学院", "priority": "high" if failed else "medium", "action": "核查受影响学生名单", "detail": "区分明确未通过和缺结果候选，避免把数据候选直接作为学生问题处理。"},
            {"role": "排课/教学运行人员", "priority": "medium", "action": "评估补修班或替代资源", "detail": "若受影响学生集中且教师容量不足，应提前准备课程资源方案。"},
        ],
        "nextActions": [
            "打开课程保障证据，查看历史教学班、教师、容量和替代关系。",
            "查看受影响学生名单，优先处理明确未通过学生。",
            "如无开课证据，核查课程代码映射和培养方案课程替代规则。",
        ],
        "limitations": ["当前未接入未来开课计划和重修班正式安排，课程保障建议需结合教务排课计划人工确认。"],
    })


@router.get("/insight/operation/course-offering/{course_id}")
def operation_course_offering_insight(course_id: str, semester: str = "2023-2024-1",
                                      user: dict = Depends(get_current_user),
                                      conn: sqlite3.Connection = Depends(get_v2_db)):
    course = dbm.query_one(conn, """
        SELECT course_id,name,category,nature,organization_id
        FROM dim_course WHERE course_id=?
    """, (course_id,)) or {"course_id": course_id, "name": course_id}
    offering = dbm.query_one(conn, """
        SELECT a.*,c.name course_name,c.category,c.nature,c.organization_id
        FROM agg_course_offering a
        LEFT JOIN dim_course c ON c.course_id=a.course_id
        WHERE a.semester_id=? AND a.course_id=?
    """, (semester, course_id))
    if not offering:
        offering = dbm.query_one(conn, """
            SELECT ? semester_id,l.course_id,COUNT(DISTINCT l.lesson_id) lesson_count,
                   COUNT(DISTINCT lt.staff_id) teacher_count,
                   SUM(COALESCE(l.capacity,0)) capacity,
                   SUM(COALESCE(l.enrolled,0)) enrolled,
                   COALESCE(MAX(c.name),MAX(l.course_name),l.course_id) course_name,
                   MAX(c.category) category,MAX(c.nature) nature,MAX(c.organization_id) organization_id
            FROM teaching_lesson l
            LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
            LEFT JOIN dim_course c ON c.course_id=l.course_id
            WHERE l.semester_id=? AND l.course_id=?
            GROUP BY l.course_id
        """, (semester, semester, course_id))
    if not offering:
        raise ApiError("暂无该课程开课供给数据", code=404, status_code=404)

    raw_metrics = dbm.query_one(conn, """
        SELECT r.lesson_count,r.capacity,r.enrolled,COALESCE(t.teacher_count,0) teacher_count
        FROM (
          SELECT COUNT(DISTINCT lesson_id) lesson_count,
                 SUM(COALESCE(capacity,0)) capacity,
                 SUM(COALESCE(enrolled,0)) enrolled
          FROM teaching_lesson
          WHERE semester_id=? AND course_id=?
        ) r
        CROSS JOIN (
          SELECT COUNT(DISTINCT lt.staff_id) teacher_count
          FROM teaching_lesson l
          LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
          WHERE l.semester_id=? AND l.course_id=?
        ) t
    """, (semester, course_id, semester, course_id))
    if raw_metrics and raw_metrics.get("lesson_count"):
        offering["lesson_count"] = raw_metrics.get("lesson_count") or 0
        offering["teacher_count"] = raw_metrics.get("teacher_count") or 0
        offering["capacity"] = raw_metrics.get("capacity") or 0
        offering["enrolled"] = raw_metrics.get("enrolled") or 0

    lesson_count = offering.get("lesson_count") or 0
    teacher_count = offering.get("teacher_count") or 0
    enrolled = offering.get("enrolled") or 0
    capacity = offering.get("capacity") or 0
    avg_size = round(enrolled / lesson_count, 1) if lesson_count else 0
    fill_rate = round(enrolled / capacity * 100, 1) if capacity else None
    schedule_cells = dbm.query(conn, """
        SELECT m.weekday,
               CASE WHEN m.period_start<=4 THEN '上午'
                    WHEN m.period_start<=8 THEN '下午' ELSE '晚上' END day_part,
               COUNT(DISTINCT m.meeting_id) meeting_count,
               COUNT(DISTINCT l.lesson_id) lesson_count
        FROM course_meeting m
        JOIN teaching_lesson l ON l.lesson_id=m.lesson_id
        WHERE l.semester_id=? AND l.course_id=?
        GROUP BY m.weekday,CASE WHEN m.period_start<=4 THEN '上午'
                    WHEN m.period_start<=8 THEN '下午' ELSE '晚上' END
        ORDER BY meeting_count DESC
    """, (semester, course_id))
    meeting_total = sum((r.get("meeting_count") or 0) for r in schedule_cells)
    top_cell = schedule_cells[0] if schedule_cells else {}
    evening = sum((r.get("meeting_count") or 0) for r in schedule_cells if r.get("day_part") == "晚上")
    evening_share = round(evening / meeting_total * 100, 1) if meeting_total else 0
    teacher_rows = dbm.query(conn, """
        SELECT COALESCE(s.display_name,lt.staff_id) teacher_name,lt.staff_id,
               COUNT(DISTINCT l.lesson_id) lesson_count,
               SUM(COALESCE(l.enrolled,0)) enrolled
        FROM teaching_lesson l
        LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        LEFT JOIN dim_staff s ON s.staff_id=lt.staff_id
        WHERE l.semester_id=? AND l.course_id=?
        GROUP BY lt.staff_id,COALESCE(s.display_name,lt.staff_id)
        ORDER BY lesson_count DESC,enrolled DESC
        LIMIT 5
    """, (semester, course_id))
    top_teacher = teacher_rows[0] if teacher_rows else {}

    attention: list[str] = []
    if avg_size >= 120:
        attention.append(f"平均班额 {avg_size} 人，已达到超大班核查区间")
    elif avg_size >= 80:
        attention.append(f"平均班额 {avg_size} 人，建议核查是否需要拆班或增加教学班")
    if teacher_count <= 1 and lesson_count >= 3:
        attention.append(f"{lesson_count} 个教学班主要由单一教师覆盖，需要核查教师连续授课和替补风险")
    if lesson_count == 1 and enrolled >= 80:
        attention.append("单班集中供给，若学生来源跨学院/跨专业，排课冲突和容量风险会被放大")
    if evening_share >= 30:
        attention.append(f"晚上时段占比 {evening_share}%，需要确认是否为课程特性或资源紧张导致")
    risk = "critical" if avg_size >= 120 or (teacher_count <= 1 and lesson_count >= 3) or (lesson_count == 1 and enrolled >= 120) else "warning" if attention else "info"
    enhanced = risk == "critical" or (avg_size >= 80 and teacher_count <= 2)
    summary = (
        f"{offering.get('course_name') or course.get('name') or course_id}在 {semester} 学期共有 {lesson_count} 个教学班、"
        f"{teacher_count} 名教师、{enrolled} 人次选课，平均班额 {avg_size} 人。"
        + ("建议作为本轮排课供给优化的优先核查课程。" if attention else "当前未发现明显供给压力，可作为常规观察对象。")
    )
    return ok({
        "targetType": "operationCourseOffering",
        "targetId": course_id,
        "targetName": offering.get("course_name") or course.get("name") or course_id,
        "scenario": "operation_course_offering",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if enhanced else "rule",
        "sourceLabel": "AI增强研判样本" if enhanced else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if enhanced else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "高" if lesson_count and meeting_total else "中",
        "profile": {"college": offering.get("organization_id") or course.get("organization_id"),
                    "major": offering.get("category") or course.get("category"),
                    "semester": semester},
        "evidence": [
            {"label": "教学班", "value": f"{lesson_count} 个", "detail": "来自真实教学任务/开课聚合数据", "tone": "info"},
            {"label": "平均班额", "value": f"{avg_size} 人", "detail": "选课人次 ÷ 教学班数", "tone": "danger" if avg_size >= 120 else "warning" if avg_size >= 80 else "success"},
            {"label": "教师覆盖", "value": f"{teacher_count} 人", "detail": f"重点教师：{top_teacher.get('teacher_name') or '暂无'}", "tone": "danger" if teacher_count <= 1 and lesson_count >= 3 else "info"},
            {"label": "容量使用", "value": f"{fill_rate}%" if fill_rate is not None else "待核验", "detail": f"容量 {capacity}；选课 {enrolled}", "tone": "warning" if fill_rate and fill_rate >= 95 else "info"},
            {"label": "高频时段", "value": f"周{top_cell.get('weekday')} {top_cell.get('day_part')}" if top_cell else "暂无", "detail": f"晚上占比 {evening_share}%", "tone": "warning" if evening_share >= 30 else "info"},
        ],
        "reasons": attention or [
            "当前课程供给规模、班额、教师覆盖和时段分布未触发明显风险阈值，建议纳入常规运行观察。",
            "如果该课程属于体育、思政、数学、英语等重点公共课，仍建议结合学院需求和资源约束做专项核查。",
        ],
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "核查课程供给策略", "detail": "确认是否需要拆班、增开教学班、调整容量或提前协调跨学院公共课资源。"},
            {"role": "二级学院", "priority": "medium", "action": "确认学生修读需求", "detail": "结合年级、专业和培养方案要求，判断该课程是否存在集中修读或补修需求。"},
            {"role": "排课人员", "priority": "high" if evening_share >= 30 or avg_size >= 120 else "medium", "action": "优化时段与教师安排", "detail": "重点核查高频时段、晚上时段、单教师连续覆盖和教室容量是否会影响教学运行体验。"},
        ],
        "nextActions": [
            "查看完整课程清单中同类课程的班额和教师覆盖情况，判断是否为个别课程异常。",
            "对平均班额偏高课程，核查是否具备拆班、增加教师或调整容量的现实条件。",
            "对单教师多班覆盖课程，提前准备替补教师或课程团队保障方案。",
        ],
        "limitations": [
            "当前研判基于已接入教学任务、排课时段和教师覆盖数据，尚未纳入未来开课计划审批结果。",
            "班额阈值用于管理核查提示，不直接评价课程质量或教师教学效果。",
        ],
    })


@router.get("/insight/operation/classroom-occupancy")
def operation_classroom_occupancy_insight(semester: Optional[str] = None,
                                          building: Optional[str] = None,
                                          include_evening: bool = True,
                                          user: dict = Depends(get_current_user),
                                          conn: sqlite3.Connection = Depends(get_db)):
    if not dbm.scalar(conn, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='fact_room_occupancy'"):
        raise ApiError("暂无实际教室占用数据", code=404, status_code=404)
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM fact_room_occupancy")
    fact_conds, params = ["o.semester_id=?"], [sem]
    if building:
        fact_conds.append("o.building_name=?")
        params.append(building)
    where = " AND ".join(fact_conds)
    period_filter = "" if include_evening else " AND p.period_index<=8"
    summary = dbm.query_one(conn, f"""
        SELECT COUNT(DISTINCT o.occupancy_id) occupancyRecords,
               COUNT(DISTINCT o.room_name) observedRooms,
               COUNT(DISTINCT o.activity_date) observedDates,
               COUNT(DISTINCT CASE WHEN o.overlap_count>0 THEN o.occupancy_id END) overlapRecords,
               COUNT(DISTINCT CASE WHEN o.building_mapping_status='pending' THEN o.occupancy_id END) pendingMappingRecords,
               COUNT(DISTINCT CASE WHEN o.is_evening=1 THEN o.occupancy_id END) eveningRecords
        FROM fact_room_occupancy o
        WHERE {where}
    """, tuple(params)) or {}
    heat_rows = dbm.query(conn, f"""
        SELECT o.weekday,p.period_index,
               COUNT(DISTINCT o.room_name||'|'||o.activity_date) occupiedRoomDays
        FROM fact_room_occupancy o
        JOIN fact_room_occupancy_period p ON p.occupancy_id=o.occupancy_id
        WHERE {where}{period_filter}
        GROUP BY o.weekday,p.period_index
        ORDER BY occupiedRoomDays DESC
        LIMIT 5
    """, tuple(params))
    day_counts = {r["weekday"]: r["days"] for r in dbm.query(conn, """
        SELECT weekday,COUNT(DISTINCT activity_date) days
        FROM fact_room_occupancy
        WHERE semester_id=?
        GROUP BY weekday
    """, (sem,))}
    observed_rooms = summary.get("observedRooms") or 0
    for row in heat_rows:
        opportunities = observed_rooms * day_counts.get(row["weekday"], 0)
        row["observedUtilizationPct"] = round(row["occupiedRoomDays"] * 100 / opportunities, 1) if opportunities else 0
    buildings = dbm.query(conn, f"""
        SELECT COALESCE(o.building_name,'待映射') name,
               COUNT(DISTINCT o.room_name) observedRooms,
               COUNT(DISTINCT o.activity_date) observedDates,
               COUNT(DISTINCT o.occupancy_id) occupancyRecords,
               COUNT(DISTINCT o.room_name||'|'||o.activity_date||'|'||p.period_index) occupiedRoomSlots
        FROM fact_room_occupancy o
        LEFT JOIN fact_room_occupancy_period p ON p.occupancy_id=o.occupancy_id
        WHERE {where}{period_filter}
        GROUP BY COALESCE(o.building_name,'待映射')
        ORDER BY occupancyRecords DESC
        LIMIT 8
    """, tuple(params))
    period_count = 12 if include_evening else 8
    for row in buildings:
        denominator = (row.get("observedRooms") or 0) * (row.get("observedDates") or 0) * period_count
        row["observedLoadPct"] = round((row.get("occupiedRoomSlots") or 0) * 100 / denominator, 1) if denominator else 0
    top_building = buildings[0] if buildings else {}
    peak = heat_rows[0] if heat_rows else {}
    activity_rows = dbm.query(conn, f"""
        SELECT o.activity_type type,COUNT(DISTINCT o.occupancy_id) records
        FROM fact_room_occupancy o
        WHERE {where}
        GROUP BY o.activity_type
        ORDER BY records DESC
        LIMIT 4
    """, tuple(params))
    evening_records = summary.get("eveningRecords") or 0
    occupancy_records = summary.get("occupancyRecords") or 0
    evening_share = round(evening_records * 100 / occupancy_records, 1) if occupancy_records else 0
    top_load = top_building.get("observedLoadPct") or 0
    overlap = summary.get("overlapRecords") or 0
    pending_mapping = summary.get("pendingMappingRecords") or 0
    risk = "critical" if top_load >= 50 or overlap >= 100 or pending_mapping >= 100 else "warning" if top_load >= 30 or evening_share >= 15 or overlap else "info"
    reasons: list[str] = []
    if top_building:
        reasons.append(f"{top_building['name']} 的观察负荷最高，为 {top_load}%，应优先核查是否存在时段集中或活动集中占用。")
    if peak:
        reasons.append(f"最高占用时段出现在周{peak.get('weekday')}第 {peak.get('period_index')} 节，观察占用强度为 {peak.get('observedUtilizationPct')}%。")
    if evening_share:
        reasons.append(f"晚间占用记录占 {evening_share}%，建议结合“是否包含晚间”开关比较日间与晚间资源压力。")
    if overlap:
        reasons.append(f"存在 {overlap} 条时段重叠记录，应作为源数据核查线索，避免误判真实资源紧张。")
    if pending_mapping:
        reasons.append(f"存在 {pending_mapping} 条楼宇待映射记录，需先治理教室名称/楼宇映射后再用于正式资源决策。")
    target_name = f"{building}教室占用" if building else "全校教室占用"
    summary_text = (
        f"{target_name}在 {sem} 学期共观察到 {occupancy_records} 条实际占用记录，"
        f"覆盖 {summary.get('observedRooms') or 0} 间已观察教室、{summary.get('observedDates') or 0} 个日期。"
        + (f" 当前最高负荷楼宇为 {top_building.get('name')}，观察负荷 {top_load}%。" if top_building else "")
    )
    return ok({
        "targetType": "operationClassroomOccupancy",
        "targetId": building or "all-buildings",
        "targetName": target_name,
        "scenario": "operation_classroom_occupancy",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI增强研判样本" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary_text,
        "confidence": "高" if occupancy_records else "中",
        "profile": {"college": "教学运行", "major": "教室资源", "semester": sem},
        "evidence": [
            {"label": "实际占用记录", "value": f"{occupancy_records} 条", "detail": "课程、考试、自习及其他活动占用事件", "tone": "info"},
            {"label": "已观察教室", "value": f"{summary.get('observedRooms') or 0} 间", "detail": "不是学校正式可用教室总数", "tone": "info"},
            {"label": "最高楼宇负荷", "value": f"{top_load}%", "detail": top_building.get("name") or "暂无楼宇数据", "tone": "danger" if top_load >= 50 else "warning" if top_load >= 30 else "success"},
            {"label": "晚间占用", "value": f"{evening_records} 条", "detail": f"占全部记录 {evening_share}%", "tone": "warning" if evening_share >= 15 else "info"},
            {"label": "待核查记录", "value": f"{overlap + pending_mapping} 条", "detail": f"重叠 {overlap}；楼宇待映射 {pending_mapping}", "tone": "danger" if overlap + pending_mapping >= 100 else "warning" if overlap + pending_mapping else "success"},
        ],
        "reasons": reasons or ["当前筛选范围未发现明显教室占用压力，可作为常规运行观察对象。"],
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "识别资源压力楼宇与高峰时段", "detail": "优先查看高负荷楼宇、高峰节次和晚间占用，判断是否需要调整排课策略或开放更多资源。"},
            {"role": "排课人员", "priority": "high" if top_load >= 50 else "medium", "action": "优化楼宇与时段分配", "detail": "对高峰节次进行课程、考试、自习等活动分层核查，避免同一楼宇在同一时段过度集中。"},
            {"role": "数据治理人员", "priority": "high" if pending_mapping or overlap else "medium", "action": "处理楼宇映射和重叠记录", "detail": "先修正待映射教室和时段重叠记录，再把结果用于正式教室资源决策。"},
        ],
        "nextActions": [
            "切换“包含晚间”开关，比较日间资源压力和晚间资源使用结构。",
            "点开最高负荷楼宇的 AI 研判，确认压力来自课程教学、考试、自习还是临时活动。",
            "对待映射和重叠记录建立源数据核查清单，避免把数据问题误判为资源问题。",
        ],
        "focusItems": {"buildings": buildings[:5], "peakSlots": heat_rows[:5], "activityTypes": activity_rows},
        "limitations": [
            "当前结果基于已接入的实际教室占用记录，不等同于全校正式教室空闲率。",
            "分母使用已观察教室和实际采集日期，生产系统应接入正式可用教室清单、座位数和占用审批全量数据。",
        ],
    })


def _schedule_reason_ai_category(reason: str) -> dict:
    text = (reason or "").strip()
    rules = [
        ("公派/会议/培训", ["会议", "培训", "出差", "公派", "外出", "公务"], "warning"),
        ("教师个人或健康", ["病", "身体", "家庭", "个人", "请假"], "warning"),
        ("考试/竞赛/活动冲突", ["考试", "竞赛", "活动", "讲座", "答辩"], "info"),
        ("教学安排调整", ["教学计划", "计划", "节假日", "调休", "补课", "实践", "实验", "实习", "课程安排", "进度"], "info"),
        ("场地/设备/资源", ["教室", "场地", "设备", "容量", "停电", "网络"], "danger"),
        ("课程冲突调整", ["课程冲突", "冲突"], "warning"),
    ]
    for category, keywords, tone in rules:
        for keyword in keywords:
            if keyword in text:
                return {"category": category, "matchedKeyword": keyword, "tone": tone}
    return {"category": "其他待核验", "matchedKeyword": "", "tone": "info"}


def _schedule_scope(college: Optional[str], user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    conds: list[str] = []
    params: list = []
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope:
        conds.append(f"{alias}." + col_scope)
        params.extend(col_params)
    if college:
        conds.append(f"{alias}.college_id=?")
        params.append(college)
    return " AND ".join(conds), params


@router.get("/insight/operation/schedule-changes")
def operation_schedule_changes_insight(semester: Optional[str] = None,
                                       college: Optional[str] = None,
                                       user: dict = Depends(get_current_user),
                                       conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM fact_schedule_change")
    scope_sql, scope_params = _schedule_scope(college, user, conn, "s")
    conds = ["s.semester_id=?"]
    params: list = [sem]
    if scope_sql:
        conds.append(scope_sql)
        params.extend(scope_params)
    where = " AND ".join(conds)
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_schedule_change s WHERE {where}", tuple(params)) or 0
    if not total:
        raise ApiError("暂无调停课数据", code=404, status_code=404)
    stats = dbm.query_one(conn, f"""
        SELECT COUNT(*) total,
               COUNT(CASE WHEN s.kind='调课' THEN 1 END) change_count,
               COUNT(CASE WHEN s.kind='停课' THEN 1 END) stop_count,
               COALESCE(SUM(s.affected),0) affected,
               AVG(s.auto_approved) auto_approved,
               AVG(s.review_days) avg_review_days
        FROM fact_schedule_change s WHERE {where}
    """, tuple(params)) or {}
    raw_reasons = dbm.query(conn, f"""
        SELECT s.reason,COUNT(*) count
        FROM fact_schedule_change s
        WHERE {where}
        GROUP BY s.reason
        ORDER BY count DESC
        LIMIT 12
    """, tuple(params))
    semantic: dict[str, dict] = {}
    for row in raw_reasons:
        classified = _schedule_reason_ai_category(row.get("reason") or "")
        item = semantic.setdefault(classified["category"], {"name": classified["category"], "count": 0, "tone": classified["tone"], "rawReasons": []})
        item["count"] += row["count"]
        item["rawReasons"].append({"text": row.get("reason") or "未填写", "count": row["count"], "matchedKeyword": classified["matchedKeyword"]})
    semantic_rows = sorted(semantic.values(), key=lambda x: -x["count"])
    top_semantic = semantic_rows[0] if semantic_rows else {}
    monthly = dbm.query(conn, f"""
        SELECT s.month,COUNT(*) count,COALESCE(SUM(s.affected),0) affected
        FROM fact_schedule_change s
        WHERE {where}
        GROUP BY s.month
        ORDER BY count DESC
    """, tuple(params))
    top_month = monthly[0] if monthly else {}
    teacher_rows = dbm.query(conn, f"""
        SELECT s.teacher_id,COALESCE(t.name,s.teacher_id) teacher_name,COALESCE(t.dept,'') dept,
               COUNT(*) count,COALESCE(SUM(s.affected),0) affected
        FROM fact_schedule_change s
        LEFT JOIN dim_teacher t ON t.teacher_id=s.teacher_id
        WHERE {where}
        GROUP BY s.teacher_id,COALESCE(t.name,s.teacher_id),COALESCE(t.dept,'')
        ORDER BY count DESC,affected DESC
        LIMIT 5
    """, tuple(params))
    college_name = dbm.scalar(conn, "SELECT name FROM dim_college WHERE college_id=?", (college,)) if college else None
    change_count = stats.get("change_count") or 0
    stop_count = stats.get("stop_count") or 0
    affected = stats.get("affected") or 0
    stop_share = round(stop_count * 100 / total, 1) if total else 0
    auto_rate = round((stats.get("auto_approved") or 0) * 100, 1)
    risk = "critical" if stop_share >= 25 or affected >= 3000 or (teacher_rows and teacher_rows[0]["count"] >= 8) else "warning" if total >= 50 or stop_count or (top_semantic.get("count") or 0) >= total * 0.35 else "info"
    enhanced = risk in {"critical", "warning"}
    target_name = f"{college_name}调停课" if college_name else "当前调停课切片"
    summary = (
        f"{target_name}在 {sem} 学期共有 {total} 条调停课记录，其中调课 {change_count} 次、停课 {stop_count} 次，"
        f"影响 {affected} 人次。主要原因集中在“{top_semantic.get('name') or '暂无'}”，建议优先核查高频教师、集中月份和停课占比。"
    )
    reasons = [
        f"停课占比为 {stop_share}%，停课通常比调课更需要关注教学进度补偿和学生通知到达。",
        f"院系自动审核占比约 {auto_rate}%，可用于判断是否存在大量短时长、低风险调课。",
    ]
    if top_semantic:
        reasons.append(f"原因文本经语义归类后，“{top_semantic['name']}”占 {top_semantic['count']} 条，是本切片最主要的管理解释线索。")
    if top_month:
        reasons.append(f"调停课最集中月份为 {top_month['month']} 月，共 {top_month['count']} 条，建议结合考试周、实践周或大型活动安排核查。")
    if teacher_rows:
        reasons.append(f"最高频教师为 {teacher_rows[0]['teacher_name']}，本学期 {teacher_rows[0]['count']} 条记录，建议进入教师维度核查原因是否集中。")
    return ok({
        "targetType": "operationScheduleChanges",
        "targetId": college or "current-schedule-change-filter",
        "targetName": target_name,
        "scenario": "operation_schedule_changes",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if enhanced else "rule",
        "sourceLabel": "AI增强研判样本" if enhanced else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if enhanced else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高" if raw_reasons else "中",
        "profile": {"college": college_name or "全校/当前权限", "major": "调停课治理", "semester": sem},
        "evidence": [
            {"label": "调停课记录", "value": f"{total} 条", "detail": f"调课 {change_count}；停课 {stop_count}", "tone": "warning" if total >= 50 else "info"},
            {"label": "影响学生", "value": f"{affected} 人次", "detail": "调停课教学班关联学生人次", "tone": "danger" if affected >= 3000 else "warning" if affected else "info"},
            {"label": "主要原因", "value": top_semantic.get("name") or "暂无", "detail": f"{top_semantic.get('count') or 0} 条记录", "tone": top_semantic.get("tone") or "info"},
            {"label": "高峰月份", "value": f"{top_month.get('month')}月" if top_month else "暂无", "detail": f"{top_month.get('count') or 0} 条记录", "tone": "warning" if top_month else "info"},
            {"label": "自动审核", "value": f"{auto_rate}%", "detail": "院系自动审核占比", "tone": "success" if auto_rate >= 70 else "info"},
        ],
        "reasons": reasons,
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "核查调停课集中原因", "detail": "优先看停课占比、影响学生人次和高峰月份，判断是否需要优化审核规则或教学运行安排。"},
            {"role": "二级学院", "priority": "high" if teacher_rows and teacher_rows[0]["count"] >= 8 else "medium", "action": "跟进高频教师和课程", "detail": "对高频教师逐条核查原始原因文本，区分正常公务冲突、健康因素、教学安排问题和资源问题。"},
            {"role": "排课人员", "priority": "medium", "action": "调整冲突高发时段", "detail": "结合月份趋势和原因分类，提前规避会议培训、考试活动、场地设备等冲突集中期。"},
        ],
        "nextActions": [
            "打开教师调课 TOP10 中前 3 名教师的 AI 研判，确认原因是否高度集中。",
            "核查停课记录是否已有补课安排或学生通知证据。",
            "按月份查看集中波峰是否与考试、实践、会议培训或大型活动相关。",
        ],
        "focusItems": {"reasons": semantic_rows[:5], "teachers": teacher_rows, "monthly": monthly},
        "limitations": [
            "当前原型使用规则与样本化 AI 文案解释原因文本，未调用外部大模型。",
            "生产系统应接入真实调课申请、审批记录、补课安排和通知到达证据，以支持闭环治理。",
        ],
    })


@router.get("/insight/operation/schedule-changes/teacher/{teacher_id}")
def operation_schedule_teacher_insight(teacher_id: str, semester: Optional[str] = None,
                                       user: dict = Depends(get_current_user),
                                       conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM fact_schedule_change")
    scope_sql, scope_params = _schedule_scope(None, user, conn, "s")
    conds = ["s.semester_id=?", "s.teacher_id=?"]
    params: list = [sem, teacher_id]
    if scope_sql:
        conds.append(scope_sql)
        params.extend(scope_params)
    where = " AND ".join(conds)
    teacher = dbm.query_one(conn, "SELECT teacher_id,name,dept,title FROM dim_teacher WHERE teacher_id=?", (teacher_id,)) or {"teacher_id": teacher_id, "name": teacher_id}
    stats = dbm.query_one(conn, f"""
        SELECT COUNT(*) total,COUNT(CASE WHEN s.kind='停课' THEN 1 END) stop_count,
               COALESCE(SUM(s.affected),0) affected,AVG(s.review_days) avg_review_days
        FROM fact_schedule_change s WHERE {where}
    """, tuple(params)) or {}
    total = stats.get("total") or 0
    if not total:
        raise ApiError("暂无该教师调停课数据或无权访问", code=404, status_code=404)
    reasons_raw = dbm.query(conn, f"""
        SELECT s.reason,COUNT(*) count,COALESCE(SUM(s.affected),0) affected
        FROM fact_schedule_change s
        WHERE {where}
        GROUP BY s.reason
        ORDER BY count DESC,affected DESC
    """, tuple(params))
    reason_items = []
    for row in reasons_raw:
        classified = _schedule_reason_ai_category(row.get("reason") or "")
        reason_items.append({**row, "semanticCategory": classified["category"], "tone": classified["tone"], "matchedKeyword": classified["matchedKeyword"]})
    top = reason_items[0] if reason_items else {}
    months = dbm.query(conn, f"""
        SELECT s.month,COUNT(*) count
        FROM fact_schedule_change s
        WHERE {where}
        GROUP BY s.month
        ORDER BY count DESC
    """, tuple(params))
    stop_count = stats.get("stop_count") or 0
    affected = stats.get("affected") or 0
    risk = "critical" if total >= 8 or stop_count >= 3 or affected >= 800 else "warning" if total >= 3 or stop_count else "info"
    summary = (
        f"{teacher.get('name') or teacher_id}在 {sem} 学期共有 {total} 条调停课记录，停课 {stop_count} 条，"
        f"影响 {affected} 人次。主要原因归类为“{top.get('semanticCategory') or '暂无'}”，建议核查是否属于可提前规避的安排冲突。"
    )
    return ok({
        "targetType": "operationScheduleTeacher",
        "targetId": teacher_id,
        "targetName": teacher.get("name") or teacher_id,
        "scenario": "operation_schedule_teacher",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI增强研判样本" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": teacher.get("dept"), "major": teacher.get("title"), "semester": sem},
        "evidence": [
            {"label": "调停课记录", "value": f"{total} 条", "detail": f"停课 {stop_count} 条", "tone": "danger" if total >= 8 else "warning" if total >= 3 else "info"},
            {"label": "影响学生", "value": f"{affected} 人次", "detail": "该教师调停课关联教学班学生人次", "tone": "danger" if affected >= 800 else "warning" if affected else "info"},
            {"label": "主要原因", "value": top.get("semanticCategory") or "暂无", "detail": top.get("reason") or "无原始原因", "tone": top.get("tone") or "info"},
            {"label": "集中月份", "value": f"{months[0]['month']}月" if months else "暂无", "detail": f"{months[0]['count']} 条记录" if months else "无月份分布", "tone": "warning" if months and months[0]["count"] >= 3 else "info"},
        ],
        "reasons": [
            "教师维度研判用于判断调停课是否集中在少数教师、少数原因或少数月份，避免只看全校总量。",
            f"该教师最高频原始原因是“{top.get('reason') or '暂无'}”，系统将其归类为“{top.get('semanticCategory') or '暂无'}”。",
            "如果原因集中在会议培训、公务外出或场地资源，应考虑提前排课避让；如果集中在个人健康，应以支持和替补安排为主。",
        ],
        "suggestions": [
            {"role": "二级学院", "priority": "high" if risk == "critical" else "medium", "action": "与教师确认高频原因", "detail": "核查是否存在可提前预判的会议培训、实践安排、健康因素或课程资源冲突。"},
            {"role": "教务处", "priority": "medium", "action": "优化审核与补课证据", "detail": "对停课和影响学生较多的记录，确认补课安排、审批依据和学生通知是否完整。"},
            {"role": "排课人员", "priority": "medium", "action": "下一轮排课规避冲突", "detail": "将高频月份和原因作为下一轮排课优化输入，减少同类调课重复发生。"},
        ],
        "nextActions": [
            "查看教师教学档案，结合课程团队和教师负荷判断是否存在替补资源不足。",
            "抽查原始调课申请文本，确认语义分类是否准确。",
            "若停课较多，补充核查补课安排和学生通知记录。",
        ],
        "focusItems": {"reasons": reason_items[:8], "months": months},
        "limitations": ["教师调停课频次不直接等同于教学质量问题，应结合原始原因、审批依据和补课安排综合判断。"],
    })


def _teacher_scope_filter(college: Optional[str], user: dict, conn: sqlite3.Connection) -> tuple[Optional[str], Optional[str]]:
    col_scope, col_params = college_data_scope(user, conn)
    scoped_college = college
    if col_scope and not scoped_college:
        row = dbm.query_one(conn, f"SELECT college_id,name FROM dim_college WHERE {col_scope}", tuple(col_params))
        if row:
            scoped_college = row["college_id"]
    if scoped_college:
        name = dbm.scalar(conn, "SELECT name FROM dim_college WHERE college_id=?", (scoped_college,))
        if not name:
            raise ApiError("学院不存在或无权访问", code=404, status_code=404)
        return scoped_college, name
    return None, None


def _teacher_title_map(conn: sqlite3.Connection) -> dict:
    prof = {r["teacher_id"]: r["norm_title"] for r in dbm.query(conn, "SELECT teacher_id,norm_title FROM fact_teacher_profile")}
    rows = dbm.query(conn, "SELECT teacher_id,title FROM dim_teacher")
    return {r["teacher_id"]: prof.get(r["teacher_id"]) or normalize_title(r.get("title")) for r in rows}


def _teacher_load_quality_issues(conn: sqlite3.Connection, semester: str) -> dict[str, dict]:
    rows = dbm.query(conn, """
        SELECT entity_id,affected_rows,severity,status,detail,recommendation
        FROM data_quality_issue
        WHERE domain='operation' AND issue_type='teacher_lesson_overflow'
          AND semester_id=? AND status IN ('open','reviewing')
    """, (semester,))
    return {r["entity_id"]: r for r in rows}


def _teacher_load_anomaly_ids(conn: sqlite3.Connection, semester: str) -> set[str]:
    ids = set(_teacher_load_quality_issues(conn, semester).keys())
    rows = dbm.query(conn, """
        SELECT teacher_id FROM agg_teacher_load
        WHERE semester_id=? AND (COALESCE(classes,0)>200 OR COALESCE(hours,0)>1000 OR COALESCE(courses,0)>20)
    """, (semester,))
    ids.update(r["teacher_id"] for r in rows)
    return ids


def _teacher_load_rows(conn: sqlite3.Connection, semester: str, college_name: Optional[str] = None,
                       title: Optional[str] = None, include_quality_issues: bool = False) -> list[dict]:
    title_of = _teacher_title_map(conn)
    anomaly_ids = _teacher_load_anomaly_ids(conn, semester)
    rows = dbm.query(conn, """
        SELECT a.teacher_id,COALESCE(t.name,a.teacher_id) name,t.dept,t.title,
               a.hours,a.courses,a.classes
        FROM agg_teacher_load a
        LEFT JOIN dim_teacher t ON t.teacher_id=a.teacher_id
        WHERE a.semester_id=?
    """, (semester,))
    result = []
    for row in rows:
        dept = clean_dept(row.get("dept")) or "未归属"
        norm_title = title_of.get(row["teacher_id"]) or normalize_title(row.get("title"))
        if college_name and dept != college_name:
            continue
        if title and norm_title != title:
            continue
        if not include_quality_issues and row["teacher_id"] in anomaly_ids:
            continue
        item = dict(row)
        item["dept"] = dept
        item["norm_title"] = norm_title
        item["hours"] = round(item.get("hours") or 0, 1)
        item["courses"] = item.get("courses") or 0
        item["classes"] = item.get("classes") or 0
        result.append(item)
    result.sort(key=lambda x: (x["hours"], x["courses"], x["classes"]), reverse=True)
    return result


@router.get("/insight/operation/teacher-load")
def operation_teacher_load_insight(semester: Optional[str] = None,
                                   college: Optional[str] = None,
                                   title: Optional[str] = None,
                                   user: dict = Depends(get_current_user),
                                   conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM agg_teacher_load")
    college_id, college_name = _teacher_scope_filter(college, user, conn)
    anomaly_ids = _teacher_load_anomaly_ids(conn, sem)
    rows = _teacher_load_rows(conn, sem, college_name, title)
    if not rows:
        raise ApiError("暂无教师负荷数据", code=404, status_code=404)
    total = len(rows)
    sum_hours = sum(r["hours"] for r in rows)
    sum_courses = sum(r["courses"] for r in rows)
    sum_classes = sum(r["classes"] for r in rows)
    avg_hours = round(sum_hours / total, 1) if total else 0
    avg_courses = round(sum_courses / total, 1) if total else 0
    avg_classes = round(sum_classes / total, 1) if total else 0
    overloaded = [r for r in rows if r["hours"] > 280 or r["courses"] > 5]
    top = rows[0]
    title_map: dict[str, dict] = {}
    for row in rows:
        item = title_map.setdefault(row["norm_title"] or "其他", {"title": row["norm_title"] or "其他", "teachers": 0, "hours": 0.0, "courses": 0.0, "overloaded": 0})
        item["teachers"] += 1
        item["hours"] += row["hours"]
        item["courses"] += row["courses"]
        if row in overloaded:
            item["overloaded"] += 1
    title_rows = []
    for item in title_map.values():
        n = item["teachers"] or 1
        title_rows.append({**item, "avgHours": round(item["hours"] / n, 1), "avgCourses": round(item["courses"] / n, 1)})
    title_rows.sort(key=lambda x: x["avgHours"], reverse=True)
    dept_map: dict[str, dict] = {}
    for row in rows:
        item = dept_map.setdefault(row["dept"], {"dept": row["dept"], "teachers": 0, "hours": 0.0, "courses": 0.0})
        item["teachers"] += 1
        item["hours"] += row["hours"]
        item["courses"] += row["courses"]
    dept_rows = []
    for item in dept_map.values():
        n = item["teachers"] or 1
        dept_rows.append({**item, "avgHours": round(item["hours"] / n, 1), "avgCourses": round(item["courses"] / n, 1)})
    dept_rows.sort(key=lambda x: x["avgHours"], reverse=True)
    overload_share = round(len(overloaded) * 100 / total, 1) if total else 0
    risk = "critical" if len(overloaded) >= 3 or top["hours"] >= 320 or avg_hours >= 220 else "warning" if overloaded or avg_hours >= 180 else "info"
    target_name = f"{college_name}教师负荷" if college_name else "当前教师负荷切片"
    if title:
        target_name += f" · {title}"
    summary = (
        f"{target_name}在 {sem} 学期共覆盖 {total} 名授课教师，人均 {avg_hours} 学时、"
        f"{avg_courses} 门课程、{avg_classes} 个教学班。当前识别 {len(overloaded)} 名高负荷核查对象，"
        f"最高负荷教师为 {top['name']}（{top['hours']} 学时、{top['courses']} 门课）。"
    )
    reasons = [
        "教师负荷研判用于定位需要优先人工核查的对象，不直接等同于学校正式超工作量认定。",
        f"当前高负荷核查对象占 {overload_share}%，建议结合学校工作量办法、合讲拆分、减免规则和课程团队实际承担情况判断。",
    ]
    if title_rows:
        reasons.append(f"按职称看，{title_rows[0]['title']} 人均学时最高，为 {title_rows[0]['avgHours']} 学时，可作为结构性投入核查线索。")
    if dept_rows and not college_name:
        reasons.append(f"按学院看，{dept_rows[0]['dept']} 人均学时最高，为 {dept_rows[0]['avgHours']} 学时，建议核查是否存在师资结构或公共课承担压力。")
    return ok({
        "targetType": "operationTeacherLoad",
        "targetId": college_id or title or "current-teacher-load-filter",
        "targetName": target_name,
        "scenario": "operation_teacher_load",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI增强研判样本" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": college_name or "全校/当前权限", "major": title or "全部职称", "semester": sem},
        "evidence": [
            {"label": "授课教师", "value": f"{total} 人", "detail": "当前筛选范围内有教学负荷记录的教师", "tone": "info"},
            {"label": "人均学时", "value": f"{avg_hours}", "detail": "总学时 ÷ 授课教师数", "tone": "danger" if avg_hours >= 220 else "warning" if avg_hours >= 180 else "success"},
            {"label": "高负荷对象", "value": f"{len(overloaded)} 人", "detail": "学时>280 或课程数>5 的优先核查对象", "tone": "danger" if overloaded else "success"},
            {"label": "最高负荷教师", "value": top["name"], "detail": f"{top['hours']} 学时；{top['courses']} 门课；{top['classes']} 个班", "tone": "danger" if top["hours"] >= 320 else "warning"},
            {"label": "已排除异常", "value": f"{len(anomaly_ids)} 人", "detail": "命中教师负荷异常或数据质量问题，未计入AI真实负荷排序", "tone": "warning" if anomaly_ids else "success"},
            {"label": "最高职称层", "value": title_rows[0]["title"] if title_rows else "暂无", "detail": f"人均 {title_rows[0]['avgHours']} 学时" if title_rows else "无职称统计", "tone": "info"},
        ],
        "reasons": reasons,
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "核查高负荷教师清单", "detail": "优先查看学时高、课程数多、教学班多且学生覆盖人次大的教师，确认是否存在工作量口径差异或拆分规则。"},
            {"role": "二级学院", "priority": "high" if overloaded else "medium", "action": "评估课程团队保障", "detail": "结合课程团队、青年教师储备、职称结构和替补教师情况，判断高负荷是否会带来教学运行风险。"},
            {"role": "排课人员", "priority": "medium", "action": "优化下一轮授课分配", "detail": "将高负荷教师、公共课承担和多班连排情况作为下一轮教学任务安排和排课优化输入。"},
        ],
        "nextActions": [
            "打开 TOP10 高负荷教师的 AI 研判，核查课程构成和学生覆盖人次。",
            "按学院和职称切换筛选，判断高负荷是个体问题还是结构性师资压力。",
            "对高负荷且课程团队薄弱的课程，进入师资保障分析核查课程团队风险。",
        ],
        "focusItems": {"topTeachers": rows[:10], "titleLoad": title_rows, "deptLoad": dept_rows[:8]},
        "limitations": ["本研判用于管理核查排序，不替代学校正式工作量核算、超工作量认定或绩效结论。"],
    })


@router.get("/insight/operation/teacher-load/teacher/{teacher_id}")
def operation_teacher_load_teacher_insight(teacher_id: str, semester: Optional[str] = None,
                                           user: dict = Depends(get_current_user),
                                           conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM agg_teacher_load")
    _, scoped_college_name = _teacher_scope_filter(None, user, conn)
    teacher = dbm.query_one(conn, "SELECT teacher_id,name,dept,title FROM dim_teacher WHERE teacher_id=?", (teacher_id,))
    if not teacher:
        raise ApiError("教师不存在", code=404, status_code=404)
    teacher_dept = clean_dept(teacher.get("dept")) or "未归属"
    if scoped_college_name and teacher_dept != scoped_college_name:
        raise ApiError("无权访问该教师负荷数据", code=403, status_code=403)
    load = dbm.query_one(conn, "SELECT teacher_id,hours,courses,classes FROM agg_teacher_load WHERE semester_id=? AND teacher_id=?", (sem, teacher_id))
    if not load:
        raise ApiError("暂无该教师负荷数据", code=404, status_code=404)
    quality_issue = _teacher_load_quality_issues(conn, sem).get(teacher_id)
    heuristic_anomaly = (load.get("classes") or 0) > 200 or (load.get("hours") or 0) > 1000 or (load.get("courses") or 0) > 20
    if quality_issue or heuristic_anomaly:
        return ok({
            "targetType": "operationTeacherLoadDataQuality",
            "targetId": teacher_id,
            "targetName": teacher.get("name") or teacher_id,
            "scenario": "operation_teacher_load_teacher",
            "riskLevel": "critical",
            "riskLabel": RISK_LABEL["critical"],
            "riskTone": TONE["critical"],
            "source": "rule",
            "sourceLabel": "数据质量规则拦截",
            "generatedBy": "deterministic_rule_engine",
            "generatedAt": _now(),
            "summary": f"{teacher.get('name') or teacher_id}在 {sem} 学期命中教师教学班溢出数据质量问题：当前记录显示 {load.get('hours') or 0} 学时、{load.get('courses') or 0} 门课、{load.get('classes') or 0} 个教学班。该结果不应作为真实教师负荷结论，应优先核查源系统教师映射、通识课合并和教学班生成逻辑。",
            "confidence": "高",
            "profile": {"college": teacher_dept, "major": normalize_title(teacher.get("title")), "semester": sem},
            "evidence": [
                {"label": "异常教学班", "value": f"{load.get('classes') or 0} 个", "detail": "超过原型数据质量阈值 200", "tone": "danger"},
                {"label": "异常学时", "value": f"{load.get('hours') or 0}", "detail": "不进入AI真实负荷排序", "tone": "danger"},
                {"label": "质量状态", "value": quality_issue.get("status") if quality_issue else "heuristic", "detail": quality_issue.get("detail") if quality_issue else "启发式识别为疑似异常", "tone": "warning"},
            ],
            "reasons": [
                "该教师负荷记录远超正常教学任务范围，更可能是教师映射、公共课/通识课合并或教学班明细重复导致。",
                "AI 研判已将该对象从真实高负荷排序中排除，避免把数据质量问题误判为教师工作量问题。",
            ],
            "suggestions": [
                {"role": "数据治理人员", "priority": "high", "action": "核查源数据映射", "detail": "重点检查教师编号、课程合班、通识课教学班生成和教师-教学班关联是否重复。"},
                {"role": "教务处", "priority": "high", "action": "暂缓使用该记录做工作量判断", "detail": "在源数据修复和复核关闭前，不建议将该记录用于教师负荷、绩效或排课优化结论。"},
                {"role": "二级学院", "priority": "medium", "action": "确认真实承担情况", "detail": "可通过教师本人、课程团队和教学任务书确认真实承担课程与教学班范围。"},
            ],
            "nextActions": [
                "进入教学运行数据质量清单，查看 teacher_lesson_overflow 问题状态。",
                "核查该教师在源系统中的教师编号和课程关联关系。",
                "修复源数据后重新生成教师负荷聚合并复核关闭异常。",
            ],
            "limitations": ["该结果是数据质量拦截提示，不是教师负荷管理结论。"],
        })
    courses = dbm.query(conn, """
        SELECT l.course_id,COALESCE(MAX(c.name),l.course_id) course_name,
               COUNT(DISTINCT l.lesson_id) lessons,
               ROUND(SUM(COALESCE(l.total_hours,0)),1) hours,
               SUM(COALESCE(l.enrolled,0)) studentVisits,
               ROUND(AVG(NULLIF(l.enrolled,0)),1) avgClassSize
        FROM fact_lesson l
        LEFT JOIN dim_course c ON c.course_id=l.course_id
        WHERE l.semester_id=? AND l.teacher_id=?
        GROUP BY l.course_id
        ORDER BY hours DESC,studentVisits DESC
    """, (sem, teacher_id))
    title_of = _teacher_title_map(conn)
    norm_title = title_of.get(teacher_id) or normalize_title(teacher.get("title"))
    hours = round(load.get("hours") or 0, 1)
    course_count = load.get("courses") or 0
    class_count = load.get("classes") or 0
    student_visits = sum((r.get("studentVisits") or 0) for r in courses)
    avg_class = round(student_visits / class_count, 1) if class_count else 0
    all_rows = _teacher_load_rows(conn, sem, teacher_dept)
    rank = next((i + 1 for i, r in enumerate(all_rows) if r["teacher_id"] == teacher_id), None)
    top_course = courses[0] if courses else {}
    risk = "critical" if hours > 280 or course_count > 5 or class_count >= 12 else "warning" if hours >= 180 or course_count >= 4 else "info"
    summary = (
        f"{teacher.get('name') or teacher_id}在 {sem} 学期承担 {hours} 学时、{course_count} 门课程、"
        f"{class_count} 个教学班，覆盖 {student_visits} 学生人次。"
        f"在 {teacher_dept} 当前教师负荷中排名第 {rank or '-'}，建议结合课程构成和团队保障核查。"
    )
    reasons = [
        f"该教师最高负荷课程为“{top_course.get('course_name') or '暂无'}”，对应 {top_course.get('hours') or 0} 学时、{top_course.get('lessons') or 0} 个教学班。",
        "若课程数多且教学班分散，管理重点是排课冲突、备课压力和课程团队替补能力。",
        "若学生覆盖人次高，管理重点是答疑、实验/实践支撑、助教资源和教学质量保障。",
    ]
    return ok({
        "targetType": "operationTeacherLoadTeacher",
        "targetId": teacher_id,
        "targetName": teacher.get("name") or teacher_id,
        "scenario": "operation_teacher_load_teacher",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI增强研判样本" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": teacher_dept, "major": norm_title, "semester": sem},
        "evidence": [
            {"label": "总学时", "value": f"{hours}", "detail": "来自教学任务学时汇总", "tone": "danger" if hours > 280 else "warning" if hours >= 180 else "success"},
            {"label": "课程/教学班", "value": f"{course_count} 门 / {class_count} 班", "detail": "课程数和教学班数共同反映备课与授课压力", "tone": "danger" if course_count > 5 or class_count >= 12 else "info"},
            {"label": "学生覆盖", "value": f"{student_visits} 人次", "detail": f"平均班额 {avg_class}", "tone": "warning" if student_visits >= 800 else "info"},
            {"label": "学院内排名", "value": f"第 {rank or '-'}", "detail": "按当前学院总学时降序", "tone": "warning" if rank and rank <= 3 else "info"},
            {"label": "重点课程", "value": top_course.get("course_name") or "暂无", "detail": f"{top_course.get('hours') or 0} 学时；{top_course.get('studentVisits') or 0} 人次", "tone": "info"},
        ],
        "reasons": reasons,
        "suggestions": [
            {"role": "二级学院", "priority": "high" if risk == "critical" else "medium", "action": "核查课程团队和替补安排", "detail": "确认高负荷课程是否有课程团队、助教或替补教师支撑，避免形成高影响单点。"},
            {"role": "教务处", "priority": "medium", "action": "核对工作量口径", "detail": "结合学校工作量办法、合讲拆分、实验实践折算和减免规则，避免仅凭原始学时下结论。"},
            {"role": "排课人员", "priority": "medium", "action": "优化排课节奏", "detail": "核查是否存在多班连排、跨校区移动或高峰时段集中，必要时调整下一轮教学任务安排。"},
        ],
        "nextActions": [
            "查看课程构成证据，确认高学时是否集中在少数课程或多个小课程。",
            "进入师资保障分析，核查相关课程团队是否存在年龄/职称结构风险。",
            "如同时存在频繁调课，结合调课 AI 研判判断是否为负荷压力的外显信号。",
        ],
        "focusItems": {"courseBreakdown": courses},
        "limitations": ["教师个人负荷研判只用于管理支持和核查排序，不直接评价教师教学质量或绩效。"],
    })


def _faculty_course_attention(row: dict) -> list[str]:
    reasons: list[str] = []
    if (row.get("teacher_count") or 0) <= 1:
        reasons.append("single_teacher")
    if (row.get("unknown_title_count") or 0) > 0:
        reasons.append("title_incomplete")
    known = (row.get("teacher_count") or 0) - (row.get("unknown_title_count") or 0)
    if known > 0 and ((row.get("professor_count") or 0) + (row.get("associate_professor_count") or 0)) == 0:
        reasons.append("no_senior_title")
    return reasons


def _faculty_reason_label(reason: str) -> str:
    return {
        "single_teacher": "当期单一教师承担",
        "title_incomplete": "职称信息不完整",
        "no_senior_title": "已知成员无教授/副教授",
    }.get(reason, reason)


def _course_raw_offering(conn: sqlite3.Connection, semester: str, course_id: str) -> dict:
    return dbm.query_one(conn, """
        SELECT COUNT(DISTINCT l.lesson_id) lesson_count,
               SUM(COALESCE(l.enrolled,0)) enrolled,
               SUM(COALESCE(l.capacity,0)) capacity,
               SUM(COALESCE(l.total_hours,0)) total_hours
        FROM teaching_lesson l
        WHERE l.semester_id=? AND l.course_id=?
    """, (semester, course_id)) or {"lesson_count": 0, "enrolled": 0, "capacity": 0, "total_hours": 0}


@router.get("/insight/faculty-resource-risk")
def faculty_resource_risk_insight(semester: str = "2023-2024-1",
                                  user: dict = Depends(get_current_user),
                                  conn: sqlite3.Connection = Depends(get_v2_db)):
    if user.get("role_id") not in V2_ALL_SCOPE_ROLES:
        raise ApiError("当前角色没有V2全校师资专题访问范围", code=403, status_code=403)
    rows = dbm.query(conn, """
        SELECT t.*,COALESCE(c.name,t.course_id) course_name,c.organization_id
        FROM agg_course_team t
        LEFT JOIN dim_course c ON c.course_id=t.course_id
        WHERE t.semester_id=?
    """, (semester,))
    if not rows:
        raise ApiError("暂无课程团队数据", code=404, status_code=404)
    for row in rows:
        raw = _course_raw_offering(conn, semester, row["course_id"])
        row["lesson_count"] = raw.get("lesson_count") or 0
        row["enrolled"] = raw.get("enrolled") or 0
        row["attention_reasons"] = _faculty_course_attention(row)
    attention = [r for r in rows if r["attention_reasons"]]
    attention.sort(key=lambda x: (
        "single_teacher" not in x["attention_reasons"],
        "title_incomplete" not in x["attention_reasons"],
        -int(x.get("enrolled") or 0),
        x["course_id"],
    ))
    single = sum(1 for r in rows if "single_teacher" in r["attention_reasons"])
    title_gap = sum(1 for r in rows if "title_incomplete" in r["attention_reasons"])
    no_senior = sum(1 for r in rows if "no_senior_title" in r["attention_reasons"])
    affected_enrolled = sum((r.get("enrolled") or 0) for r in attention[:20])
    top = attention[0] if attention else rows[0]
    risk = "critical" if single >= 10 or title_gap >= 20 else "warning" if attention else "info"
    summary = (
        f"{semester} 学期共识别 {len(rows)} 门有真实教学任务的课程团队，其中 {len(attention)} 门需要进一步核查。"
        f"主要问题包括单一教师承担 {single} 门、职称信息不完整 {title_gap} 门、已知成员无教授/副教授 {no_senior} 门。"
        f"建议优先核查选课人次较高且同时命中多项原因的课程，例如 {top.get('course_name') or top.get('course_id')}。"
    )
    reasons = [
        "课程团队风险关注的是教学运行保障，不直接评价课程质量或教师个人能力。",
        "单一教师承担表示当期教学任务存在备份能力核查需求，尤其是公共课、必修课或学生覆盖人次较高课程。",
        "职称信息不完整首先是主数据治理问题，不能据此直接判断团队梯队。",
        "已知成员无高职称只作为结构核查线索，需结合课程性质、教师资历、学院培养安排和课程团队建设实际判断。",
    ]
    return ok({
        "targetType": "facultyResourceRisk",
        "targetId": "faculty-resource-risk",
        "targetName": "资源与师资风险专题",
        "scenario": "faculty_resource_risk",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI增强研判样本" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": "全校", "major": "课程团队保障", "semester": semester},
        "evidence": [
            {"label": "真实团队课程", "value": f"{len(rows)} 门", "detail": "有真实教学任务教师关联的去重课程", "tone": "info"},
            {"label": "需核查课程", "value": f"{len(attention)} 门", "detail": "命中单教师/职称缺口/无高职称线索", "tone": "danger" if attention else "success"},
            {"label": "单一教师承担", "value": f"{single} 门", "detail": "优先核查备份教师和课程团队支撑", "tone": "danger" if single else "success"},
            {"label": "职称信息不完整", "value": f"{title_gap} 门", "detail": "优先补齐人事主数据", "tone": "warning" if title_gap else "success"},
            {"label": "重点覆盖人次", "value": f"{affected_enrolled} 人次", "detail": "TOP20 核查课程的选课人次合计", "tone": "warning" if affected_enrolled else "info"},
        ],
        "reasons": reasons,
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "建立课程团队核查清单", "detail": "优先核查单教师承担且学生覆盖人次高的课程，确认备份教师、教学资料和应急替代机制。"},
            {"role": "二级学院", "priority": "high" if single else "medium", "action": "完善课程团队梯队", "detail": "对重点课程补充课程团队成员、青年教师培养和高职称教师指导安排。"},
            {"role": "人事/数据治理", "priority": "high" if title_gap else "medium", "action": "补齐教师职称主数据", "detail": "先处理职称缺失，再进行职称结构、人才梯队和课程团队风险判断。"},
        ],
        "nextActions": [
            "打开命中多项原因的课程 AI 研判，核查是否存在高影响单点。",
            "按学院导出课程团队核查清单，交由学院确认课程负责人和备份教师。",
            "补齐职称主数据后重新计算课程团队结构风险。",
        ],
        "focusItems": {"courses": attention[:10]},
        "limitations": [
            "当前没有教师年龄数据，因此不判断年龄断层。",
            "当前结果基于一个接入学期的真实教学任务，不等同于长期师资梯队结论。",
        ],
    })


@router.get("/insight/faculty-resource-risk/course/{course_id}")
def faculty_resource_course_insight(course_id: str, semester: str = "2023-2024-1",
                                    user: dict = Depends(get_current_user),
                                    conn: sqlite3.Connection = Depends(get_v2_db)):
    if user.get("role_id") not in V2_ALL_SCOPE_ROLES:
        raise ApiError("当前角色没有V2全校师资专题访问范围", code=403, status_code=403)
    row = dbm.query_one(conn, """
        SELECT t.*,COALESCE(c.name,t.course_id) course_name,c.organization_id,c.category,c.nature
        FROM agg_course_team t
        LEFT JOIN dim_course c ON c.course_id=t.course_id
        WHERE t.semester_id=? AND t.course_id=?
    """, (semester, course_id))
    if not row:
        raise ApiError("暂无该课程团队数据", code=404, status_code=404)
    raw = _course_raw_offering(conn, semester, course_id)
    members = dbm.query(conn, """
        SELECT DISTINCT s.staff_id,s.display_name,s.title,s.organization_id,s.status
        FROM teaching_lesson l
        JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        LEFT JOIN dim_staff s ON s.staff_id=lt.staff_id
        WHERE l.semester_id=? AND l.course_id=?
        ORDER BY s.title,s.staff_id
    """, (semester, course_id))
    reasons = _faculty_course_attention(row)
    teacher_count = row.get("teacher_count") or 0
    known = teacher_count - (row.get("unknown_title_count") or 0)
    senior = (row.get("professor_count") or 0) + (row.get("associate_professor_count") or 0)
    risk = "critical" if "single_teacher" in reasons and (raw.get("enrolled") or 0) >= 80 else "warning" if reasons else "info"
    reason_text = "、".join(_faculty_reason_label(r) for r in reasons) or "未命中明显团队风险线索"
    summary = (
        f"{row.get('course_name') or course_id}在 {semester} 学期有 {teacher_count} 名实际授课教师、"
        f"{raw.get('lesson_count') or 0} 个教学班、{raw.get('enrolled') or 0} 人次选课。"
        f"当前关注原因：{reason_text}。"
    )
    explain = []
    if "single_teacher" in reasons:
        explain.append("当期仅 1 名教师承担该课程教学任务，若课程为必修、公共课或覆盖学生较多，需要核查备份教师和教学资料交接机制。")
    if "title_incomplete" in reasons:
        explain.append("团队中存在职称缺失，当前不宜直接判断职称梯队，应先补齐人事主数据。")
    if "no_senior_title" in reasons:
        explain.append("已知职称成员中未见教授/副教授，建议结合课程性质核查高职称教师指导或课程负责人安排。")
    return ok({
        "targetType": "facultyResourceCourse",
        "targetId": course_id,
        "targetName": row.get("course_name") or course_id,
        "scenario": "faculty_resource_course",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI增强研判样本" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": row.get("organization_id"), "major": row.get("category") or row.get("nature"), "semester": semester},
        "evidence": [
            {"label": "实际授课教师", "value": f"{teacher_count} 人", "detail": "当期教学任务关联教师", "tone": "danger" if teacher_count <= 1 else "success"},
            {"label": "教学班/选课", "value": f"{raw.get('lesson_count') or 0} 班 / {raw.get('enrolled') or 0} 人次", "detail": "基于 teaching_lesson 去重口径", "tone": "warning" if (raw.get("enrolled") or 0) >= 80 else "info"},
            {"label": "职称已知", "value": f"{known} / {teacher_count}", "detail": f"缺失 {row.get('unknown_title_count') or 0} 人", "tone": "warning" if row.get("unknown_title_count") else "success"},
            {"label": "教授/副教授", "value": f"{senior} 人", "detail": "已知成员中的高级职称线索", "tone": "warning" if known > 0 and senior == 0 else "info"},
            {"label": "命中原因", "value": f"{len(reasons)} 项", "detail": reason_text, "tone": "danger" if "single_teacher" in reasons else "warning" if reasons else "success"},
        ],
        "reasons": explain or ["当前未发现明显课程团队保障风险，可作为常规观察对象。"],
        "suggestions": [
            {"role": "二级学院", "priority": "high" if risk == "critical" else "medium", "action": "确认课程团队与备份教师", "detail": "核查课程负责人、备份教师、教学资料和青年教师培养安排，避免高影响单点。"},
            {"role": "教务处", "priority": "medium", "action": "纳入重点课程保障清单", "detail": "对覆盖学生较多、必修或公共课程，建议纳入教学运行保障台账。"},
            {"role": "人事/数据治理", "priority": "high" if "title_incomplete" in reasons else "medium", "action": "补齐职称与组织归属", "detail": "职称缺失课程需先完成教师主数据治理，再判断职称结构风险。"},
        ],
        "nextActions": [
            "查看成员列表，确认是否存在未关联到系统的实际课程团队成员。",
            "若为单教师承担，确认下一学期是否已有备份教师或团队共建安排。",
            "若无高级职称，结合课程性质判断是否需要高职称教师指导或课程负责人调整。",
        ],
        "focusItems": {"members": members},
        "limitations": [
            "当前没有教师年龄数据，因此不判断年龄断层。",
            "单学期单教师承担不等同于长期人才危机，需要结合连续学期和学院确认信息。",
        ],
    })

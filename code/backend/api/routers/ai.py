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
from ..deps import get_current_user, get_db, get_v2_db, student_data_scope
from ..envelope import ApiError, ok

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

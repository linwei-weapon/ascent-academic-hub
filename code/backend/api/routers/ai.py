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
from ..deps import get_current_user, get_db, student_data_scope
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


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _student_scope_sql(user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    frag, params = student_data_scope(user, conn, alias)
    return (f" AND {frag}" if frag else "", params)


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

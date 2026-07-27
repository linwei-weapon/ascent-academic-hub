"""学业预警监控 V2：学生口径摘要与服务端分页列表。

旧 ``GET /api/admin/alerts`` 为兼容接口，返回记录级全量数据。新接口把当前规则
命中（风险事实）与人工核查状态（管理过程）拆开，并默认按去重学生统计。
"""
from __future__ import annotations

import csv
import io
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Response

from .. import db as dbm
from ..deps import get_current_user, get_db, student_data_scope
from ..envelope import ApiError, ok
from ..settings import CURRENT_SEMESTER


router = APIRouter(prefix="/api/admin/alerts", tags=["alert-monitor"])

DEFINITION_VERSION = "alert-monitor-v2.0"
PRIORITY_VERSION = "alert-priority-v2.0"
RISK_LEVELS = {"严重", "警告", "提醒"}
MANAGEMENT_STATES = {
    "pending_review", "in_review", "recorded", "closed",
}
MANAGEMENT_LABELS = {
    "pending_review": "仍有待核查",
    "in_review": "核查中",
    "recorded": "已有核查记录",
    "closed": "已关闭",
}
WORKFLOW_REVIEWING = {
    "assigned", "notified", "contacted", "supporting", "review_pending",
}
DIMENSIONS = {"college", "major", "class"}


def _scope_meta(user: dict) -> dict:
    context = user.get("permission_context") or {}
    detail = context.get("detailScope") or {}
    scope_type = detail.get("type") or "denied"
    ids = detail.get("sourceScopeIds") or []
    labels = {
        "all": "全校",
        "college": "授权学院",
        "major": "授权专业",
        "class": "所带行政班",
        "staff_relation": "所带学生",
        "teacher": "授课关联学生",
        "denied": "无有效范围",
    }
    return {
        "type": scope_type,
        "label": labels.get(scope_type, "授权范围"),
        "sourceScopeIds": ids,
        "restricted": scope_type != "all",
        "scopeFingerprint": context.get("scopeFingerprint"),
    }


def _validate_common_filters(level: Optional[str], management: Optional[str],
                             page: int = 1, page_size: int = 20) -> None:
    if level and level not in RISK_LEVELS:
        raise ApiError("无效的预警等级", code=400, status_code=400)
    if management and management not in MANAGEMENT_STATES:
        raise ApiError("无效的管理状态", code=400, status_code=400)
    if page < 1:
        raise ApiError("页码必须大于等于1", code=400, status_code=400)
    if page_size < 10 or page_size > 50:
        raise ApiError("每页条数必须在10到50之间", code=400, status_code=400)


def _validate_explicit_scope(user: dict, college: Optional[str],
                             major: Optional[str], class_id: Optional[str]) -> None:
    """阻止受限身份用显式筛选探测授权范围外的数据。"""
    detail = (user.get("permission_context") or {}).get("detailScope") or {}
    scope_type = detail.get("type")
    source_ids = set(detail.get("sourceScopeIds") or [])
    if scope_type in (None, "all"):
        return
    requested = {
        "college": college,
        "major": major,
        "class": class_id,
    }
    own_value = requested.get(scope_type)
    if own_value and own_value not in source_ids:
        raise ApiError("筛选条件超出当前数据权限范围", code=403, status_code=403)
    # 受限身份不接受高于其授权粒度的显式组织筛选，避免返回空集时泄露存在性。
    if scope_type in {"major", "class", "staff_relation", "teacher"} and college:
        raise ApiError("当前身份不支持显式学院筛选", code=403, status_code=403)
    if scope_type in {"class", "staff_relation", "teacher"} and major:
        raise ApiError("当前身份不支持显式专业筛选", code=403, status_code=403)
    if scope_type in {"staff_relation", "teacher"} and class_id:
        raise ApiError("当前身份不支持显式班级筛选", code=403, status_code=403)


def _default_dimension(user: dict) -> str:
    scope_type = (
        (user.get("permission_context") or {}).get("detailScope") or {}
    ).get("type")
    if scope_type == "all":
        return "college"
    if scope_type == "college":
        return "major"
    return "class"


def _validate_dimension(user: dict, dimension: str) -> None:
    if dimension not in DIMENSIONS:
        raise ApiError("无效的组织分析维度", code=400, status_code=400)
    scope_type = (
        (user.get("permission_context") or {}).get("detailScope") or {}
    ).get("type")
    allowed = {
        "all": DIMENSIONS,
        "college": {"major", "class"},
        "major": {"major", "class"},
        "class": {"class"},
        "staff_relation": {"class"},
        "teacher": {"class"},
    }.get(scope_type, set())
    if dimension not in allowed:
        raise ApiError("当前身份不支持该组织分析维度", code=403, status_code=403)


def _population_where(user: dict, conn: sqlite3.Connection, *,
                      college: Optional[str] = None,
                      major: Optional[str] = None,
                      class_id: Optional[str] = None) -> tuple[str, list]:
    _validate_explicit_scope(user, college, major, class_id)
    conditions = ["COALESCE(st.status,'在籍')='在籍'"]
    params: list = []
    scope_sql, scope_params = student_data_scope(user, conn, "st")
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    for column, value in (
        ("st.college_id", college),
        ("st.major_id", major),
        ("st.class_id", class_id),
    ):
        if value:
            conditions.append(f"{column}=?")
            params.append(value)
    return " AND ".join(conditions), params


def _base_sql(user: dict, conn: sqlite3.Connection, *,
              level: Optional[str] = None, alert_type: Optional[str] = None,
              college: Optional[str] = None, major: Optional[str] = None,
              class_id: Optional[str] = None, keyword: Optional[str] = None
              ) -> tuple[str, list]:
    _validate_explicit_scope(user, college, major, class_id)
    conditions = ["COALESCE(a.is_active,1)=1"]
    params: list = []
    scope_sql, scope_params = student_data_scope(user, conn, "st")
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    if level:
        conditions.append("a.level=?")
        params.append(level)
    if alert_type:
        conditions.append("a.type=?")
        params.append(alert_type)
    if college:
        conditions.append("st.college_id=?")
        params.append(college)
    if major:
        conditions.append("st.major_id=?")
        params.append(major)
    if class_id:
        conditions.append("st.class_id=?")
        params.append(class_id)
    if keyword and keyword.strip():
        conditions.append("(st.student_id LIKE ? OR st.name LIKE ?)")
        term = f"%{keyword.strip()}%"
        params.extend([term, term])
    where = " AND ".join(conditions)
    sql = f"""
        SELECT a.alert_id, a.student_id, st.name student_name,
               st.college_id, c.name college_name,
               st.major_id, m.name major_name,
               st.class_id, cl.name class_name, st.grade,
               a.rule_id, a.type alert_type, a.level,
               a.trigger_detail, a.created_at, a.semester_id,
               COALESCE(a.source,'unknown') source,
               COALESCE(a.rule_version,'legacy') rule_version,
               a.activation_batch_id,
               COALESCE(e.workflow_status,'new') workflow_status,
               e.event_id, e.updated_at,
               CASE a.level WHEN '严重' THEN 3
                            WHEN '警告' THEN 2 ELSE 1 END risk_rank,
               CASE WHEN EXISTS (
                    SELECT 1 FROM alert_assignee aa
                    WHERE aa.event_id=e.event_id AND aa.username=?
                      AND COALESCE(e.workflow_status,'new')
                          NOT IN ('resolved','closed')
               ) THEN 1 ELSE 0 END assigned_to_current
        FROM fact_alert a
        JOIN dim_student st ON st.student_id=a.student_id
        LEFT JOIN alert_event e ON e.alert_id=a.alert_id
        LEFT JOIN dim_college c ON c.college_id=st.college_id
        LEFT JOIN dim_major m ON m.major_id=st.major_id
        LEFT JOIN dim_class cl ON cl.class_id=st.class_id
        WHERE {where}
    """
    return sql, [user.get("username", "")] + params


def _student_cte(base_sql: str) -> str:
    reviewing = ",".join(f"'{value}'" for value in sorted(WORKFLOW_REVIEWING))
    return f"""
        WITH base AS ({base_sql}),
        ranked AS (
            SELECT base.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY student_id
                       ORDER BY risk_rank DESC, created_at DESC, alert_id DESC
                   ) row_no,
                   COUNT(*) OVER (PARTITION BY student_id) alert_count,
                   MAX(risk_rank) OVER (PARTITION BY student_id) highest_rank,
                   MAX(CASE WHEN workflow_status='new' THEN 1 ELSE 0 END)
                       OVER (PARTITION BY student_id) has_pending,
                   MAX(CASE WHEN workflow_status IN ({reviewing}) THEN 1 ELSE 0 END)
                       OVER (PARTITION BY student_id) has_reviewing,
                   MAX(CASE WHEN workflow_status='resolved' THEN 1 ELSE 0 END)
                       OVER (PARTITION BY student_id) has_recorded,
                   MAX(assigned_to_current) OVER (PARTITION BY student_id)
                       assigned_to_current_student,
                   MIN(created_at) OVER (PARTITION BY student_id)
                       first_detected_at,
                   MAX(COALESCE(updated_at,created_at))
                       OVER (PARTITION BY student_id) latest_at
            FROM base
        ),
        students AS (
            SELECT *,
                   CASE
                       WHEN has_pending=1 THEN 'pending_review'
                       WHEN has_reviewing=1 THEN 'in_review'
                       WHEN has_recorded=1 THEN 'recorded'
                       ELSE 'closed'
                   END management_state
            FROM ranked WHERE row_no=1
        )
    """


def _history_capability(conn: sqlite3.Connection, where_sql: str,
                        params: list) -> dict:
    row = dbm.query_one(conn, f"""
        SELECT COUNT(*) total_records,
               SUM(CASE WHEN activation_batch_id IS NOT NULL THEN 1 ELSE 0 END)
                   batched_records,
               COUNT(DISTINCT activation_batch_id) batch_count,
               MAX(COALESCE(updated_at,created_at)) data_as_of,
               MAX(semester_id) semester_id
        FROM ({where_sql}) history_base
    """, tuple(params)) or {}
    return _history_capability_from_row(row)


def _history_capability_from_row(row: dict) -> dict:
    total = int(row.get("total_records") or 0)
    batched = int(row.get("batched_records") or 0)
    batches = int(row.get("batch_count") or 0)
    coverage = round(batched / total * 100, 1) if total else 0.0
    available = batches >= 2 and coverage >= 95
    return {
        "available": available,
        "batchCount": batches,
        "batchCoverage": coverage,
        "reason": None if available else (
            "当前只有部分规则具备计算批次标识，不能可靠判断新增、升级或持续。"
        ),
    }


def _static_meta(user: dict) -> dict:
    """列表、图表等接口只返回无需再次扫描事实表的稳定元数据。

    完整的数据时点、规则版本和历史批次能力由摘要接口统一返回，前端也只以
    摘要接口作为当前分析上下文的权威来源。
    """
    return {
        "definitionVersion": DEFINITION_VERSION,
        "scope": _scope_meta(user),
        "source": {
            "tables": ["fact_alert", "alert_event", "dim_student"],
            "limitation": (
                "完整数据时点、规则版本和历史可比能力以摘要接口为准。"
            ),
        },
    }


def _meta(conn: sqlite3.Connection, user: dict, base_sql: str,
          params: list) -> dict:
    data_row = dbm.query_one(conn, f"""
        SELECT COUNT(*) total_records,
               SUM(CASE WHEN activation_batch_id IS NOT NULL THEN 1 ELSE 0 END)
                   batched_records,
               COUNT(DISTINCT activation_batch_id) batch_count,
               MAX(COALESCE(updated_at,created_at)) data_as_of,
               MAX(semester_id) semester_id
        FROM ({base_sql}) meta_base
    """, tuple(params)) or {}
    versions = dbm.query(conn, f"""
        SELECT rule_id, rule_version, COUNT(*) record_count
        FROM ({base_sql}) version_base
        GROUP BY rule_id,rule_version ORDER BY rule_id,rule_version
    """, tuple(params))
    return {
        "definitionVersion": DEFINITION_VERSION,
        "scope": _scope_meta(user),
        "currentSemester": data_row.get("semester_id") or CURRENT_SEMESTER,
        "dataAsOf": data_row.get("data_as_of"),
        "ruleVersions": versions,
        "historyComparison": _history_capability_from_row(data_row),
        "source": {
            "tables": ["fact_alert", "alert_event", "dim_student"],
            "limitation": (
                "当前预警为规则计算快照；人工核查状态不代表风险已经消失。"
            ),
        },
    }


@router.get("/summary")
def alert_summary(level: Optional[str] = None, type: Optional[str] = None,
                  college: Optional[str] = None, major: Optional[str] = None,
                  class_id: Optional[str] = None,
                  user: dict = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    """按去重学生返回当前预警摘要，不返回全量明细。"""
    _validate_common_filters(level, None)
    base_sql, params = _base_sql(
        user, conn, level=level, alert_type=type, college=college,
        major=major, class_id=class_id,
    )
    cte = _student_cte(base_sql)
    summary = dbm.query_one(conn, cte + """
        SELECT COUNT(*) current_students,
               SUM(CASE WHEN highest_rank=3 THEN 1 ELSE 0 END)
                   critical_students,
               SUM(CASE WHEN highest_rank=3
                         AND management_state='pending_review'
                        THEN 1 ELSE 0 END) critical_pending_students,
               SUM(CASE WHEN management_state='pending_review' THEN 1 ELSE 0 END)
                   pending_students,
               SUM(CASE WHEN management_state='in_review' THEN 1 ELSE 0 END)
                   in_review_students,
               SUM(CASE WHEN management_state='recorded' THEN 1 ELSE 0 END)
                   recorded_students,
               SUM(CASE WHEN management_state='closed' THEN 1 ELSE 0 END)
                   closed_students,
               SUM(assigned_to_current_student) inbox_students,
               SUM(alert_count) current_alert_records
        FROM students
    """, tuple(params)) or {}
    values = {key: int(value or 0) for key, value in summary.items()}

    student_scope, student_params = student_data_scope(user, conn, "st")
    eligible_where = ["COALESCE(st.status,'在籍')='在籍'"]
    if student_scope:
        eligible_where.append(student_scope)
    eligible = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT st.student_id) FROM dim_student st
        WHERE {' AND '.join(eligible_where)}
    """, tuple(student_params)) or 0
    current_students = values.get("current_students", 0)
    values["eligible_students"] = int(eligible)
    values["alert_student_rate"] = (
        round(current_students / eligible * 100, 1) if eligible else None
    )

    definitions = {
        "current_students": {
            "label": "当前预警学生",
            "unit": "人",
            "formula": "当前快照至少命中1条有效规则的去重学生数",
            "managementUse": "判断当前需关注学生总体规模",
        },
        "critical_pending_students": {
            "label": "严重且待核查学生",
            "unit": "人",
            "formula": "当前最高风险为严重且管理状态为待核查的去重学生数",
            "managementUse": "形成本轮优先核查基础队列",
        },
        "pending_students": {
            "label": "待核查学生",
            "unit": "人",
            "formula": "至少存在1条管理状态为new的当前预警学生数",
            "managementUse": "评估尚未形成核查记录的工作量",
        },
        "alert_student_rate": {
            "label": "当前预警学生率",
            "unit": "%",
            "formula": "当前预警去重学生数 ÷ 当前权限范围内在籍学生数",
            "managementUse": "跨不同规模组织进行可比分析",
        },
    }
    return ok({
        "summary": values,
        "definitions": definitions,
        "meta": _meta(conn, user, base_sql, params),
    })


@router.get("/students")
def alert_students(page: int = 1, page_size: int = 20,
                   level: Optional[str] = None, type: Optional[str] = None,
                   management: Optional[str] = None,
                   assigned_to_me: bool = False,
                   college: Optional[str] = None, major: Optional[str] = None,
                   class_id: Optional[str] = None, q: Optional[str] = None,
                   user: dict = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    """按学生聚合当前预警，服务端筛选和分页。"""
    _validate_common_filters(level, management, page, page_size)
    base_sql, params = _base_sql(
        user, conn, level=level, alert_type=type, college=college,
        major=major, class_id=class_id, keyword=q,
    )
    cte = _student_cte(base_sql)
    outer_conditions = []
    management_params = []
    if management:
        outer_conditions.append("management_state=?")
        management_params.append(management)
    if assigned_to_me:
        outer_conditions.append("assigned_to_current_student=1")
    management_where = (
        " WHERE " + " AND ".join(outer_conditions) if outer_conditions else ""
    )
    offset = (page - 1) * page_size
    rows = dbm.query(conn, cte + f"""
        SELECT student_id,student_name,college_id,college_name,
               major_id,major_name,class_id,class_name,grade,
               level highest_level,alert_type primary_type,
               trigger_detail primary_reason,rule_id primary_rule_id,
               alert_count,management_state,latest_at,
               assigned_to_current_student assigned_to_current,
               COUNT(*) OVER () total_count
        FROM students{management_where}
        ORDER BY highest_rank DESC,
                 CASE management_state
                     WHEN 'pending_review' THEN 0
                     WHEN 'in_review' THEN 1
                     WHEN 'recorded' THEN 2 ELSE 3 END,
                 latest_at DESC,student_id
        LIMIT ? OFFSET ?
    """, tuple(params + management_params + [page_size, offset]))
    total = int(rows[0]["total_count"] or 0) if rows else 0

    ids = [row["student_id"] for row in rows]
    signals: dict[str, list] = {sid: [] for sid in ids}
    if ids:
        placeholders = ",".join("?" * len(ids))
        signal_rows = dbm.query(conn, f"""
            SELECT a.student_id,a.alert_id,e.event_id,a.rule_id,a.type,a.level,
                   a.trigger_detail,a.created_at,
                   COALESCE(a.rule_version,'legacy') rule_version,
                   COALESCE(e.workflow_status,'new') workflow_status
            FROM fact_alert a
            LEFT JOIN alert_event e ON e.alert_id=a.alert_id
            WHERE COALESCE(a.is_active,1)=1
              AND a.student_id IN ({placeholders})
            ORDER BY a.student_id,
                     CASE a.level WHEN '严重' THEN 3
                                  WHEN '警告' THEN 2 ELSE 1 END DESC,
                     a.created_at DESC,a.alert_id DESC
        """, tuple(ids))
        for signal in signal_rows:
            signals.setdefault(signal["student_id"], []).append({
                "alertId": signal["alert_id"],
                "eventId": signal["event_id"],
                "ruleId": signal["rule_id"],
                "type": signal["type"],
                "level": signal["level"],
                "reason": signal["trigger_detail"],
                "managementStatus": signal["workflow_status"],
                "ruleVersion": signal["rule_version"],
                "detectedAt": signal["created_at"],
            })

    items = []
    for row in rows:
        state = row["management_state"]
        items.append({
            "studentId": row["student_id"],
            "studentName": row["student_name"],
            "collegeId": row["college_id"],
            "collegeName": row["college_name"] or "—",
            "majorId": row["major_id"],
            "majorName": row["major_name"] or "—",
            "classId": row["class_id"],
            "className": row["class_name"] or "—",
            "grade": row["grade"],
            "highestLevel": row["highest_level"],
            "primaryType": row["primary_type"],
            "primaryReason": row["primary_reason"],
            "primaryRuleId": row["primary_rule_id"],
            "alertCount": row["alert_count"],
            "riskState": "current",
            "riskChange": None,
            "managementState": state,
            "managementLabel": MANAGEMENT_LABELS[state],
            "latestAt": row["latest_at"],
            "assignedToCurrent": bool(row["assigned_to_current"]),
            "signals": signals.get(row["student_id"], []),
        })
    return ok({
        "items": items,
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": int(total),
            "pages": (int(total) + page_size - 1) // page_size,
        },
        "meta": _static_meta(user),
    })


@router.get("/priority")
def alert_priority(limit: int = 10,
                   level: Optional[str] = None, type: Optional[str] = None,
                   management: Optional[str] = None,
                   college: Optional[str] = None, major: Optional[str] = None,
                   class_id: Optional[str] = None,
                   user: dict = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    """形成有限的学生级核查队列，并返回可核验的评分分解。"""
    _validate_common_filters(level, management)
    if limit < 1 or limit > 30:
        raise ApiError("优先队列条数必须在1到30之间", code=400, status_code=400)
    base_sql, params = _base_sql(
        user, conn, level=level, alert_type=type, college=college,
        major=major, class_id=class_id,
    )
    cte = _student_cte(base_sql)
    management_where = (
        "management_state=?" if management
        else "management_state IN ('pending_review','in_review')"
    )
    management_params = [management] if management else []
    rows = dbm.query(conn, cte + f"""
        SELECT student_id,student_name,college_id,college_name,
               major_id,major_name,class_id,class_name,grade,
               alert_id,event_id,rule_id,rule_version,
               level highest_level,alert_type primary_type,
               trigger_detail primary_reason,alert_count,
               management_state,assigned_to_current_student,
               first_detected_at,latest_at,
               CAST(MAX(0, julianday('now') -
                   julianday(first_detected_at)) AS INTEGER) open_days,
               (
                   CASE highest_rank WHEN 3 THEN 50
                                     WHEN 2 THEN 30 ELSE 15 END
                   + CASE management_state
                         WHEN 'pending_review' THEN 15
                         WHEN 'in_review' THEN 8 ELSE 0 END
                   + MIN(MAX(alert_count - 1, 0), 3) * 5
                   + CASE
                         WHEN julianday('now') - julianday(first_detected_at) >= 60
                             THEN 10
                         WHEN julianday('now') - julianday(first_detected_at) >= 30
                             THEN 5
                         ELSE 0
                     END
               ) priority_score
        FROM students
        WHERE {management_where}
        ORDER BY priority_score DESC,highest_rank DESC,
                 first_detected_at,latest_at DESC,student_id
        LIMIT ?
    """, tuple(params + management_params + [limit]))

    items = []
    for row in rows:
        reasons = [f"{row['highest_level']}风险"]
        if int(row["alert_count"] or 0) > 1:
            reasons.append(f"{row['alert_count']}条当前规则同时命中")
        reasons.append(
            "仍有当前规则尚未核查"
            if row["management_state"] == "pending_review"
            else "已进入核查但尚未闭合"
        )
        if int(row["open_days"] or 0) >= 30:
            reasons.append(f"当前风险池已持续{row['open_days']}天")
        items.append({
            "studentId": row["student_id"],
            "studentName": row["student_name"],
            "collegeId": row["college_id"],
            "collegeName": row["college_name"] or "—",
            "majorId": row["major_id"],
            "majorName": row["major_name"] or "—",
            "classId": row["class_id"],
            "className": row["class_name"] or "—",
            "grade": row["grade"],
            "highestLevel": row["highest_level"],
            "primaryType": row["primary_type"],
            "primaryReason": row["primary_reason"],
            "alertCount": int(row["alert_count"] or 0),
            "managementState": row["management_state"],
            "managementLabel": MANAGEMENT_LABELS[row["management_state"]],
            "assignedToCurrent": bool(row["assigned_to_current_student"]),
            "firstDetectedAt": row["first_detected_at"],
            "latestAt": row["latest_at"],
            "openDays": int(row["open_days"] or 0),
            "priorityScore": int(row["priority_score"] or 0),
            "priorityReasons": reasons,
            "signals": [{
                "alertId": row["alert_id"],
                "eventId": row["event_id"],
                "ruleId": row["rule_id"],
                "type": row["primary_type"],
                "level": row["highest_level"],
                "reason": row["primary_reason"],
                "managementStatus": (
                    "new" if row["management_state"] == "pending_review"
                    else "review_pending"
                ),
                "ruleVersion": row["rule_version"],
                "detectedAt": row["first_detected_at"],
            }],
            "scoreBreakdown": {
                "risk": 50 if row["highest_level"] == "严重"
                        else 30 if row["highest_level"] == "警告" else 15,
                "management": (
                    15 if row["management_state"] == "pending_review" else 8
                ),
                "multipleSignals": min(
                    max(int(row["alert_count"] or 0) - 1, 0), 3
                ) * 5,
                "duration": (
                    10 if int(row["open_days"] or 0) >= 60
                    else 5 if int(row["open_days"] or 0) >= 30 else 0
                ),
            },
        })
    return ok({
        "items": items,
        "definition": {
            "version": PRIORITY_VERSION,
            "formula": (
                "最高风险分（严重50/警告30/提醒15）＋管理状态分"
                "（待核查15/核查中8）＋多规则分（每增加1条加5，最多15）"
                "＋持续时长分（30天5/60天10）"
            ),
            "managementUse": "把有限核查精力优先用于风险高、证据叠加且尚未闭合的学生",
            "boundary": (
                "分数仅用于安排核查先后，不是风险概率，也不是学生评价或处分依据。"
                "同分时优先持续时间更长者。"
            ),
            "sourceTables": ["fact_alert", "alert_event", "dim_student"],
        },
        "meta": _static_meta(user),
    })


@router.get("/students.csv")
def export_alert_students(level: Optional[str] = None,
                          type: Optional[str] = None,
                          management: Optional[str] = None,
                          assigned_to_me: bool = False,
                          college: Optional[str] = None,
                          major: Optional[str] = None,
                          class_id: Optional[str] = None,
                          q: Optional[str] = None,
                          user: dict = Depends(get_current_user),
                          conn: sqlite3.Connection = Depends(get_db)):
    """导出当前授权范围及筛选条件下的去重学生名单。"""
    _validate_common_filters(level, management)
    context = user.get("permission_context") or {}
    if not context.get("authorized"):
        raise ApiError("当前工作身份没有有效数据范围", code=403, status_code=403)
    base_sql, params = _base_sql(
        user, conn, level=level, alert_type=type, college=college,
        major=major, class_id=class_id, keyword=q,
    )
    cte = _student_cte(base_sql)
    conditions = []
    extra_params = []
    if management:
        conditions.append("management_state=?")
        extra_params.append(management)
    if assigned_to_me:
        conditions.append("assigned_to_current_student=1")
    outer_where = " WHERE " + " AND ".join(conditions) if conditions else ""
    total = int(dbm.scalar(
        conn, cte + f"SELECT COUNT(*) FROM students{outer_where}",
        tuple(params + extra_params),
    ) or 0)
    if total > 5000:
        raise ApiError(
            f"当前筛选包含{total}名学生，超过单次导出上限5000人，请先收窄条件",
            code=409, status_code=409,
        )
    rows = dbm.query(conn, cte + f"""
        SELECT student_id,student_name,college_name,major_name,class_name,grade,
               level highest_level,alert_type primary_type,
               trigger_detail primary_reason,alert_count,
               management_state,first_detected_at,latest_at
        FROM students{outer_where}
        ORDER BY highest_rank DESC,
                 CASE management_state
                     WHEN 'pending_review' THEN 0
                     WHEN 'in_review' THEN 1
                     WHEN 'recorded' THEN 2 ELSE 3 END,
                 latest_at DESC,student_id
    """, tuple(params + extra_params))
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow([
        "学号", "姓名", "学院", "专业", "行政班", "年级", "最高风险",
        "主要预警类型", "主要触发证据", "当前规则命中数", "核查状态",
        "首次进入当前风险池", "最近变化",
    ])
    for row in rows:
        writer.writerow([
            row["student_id"], row["student_name"], row["college_name"] or "",
            row["major_name"] or "", row["class_name"] or "", row["grade"] or "",
            row["highest_level"], row["primary_type"], row["primary_reason"],
            row["alert_count"], MANAGEMENT_LABELS[row["management_state"]],
            row["first_detected_at"] or "", row["latest_at"] or "",
        ])
    return Response(
        content="\ufeff" + stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="current-alert-students.csv"'
            ),
            "X-Export-Count": str(total),
            "X-Definition-Version": DEFINITION_VERSION,
        },
    )


@router.get("/distribution")
def alert_distribution(dimension: Optional[str] = None,
                       level: Optional[str] = None,
                       type: Optional[str] = None,
                       college: Optional[str] = None,
                       major: Optional[str] = None,
                       class_id: Optional[str] = None,
                       user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db)):
    """返回角色适配的组织预警学生率，同时保留人数作为资源规模依据。"""
    _validate_common_filters(level, None)
    selected_dimension = dimension or _default_dimension(user)
    _validate_dimension(user, selected_dimension)
    base_sql, params = _base_sql(
        user, conn, level=level, alert_type=type, college=college,
        major=major, class_id=class_id,
    )
    population_where, population_params = _population_where(
        user, conn, college=college, major=major, class_id=class_id,
    )
    columns = {
        "college": ("st.college_id", "c.name"),
        "major": ("st.major_id", "m.name"),
        "class": ("st.class_id", "cl.name"),
    }
    group_id, group_name = columns[selected_dimension]
    rows = dbm.query(conn, f"""
        WITH alert_base AS ({base_sql}),
        alerted AS (
            SELECT student_id,
                   MAX(risk_rank) highest_rank
            FROM alert_base GROUP BY student_id
        ),
        population AS (
            SELECT st.student_id,{group_id} group_id,{group_name} group_name
            FROM dim_student st
            LEFT JOIN dim_college c ON c.college_id=st.college_id
            LEFT JOIN dim_major m ON m.major_id=st.major_id
            LEFT JOIN dim_class cl ON cl.class_id=st.class_id
            WHERE {population_where}
        )
        SELECT p.group_id,p.group_name,
               COUNT(DISTINCT p.student_id) eligible_students,
               COUNT(DISTINCT a.student_id) alert_students,
               COUNT(DISTINCT CASE WHEN a.highest_rank=3
                                   THEN a.student_id END) critical_students
        FROM population p
        LEFT JOIN alerted a ON a.student_id=p.student_id
        WHERE p.group_id IS NOT NULL
        GROUP BY p.group_id,p.group_name
        ORDER BY
            CASE WHEN COUNT(DISTINCT p.student_id)=0 THEN 0
                 ELSE 1.0*COUNT(DISTINCT a.student_id)
                      /COUNT(DISTINCT p.student_id) END DESC,
            alert_students DESC,p.group_name
    """, tuple(params + population_params))
    items = []
    for row in rows:
        eligible = int(row["eligible_students"] or 0)
        alerted = int(row["alert_students"] or 0)
        items.append({
            "id": row["group_id"],
            "name": row["group_name"] or row["group_id"],
            "eligibleStudents": eligible,
            "alertStudents": alerted,
            "criticalStudents": int(row["critical_students"] or 0),
            "alertStudentRate": (
                round(alerted / eligible * 100, 1) if eligible else None
            ),
        })
    total_eligible = sum(item["eligibleStudents"] for item in items)
    total_alerted = sum(item["alertStudents"] for item in items)
    return ok({
        "dimension": selected_dimension,
        "items": items,
        "benchmark": {
            "label": "当前权限范围平均值",
            "alertStudentRate": (
                round(total_alerted / total_eligible * 100, 1)
                if total_eligible else None
            ),
        },
        "definition": {
            "formula": "当前预警去重学生数 ÷ 当前组织在籍学生数",
            "managementUse": "避免不同规模组织仅按人数排名造成误判",
            "boundary": "人数用于估算工作量，比例用于组织间可比分析",
        },
        "meta": _static_meta(user),
    })


@router.get("/time-distribution")
def alert_time_distribution(level: Optional[str] = None,
                            type: Optional[str] = None,
                            college: Optional[str] = None,
                            major: Optional[str] = None,
                            class_id: Optional[str] = None,
                            user: dict = Depends(get_current_user),
                            conn: sqlite3.Connection = Depends(get_db)):
    """当前活动预警按首次生成月份分布；批次证据不足时不冒充历史趋势。"""
    _validate_common_filters(level, None)
    base_sql, params = _base_sql(
        user, conn, level=level, alert_type=type, college=college,
        major=major, class_id=class_id,
    )
    rows = dbm.query(conn, f"""
        SELECT substr(created_at,1,7) month,
               COUNT(*) alert_records,
               COUNT(DISTINCT student_id) alert_students
        FROM ({base_sql}) time_base
        WHERE created_at IS NOT NULL
        GROUP BY substr(created_at,1,7)
        ORDER BY month
    """, tuple(params))
    capability = _history_capability(conn, base_sql, params)
    return ok({
        "mode": "snapshot_first_detected_month",
        "items": [{
            "month": row["month"],
            "alertRecords": int(row["alert_records"] or 0),
            "alertStudents": int(row["alert_students"] or 0),
        } for row in rows],
        "comparison": capability,
        "definition": {
            "label": "当前预警首次生成时间分布",
            "formula": "仅对当前仍命中的预警，按首次生成月份汇总",
            "managementUse": "识别当前风险池中滞留时间较长的预警",
            "boundary": (
                "这不是各月历史新增趋势；历史批次覆盖达到要求后再提供新增、升级和持续变化。"
            ),
        },
        "meta": _static_meta(user),
    })


@router.get("/options")
def alert_filter_options(college: Optional[str] = None,
                         major: Optional[str] = None,
                         user: dict = Depends(get_current_user),
                         conn: sqlite3.Connection = Depends(get_db)):
    """按当前权限范围返回筛选选项，不依赖前端下载全量预警后去重。"""
    base_sql, params = _base_sql(
        user, conn, college=college, major=major
    )
    types = dbm.query(conn, f"""
        SELECT alert_type value,COUNT(*) record_count
        FROM ({base_sql}) option_base
        WHERE alert_type IS NOT NULL
        GROUP BY alert_type ORDER BY record_count DESC,alert_type
    """, tuple(params))
    scope_type = (
        (user.get("permission_context") or {}).get("detailScope") or {}
    ).get("type")
    organizations = {}
    allowed_dimensions = {
        "all": ("college", "major", "class"),
        "college": ("major", "class"),
        "major": ("major", "class"),
        "class": ("class",),
        "staff_relation": ("class",),
        "teacher": ("class",),
    }.get(scope_type, ())
    columns = {
        "college": ("college_id", "college_name"),
        "major": ("major_id", "major_name"),
        "class": ("class_id", "class_name"),
    }
    for dimension in allowed_dimensions:
        key, name = columns[dimension]
        organizations[dimension] = dbm.query(conn, f"""
            SELECT {key} value,COALESCE({name},{key}) label,
                   COUNT(DISTINCT student_id) student_count
            FROM ({base_sql}) option_base
            WHERE {key} IS NOT NULL
            GROUP BY {key},{name} ORDER BY label
        """, tuple(params))
    return ok({
        "levels": [
            {"value": "严重", "label": "严重"},
            {"value": "警告", "label": "警告"},
            {"value": "提醒", "label": "提醒"},
        ],
        "types": types,
        "managementStates": [
            {"value": key, "label": value}
            for key, value in MANAGEMENT_LABELS.items()
        ],
        "organizations": organizations,
        "defaultDimension": _default_dimension(user),
        "meta": _static_meta(user),
    })

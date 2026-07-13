"""预警组：预警总览/列表 + 学生明细。数据来自 fact_alert + fact_grade + dim_*。
形状对齐 vite.config.ts mock（/api/admin/alerts、/api/admin/student/{sid}）。
"""
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import db as dbm
from ..deps import (ADMIN_ROLES, get_db, get_db_rw, get_current_user,
                    student_data_scope)
from ..envelope import ok, ApiError
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin", tags=["alert"])

CUR = CURRENT_SEMESTER

WORKFLOW_LABELS = {
    "new": "待处理", "assigned": "已分派", "notified": "已通知",
    "contacted": "已联系", "supporting": "帮扶中",
    "review_pending": "待复核", "resolved": "已解决", "closed": "已关闭",
}
WORKFLOW_STATUSES = set(WORKFLOW_LABELS)
WORKFLOW_BY_LABEL = {v: k for k, v in WORKFLOW_LABELS.items()}
ALLOWED_TRANSITIONS = {
    "new": {"assigned", "notified", "contacted", "closed"},
    "assigned": {"notified", "contacted", "closed"},
    "notified": {"contacted", "supporting", "closed"},
    "contacted": {"supporting", "review_pending", "resolved", "closed"},
    "supporting": {"review_pending", "resolved", "closed"},
    "review_pending": {"supporting", "resolved", "closed"},
    "resolved": set(), "closed": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _gpa_history(conn, sid, limit=6) -> list[float]:
    rows = dbm.query(conn, """
        SELECT semester_id, AVG(gpa) g FROM fact_grade
        WHERE student_id=? AND gpa IS NOT NULL
        GROUP BY semester_id ORDER BY semester_id""", (sid,))
    seq = [round(r["g"], 2) for r in rows if r["g"] is not None]
    return seq[-limit:]


@router.get("/alerts")
def alerts(level: Optional[str] = None, type: Optional[str] = None,
           status: Optional[str] = None, college: Optional[str] = None,
           user: dict = Depends(get_current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    # 统一过滤条件：等级/类型/状态/学院。无值=不加 WHERE=全量。
    # summary/列表/月度趋势/学院分布共用同一切片，保证卡片与列表口径一致
    # （不会出现"卡片是全量、列表是筛选后"的穿帮）。
    conds, params = ["COALESCE(a.is_active,1)=1"], []
    if level:
        conds.append("a.level=?"); params.append(level)
    if type:
        conds.append("a.type=?"); params.append(type)
    if status:
        workflow_status = WORKFLOW_BY_LABEL.get(status, status)
        conds.append("e.workflow_status=?"); params.append(workflow_status)
    if college:
        conds.append("st.college_id=?"); params.append(college)
    # 数据范围过滤：college/major/class 角色仅看自己范围内的学生
    scope_frag, scope_params = student_data_scope(user, conn, "st")
    if scope_frag:
        conds.append(scope_frag); params += scope_params
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    p = tuple(params)
    join = ("FROM fact_alert a JOIN dim_student st ON a.student_id=st.student_id "
            "LEFT JOIN alert_event e ON e.alert_id=a.alert_id")

    lv = {r["level"]: r["n"] for r in dbm.query(
        conn, f"SELECT a.level, COUNT(*) n {join}{where} GROUP BY a.level", p)}
    total = dbm.scalar(conn, f"SELECT COUNT(*) {join}{where}", p) or 0
    resolved = dbm.scalar(
        conn, f"SELECT COUNT(*) {join}{where}{' AND' if where else ' WHERE'} "
        "e.workflow_status='resolved'", p) or 0
    workflow_counts = {r["workflow_status"]: r["n"] for r in dbm.query(
        conn, f"SELECT e.workflow_status,COUNT(*) n {join}{where} "
              "GROUP BY e.workflow_status", p)}
    inbox_count = dbm.scalar(conn, f"""SELECT COUNT(*) {join}
        JOIN alert_assignee aa ON aa.event_id=e.event_id
        {where}{' AND' if where else ' WHERE'} aa.username=?
        AND e.workflow_status NOT IN ('resolved','closed')""", (*p, user["username"])) or 0
    summary = {
        "critical": lv.get("严重", 0), "warning": lv.get("警告", 0),
        "info": lv.get("提醒", 0), "resolved": resolved,
        "resolvedRate": f"{round(resolved / total * 100, 1)}%" if total else "0%",
        "inbox": inbox_count,
        "workflow": {key: workflow_counts.get(key, 0) for key in WORKFLOW_STATUSES},
    }

    rules = [{"id": r["rule_id"], "name": r["name"], "level": r["level"],
              "triggerType": r["trigger_type"], "params": _rule_text(r["params"])}
             for r in dbm.query(conn, "SELECT rule_id,name,level,trigger_type,params "
                                "FROM sys_alert_rule WHERE enabled=1 ORDER BY rule_id")]

    # 列表：含学生属性 + GPA 轨迹（明细页另取 scores/alertHistory）
    lst = []
    for r in dbm.query(conn, f"""
        SELECT a.student_id sid, st.name, c.name college, cl.name cls,
               a.level, a.type, a.trigger_detail detail, a.status, a.created_at time,
               e.event_id, e.workflow_status,
               (SELECT aa.username FROM alert_assignee aa WHERE aa.event_id=e.event_id
                AND aa.is_primary=1 LIMIT 1) assignee,
               (SELECT MAX(af.created_at) FROM alert_followup af
                WHERE af.event_id=e.event_id) last_followup_at
        {join}
        LEFT JOIN dim_college c ON st.college_id=c.college_id
        LEFT JOIN dim_class cl ON st.class_id=cl.class_id{where}
        ORDER BY CASE a.level WHEN '严重' THEN 0 WHEN '警告' THEN 1 ELSE 2 END, a.created_at DESC""",
            p):
        lst.append({
            "sid": r["sid"], "name": r["name"], "college": r["college"] or "—",
            "class": r["cls"] or "—", "level": r["level"], "type": r["type"],
            "detail": r["detail"],
            "status": WORKFLOW_LABELS.get(r["workflow_status"], r["status"]),
            "workflowStatus": r["workflow_status"], "eventId": r["event_id"],
            "assignee": r["assignee"] or "—", "lastFollowupAt": r["last_followup_at"],
            "time": r["time"],
            "gpaHistory": _gpa_history(conn, r["sid"]), "alerts": [], "scores": [],
        })

    monthlyTrend = [{"month": r["m"], "count": r["n"]} for r in dbm.query(
        conn, f"SELECT substr(a.created_at,1,7) m, COUNT(*) n {join}{where} "
        "GROUP BY m ORDER BY m", p)]

    collegeDist = []
    for r in dbm.query(conn, f"""
        SELECT c.name,
               SUM(CASE WHEN a.level='严重' THEN 1 ELSE 0 END) critical,
               SUM(CASE WHEN a.level='警告' THEN 1 ELSE 0 END) warning,
               SUM(CASE WHEN a.level='提醒' THEN 1 ELSE 0 END) info,
               COUNT(*) total
        {join}
        LEFT JOIN dim_college c ON st.college_id=c.college_id{where}
        GROUP BY st.college_id ORDER BY total DESC""", p):
        collegeDist.append({"name": r["name"] or "—", "critical": r["critical"],
                            "warning": r["warning"], "info": r["info"], "total": r["total"]})

    return ok({"summary": summary, "rules": rules, "list": lst,
               "monthlyTrend": monthlyTrend, "collegeDist": collegeDist})


def _event_for_user(conn: sqlite3.Connection, event_id: int, user: dict) -> dict:
    scope_frag, scope_params = student_data_scope(user, conn, "st")
    scope_sql = f" AND {scope_frag}" if scope_frag else ""
    event = dbm.query_one(conn, f"""
        SELECT e.*, a.type, a.level, a.trigger_detail, st.name student_name,
               c.name college_name, cl.name class_name
        FROM alert_event e JOIN fact_alert a ON e.alert_id=a.alert_id
        JOIN dim_student st ON e.student_id=st.student_id
        LEFT JOIN dim_college c ON st.college_id=c.college_id
        LEFT JOIN dim_class cl ON st.class_id=cl.class_id
        WHERE e.event_id=?{scope_sql}""", [event_id] + scope_params)
    if not event:
        raise ApiError("预警事件不存在或无权访问", code=404, status_code=404)
    return event


def _require_event_operator(conn: sqlite3.Connection, event_id: int, user: dict) -> None:
    if user.get("role_id") in ADMIN_ROLES:
        return
    assigned = dbm.scalar(conn, """SELECT 1 FROM alert_assignee
        WHERE event_id=? AND username=?""", (event_id, user["username"]))
    if not assigned:
        raise ApiError("仅事件责任人可执行处理操作", code=403, status_code=403)


@router.get("/alert-inbox")
def alert_inbox(user: dict = Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    scope_frag, scope_params = student_data_scope(user, conn, "st")
    scope_sql = f" AND {scope_frag}" if scope_frag else ""
    rows = dbm.query(conn, f"""
        SELECT e.event_id, e.student_id, st.name student_name, a.type, a.level,
               a.trigger_detail detail, e.workflow_status, e.updated_at,
               aa.assignment_reason
        FROM alert_assignee aa JOIN alert_event e ON aa.event_id=e.event_id
        JOIN fact_alert a ON e.alert_id=a.alert_id
        JOIN dim_student st ON e.student_id=st.student_id
        WHERE aa.username=? AND e.workflow_status NOT IN ('resolved','closed')
        {scope_sql}
        ORDER BY CASE a.level WHEN '严重' THEN 0 WHEN '警告' THEN 1 ELSE 2 END,
                 COALESCE(e.updated_at,e.first_detected_at)""",
        [user["username"]] + scope_params)
    return ok({"total": len(rows), "list": [{
        **row, "statusLabel": WORKFLOW_LABELS.get(row["workflow_status"], row["workflow_status"])
    } for row in rows]})


@router.get("/alert-events/{event_id}")
def alert_event_detail(event_id: int, user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db)):
    event = _event_for_user(conn, event_id, user)
    assignees = dbm.query(conn, """
        SELECT username,role_id,assignment_reason,assigned_at,is_primary
        FROM alert_assignee WHERE event_id=? ORDER BY is_primary DESC,assigned_at""",
        (event_id,))
    followups = dbm.query(conn, """
        SELECT followup_id,operator,action_type,content,next_action_at,created_at
        FROM alert_followup WHERE event_id=? ORDER BY created_at DESC,followup_id DESC""",
        (event_id,))
    history = dbm.query(conn, """
        SELECT from_status,to_status,operator,reason,changed_at
        FROM alert_status_history WHERE event_id=? ORDER BY changed_at DESC,history_id DESC""",
        (event_id,))
    return ok({
        "eventId": event["event_id"], "studentId": event["student_id"],
        "studentName": event["student_name"], "college": event["college_name"],
        "className": event["class_name"], "ruleId": event["rule_id"],
        "type": event["type"], "level": event["level"],
        "detail": event["trigger_detail"],
        "workflowStatus": event["workflow_status"],
        "workflowStatusLabel": WORKFLOW_LABELS.get(event["workflow_status"], event["workflow_status"]),
        "cycleNo": event.get("cycle_no") or 1,
        "recurrenceOfEventId": event.get("recurrence_of_event_id"),
        "cycleReason": event.get("cycle_reason"),
        "assignees": assignees, "followups": followups, "statusHistory": history,
    })


class FollowupBody(BaseModel):
    action_type: str = Field(min_length=1, max_length=30)
    content: str = Field(min_length=1, max_length=1000)
    next_action_at: Optional[str] = None


@router.post("/alert-events/{event_id}/followups")
def add_alert_followup(event_id: int, body: FollowupBody,
                       user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db_rw)):
    _event_for_user(conn, event_id, user)
    _require_event_operator(conn, event_id, user)
    created_at = _now()
    cur = dbm.execute(conn, """
        INSERT INTO alert_followup
        (event_id,operator,action_type,content,next_action_at,created_at)
        VALUES (?,?,?,?,?,?)""",
        (event_id, user["username"], body.action_type, body.content.strip(),
         body.next_action_at, created_at))
    dbm.execute(conn, "UPDATE alert_event SET updated_at=? WHERE event_id=?",
                (created_at, event_id))
    return ok({"followupId": cur.lastrowid, "createdAt": created_at})


class StatusBody(BaseModel):
    status: str
    reason: Optional[str] = Field(default=None, max_length=500)


@router.put("/alert-events/{event_id}/status")
def update_alert_status(event_id: int, body: StatusBody,
                        user: dict = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db_rw)):
    if body.status not in WORKFLOW_STATUSES:
        raise ApiError("无效的预警状态", code=400, status_code=400)
    event = _event_for_user(conn, event_id, user)
    _require_event_operator(conn, event_id, user)
    old = event["workflow_status"]
    if old == body.status:
        return ok({"status": body.status, "label": WORKFLOW_LABELS[body.status]})
    if body.status not in ALLOWED_TRANSITIONS.get(old, set()):
        raise ApiError(
            f"不允许从{WORKFLOW_LABELS.get(old, old)}直接变更为"
            f"{WORKFLOW_LABELS[body.status]}", code=400, status_code=400)
    changed_at = _now()
    dbm.execute(conn, """UPDATE alert_event SET workflow_status=?,updated_at=?
                          WHERE event_id=?""", (body.status, changed_at, event_id))
    dbm.execute(conn, """INSERT INTO alert_status_history
        (event_id,from_status,to_status,operator,reason,changed_at)
        VALUES (?,?,?,?,?,?)""",
        (event_id, old, body.status, user["username"], body.reason, changed_at))
    return ok({"status": body.status, "label": WORKFLOW_LABELS[body.status],
               "changedAt": changed_at})


def _rule_text(params):
    import json
    try:
        return json.loads(params).get("text", "") if params else ""
    except (ValueError, TypeError):
        return ""


@router.get("/student/{sid}")
def student_detail(sid: str, user: dict = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    st = dbm.query_one(conn, """
        SELECT s.student_id, s.name, s.grade, s.enroll_on,
               c.college_id, c.name college, m.name major, cl.name cls
        FROM dim_student s
        LEFT JOIN dim_college c ON s.college_id=c.college_id
        LEFT JOIN dim_major m ON s.major_id=m.major_id
        LEFT JOIN dim_class cl ON s.class_id=cl.class_id
        WHERE s.student_id=?""", (sid,))
    if not st:
        raise ApiError("学生不存在", code=404, status_code=404)
    # 数据范围校验：确保该学生在当前用户的数据范围内
    scope_frag, scope_params = student_data_scope(user, conn, "s")
    if scope_frag:
        allowed = dbm.scalar(conn, f"""
            SELECT 1 FROM dim_student s
            WHERE s.student_id=? AND {scope_frag}""", [sid] + scope_params)
        if not allowed:
            raise ApiError("无权限查看该学生", code=403, status_code=403)

    gpa_hist = _gpa_history(conn, sid)
    cur_gpa = gpa_hist[-1] if gpa_hist else 0
    earned = dbm.scalar(conn, "SELECT SUM(credits) FROM fact_grade WHERE student_id=? AND is_pass=1",
                        (sid,)) or 0
    all_alert_rows = dbm.query(conn, """
        SELECT a.alert_id,a.rule_id,a.level,a.type,a.trigger_detail detail,a.status,
               a.created_at time,COALESCE(a.is_active,1) is_active,e.event_id,
               e.workflow_status,e.first_detected_at,e.last_detected_at,e.cycle_no
        FROM fact_alert a LEFT JOIN alert_event e ON e.alert_id=a.alert_id
        WHERE a.student_id=? ORDER BY a.created_at DESC,a.alert_id DESC""", (sid,))
    alert_rows = [row for row in all_alert_rows if row["is_active"] == 1]
    top_level = "正常"
    if any(a["level"] == "严重" for a in alert_rows):
        top_level = "⚠ 严重"
    elif any(a["level"] == "警告" for a in alert_rows):
        top_level = "⚠ 警告"
    elif alert_rows:
        top_level = "提醒"

    severity = {"提醒": 1, "警告": 2, "严重": 3}
    chronological = list(reversed(all_alert_rows))
    for index, row in enumerate(chronological):
        previous = chronological[index - 1] if index else None
        if previous is None:
            row["change_type"] = "首次预警"
        elif row["rule_id"] == previous["rule_id"]:
            row["change_type"] = "持续预警"
        elif severity.get(row["level"], 0) > severity.get(previous["level"], 0):
            row["change_type"] = "风险升级"
        elif severity.get(row["level"], 0) < severity.get(previous["level"], 0):
            row["change_type"] = "风险缓解"
        else:
            row["change_type"] = "类型变化"
    intervention_rows = dbm.query(conn, """
        SELECT e.event_id,a.type,a.level,f.operator,f.action_type,f.content,
               f.next_action_at,f.created_at
        FROM alert_event e JOIN fact_alert a ON a.alert_id=e.alert_id
        JOIN alert_followup f ON f.event_id=e.event_id
        WHERE e.student_id=? ORDER BY f.created_at DESC,f.followup_id DESC""", (sid,))
    status_rows = dbm.query(conn, """
        SELECT e.event_id,a.type,a.level,h.from_status,h.to_status,h.operator,
               h.reason,h.changed_at
        FROM alert_event e JOIN fact_alert a ON a.alert_id=e.alert_id
        JOIN alert_status_history h ON h.event_id=e.event_id
        WHERE e.student_id=? ORDER BY h.changed_at DESC,h.history_id DESC""", (sid,))
    alert_comparison = {
        "totalCycles": len(all_alert_rows), "activeAlerts": len(alert_rows),
        "firstDetectedAt": chronological[0]["time"] if chronological else None,
        "latestDetectedAt": all_alert_rows[0]["time"] if all_alert_rows else None,
        "latestChange": all_alert_rows[0].get("change_type") if all_alert_rows else "无预警",
        "interventionCount": len(intervention_rows),
    }

    kpis = [
        {"label": "当前GPA", "value": f"{cur_gpa:.2f}", "formula": "最新学期平均绩点",
         "color": "#DC2626" if cur_gpa < 2 else "#16A34A", "sub": "5分制"},
        {"label": "已修学分", "value": f"{earned:.0f}", "formula": "已通过课程学分合计",
         "color": "#2563EB", "sub": ""},
        {"label": "预警状态", "value": top_level, "formula": "当前最高预警等级",
         "color": "#DC2626" if "严重" in top_level else "#EA580C", "sub": f"{len(alert_rows)}条预警"},
        {"label": "在读年级", "value": f"{st['grade']}级" if st["grade"] else "—",
         "formula": "入学年级", "color": "#6B7280", "sub": st["major"] or ""},
    ]

    scores = []
    for r in dbm.query(conn, """
        SELECT g.semester_id, g.course_id, g.score, g.gpa, g.is_pass,
               g.is_retake, g.exam_status, co.name cname
        FROM fact_grade g LEFT JOIN dim_course co ON g.course_id=co.course_id
        WHERE g.student_id=? ORDER BY g.semester_id DESC, g.score ASC""", (sid,)):
        scores.append({
            "semester": r["semester_id"], "courseCode": r["course_id"],
            "courseName": r["cname"] or r["course_id"], "score": r["score"],
            "gp": r["gpa"], "passed": bool(r["is_pass"]),
            "takeType": "重修" if r["is_retake"] == 1 else "正常",
            "examStatus": r["exam_status"] or "正常",
        })

    # V1.1：挂科溯源——关联教师和开课学院
    fail_trace = []
    for r in dbm.query(conn, """
        SELECT g.course_id, co.name cname, co.dept college,
               t.name tname, COUNT(*) fc,
               GROUP_CONCAT(DISTINCT g.semester_id) semesters
        FROM fact_grade g
        LEFT JOIN dim_course co ON g.course_id=co.course_id
        LEFT JOIN fact_lesson l ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
        LEFT JOIN dim_teacher t ON l.teacher_id=t.teacher_id
        WHERE g.student_id=? AND g.is_pass=0
        GROUP BY g.course_id ORDER BY fc DESC
    """, (sid,)):
        sem_list = sorted(set((r["semesters"] or "").split(",")))
        fail_trace.append({
            "courseName": r["cname"] or r["course_id"],
            "teacherName": r["tname"] or "—",
            "college": r["college"] or "—",
            "failCount": r["fc"],
            "semesters": sem_list,
        })

    # V1.1：逐学期摘要
    semester_summary = []
    for r in dbm.query(conn, """
        SELECT semester_id,
               AVG(gpa) gpa,
               SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) fail_count,
               SUM(CASE WHEN is_pass=1 THEN credits ELSE 0 END) earned
        FROM fact_grade WHERE student_id=? AND gpa IS NOT NULL
        GROUP BY semester_id ORDER BY semester_id
    """, (sid,)):
        semester_summary.append({
            "semester": r["semester_id"],
            "gpa": round(r["gpa"], 2) if r["gpa"] is not None else 0,
            "failCount": r["fail_count"] or 0,
            "earnedCredits": round(r["earned"] or 0, 1),
        })

    # V1.1：学业统计摘要（已修 vs 挂科 双栏对比）
    total_req = dbm.scalar(conn,
        "SELECT total_req FROM fact_major_req WHERE major_id=?",
        (st["major_id"] if "major_id" in st else None,)) or 0
    earned_credits = dbm.scalar(conn,
        "SELECT SUM(credits) FROM fact_grade WHERE student_id=? AND is_pass=1",
        (sid,)) or 0
    study_summary = {
        "passed": {
            "courses": dbm.scalar(conn,
                "SELECT COUNT(*) FROM fact_grade WHERE student_id=? AND score IS NOT NULL",
                (sid,)) or 0,
            "hours": round((dbm.scalar(conn,
                "SELECT SUM(credits*16) FROM fact_grade WHERE student_id=? AND score IS NOT NULL",
                (sid,)) or 0), 1),
            "credits": round(earned_credits, 1),
            "completionRate": round(earned_credits / total_req * 100, 1) if total_req else 0,
        },
        "failed": {
            "courses": dbm.scalar(conn,
                "SELECT COUNT(DISTINCT course_id) FROM fact_grade WHERE student_id=? AND is_pass=0",
                (sid,)) or 0,
            "hours": round((dbm.scalar(conn,
                "SELECT SUM(credits*16) FROM fact_grade WHERE student_id=? AND is_pass=0",
                (sid,)) or 0), 1),
            "credits": round((dbm.scalar(conn,
                "SELECT SUM(credits) FROM fact_grade WHERE student_id=? AND is_pass=0",
                (sid,)) or 0), 1),
            "currentCourses": dbm.scalar(conn,
                "SELECT COUNT(DISTINCT course_id) FROM fact_grade WHERE student_id=? AND is_pass=0 AND semester_id=?",
                (sid, CUR)) or 0,
        },
    }

    return ok({
        "code": st["student_id"], "name": st["name"], "collegeId": st["college_id"],
        "collegeName": st["college"], "majorName": st["major"], "className": st["cls"],
        "enrollOn": st["enroll_on"], "kpis": kpis, "gpaHistory": gpa_hist,
        "alertHistory": [{"alertId": a["alert_id"], "eventId": a["event_id"],
                          "level": a["level"], "type": a["type"], "detail": a["detail"],
                          "time": a["time"], "active": bool(a["is_active"]),
                          "changeType": a.get("change_type"),
                          "workflowStatus": a["workflow_status"],
                          "workflowStatusLabel": WORKFLOW_LABELS.get(a["workflow_status"], a["workflow_status"])
                          } for a in all_alert_rows],
        "alertComparison": alert_comparison,
        "interventionHistory": [{**row, "kind": "followup"} for row in intervention_rows],
        "alertStatusHistory": [{**row, "kind": "status",
                                "fromStatusLabel": WORKFLOW_LABELS.get(row["from_status"], row["from_status"]),
                                "toStatusLabel": WORKFLOW_LABELS.get(row["to_status"], row["to_status"])}
                               for row in status_rows],
        "scores": scores,
        "failTrace": fail_trace,
        "semesterSummary": semester_summary,
        "studySummary": study_summary,
    })

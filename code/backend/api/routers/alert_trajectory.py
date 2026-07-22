"""M5：同类预警后续轨迹分布（历史统计，不做个体预测）。

GET /api/admin/alerts/trajectory?rule_id=&level=

口径（固定披露）：
- 观察点 = 预警记录（fact_alert，含已关闭记录），按 规则×等级 分桶；
- T = 预警发生学期（fact_alert.semester_id）；后续观察学期 = 该生 T 之后
  最新一个有成绩的学期；T 之后无成绩学期的观察点计入"待观察"，
  不进入 GPA 变化 / 新增未通过 / 风险升级统计；
- GPA = 学期平均绩点（fact_grade.gpa 算术平均）；
  GPA 变化分档：上升 > +0.05、下降 < -0.05、其余持平；
- 新增未通过 = 后续学期未通过且 T 学期未未通过的课程门数（按成绩记录计）；
- 风险升级 = T 之后学期出现同级或更高等级的新预警；
- 解除占比 = 预警事件工作流状态 resolved/closed（无事件时回退 fact_alert.status）；
- 毕业结果优先取 V2 真实毕业去向（source=real），缺失时取演示库合成数据
  （source=sim）并按来源分别计数；
- 样本量 < 10 的桶标记 low_confidence=true。

边界：只做历史统计分布，不构成对任何个体学生的预测；不引入模型。
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user, student_data_scope
from ..envelope import ok
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin", tags=["alert-trajectory"])

SEVERITY = {"提醒": 1, "警告": 2, "严重": 3}
GPA_DELTA_BAND = 0.05
LOW_CONFIDENCE_SAMPLE = 10
RESOLVED_STATUSES = ("resolved", "closed")
RESOLVED_ALERT_LABELS = ("已解决", "已关闭")

DISCLAIMER = "历史统计分布，不构成个体预测"

METHODOLOGY_TEXT = (
    "观察点为预警记录（fact_alert，含已关闭记录），按 规则×等级 分桶；"
    "T 为预警发生学期（fact_alert.semester_id）。"
    "后续观察学期取该生 T 之后最新一个有成绩的学期；"
    "T 之后无任何成绩学期的观察点计入“待观察”，不进入 GPA 变化、新增未通过与风险升级统计"
    "（当前学期发生的预警通常处于待观察状态）。"
    "GPA 为学期平均绩点（fact_grade.gpa 算术平均）；"
    "GPA 变化 = 后续学期 GPA − T 学期 GPA，分档：上升 > +0.05、下降 < −0.05、其余持平。"
    "新增未通过 = 后续学期未通过且 T 学期未未通过的课程门数（按成绩记录计）。"
    "风险升级 = T 之后学期出现同级或更高等级的新预警。"
    "解除占比按预警事件工作流状态 resolved/closed 计（无事件时回退预警记录状态）。"
    "毕业结果优先取 V2 真实毕业去向（source=real），缺失时取演示库合成数据（source=sim），"
    "按来源分别计数且仅统计有毕业结果数据的学生子集。"
    "样本量 < 10 的桶标记为低置信（low_confidence）。"
    "本接口只提供历史统计分布，不构成对任何个体学生的预测。"
)


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


def compute_trajectory(conn: sqlite3.Connection, v2_conn: sqlite3.Connection,
                       scope_sql: str = "", scope_params: Optional[list] = None,
                       rule_id: Optional[str] = None,
                       level: Optional[str] = None) -> dict:
    """按桶计算同类轨迹分布。scope_sql 为 "" 或 " AND <片段>"（别名 st）。"""
    scope_params = list(scope_params or [])
    conds, params = [], []
    if rule_id:
        conds.append("a.rule_id=?"); params.append(rule_id)
    if level:
        conds.append("a.level=?"); params.append(level)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    if scope_sql:
        where = (where + scope_sql) if where else (" WHERE 1=1" + scope_sql)

    observations = dbm.query(conn, f"""
        SELECT a.alert_id, a.student_id, a.rule_id, a.level, a.semester_id,
               a.status alert_status, a.created_at,
               COALESCE(e.workflow_status,'') workflow_status
        FROM fact_alert a
        JOIN dim_student st ON st.student_id = a.student_id
        LEFT JOIN alert_event e ON e.alert_id = a.alert_id
        {where}""", tuple(params + scope_params))

    rule_names = {r["rule_id"]: r["name"] for r in dbm.query(
        conn, "SELECT rule_id, name FROM sys_alert_rule")}

    students = sorted({o["student_id"] for o in observations})
    sem_gpa: dict[tuple[str, str], float] = {}
    sem_fails: dict[tuple[str, str], set] = {}
    student_sems: dict[str, list[str]] = {}
    later_alerts: dict[str, list[dict]] = {}
    grad_status: dict[str, tuple[str, str]] = {}  # sid -> (status, source)
    if students:
        ph = _placeholders(len(students))
        for r in dbm.query(conn, f"""
            SELECT student_id, semester_id, AVG(gpa) gpa
            FROM fact_grade
            WHERE gpa IS NOT NULL AND student_id IN ({ph})
            GROUP BY student_id, semester_id""", tuple(students)):
            sem_gpa[(r["student_id"], r["semester_id"])] = r["gpa"]
        for r in dbm.query(conn, f"""
            SELECT student_id, semester_id, course_id
            FROM fact_grade
            WHERE is_pass=0 AND student_id IN ({ph})""", tuple(students)):
            sem_fails.setdefault((r["student_id"], r["semester_id"]), set()).add(r["course_id"])
        for r in dbm.query(conn, f"""
            SELECT DISTINCT student_id, semester_id FROM fact_grade
            WHERE student_id IN ({ph})""", tuple(students)):
            student_sems.setdefault(r["student_id"], []).append(r["semester_id"])
        for sems in student_sems.values():
            sems.sort()
        for r in dbm.query(conn, f"""
            SELECT alert_id, student_id, level, semester_id
            FROM fact_alert WHERE student_id IN ({ph})""", tuple(students)):
            later_alerts.setdefault(r["student_id"], []).append(r)
        # 毕业结果：V2 真实数据优先，legacy 合成数据兜底（来源分别计数）
        try:
            for r in dbm.query(v2_conn, f"""
                SELECT student_id, graduation_status
                FROM graduation_outcome WHERE student_id IN ({ph})""", tuple(students)):
                if r["graduation_status"]:
                    grad_status[r["student_id"]] = (r["graduation_status"], "real")
        except sqlite3.Error:
            pass  # V2 库缺表时退化为仅 legacy 合成数据
        remaining = [s for s in students if s not in grad_status]
        if remaining:
            ph2 = _placeholders(len(remaining))
            for r in dbm.query(conn, f"""
                SELECT student_id, grad_status FROM fact_graduation
                WHERE student_id IN ({ph2})""", tuple(remaining)):
                if r["grad_status"]:
                    grad_status[r["student_id"]] = (r["grad_status"], "sim")

    buckets: dict[tuple[str, str], list[dict]] = {}
    for o in observations:
        buckets.setdefault((o["rule_id"], o["level"]), []).append(o)

    out_buckets = []
    for (rid, lv), obs in sorted(
            buckets.items(),
            key=lambda kv: (-SEVERITY.get(kv[0][1], 0), kv[0][0])):
        out_buckets.append(_bucket_stats(
            rid, lv, obs, rule_names, sem_gpa, sem_fails,
            student_sems, later_alerts, grad_status))

    created = [o["created_at"] for o in observations if o["created_at"]]
    semesters = [r["semester_id"] for r in dbm.query(
        conn, "SELECT DISTINCT semester_id FROM fact_grade ORDER BY semester_id")]
    return {
        "filters": {"ruleId": rule_id or "", "level": level or ""},
        "methodology": {
            "text": METHODOLOGY_TEXT,
            "disclaimer": DISCLAIMER,
            "thresholds": {"gpaDeltaBand": GPA_DELTA_BAND,
                           "lowConfidenceSample": LOW_CONFIDENCE_SAMPLE},
            "dataRange": {
                "alertCreatedAt": {"min": min(created) if created else None,
                                   "max": max(created) if created else None},
                "gradeSemesters": {"first": semesters[0] if semesters else None,
                                   "last": semesters[-1] if semesters else None},
                "currentSemester": CURRENT_SEMESTER,
            },
        },
        "buckets": out_buckets,
    }


def _bucket_stats(rid, lv, obs, rule_names, sem_gpa, sem_fails,
                  student_sems, later_alerts, grad_status) -> dict:
    sample = len(obs)
    resolved = sum(
        1 for o in obs
        if (o["workflow_status"] in RESOLVED_STATUSES)
        or (not o["workflow_status"] and o["alert_status"] in RESOLVED_ALERT_LABELS))

    observable = pending = 0
    gpa_up = gpa_flat = gpa_down = gpa_unknown = 0
    deltas: list[float] = []
    fail_zero = fail_one = fail_two_plus = 0
    escalate = 0
    bucket_sev = SEVERITY.get(lv, 0)

    for o in obs:
        sid, t_sem = o["student_id"], o["semester_id"]
        later = [s for s in student_sems.get(sid, []) if t_sem and s > t_sem]
        if not later:
            pending += 1
            continue
        observable += 1
        t_obs = later[-1]
        g_t = sem_gpa.get((sid, t_sem))
        g_obs = sem_gpa.get((sid, t_obs))
        if g_t is None or g_obs is None:
            gpa_unknown += 1
        else:
            delta = g_obs - g_t
            deltas.append(delta)
            if delta > GPA_DELTA_BAND:
                gpa_up += 1
            elif delta < -GPA_DELTA_BAND:
                gpa_down += 1
            else:
                gpa_flat += 1
        new_fails = len(sem_fails.get((sid, t_obs), set())
                        - sem_fails.get((sid, t_sem), set()))
        if new_fails == 0:
            fail_zero += 1
        elif new_fails == 1:
            fail_one += 1
        else:
            fail_two_plus += 1
        for o2 in later_alerts.get(sid, []):
            if (o2["alert_id"] != o["alert_id"] and o2["semester_id"]
                    and o2["semester_id"] > t_sem
                    and SEVERITY.get(o2["level"], 0) >= bucket_sev):
                escalate += 1
                break

    gpa_valid = len(deltas)
    grad_dist: dict[str, int] = {}
    grad_sources = {"real": 0, "sim": 0}
    for sid in {o["student_id"] for o in obs}:
        entry = grad_status.get(sid)
        if not entry:
            continue
        status, source = entry
        grad_dist[status] = grad_dist.get(status, 0) + 1
        grad_sources[source] = grad_sources.get(source, 0) + 1
    grad_sample = sum(grad_dist.values())

    return {
        "ruleId": rid, "ruleName": rule_names.get(rid, rid), "level": lv,
        "sampleSize": sample,
        "studentCount": len({o["student_id"] for o in obs}),
        "lowConfidence": sample < LOW_CONFIDENCE_SAMPLE,
        "resolved": {"count": resolved, "ratio": _ratio(resolved, sample)},
        "post": {
            "observable": observable, "pending": pending,
            "gpaDelta": {
                "valid": gpa_valid, "unknown": gpa_unknown,
                "mean": round(sum(deltas) / gpa_valid, 2) if gpa_valid else None,
                "up": gpa_up, "flat": gpa_flat, "down": gpa_down,
                "upRatio": _ratio(gpa_up, gpa_valid),
                "flatRatio": _ratio(gpa_flat, gpa_valid),
                "downRatio": _ratio(gpa_down, gpa_valid),
            },
            "newFail": {
                "zero": fail_zero, "one": fail_one, "twoPlus": fail_two_plus,
                "zeroRatio": _ratio(fail_zero, observable),
                "oneRatio": _ratio(fail_one, observable),
                "twoPlusRatio": _ratio(fail_two_plus, observable),
            },
            "escalate": {"count": escalate,
                         "ratio": _ratio(escalate, observable)},
        },
        "gradOutcome": {
            "sample": grad_sample,
            "sourceCounts": grad_sources,
            "dist": [{"status": s, "count": n,
                      "ratio": _ratio(n, grad_sample)}
                     for s, n in sorted(grad_dist.items(),
                                        key=lambda kv: -kv[1])],
        },
    }


@router.get("/alerts/trajectory")
def alerts_trajectory(rule_id: Optional[str] = None, level: Optional[str] = None,
                      user: dict = Depends(get_current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    frag, params = student_data_scope(user, conn, "st")
    scope_sql = f" AND {frag}" if frag else ""
    v2_conn = dbm.get_v2_conn()
    try:
        data = compute_trajectory(conn, v2_conn, scope_sql, params,
                                  rule_id=rule_id, level=level)
    finally:
        v2_conn.close()
    return ok(data)

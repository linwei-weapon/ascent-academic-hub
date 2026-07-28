"""数据大屏组：dashboard / college / major / course。
学籍、成绩、课程、教师与预警来自分析库真实数据；毕业、学位与就业去向来自
固定种子合成业务表并在接口和页面显式披露。默认学期为 CURRENT_SEMESTER。
"""
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query

from .. import db as dbm
from ..academic_metrics import (
    per_student_weighted_gpa,
    term_grade_and_failed_students,
    weighted_gpa_expression,
)
from ..deps import get_db, get_current_user, student_data_scope
from ..envelope import ok, ApiError
from ..historical_roster import SEMESTERS, read_historical_roster
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin", tags=["dashboard"])

CUR = CURRENT_SEMESTER
# 数据为 5 分制绩点，当前真实记录最大值 4.5；最高档使用开放区间，避免“3.5-4.0”误导。
_GPA_BANDS = [("<2.0", "<2.0", 0.0), ("2.0-2.5", "2.0-2.5", 2.0),
              ("2.5-3.0", "2.5-3.0", 2.5), ("3.0-3.5", "3.0-3.5", 3.0),
              ("3.5-4.0", "≥3.5", 3.5)]
_DASHBOARD_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_DASHBOARD_CACHE_TTL_SECONDS = 90
_METRIC_HISTORY_CACHE: dict[tuple, tuple[float, dict]] = {}
_METRIC_HISTORY_CACHE_TTL_SECONDS = 90

_HISTORY_METRICS = {
    "valid_result_coverage_rate": {
        "label": "有效成绩覆盖率",
        "unit": "%",
        "formula": "所选学期至少一条真实有效成绩的去重学生数÷对应学期范围内在籍学生数",
        "numeratorLabel": "有效成绩覆盖人数",
        "denominatorLabel": "在籍学生数",
        "betterDirection": "up",
        "chart": "ratio",
        "source": "各学期源库 students + analytics.sqlite fact_grade",
    },
    "current_fail_student_rate": {
        "label": "挂科学生率",
        "unit": "%",
        "formula": "所选学期至少一门未通过的去重学生数÷所选学期有真实有效成绩的去重学生数",
        "numeratorLabel": "挂科学生数",
        "denominatorLabel": "有效成绩学生数",
        "betterDirection": "down",
        "chart": "ratio",
        "source": "analytics.sqlite fact_grade",
    },
    "average_student_gpa": {
        "label": "学生平均 GPA",
        "unit": "",
        "formula": "先按学生计算所选学期课程学分加权 GPA，再对有 GPA 的学生求算术平均",
        "numeratorLabel": "有 GPA 学生数",
        "denominatorLabel": "在籍学生数",
        "betterDirection": "up",
        "chart": "gpa",
        "source": "analytics.sqlite fact_grade",
    },
    "active_alert_student_rate": {
        "label": "有效预警学生率",
        "unit": "%",
        "formula": "所选学期真实有效预警去重学生数÷对应学期范围内在籍学生数",
        "numeratorLabel": "有效预警学生数",
        "denominatorLabel": "在籍学生数",
        "betterDirection": "down",
        "chart": "ratio",
        "source": "analytics.sqlite fact_alert；无真实历史记录的学期不回算",
    },
    "first_pass_rate": {
        "label": "首次通过率",
        "unit": "%",
        "formula": "首次修读通过人次÷首次修读有效人次",
        "numeratorLabel": "首次通过人次",
        "denominatorLabel": "首次修读人次",
        "betterDirection": "up",
        "chart": "ratio",
        "source": "analytics_v2.sqlite grade_attempt/agg_course_pass_stat",
    },
    "makeup_pass_rate": {
        "label": "补考通过率",
        "unit": "%",
        "formula": "补考通过人次÷补考有效人次",
        "numeratorLabel": "补考通过人次",
        "denominatorLabel": "补考人次",
        "betterDirection": "up",
        "chart": "ratio",
        "source": "analytics_v2.sqlite grade_attempt/agg_course_pass_stat",
    },
    "retake_pass_rate": {
        "label": "重修通过率",
        "unit": "%",
        "formula": "重修通过人次÷重修有效人次",
        "numeratorLabel": "重修通过人次",
        "denominatorLabel": "重修人次",
        "betterDirection": "up",
        "chart": "ratio",
        "source": "analytics_v2.sqlite grade_attempt/agg_course_pass_stat",
    },
    "public_required_first_pass_rate": {
        "label": "公共必修首次通过率",
        "unit": "%",
        "formula": "公共必修课程首次修读通过人次÷公共必修课程首次修读有效人次",
        "numeratorLabel": "首次通过人次",
        "denominatorLabel": "首次修读人次",
        "betterDirection": "up",
        "chart": "ratio",
        "source": "analytics_v2.sqlite grade_attempt/agg_course_pass_stat",
    },
}


def _pct(x, nd=1):
    return f"{round((x or 0) * 100, nd)}%"


def _pct_value(numerator, denominator, nd=1):
    """可展示百分比；分母为空时返回“—”，不把无数据伪装成 0%。"""
    if not denominator:
        return "—"
    return f"{round((numerator or 0) * 100 / denominator, nd)}%"


def _pct_number(numerator, denominator, nd=1):
    """数值百分比；分母为空时返回 None。"""
    return round((numerator or 0) * 100 / denominator, nd) if denominator else None


def _gpa_bucket(value: float) -> str:
    for bucket, _, lower in reversed(_GPA_BANDS):
        if value >= lower:
            return bucket
    return "<2.0"


def _rate(passed, attempts):
    """百分数通过率（1位小数）；分母为0或None时返回None，不落0。"""
    return round(passed * 100.0 / attempts, 1) if attempts else None


def _v2_pass_stats(semester: str, student_ids: Optional[list[str]] = None):
    """读取所选学期的 V2 课程通过率三分层。

    V2 库或聚合表缺失时返回 None：总览其余指标仍走 V1 正常输出，
    三分层字段输出 None 并在 coursePassRates.source 中说明，不静默混用口径。

    全校范围直接读取课程×学期聚合表；受限范围按授权学生从 grade_attempt
    重新聚合，确保学院、班级和导师身份不会看到或引用全校通过率。
    """
    try:
        conn = dbm.get_v2_conn()
    except Exception:
        return None
    try:
        if not dbm.scalar(conn, """SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='agg_course_pass_stat'"""):
            return None
        groups = {r["course_id"]: r["course_group"] for r in dbm.query(conn, """
            SELECT course_id,MAX(course_group) course_group
            FROM agg_course_pass_stat WHERE semester_id=? GROUP BY course_id
        """, (semester,))}
        if student_ids is None:
            courses = {r["course_id"]: r for r in dbm.query(conn, """
                SELECT course_id, MAX(course_group) course_group,
                  SUM(first_attempts) fa, SUM(first_pass) fp,
                  SUM(makeup_attempts) ma, SUM(makeup_pass) mp,
                  SUM(retake_attempts) ra, SUM(retake_pass) rp
                FROM agg_course_pass_stat WHERE semester_id=? GROUP BY course_id
            """, (semester,))}
        else:
            courses = {}
            ids = sorted({sid for sid in student_ids if sid})
            # 单批不超过 800，兼容 SQLite 变量数量限制。
            for start in range(0, len(ids), 800):
                batch = ids[start:start + 800]
                marks = ",".join("?" * len(batch))
                for row in dbm.query(conn, f"""
                    SELECT course_id,
                      SUM(CASE WHEN attempt_type IS NULL OR attempt_type NOT IN ('makeup','retake')
                          THEN 1 ELSE 0 END) fa,
                      SUM(CASE WHEN (attempt_type IS NULL OR attempt_type NOT IN ('makeup','retake'))
                          AND is_pass=1 THEN 1 ELSE 0 END) fp,
                      SUM(CASE WHEN attempt_type='makeup' THEN 1 ELSE 0 END) ma,
                      SUM(CASE WHEN attempt_type='makeup' AND is_pass=1 THEN 1 ELSE 0 END) mp,
                      SUM(CASE WHEN attempt_type='retake' THEN 1 ELSE 0 END) ra,
                      SUM(CASE WHEN attempt_type='retake' AND is_pass=1 THEN 1 ELSE 0 END) rp
                    FROM grade_attempt
                    WHERE semester_id=? AND is_published=1 AND is_void=0
                      AND is_pass IS NOT NULL AND student_id IN ({marks})
                    GROUP BY course_id
                """, tuple([semester] + batch)):
                    current = courses.setdefault(row["course_id"], {
                        "course_id": row["course_id"],
                        "course_group": groups.get(row["course_id"], "其他"),
                        "fa": 0, "fp": 0, "ma": 0, "mp": 0, "ra": 0, "rp": 0,
                    })
                    for key in ("fa", "fp", "ma", "mp", "ra", "rp"):
                        current[key] += row[key] or 0
        overall = {
            key: sum((row.get(key) or 0) for row in courses.values())
            for key in ("fa", "fp", "ma", "mp", "ra", "rp")
        }
        public_courses = [
            row for row in courses.values()
            if row.get("course_group") == "公共必修"
        ]
        public = {
            "fa": sum((row.get("fa") or 0) for row in public_courses),
            "fp": sum((row.get("fp") or 0) for row in public_courses),
        }
        return {"courses": courses, "overall": overall, "public_required": public}
    except Exception:
        return None
    finally:
        conn.close()


def _apply_kpi_config(conn: sqlite3.Connection, kpis: list[dict]) -> tuple[list[dict], bool]:
    """Apply display-only governance to registered dashboard KPIs.

    Missing rows keep their built-in defaults so a partial or legacy database never
    makes a valid KPI disappear unexpectedly.
    """
    exists = dbm.scalar(conn, """SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='sys_kpi_config'""")
    if not exists:
        return kpis, False
    rows = dbm.query(conn, """SELECT kpi_id,enabled,sort_order,color_rule,
        threshold_warn,threshold_danger FROM sys_kpi_config
        WHERE module='dashboard'""")
    config = {row["kpi_id"]: row for row in rows}
    shaped = []
    for default_order, item in enumerate(kpis, start=1):
        row = config.get(item["id"])
        if row and not bool(row["enabled"]):
            continue
        current = dict(item)
        current["sortOrder"] = row["sort_order"] if row else default_order
        if row:
            current["colorRule"] = row["color_rule"]
            current["thresholdWarn"] = row["threshold_warn"]
            current["thresholdDanger"] = row["threshold_danger"]
        shaped.append(current)
    shaped.sort(key=lambda item: (item["sortOrder"], item["id"]))
    return shaped, True


def _authorized_student_ids(
    conn: sqlite3.Connection,
    user: dict,
) -> Optional[list[str]]:
    scope, params = student_data_scope(user, conn, "s")
    if not scope:
        return None
    return [
        row["student_id"]
        for row in dbm.query(
            conn,
            f"SELECT s.student_id FROM dim_student s WHERE {scope}",
            tuple(params),
        )
    ]


def _current_analytics_roster(
    conn: sqlite3.Connection,
    *,
    scope_type: str,
    scope_id: Optional[str],
    authorized_student_ids: Optional[list[str]],
) -> dict:
    """当前统计学期沿用总览卡片的 dim_student 分母。

    历史学期仍读取只读学期源库；当前点必须与总览当前卡使用同一名单，
    避免同一个指标在卡片与趋势最后一点出现不同分母。
    """
    conditions: list[str] = []
    params: list[str] = []
    if scope_type == "college":
        conditions.append("s.college_id=?")
        params.append(str(scope_id))
    elif scope_type == "major":
        conditions.append("s.major_id=?")
        params.append(str(scope_id))
    sql = "SELECT s.student_id FROM dim_student s"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY s.student_id"
    source_ids = [
        str(row["student_id"])
        for row in dbm.query(conn, sql, tuple(params))
    ]
    authorized = (
        None
        if authorized_student_ids is None
        else {str(value) for value in authorized_student_ids}
    )
    student_ids = [
        student_id for student_id in source_ids
        if authorized is None or student_id in authorized
    ]
    return {
        "semester": CUR,
        "studentIds": student_ids,
        "students": [],
        "scopeLabel": _scope_label(
            conn,
            scope_type,
            scope_id,
            authorized_student_ids is not None,
        ),
        "available": True,
        "status": "available",
        "unavailableReason": None,
        "source": "analytics_v1.sqlite/dim_student（当前统计学期）",
        "mapping": {
            "matched": len(student_ids),
            "sourceRows": len(source_ids),
            "excludedByAuthorization": len(source_ids) - len(student_ids),
            "currentCardAligned": True,
        },
    }


def _scope_label(
    conn: sqlite3.Connection,
    scope_type: str,
    scope_id: Optional[str],
    restricted: bool,
) -> str:
    if scope_type == "school":
        return "当前身份授权范围" if restricted else "全校"
    table, id_field = (
        ("dim_college", "college_id")
        if scope_type == "college"
        else ("dim_major", "major_id")
    )
    label = dbm.scalar(
        conn,
        f"SELECT name FROM {table} WHERE {id_field}=?",
        (scope_id,),
    )
    if not label:
        raise ApiError(
            "学院不存在" if scope_type == "college" else "专业不存在",
            code=404,
            status_code=404,
        )
    return label


def _assert_history_scope_allowed(
    conn: sqlite3.Connection,
    user: dict,
    scope_type: str,
    scope_id: Optional[str],
) -> None:
    if scope_type == "school":
        return
    scope, params = student_data_scope(user, conn, "s")
    field = "college_id" if scope_type == "college" else "major_id"
    conditions = [f"s.{field}=?"]
    values: list = [scope_id]
    if scope:
        conditions.append(scope)
        values.extend(params)
    allowed = dbm.scalar(
        conn,
        "SELECT 1 FROM dim_student s WHERE "
        + " AND ".join(conditions)
        + " LIMIT 1",
        tuple(values),
    )
    if not allowed:
        raise ApiError("无权限查看该统计范围", code=403, status_code=403)


def _active_alert_students(
    conn: sqlite3.Connection,
    student_ids: list[str],
    semester: str,
) -> int:
    if not student_ids:
        return 0
    matched: set[str] = set()
    for start in range(0, len(student_ids), 800):
        chunk = student_ids[start:start + 800]
        placeholders = ",".join("?" * len(chunk))
        rows = dbm.query(conn, f"""
            SELECT DISTINCT student_id FROM fact_alert
            WHERE semester_id=? AND COALESCE(is_active,1)=1
              AND student_id IN ({placeholders})
        """, tuple([semester] + chunk))
        matched.update(row["student_id"] for row in rows)
    return len(matched)


def _metric_period_value(
    conn: sqlite3.Connection,
    metric_id: str,
    semester: str,
    roster: dict,
    *,
    unrestricted_school: bool,
) -> dict:
    if not roster["available"]:
        return {
            "value": None,
            "numerator": None,
            "denominator": None,
            "sampleCount": 0,
            "status": "unavailable",
            "unavailableReason": roster["unavailableReason"],
        }
    student_ids = roster["studentIds"]
    if not student_ids:
        return {
            "value": None,
            "numerator": 0,
            "denominator": 0,
            "sampleCount": 0,
            "status": "insufficient",
            "unavailableReason": "该学期与当前授权范围没有可统计学生",
        }
    if metric_id in {
        "valid_result_coverage_rate",
        "current_fail_student_rate",
    }:
        graded, failed = term_grade_and_failed_students(
            conn, student_ids, semester
        )
        if metric_id == "valid_result_coverage_rate":
            numerator, denominator = len(graded), len(student_ids)
        else:
            numerator, denominator = len(failed), len(graded)
        return {
            "value": _pct_number(numerator, denominator),
            "numerator": numerator,
            "denominator": denominator,
            "sampleCount": denominator,
            "status": "available" if denominator else "insufficient",
            "unavailableReason": (
                None if denominator else "该学期没有真实有效成绩"
            ),
        }
    if metric_id == "average_student_gpa":
        gpa_map = per_student_weighted_gpa(conn, student_ids, [semester])
        values = [float(value) for value in gpa_map.values()]
        return {
            "value": round(sum(values) / len(values), 2) if values else None,
            "numerator": len(values),
            "denominator": len(student_ids),
            "sampleCount": len(values),
            "status": "available" if values else "insufficient",
            "unavailableReason": (
                None if values else "该学期没有可计算 GPA 的真实有效成绩"
            ),
        }
    if metric_id == "active_alert_student_rate":
        has_period_data = bool(dbm.scalar(
            conn,
            "SELECT 1 FROM fact_alert WHERE semester_id=? LIMIT 1",
            (semester,),
        ))
        if not has_period_data:
            return {
                "value": None,
                "numerator": None,
                "denominator": len(student_ids),
                "sampleCount": 0,
                "status": "unavailable",
                "unavailableReason": "该学期没有真实预警快照，不按当前规则回算",
            }
        numerator = _active_alert_students(conn, student_ids, semester)
        return {
            "value": _pct_number(numerator, len(student_ids)),
            "numerator": numerator,
            "denominator": len(student_ids),
            "sampleCount": len(student_ids),
            "status": "available",
            "unavailableReason": None,
        }

    pass_stats = _v2_pass_stats(
        semester,
        None if unrestricted_school else student_ids,
    )
    if pass_stats is None:
        return {
            "value": None,
            "numerator": None,
            "denominator": None,
            "sampleCount": 0,
            "status": "unavailable",
            "unavailableReason": "V2 课程修读结果数据不可用",
        }
    overall = pass_stats.get("overall") or {}
    public = pass_stats.get("public_required") or {}
    numerator, denominator = {
        "first_pass_rate": (overall.get("fp"), overall.get("fa")),
        "makeup_pass_rate": (overall.get("mp"), overall.get("ma")),
        "retake_pass_rate": (overall.get("rp"), overall.get("ra")),
        "public_required_first_pass_rate": (
            public.get("fp"), public.get("fa")
        ),
    }[metric_id]
    numerator, denominator = int(numerator or 0), int(denominator or 0)
    return {
        "value": _rate(numerator, denominator),
        "numerator": numerator,
        "denominator": denominator,
        "sampleCount": denominator,
        "status": "available" if denominator else "insufficient",
        "unavailableReason": (
            None if denominator else "该学期没有对应类型的有效修读记录"
        ),
    }


@router.get("/dashboard/metric-history")
def metric_history(
    metric_id: str = Query(alias="metricId"),
    scope_type: str = Query(default="school", alias="scopeType"),
    scope_id: Optional[str] = Query(default=None, alias="scopeId"),
    start_semester: Optional[str] = Query(default=None, alias="startSemester"),
    end_semester: Optional[str] = Query(default=None, alias="endSemester"),
    conn: sqlite3.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """学校、学院和专业共用的历史指标只读查询。"""
    if metric_id not in _HISTORY_METRICS:
        raise ApiError("不支持的历史指标", code=400, status_code=400)
    if scope_type not in {"school", "college", "major"}:
        raise ApiError("scopeType 仅支持 school、college、major", code=400, status_code=400)
    if scope_type != "school" and not scope_id:
        raise ApiError("学院或专业范围必须提供 scopeId", code=400, status_code=400)
    start = start_semester or SEMESTERS[0]
    end = end_semester or SEMESTERS[-1]
    if start not in SEMESTERS or end not in SEMESTERS:
        raise ApiError("起止学期不在可用学期范围内", code=400, status_code=400)
    start_index, end_index = SEMESTERS.index(start), SEMESTERS.index(end)
    if start_index > end_index:
        raise ApiError("起始学期不能晚于结束学期", code=400, status_code=400)

    _assert_history_scope_allowed(conn, user, scope_type, scope_id)
    authorized_ids = _authorized_student_ids(conn, user)
    restricted = authorized_ids is not None
    permission_context = user.get("permission_context") or {}
    scope_fingerprint = (
        permission_context.get("scopeFingerprint")
        or f"{user.get('username', '')}:{user.get('role_id', '')}"
    )
    cache_key = (
        metric_id,
        scope_type,
        scope_id or "",
        start,
        end,
        scope_fingerprint,
    )
    cached = _METRIC_HISTORY_CACHE.get(cache_key)
    if (
        cached
        and time.monotonic() - cached[0] < _METRIC_HISTORY_CACHE_TTL_SECONDS
    ):
        return ok(cached[1])

    periods = []
    previous_value = None
    for semester_id in SEMESTERS[start_index:end_index + 1]:
        roster = (
            _current_analytics_roster(
                conn,
                scope_type=scope_type,
                scope_id=scope_id,
                authorized_student_ids=authorized_ids,
            )
            if semester_id == CUR
            else read_historical_roster(
                conn,
                semester_id,
                scope_type=scope_type,
                scope_id=scope_id,
                authorized_student_ids=authorized_ids,
                scope_fingerprint=scope_fingerprint,
            )
        )
        current = _metric_period_value(
            conn,
            metric_id,
            semester_id,
            roster,
            unrestricted_school=(scope_type == "school" and not restricted),
        )
        value = current["value"]
        comparison_previous_value = previous_value
        if (
            metric_id == "valid_result_coverage_rate"
            and semester_id == CUR
            and SEMESTERS.index(semester_id) > 0
            and roster["available"]
        ):
            previous_semester_id = SEMESTERS[
                SEMESTERS.index(semester_id) - 1
            ]
            previous_graded, _ = term_grade_and_failed_students(
                conn,
                roster["studentIds"],
                previous_semester_id,
            )
            comparison_previous_value = _pct_number(
                len(previous_graded),
                len(roster["studentIds"]),
            )
        change = (
            round(value - comparison_previous_value, 2)
            if value is not None and comparison_previous_value is not None
            else None
        )
        periods.append({
            "semester": semester_id,
            "semesterLabel": semester_id,
            **current,
            "change": change,
            "rosterSource": roster["source"],
            "mapping": roster["mapping"],
        })
        previous_value = value
    periods.reverse()

    definition = _HISTORY_METRICS[metric_id]
    payload = {
        "metricId": metric_id,
        "metric": definition,
        "scope": {
            "type": scope_type,
            "id": scope_id,
            "label": _scope_label(
                conn, scope_type, scope_id, restricted
            ),
            "restricted": restricted,
        },
        "query": {
            "startSemester": start,
            "endSemester": end,
        },
        "periods": periods,
        "availableSemesters": list(reversed(SEMESTERS)),
        "definitionVersion": "dashboard-history-v1",
        "boundary": (
            "历史学期在籍分母只读来自各学期源库；趋势中的当前统计学期使用"
            "总览卡片同一授权学籍名单；两类范围均与当前身份可见学生取交集。"
            "无真实历史预警快照的学期显示不可用，不使用当前规则或当前记录填补。"
        ),
    }
    _METRIC_HISTORY_CACHE[cache_key] = (time.monotonic(), payload)
    return ok(payload)


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
def dashboard(semester: Optional[str] = None,
              conn: sqlite3.Connection = Depends(get_db),
              user: dict = Depends(get_current_user)):
    cur = semester or CUR
    if not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)):
        raise ApiError("学期不存在", code=400, status_code=400)
    previous_semester = dbm.scalar(
        conn, "SELECT MAX(semester_id) FROM dim_semester WHERE semester_id<?", (cur,))
    permission_context = user.get("permission_context") or {}
    scope_fingerprint = (
        permission_context.get("scopeFingerprint")
        or f"{user.get('username', '')}:{permission_context.get('activeIdentityId', user.get('role_id', ''))}"
    )
    cache_key = (cur, scope_fingerprint)
    cached = _DASHBOARD_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _DASHBOARD_CACHE_TTL_SECONDS:
        return ok(cached[1])

    # 所有大屏指标统一使用同一学生授权范围，避免院级/专业/班级角色看到全校聚合。
    student_scope, scope_params = student_data_scope(user, conn, "s")
    student_where = f" WHERE {student_scope}" if student_scope else ""
    student_and = f" AND {student_scope}" if student_scope else ""
    restricted = bool(student_scope)
    scoped_student_ids = (
        [row["student_id"] for row in dbm.query(
            conn, f"SELECT s.student_id FROM dim_student s{student_where}",
            tuple(scope_params))]
        if restricted else None
    )

    students = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student s{student_where}", scope_params) or 0
    students_with_results = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT g.student_id)
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.semester_id=? AND g.is_pass IS NOT NULL{student_and}
    """, tuple([cur] + scope_params)) or 0
    comparable_semesters = [value for value in (cur, previous_semester) if value]
    semester_marks = ",".join("?" * len(comparable_semesters))
    term_summary = {row["semester_id"]: row for row in dbm.query(conn, f"""
        WITH student_term AS (
          SELECT g.semester_id,g.student_id,
            {weighted_gpa_expression("g")} student_gpa,
            MAX(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failed
          FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
          WHERE g.source='real' AND g.is_pass IS NOT NULL
            AND g.semester_id IN ({semester_marks}){student_and}
          GROUP BY g.semester_id,g.student_id)
        SELECT semester_id,COUNT(*) result_students,AVG(student_gpa) avg_gpa,
          SUM(failed) failed_students
        FROM student_term GROUP BY semester_id
    """, tuple(comparable_semesters + scope_params))}
    current_term = term_summary.get(cur, {})
    previous_term = term_summary.get(previous_semester, {}) if previous_semester else {}
    current_fail_rate_value = _pct_number(
        current_term.get("failed_students"), current_term.get("result_students"))
    previous_fail_rate_value = _pct_number(
        previous_term.get("failed_students"), previous_term.get("result_students"))
    current_avg_gpa = (
        round(current_term.get("avg_gpa"), 2)
        if current_term.get("avg_gpa") is not None else None
    )
    previous_avg_gpa = (
        round(previous_term.get("avg_gpa"), 2)
        if previous_term.get("avg_gpa") is not None else None
    )
    previous_coverage_rate = _pct_number(
        previous_term.get("result_students"), students)
    if restricted:
        courses_cur = dbm.scalar(conn, f"""SELECT COUNT(DISTINCT g.course_id)
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.semester_id=?{student_and}""", tuple([cur] + scope_params)) or 0
        teachers = dbm.scalar(conn, f"""SELECT COUNT(DISTINCT l.teacher_id)
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            JOIN fact_lesson l ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
            WHERE g.semester_id=? AND l.teacher_id IS NOT NULL{student_and}""",
            tuple([cur] + scope_params)) or 0
    else:
        courses_cur = dbm.scalar(conn,
            "SELECT COUNT(DISTINCT course_id) FROM fact_lesson WHERE semester_id=?", (cur,)) or 0
        teachers = dbm.scalar(conn, "SELECT COUNT(*) FROM dim_teacher") or 0

    alert_scope = f" AND {student_scope}" if student_scope else ""
    alert_stu = dbm.scalar(conn,
        f"SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a "
        f"JOIN dim_student s ON a.student_id=s.student_id "
        f"WHERE COALESCE(a.is_active,1)=1{alert_scope}", scope_params) or 0
    new_alert_students = dbm.scalar(conn, f"""
        SELECT COUNT(*) FROM (
          SELECT a.student_id,MIN(a.semester_id) first_semester
          FROM fact_alert a JOIN dim_student s ON a.student_id=s.student_id
          WHERE COALESCE(a.is_active,1)=1{alert_scope}
          GROUP BY a.student_id
          HAVING first_semester=?
        )""", tuple(scope_params + [cur])) or 0
    persistent_alert_students = max(alert_stu - new_alert_students, 0)
    previous_alert_students = (
        dbm.scalar(conn, f"""
            SELECT COUNT(DISTINCT a.student_id)
            FROM fact_alert a JOIN dim_student s ON a.student_id=s.student_id
            WHERE a.semester_id=?{alert_scope}
        """, tuple([previous_semester] + scope_params)) or 0
        if previous_semester else 0
    )
    alert_history_comparable = previous_alert_students > 0
    if not alert_history_comparable:
        new_alert_students = None
        persistent_alert_students = None

    grad = dbm.query_one(conn, f"""SELECT COUNT(*) total,
        SUM(CASE WHEN f.graduated=1 THEN 1 ELSE 0 END) grad_count,
        SUM(CASE WHEN f.degree=1 THEN 1 ELSE 0 END) degree_count,
        AVG(CASE WHEN f.graduated=1 THEN 1.0 ELSE 0 END) grad_rate,
        AVG(CASE WHEN f.degree=1 THEN 1.0 ELSE 0 END) degree_rate
        FROM fact_graduation f JOIN dim_student s ON f.student_id=s.student_id
        {student_where}""", tuple(scope_params)) or {}
    grad_rate = grad.get("grad_rate") or 0
    degree_rate = grad.get("degree_rate") or 0
    teacher_label = "相关授课教师数" if restricted else "专任教师数"

    kpi = [
        {"id": "student_count", "label": "在籍学生数", "value": f"{students:,}", "formula": "当前在校本科生总数（含大一至大四）", "trend": "", "up": True, "group": "在校生"},
        {"id": "course_count", "label": "本学期开课门数", "value": f"{courses_cur:,}", "formula": "当前学期授权学生范围内修读课程去重；全校视角按教学任务去重", "trend": "", "up": True, "group": "在校生"},
        {"id": "teacher_count", "label": teacher_label, "value": f"{teachers:,}", "formula": "授权学生范围内有授课关系的教师去重；全校视角为教师维表去重", "trend": "", "up": True, "group": "在校生"},
        {"id": "alert_count", "label": "当前预警", "value": f"{alert_stu}人", "formula": "处于预警状态的学生数", "trend": "", "up": False, "group": "在校生"},
        {"id": "current_fail_rate", "label": "当前挂科学生率", "value": "—", "formula": "当前学期至少一门未通过的去重学生数÷当前学期有有效成绩的去重学生数", "trend": "", "up": False, "group": "在校生"},
        {"id": "history_fail_rate", "label": "历史挂科经历率", "value": "—", "formula": "观察期内曾出现过未通过记录的去重学生数÷观察期内有历史有效成绩的去重学生数（包含后续补考或重修通过）", "trend": "", "up": False, "group": "在校生"},
    ]

    rows = dbm.query(conn, f"""SELECT c.college_id,c.name,COUNT(s.student_id) students
        FROM dim_college c JOIN dim_student s ON s.college_id=c.college_id
        {student_where} GROUP BY c.college_id,c.name ORDER BY students DESC""", tuple(scope_params))
    term_by_col = {r["college_id"]: r for r in dbm.query(conn, f"""
        SELECT s.college_id,
            SUM(CASE WHEN g.score IS NOT NULL AND g.credits>0 THEN g.score*g.credits END)
              / NULLIF(SUM(CASE WHEN g.score IS NOT NULL AND g.credits>0 THEN g.credits END),0) avg_score,
            SUM(CASE WHEN g.is_pass=1 THEN COALESCE(g.credits,0) ELSE 0 END) passed_credits,
            SUM(COALESCE(g.credits,0)) attempted_credits
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.semester_id=? AND g.is_pass IS NOT NULL{student_and}
        GROUP BY s.college_id""", tuple([cur] + scope_params))}
    # 当前与上一学期的学院 GPA、有效成绩学生数、挂科学生数一次扫描完成，
    # 避免为每个指标重复扫描大成绩表。
    college_term_rows = dbm.query(conn, f"""
        WITH student_term AS (
          SELECT g.semester_id,s.college_id,g.student_id,
            {weighted_gpa_expression("g")} student_gpa,
            MAX(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failed
          FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
          WHERE g.source='real' AND g.is_pass IS NOT NULL
            AND g.semester_id IN ({semester_marks}){student_and}
          GROUP BY g.semester_id,s.college_id,g.student_id)
        SELECT semester_id,college_id,COUNT(*) result_students,
          AVG(student_gpa) avg_gpa,SUM(failed) failed_students
        FROM student_term GROUP BY semester_id,college_id
    """, tuple(comparable_semesters + scope_params))
    gpa_by_col = {
        r["college_id"]: r["avg_gpa"]
        for r in college_term_rows if r["semester_id"] == cur
    }
    alert_by_col = {r["college_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.college_id, COUNT(DISTINCT a.student_id) AS n
        FROM fact_alert a JOIN dim_student s ON a.student_id=s.student_id
        WHERE COALESCE(a.is_active,1)=1{student_and}
        GROUP BY s.college_id""", tuple(scope_params))}
    cur_fail_by_col = {
        r["college_id"]: r["failed_students"] or 0
        for r in college_term_rows if r["semester_id"] == cur
    }
    result_students_by_col = {
        r["college_id"]: r["result_students"] or 0
        for r in college_term_rows if r["semester_id"] == cur
    }
    previous_fail_by_col = {
        r["college_id"]: r["failed_students"] or 0
        for r in college_term_rows if r["semester_id"] == previous_semester
    }
    previous_results_by_col = {
        r["college_id"]: r["result_students"] or 0
        for r in college_term_rows if r["semester_id"] == previous_semester
    }
    previous_gpa_by_col = {
        r["college_id"]: r["avg_gpa"]
        for r in college_term_rows if r["semester_id"] == previous_semester
    }
    history_rows = dbm.query(conn, f"""
        SELECT s.college_id,
          COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.student_id END) AS n,
          COUNT(DISTINCT CASE WHEN g.is_pass IS NOT NULL THEN g.student_id END)
            AS result_students
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.is_pass IS NOT NULL{student_and}
        GROUP BY s.college_id""", tuple(scope_params))
    hist_fail_by_col = {r["college_id"]: r["n"] for r in history_rows}
    history_results_by_col = {
        r["college_id"]: r["result_students"] for r in history_rows
    }
    colleges = []
    scope_alert_rate = _pct_number(alert_stu, students)
    for r in rows:
        a = term_by_col.get(r["college_id"], {})
        attempted = a.get("attempted_credits") or 0
        college_result_students = result_students_by_col.get(r["college_id"], 0)
        college_current_fail_rate = _pct_number(
            cur_fail_by_col.get(r["college_id"], 0), college_result_students)
        college_previous_fail_rate = _pct_number(
            previous_fail_by_col.get(r["college_id"], 0),
            previous_results_by_col.get(r["college_id"], 0))
        college_gpa = (
            round(gpa_by_col.get(r["college_id"]), 2)
            if gpa_by_col.get(r["college_id"]) is not None else None
        )
        college_alert_rate = _pct_number(
            alert_by_col.get(r["college_id"], 0), r["students"])
        colleges.append({
            "id": r["college_id"], "name": r["name"], "students": r["students"],
            "avgScore": round(a.get("avg_score"), 1) if a.get("avg_score") is not None else None,
            "avgGpa": college_gpa,
            "failRate": _pct(
                hist_fail_by_col.get(r["college_id"], 0)
                / history_results_by_col.get(r["college_id"], 1)
            ) if history_results_by_col.get(r["college_id"], 0) else "—",
            "currentFailRate": _pct_value(
                cur_fail_by_col.get(r["college_id"], 0),
                college_result_students),
            "currentFailRateValue": college_current_fail_rate,
            "currentFailChangePp": (
                round(college_current_fail_rate - college_previous_fail_rate, 1)
                if college_current_fail_rate is not None
                and college_previous_fail_rate is not None else None),
            "currentFailVsScopePp": (
                round(college_current_fail_rate - current_fail_rate_value, 1)
                if college_current_fail_rate is not None
                and current_fail_rate_value is not None else None),
            "avgGpaChange": (
                round(college_gpa - previous_gpa_by_col[r["college_id"]], 2)
                if college_gpa is not None
                and previous_gpa_by_col.get(r["college_id"]) is not None else None),
            "avgGpaVsScope": (
                round(college_gpa - current_avg_gpa, 2)
                if college_gpa is not None and current_avg_gpa is not None else None),
            "alertRate": _pct_value(alert_by_col.get(r["college_id"], 0), r["students"]),
            "alertRateValue": college_alert_rate,
            "alertRateVsScopePp": (
                round(college_alert_rate - scope_alert_rate, 1)
                if college_alert_rate is not None and scope_alert_rate is not None else None),
            "creditDone": round((a.get("passed_credits") or 0) / attempted * 100) if attempted else None,
            "studentsWithResults": college_result_students,
            "resultCoverageRate": _pct_number(
                college_result_students, r["students"]),
        })
    ranked_fail = sorted(
        [row for row in colleges if row["currentFailRateValue"] is not None],
        key=lambda row: (-row["currentFailRateValue"], row["name"]))
    ranked_gpa = sorted(
        [row for row in colleges if row["avgGpa"] is not None],
        key=lambda row: (-row["avgGpa"], row["name"]))
    fail_ranks = {row["id"]: index + 1 for index, row in enumerate(ranked_fail)}
    gpa_ranks = {row["id"]: index + 1 for index, row in enumerate(ranked_gpa)}
    for row in colleges:
        row["currentFailRank"] = fail_ranks.get(row["id"])
        row["avgGpaRank"] = gpa_ranks.get(row["id"])
        row["comparisonCount"] = max(len(ranked_fail), len(ranked_gpa))
    scope_label = "全校"
    if restricted:
        if (
            (user.get("permission_context") or {}).get("detailScope", {}).get("type")
            == "college"
            and len(rows) == 1
        ):
            scope_label = rows[0]["name"]
        else:
            scope_label = "当前角色授权范围"

    gpa_rows = dbm.query(conn, f"""SELECT g.student_id,s.college_id,
        {weighted_gpa_expression("g")} gpa
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.semester_id=? AND g.gpa IS NOT NULL{student_and}
        GROUP BY g.student_id,s.college_id""", tuple([cur] + scope_params))
    def _shape_gpa(values):
        counts = {bucket: 0 for bucket, _, _ in _GPA_BANDS}
        for value in values:
            counts[_gpa_bucket(value)] += 1
        total = len(values)
        return [{"range": label, "label": label, "count": counts[bucket],
                 "percent": round(counts[bucket] / total * 100) if total else 0}
                for bucket, label, _ in _GPA_BANDS]
    gpaDist = _shape_gpa([r["gpa"] for r in gpa_rows])
    gpaDistByCollege = {}
    for college_id in {r["college_id"] for r in gpa_rows}:
        gpaDistByCollege[college_id] = _shape_gpa(
            [r["gpa"] for r in gpa_rows if r["college_id"] == college_id])

    failCourses = []
    rate_map = {r["course_id"]: r for r in dbm.query(conn, """SELECT course_id,
        first_pass_rate,final_pass_rate FROM agg_course_term WHERE semester_id=?""", (cur,))}
    # 三分层通过率按所选学期读取；受限身份按授权学生重新聚合。
    # finalPassRate 仍取 V1 agg_course_term（deprecated，保留一个版本周期）。
    v2pass = _v2_pass_stats(cur, scoped_student_ids)
    v2_courses = (v2pass or {}).get("courses", {})
    previous_course_stats = {}
    if previous_semester:
        previous_course_stats = {r["course_id"]: r for r in dbm.query(conn, f"""
            SELECT g.course_id,COUNT(*) total,
              SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fail_count
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.source='real' AND g.is_pass IS NOT NULL
              AND g.semester_id=?{student_and}
            GROUP BY g.course_id
        """, tuple([previous_semester] + scope_params))}
    course_candidates = []
    for r in dbm.query(conn, f"""SELECT g.course_id,co.name,co.dept,COUNT(*) total,
        SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fail_count,
        COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.student_id END) affected_students,
        AVG(g.score) avg_score,
        AVG(CASE WHEN g.score>=90 THEN 1.0 ELSE 0 END) excellent_rate
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        LEFT JOIN dim_course co ON g.course_id=co.course_id
        WHERE g.source='real' AND g.is_pass IS NOT NULL AND g.semester_id=?{student_and}
        GROUP BY g.course_id HAVING total>=30 AND fail_count>0
        """, tuple([cur] + scope_params)):
        rates = rate_map.get(r["course_id"], {})
        v2c = v2_courses.get(r["course_id"]) or {}
        current_rate = round(r["fail_count"] / r["total"] * 100, 1)
        previous_row = previous_course_stats.get(r["course_id"], {})
        previous_rate = _pct_number(
            previous_row.get("fail_count"), previous_row.get("total"))
        change_pp = (
            round(current_rate - previous_rate, 1)
            if previous_rate is not None else None
        )
        reasons = [f"影响 {r['affected_students']} 名学生"]
        if v2c.get("course_group") == "公共必修":
            reasons.append("公共必修")
        if change_pp is not None and change_pp >= 3:
            reasons.append(f"较上期上升 {change_pp} 个百分点")
        elif previous_rate is not None and previous_rate >= 10 and current_rate >= 10:
            reasons.append("连续两期未通过率较高")
        elif current_rate >= 10:
            reasons.append(f"当前未通过率 {current_rate}%")
        course_candidates.append({
            "id": r["course_id"], "name": r["name"] or r["course_id"],
            "college": r["dept"] or "—",
            "failCount": r["fail_count"], "totalCount": r["total"],
            "affectedStudents": r["affected_students"],
            "failRate": str(current_rate),
            "failRateValue": current_rate,
            "previousFailRate": previous_rate,
            "changePp": change_pp,
            "avgScore": round(r["avg_score"] or 0, 1),
            "excellentRate": str(round((r["excellent_rate"] or 0) * 100, 1)),
            "firstPassRate": _rate(v2c.get("fp"), v2c.get("fa")),
            "makeupPassRate": _rate(v2c.get("mp"), v2c.get("ma")),
            "retakePassRate": _rate(v2c.get("rp"), v2c.get("ra")),
            "courseGroup": v2c.get("course_group"),
            "selectionReason": "；".join(reasons),
            # deprecated：V1 末次通过率口径，保留一个版本周期后移除。
            "finalPassRate": None if restricted else round((rates.get("final_pass_rate") or 0) * 100, 1),
        })
    failCourses = sorted(
        course_candidates,
        key=lambda row: (
            -row["affectedStudents"],
            -(1 if row.get("courseGroup") == "公共必修" else 0),
            -(row.get("changePp") or 0),
            -row["failRateValue"],
            row["name"],
        ),
    )[:10]
    for index, row in enumerate(failCourses, start=1):
        row["priorityRank"] = index

    course_pass_rates = None
    if v2pass is not None:
        overall, public = (v2pass or {}).get("overall") or {}, (v2pass or {}).get("public_required") or {}
        final_v1 = None if restricted else dbm.scalar(conn, """
            SELECT SUM(final_pass_rate*total)/SUM(total)
            FROM agg_course_term WHERE total>0 AND semester_id=?""", (cur,))
        course_pass_rates = {
            "firstPassRate": _rate(overall.get("fp"), overall.get("fa")),
            "makeupPassRate": _rate(overall.get("mp"), overall.get("ma")),
            "retakePassRate": _rate(overall.get("rp"), overall.get("ra")),
            "publicRequiredFirstPassRate": _rate(public.get("fp"), public.get("fa")),
            "attempts": {"first": overall.get("fa") or 0, "makeup": overall.get("ma") or 0,
                         "retake": overall.get("ra") or 0},
            # deprecated：V1 agg_course_term 末次通过率，保留一个版本周期。
            "finalPassRate": round(final_v1 * 100, 1) if final_v1 is not None else None,
            "source": (f"V2 agg_course_pass_stat（{cur}，grade_attempt attempt_type 三分层，"
                       f"{'授权学生范围重新聚合' if restricted else '全校聚合'}，SUM(pass)/SUM(attempts)）"
                       if v2pass else "V2 agg_course_pass_stat 未构建，三分层指标暂缺"),
            "deprecatedFields": ["finalPassRate"],
        }

    total_cur = sum(cur_fail_by_col.values()) if cur_fail_by_col else 0
    total_hist = sum(hist_fail_by_col.values()) if hist_fail_by_col else 0
    total_history_results = (
        sum(history_results_by_col.values()) if history_results_by_col else 0
    )
    kpi[4]["value"] = _pct_value(total_cur, students_with_results)
    kpi[5]["value"] = _pct_value(total_hist, total_history_results)
    kpi, kpi_config_applied = _apply_kpi_config(conn, kpi)
    current_coverage_rate = _pct_number(students_with_results, students)

    def _change(current_value, previous_value, digits=1):
        if current_value is None or previous_value is None:
            return None
        return round(current_value - previous_value, digits)

    management_summary = [
        {
            "id": "result_coverage",
            "label": "有效成绩覆盖率",
            "value": current_coverage_rate,
            "unit": "%",
            "change": _change(current_coverage_rate, previous_coverage_rate),
            "changeUnit": "个百分点",
            "betterDirection": "up",
            "formula": "所选学期至少一条有效成绩的去重学生数÷当前授权范围在籍学生数",
            "managementUse": "先判断当前成绩数据是否足以支持学院和课程比较；覆盖不足时优先核查成绩发布进度。",
            "actionLabel": "查看学院覆盖",
            "actionTarget": "college-compare",
        },
        {
            "id": "current_fail_rate",
            "label": "当前挂科学生率",
            "value": current_fail_rate_value,
            "unit": "%",
            "change": _change(current_fail_rate_value, previous_fail_rate_value),
            "changeUnit": "个百分点",
            "betterDirection": "down",
            "formula": "所选学期至少一门未通过的去重学生数÷所选学期有有效成绩的去重学生数",
            "managementUse": "判断当前受学业失败影响的学生范围，并下钻定位偏离学院和重点课程。",
            "actionLabel": "定位偏离学院",
            "actionTarget": "college-compare",
        },
        {
            "id": "average_gpa",
            "label": "学生平均 GPA",
            "value": current_avg_gpa,
            "unit": "",
            "change": _change(current_avg_gpa, previous_avg_gpa, 2),
            "changeUnit": "",
            "betterDirection": "up",
            "formula": "先计算每名学生所选学期课程学分加权 GPA，再对有 GPA 学生求平均",
            "managementUse": "观察总体学业水平变化，并与挂科学生率结合判断是否出现整体下移。",
            "actionLabel": "查看学院差异",
            "actionTarget": "college-compare",
        },
        {
            "id": "active_alert_rate",
            "label": "当前有效预警学生率",
            "value": scope_alert_rate,
            "unit": "%",
            "change": None,
            "changeUnit": "",
            "betterDirection": "down",
            "formula": "当前有效预警去重学生数÷当前授权范围在籍学生数",
            "managementUse": "衡量当前需要关注的预警覆盖；结合新增与持续人数安排核查优先级。",
            "supplement": (
                f"当前 {alert_stu} 人 · 新增 {new_alert_students} 人 · 持续 {persistent_alert_students} 人"
                if alert_history_comparable
                else f"当前 {alert_stu} 人 · 历史预警尚无可比基线"
            ),
            "comparisonAvailable": alert_history_comparable,
            "actionLabel": "进入学业预警",
            "actionTarget": "alert",
        },
    ]
    leading_college = next(
        (row for row in ranked_fail if row.get("currentFailVsScopePp") is not None
         and row["currentFailVsScopePp"] > 0),
        None,
    )
    focus_candidates = []
    if leading_college:
        estimated_affected = round(
            (leading_college["currentFailVsScopePp"] or 0)
            * (leading_college["studentsWithResults"] or 0) / 100
        )
        focus_candidates.append({
            "level": "warning",
            "title": f"{leading_college['name']}当前挂科学生率高于范围均值",
            "detail": (
                f"高 {leading_college['currentFailVsScopePp']} 个百分点，"
                f"在 {leading_college['comparisonCount']} 个可比学院中风险排序第 "
                f"{leading_college['currentFailRank']}。"
            ),
            "targetType": "college",
            "targetId": leading_college["id"],
            "priorityScore": estimated_affected,
        })
    if failCourses:
        top_course = failCourses[0]
        focus_candidates.append({
            "level": "danger",
            "title": f"优先核查课程：{top_course['name']}",
            "detail": top_course["selectionReason"],
            "targetType": "course",
            "targetId": top_course["id"],
            "priorityScore": top_course["affectedStudents"],
        })
    focus_candidates.sort(key=lambda item: (
        -item["priorityScore"],
        item["targetType"],
        item["title"],
    ))
    management_focus = focus_candidates[:1]
    for item in management_focus:
        item.pop("priorityScore", None)

    payload = {"kpi": kpi, "colleges": colleges, "gpaDist": gpaDist,
               "gpaDistByCollege": gpaDistByCollege, "failCourses": failCourses,
               "coursePassRates": course_pass_rates,
               "scopeBackground": {
                   "students": students,
                   "courses": courses_cur,
                   "teachers": teachers,
                   "teacherLabel": teacher_label,
               },
               "managementSummary": management_summary,
               "managementFocus": management_focus,
               "kpiConfigApplied": kpi_config_applied,
               "scope": {"restricted": restricted,
                         "label": scope_label,
                         "studentCount": students},
               "period": {"semester": cur, "previousSemester": previous_semester},
               "coverage": {
                   "rosterStudents": students,
                   "studentsWithValidResults": students_with_results,
                   "validResultCoverageRate": _pct_number(students_with_results, students),
               },
               "definitionVersion": "dashboard-v3",
               "prototypeMetrics": {
                   "officialConclusion": False,
                   "graduationRate": (
                       round(grad_rate * 100, 1) if grad.get("total") else None),
                   "degreeAwardRate": (
                       round(degree_rate * 100, 1) if grad.get("total") else None),
                   "graduated": grad.get("grad_count") or 0,
                   "degreeAwarded": grad.get("degree_count") or 0,
                   "cohortTotal": grad.get("total") or 0,
                   "source": "固定种子合成业务表",
               },
               "evidence": {
                   "real": ["学籍、成绩、GPA、课程、教师授课关系、当前有效预警"],
                   "simulated": ["毕业结果、学位授予结果"],
                   "limitation": "毕业率和学位授予率来自固定种子合成业务表；课程学分通过占比是本学期已通过学分人次÷修读学分人次，不代表培养方案完成度。"
               }}
    _DASHBOARD_CACHE[cache_key] = (time.monotonic(), payload)
    return ok(payload)


# ------------------------------------------------------------------ college
@router.get("/college/{college_id}")
def college_detail(college_id: str, semester: Optional[str] = None,
                   conn: sqlite3.Connection = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    cur = semester or CUR
    if not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)):
        raise ApiError("学期不存在", code=400, status_code=400)
    col = dbm.query_one(conn, "SELECT college_id,name FROM dim_college WHERE college_id=?", (college_id,))
    if not col:
        raise ApiError("学院不存在", code=404, status_code=404)
    student_scope, scope_params = student_data_scope(user, conn, "s")
    scope_and = f" AND {student_scope}" if student_scope else ""
    restricted = bool(student_scope)
    scoped_student_ids = (
        [row["student_id"] for row in dbm.query(conn, f"""
            SELECT s.student_id FROM dim_student s
            WHERE s.college_id=?{scope_and}
        """, tuple([college_id] + scope_params))]
        if restricted else None
    )
    allowed = dbm.scalar(conn, f"SELECT 1 FROM dim_student s WHERE s.college_id=?{scope_and} LIMIT 1",
                         tuple([college_id] + scope_params))
    if not allowed:
        raise ApiError("无权限查看该学院", code=403, status_code=403)
    students = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student s WHERE s.college_id=?{scope_and}",
                          tuple([college_id] + scope_params)) or 0
    students_with_results = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT g.student_id)
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE s.college_id=? AND g.source='real' AND g.semester_id=?
          AND g.is_pass IS NOT NULL{scope_and}
    """, tuple([college_id, cur] + scope_params)) or 0
    courses_cur = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT g.course_id) FROM fact_grade g
        JOIN dim_student s ON g.student_id=s.student_id
        WHERE s.college_id=? AND g.semester_id=?{scope_and}""",
        tuple([college_id, cur] + scope_params)) or 0
    teachers = dbm.scalar(conn, f"""SELECT COUNT(DISTINCT l.teacher_id)
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        JOIN fact_lesson l ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
        WHERE s.college_id=? AND g.semester_id=? AND l.teacher_id IS NOT NULL{scope_and}""",
        tuple([college_id, cur] + scope_params)) or 0
    alert_stu = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
        JOIN dim_student s ON a.student_id=s.student_id WHERE s.college_id=?
        AND COALESCE(a.is_active,1)=1{scope_and}""", tuple([college_id] + scope_params)) or 0
    degree_rate = dbm.scalar(conn, f"""SELECT AVG(CASE WHEN f.degree=1 THEN 1.0 ELSE 0 END)
        FROM fact_graduation f JOIN dim_student s ON f.student_id=s.student_id
        WHERE s.college_id=?{scope_and}""", tuple([college_id] + scope_params)) or 0
    hist_fail_college = dbm.scalar(conn, f"""
        SELECT ROUND(COUNT(DISTINCT g.student_id)*100.0/NULLIF(COUNT(DISTINCT s.student_id),0),1)
        FROM dim_student s LEFT JOIN fact_grade g
          ON s.student_id=g.student_id AND g.is_pass=0 AND g.source='real'
        WHERE s.college_id=?{scope_and}""", tuple([college_id] + scope_params)) or 0
    college_term_summary = dbm.query_one(conn, f"""
        WITH student_term AS (
          SELECT g.student_id, {weighted_gpa_expression("g")} gpa,
            MAX(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failed
          FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
          WHERE s.college_id=? AND g.semester_id=? AND g.source='real'
            AND g.is_pass IS NOT NULL{scope_and}
          GROUP BY g.student_id)
        SELECT COUNT(*) result_students, AVG(gpa) avg_gpa,
          SUM(failed) failed_students
        FROM student_term
    """, tuple([college_id, cur] + scope_params)) or {}
    college_failed_students = college_term_summary.get("failed_students") or 0
    college_avg_gpa = college_term_summary.get("avg_gpa")
    kpi = [
        {"id": "valid_result_coverage_rate", "label": "有效成绩覆盖率",
         "value": _pct_value(students_with_results, students),
         "formula": "当前学期至少有一条有效成绩的去重学生数÷本院范围内在籍学生数",
         "detail": f"{students_with_results}/{students}人"},
        {"id": "current_fail_student_rate", "label": "当前挂科学生率",
         "value": _pct_value(college_failed_students, students_with_results),
         "formula": "当前学期至少一门未通过的去重学生数÷当前学期有有效成绩的去重学生数",
         "detail": f"{college_failed_students}/{students_with_results}人"},
        {"id": "average_student_gpa", "label": "平均GPA",
         "value": f"{round(college_avg_gpa, 2)}" if college_avg_gpa is not None else "—",
         "formula": "先计算每名学生当前学期课程学分加权GPA，再对有GPA学生求平均"},
        {"id": "active_alert_student_rate", "label": "有效预警学生率",
         "value": _pct_value(alert_stu, students),
         "formula": "当前有效预警去重学生数÷本院范围内在籍学生数",
         "detail": f"{alert_stu}/{students}人"},
        {"id": "priority_major_count", "label": "优先核查专业", "value": "0个",
         "formula": "当前挂科学生率高于学院均值3个百分点，或有效成绩覆盖率低于70%的专业数"},
    ]

    # 专业横向
    majors = []
    # 各专业当前挂科率 + 历史挂科率
    cur_fail_by_major = {r["major_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.major_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real' AND g.semester_id=?
          AND s.college_id=?{scope_and}
        GROUP BY s.major_id""", tuple([cur, college_id] + scope_params))}
    hist_fail_by_major = {r["major_id"]: r["n"] for r in dbm.query(conn, f"""
        SELECT s.major_id, COUNT(DISTINCT g.student_id) AS n
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.is_pass=0 AND g.source='real' AND s.college_id=?{scope_and}
        GROUP BY s.major_id""", tuple([college_id] + scope_params))}
    for r in dbm.query(conn, f"""
        SELECT m.major_id, m.name,
               COUNT(DISTINCT s.student_id) AS students
        FROM dim_major m JOIN dim_student s ON s.major_id=m.major_id
        WHERE m.college_id=?{scope_and} GROUP BY m.major_id ORDER BY students DESC""",
        tuple([college_id] + scope_params)):
        mid = r["major_id"]
        stat = dbm.query_one(conn, f"""
            WITH student_term AS (
              SELECT g.student_id,{weighted_gpa_expression("g")} gpa,
                SUM(CASE WHEN g.is_pass=1 THEN COALESCE(g.credits,0) ELSE 0 END)
                  passed_credits,
                SUM(COALESCE(g.credits,0)) attempted_credits
              FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
              WHERE s.major_id=? AND g.semester_id=? AND g.source='real'
                AND g.is_pass IS NOT NULL{scope_and}
              GROUP BY g.student_id)
            SELECT AVG(gpa) gpa,COUNT(gpa) gpa_samples,
                   SUM(passed_credits) passed_credits,
                   SUM(attempted_credits) attempted_credits
            FROM student_term""",
            tuple([mid, cur] + scope_params)) or {}
        result_students = dbm.scalar(conn, f"""
            SELECT COUNT(DISTINCT g.student_id)
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            WHERE s.major_id=? AND g.semester_id=? AND g.source='real'
              AND g.is_pass IS NOT NULL{scope_and}""",
            tuple([mid, cur] + scope_params)) or 0
        acnt = dbm.scalar(conn, f"""
            SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
            JOIN dim_student s ON a.student_id=s.student_id WHERE s.major_id=?
            AND COALESCE(a.is_active,1)=1{scope_and}""", tuple([mid] + scope_params)) or 0
        majors.append({
            "id": mid, "name": r["name"], "students": r["students"],
            "gpa": round(stat.get("gpa"), 2) if stat.get("gpa") is not None else None,
            "gpaSampleCount": stat.get("gpa_samples") or 0,
            "failRate": _pct(hist_fail_by_major.get(mid, 0) / r["students"]),
            "currentFailRate": _pct_value(cur_fail_by_major.get(mid, 0), result_students),
            "alertCount": acnt,
            "alertRate": _pct_value(acnt, r["students"]),
            "studentsWithResults": result_students,
            "resultCoverageRate": _pct_number(result_students, r["students"]),
            "creditPassed": round(stat.get("passed_credits") or 0, 1),
            "creditAttempted": round(stat.get("attempted_credits") or 0, 1),
            "creditDone": _pct_number(
                stat.get("passed_credits"), stat.get("attempted_credits")
            ),
            "unavailableReason": (
                None if result_students else "本学期暂无真实有效成绩"
            ),
            "trend": "up" if (cur_fail_by_major.get(mid, 0) / max(r["students"],1)) > 0.06 else "down",
        })
    # 全院挂科率均值，修正各专业趋势
    col_avg_fail = sum(v for v in cur_fail_by_major.values()) / max(
        sum(m["studentsWithResults"] for m in majors), 1)
    for m in majors:
        current_rate = (
            cur_fail_by_major.get(m["id"], 0) / m["studentsWithResults"]
            if m["studentsWithResults"] else None
        )
        m["trend"] = (
            None if current_rate is None
            else "up" if current_rate > col_avg_fail else "down"
        )
        m["currentFailVsCollegePp"] = (
            round((current_rate - col_avg_fail) * 100, 1)
            if current_rate is not None else None
        )
        reasons = []
        if m["currentFailVsCollegePp"] is not None and m["currentFailVsCollegePp"] >= 3:
            reasons.append(f"挂科学生率高于学院{m['currentFailVsCollegePp']}个百分点")
        if (m["resultCoverageRate"] is not None
                and m["resultCoverageRate"] < 70):
            reasons.append(f"有效成绩覆盖率仅{m['resultCoverageRate']}%")
        m["priorityReason"] = "；".join(reasons) if reasons else "未达到优先核查阈值"
        m["needsPriorityReview"] = bool(reasons)
    majors.sort(key=lambda item: (
        not item["needsPriorityReview"],
        -(item["currentFailVsCollegePp"] or -999),
        item["name"],
    ))
    for rank, major in enumerate(majors, start=1):
        major["priorityRank"] = rank
    priority_major_count = sum(1 for m in majors if m["needsPriorityReview"])
    kpi[-1]["value"] = f"{priority_major_count}个"
    kpi[-1]["detail"] = f"共{len(majors)}个专业"

    # 年级对比（按当前学期成绩）
    gradeCompare = []
    for r in dbm.query(conn, f"""
        WITH student_term AS (
          SELECT s.grade,g.student_id,{weighted_gpa_expression("g")} gpa,
            MAX(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failed,
            SUM(CASE WHEN g.is_pass=1 THEN COALESCE(g.credits,0) ELSE 0 END) passed_credits,
            SUM(COALESCE(g.credits,0)) attempted_credits
          FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
          WHERE s.college_id=? AND g.semester_id=? AND g.source='real'
            AND g.is_pass IS NOT NULL AND s.grade IS NOT NULL{scope_and}
          GROUP BY s.grade,g.student_id)
        SELECT grade,COUNT(*) result_students,
          SUM(passed_credits) passed_credits,
          SUM(attempted_credits) attempted_credits,
          SUM(passed_credits)/NULLIF(SUM(attempted_credits),0) cd,
          AVG(gpa) gpa,COUNT(gpa) gpa_samples,
          SUM(failed)*1.0/COUNT(*) fr
        FROM student_term GROUP BY grade ORDER BY grade DESC
    """, tuple([college_id, cur] + scope_params)):
        gradeCompare.append({
            "grade": f"{r['grade']}级", "creditDone": round((r["cd"] or 0) * 100),
            "gpaAvg": round(r["gpa"], 2) if r["gpa"] is not None else None,
            "gpaSampleCount": r["gpa_samples"] or 0,
            "failRate": _pct(r["fr"]),
            "studentsWithResults": r["result_students"],
            "creditPassed": round(r["passed_credits"] or 0, 1),
            "creditAttempted": round(r["attempted_credits"] or 0, 1),
            "unavailableReason": (
                None if r["result_students"] else "本学期暂无真实有效成绩"
            ),
        })

    failCourses = _college_fail_courses(
        conn, college_id, cur, scope_and, scope_params,
        restricted=restricted, scoped_student_ids=scoped_student_ids)
    return ok({"name": col["name"], "kpi": kpi, "majors": majors,
               "gradeCompare": gradeCompare, "failCourses": failCourses,
               "scope": {"restricted": restricted,
                         "label": "当前角色授权范围" if restricted else "全院"},
               "period": {"semester": cur},
               "coverage": {
                   "rosterStudents": students,
                   "studentsWithValidResults": students_with_results,
                   "validResultCoverageRate": _pct_number(students_with_results, students),
               },
               "definitionVersion": "dashboard-v3",
               "prototypeMetrics": {
                   "officialConclusion": False,
                   "degreeAwardRate": round(degree_rate * 100, 1) if degree_rate is not None else None,
                   "source": "固定种子合成业务表",
               },
               "evidence": {"real": ["真实学籍、成绩、课程、教师授课关系、当前有效预警"],
                            "simulated": ["学位授予结果"],
                            "limitation": "学位率来自固定种子合成业务表；年级课程学分通过占比不等同于培养方案完成度。"}})


def _college_fail_courses(conn, college_id, cur, scope_and="", scope_params=None,
                          limit=6, restricted=False, scoped_student_ids=None):
    scope_params = scope_params or []
    previous_semester = dbm.scalar(
        conn,
        "SELECT semester_id FROM dim_semester WHERE semester_id<? "
        "ORDER BY semester_id DESC LIMIT 1",
        (cur,),
    )
    previous_rates = {}
    if previous_semester:
        previous_rates = {
            row["course_id"]: row["fail_rate"]
            for row in dbm.query(conn, f"""
                SELECT g.course_id,
                  SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END)*100.0/
                    NULLIF(COUNT(*),0) fail_rate
                FROM fact_grade g JOIN dim_student s
                  ON g.student_id=s.student_id
                WHERE g.source='real' AND s.college_id=?
                  AND g.semester_id=? AND g.is_pass IS NOT NULL{scope_and}
                GROUP BY g.course_id
            """, tuple([college_id, previous_semester] + scope_params))
        }
    cr_map = {}
    for r in dbm.query(conn,
        "SELECT course_id, first_pass_rate, final_pass_rate FROM agg_course_term "
        "WHERE semester_id=? AND first_pass_rate IS NOT NULL", (cur,)):
        cr_map[r["course_id"]] = (r["first_pass_rate"], r["final_pass_rate"])
    # 三分层通过率按所选学期读取；受限身份按授权学生重新聚合。
    # finalPassRate 仍取 V1（deprecated，保留一个版本周期）。
    v2_courses = (
        _v2_pass_stats(cur, scoped_student_ids if restricted else None) or {}
    ).get("courses", {})
    out = []
    for r in dbm.query(conn, f"""
        SELECT g.course_id, co.name, co.credits,
               COUNT(*) total, SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc,
               COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.student_id END) affected,
               AVG(g.score) av
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        JOIN dim_course co ON g.course_id=co.course_id
        WHERE g.source='real' AND s.college_id=? AND g.semester_id=?{scope_and}
        GROUP BY g.course_id HAVING total>=15
        ORDER BY affected DESC, (fc*1.0/total) DESC LIMIT ?""",
        tuple([college_id, cur] + scope_params + [limit])):
        fpr, lpr = cr_map.get(r["course_id"], (None, None))
        v2c = v2_courses.get(r["course_id"]) or {}
        current_rate = round(r["fc"] / r["total"] * 100, 1)
        previous_rate = previous_rates.get(r["course_id"])
        change_pp = (
            round(current_rate - previous_rate, 1)
            if previous_rate is not None else None
        )
        reason_parts = [f"影响{r['affected']}名学生"]
        if change_pp is not None:
            reason_parts.append(
                f"较上学期{'上升' if change_pp >= 0 else '下降'}{abs(change_pp)}个百分点")
        else:
            reason_parts.append("上学期无可比记录")
        out.append({
            "id": r["course_id"], "name": r["name"] or r["course_id"],
            "failCount": r["fc"], "totalCount": r["total"],
            "affectedStudents": r["affected"],
            "failRate": str(current_rate),
            "previousFailRate": (
                round(previous_rate, 1) if previous_rate is not None else None),
            "changePp": change_pp,
            "selectionReason": "；".join(reason_parts),
            "avgScore": round(r["av"] or 0, 1), "credits": r["credits"],
            "firstPassRate": _rate(v2c.get("fp"), v2c.get("fa")),
            "makeupPassRate": _rate(v2c.get("mp"), v2c.get("ma")),
            "retakePassRate": _rate(v2c.get("rp"), v2c.get("ra")),
            "courseGroup": v2c.get("course_group"),
            # deprecated：V1 末次通过率口径，保留一个版本周期后移除。
            "finalPassRate": None if restricted else (round((lpr or 0) * 100, 1) if lpr is not None else None),
        })
    for rank, row in enumerate(out, start=1):
        row["priorityRank"] = rank
    return out


# ------------------------------------------------------------------ major
@router.get("/major/{major_id}")
def major_detail(major_id: str, semester: Optional[str] = None,
                 conn: sqlite3.Connection = Depends(get_db),
                 user: dict = Depends(get_current_user)):
    cur = semester or CUR
    if not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)):
        raise ApiError("学期不存在", code=400, status_code=400)
    mj = dbm.query_one(conn, """
        SELECT m.major_id, m.name, m.college_id, c.name AS college
        FROM dim_major m LEFT JOIN dim_college c ON m.college_id=c.college_id
        WHERE m.major_id=?""", (major_id,))
    if not mj:
        raise ApiError("专业不存在", code=404, status_code=404)
    student_scope, scope_params = student_data_scope(user, conn, "s")
    scope_and = f" AND {student_scope}" if student_scope else ""
    restricted = bool(student_scope)
    students = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student s WHERE s.major_id=?{scope_and}",
                          tuple([major_id] + scope_params)) or 0
    if restricted and not students:
        raise ApiError("无权限查看该专业", code=403, status_code=403)
    alert_stu = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
        JOIN dim_student s ON a.student_id=s.student_id WHERE s.major_id=?
        AND COALESCE(a.is_active,1)=1{scope_and}""", tuple([major_id] + scope_params)) or 0
    term_summary = dbm.query_one(conn, f"""
        WITH student_term AS (
          SELECT g.student_id,{weighted_gpa_expression("g")} gpa,
            MAX(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failed
          FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
          WHERE s.major_id=? AND g.semester_id=? AND g.source='real'
            AND g.is_pass IS NOT NULL{scope_and}
          GROUP BY g.student_id)
        SELECT COUNT(*) result_students,AVG(gpa) avg_gpa,SUM(failed) failed_students
        FROM student_term
    """, tuple([major_id, cur] + scope_params)) or {}
    students_with_results = term_summary.get("result_students") or 0
    total_req = dbm.scalar(conn, "SELECT total_req FROM fact_major_req WHERE major_id=?", (major_id,))
    earned_avg = dbm.scalar(conn, f"""SELECT AVG(f.earned_credits)
        FROM fact_graduation f JOIN dim_student s ON f.student_id=s.student_id
        WHERE s.major_id=?{scope_and}""", tuple([major_id] + scope_params)) or 0
    cd = (earned_avg / total_req) if total_req else 0
    cd = min(cd, 1.0)
    gr = dbm.query_one(conn, f"""SELECT AVG(CASE WHEN f.graduated=1 THEN 1.0 ELSE 0 END) grad_rate
        FROM fact_graduation f JOIN dim_student s ON f.student_id=s.student_id
        WHERE s.major_id=?{scope_and}""", tuple([major_id] + scope_params)) or {}
    grad_rate = gr.get("grad_rate")
    kpi = [
        {"id": "roster_students", "label": "在籍学生", "value": str(students),
         "formula": "本专业与当前工作身份授权范围交集内的在籍学生数"},
        {"id": "valid_result_coverage_rate", "label": "有效成绩覆盖率", "value": _pct_value(students_with_results, students),
         "formula": "当前学期至少一条有效成绩的去重学生数÷本专业范围内学生数"},
        {"id": "average_student_gpa", "label": "平均GPA",
         "value": (f"{round(term_summary['avg_gpa'], 2)}"
                   if term_summary.get("avg_gpa") is not None else "—"),
         "formula": "先计算每名学生当前学期课程学分加权GPA，再对有GPA学生求平均"},
        {"id": "current_fail_student_rate", "label": "当前挂科学生率",
         "value": _pct_value(term_summary.get("failed_students"), students_with_results),
         "formula": "当前学期至少一门未通过的去重学生数÷当前学期有有效成绩的去重学生数"},
        {"id": "active_alert_students", "label": "预警学生", "value": str(alert_stu),
         "formula": "当前有效预警去重学生数"},
    ]

    gradeDetail = []
    grade_rows = dbm.query(conn, f"""SELECT s.grade,COUNT(DISTINCT s.student_id) students
        FROM dim_student s WHERE s.major_id=? AND s.grade IS NOT NULL{scope_and}
        GROUP BY s.grade ORDER BY s.grade DESC""", tuple([major_id] + scope_params))
    for base in grade_rows:
        grade = base["grade"]
        r = dbm.query_one(conn, f"""
            WITH student_term AS (
              SELECT g.student_id,{weighted_gpa_expression("g")} gpa,
                MAX(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failed,
                SUM(CASE WHEN g.is_pass=1 THEN COALESCE(g.credits,0) ELSE 0 END) passed_credits,
                SUM(COALESCE(g.credits,0)) attempted_credits
              FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
              WHERE g.source='real' AND s.major_id=? AND s.grade=? AND g.semester_id=?
                AND g.is_pass IS NOT NULL{scope_and}
              GROUP BY g.student_id)
            SELECT COUNT(*) result_students,AVG(gpa) gpa,SUM(failed) failed_students,
              SUM(passed_credits) passed_credits,SUM(attempted_credits) attempted_credits
            FROM student_term""",
            tuple([major_id, grade, cur] + scope_params)) or {}
        acnt = dbm.scalar(conn, f"""
            SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
            JOIN dim_student s ON a.student_id=s.student_id
            WHERE s.major_id=? AND s.grade=? AND COALESCE(a.is_active,1)=1{scope_and}""",
            tuple([major_id, grade] + scope_params)) or 0
        courses = []
        for cr in dbm.query(conn, f"""
            SELECT g.course_id,co.name, COUNT(*) total, SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            JOIN dim_course co ON g.course_id=co.course_id
            WHERE g.source='real' AND s.major_id=? AND s.grade=? AND g.semester_id=?{scope_and}
            GROUP BY g.course_id HAVING fc>0 AND total>=8 ORDER BY (fc*1.0/total) DESC LIMIT 3""",
                tuple([major_id, grade, cur] + scope_params)):
            courses.append({"id": cr["course_id"], "name": cr["name"], "failCount": cr["fc"],
                            "totalCount": cr["total"],
                            "failRate": str(round(cr["fc"] / cr["total"] * 100, 1))})
        course_count = dbm.scalar(conn, f"""
            SELECT COUNT(DISTINCT g.course_id)
            FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.source='real' AND g.is_pass IS NOT NULL
              AND s.major_id=? AND s.grade=? AND g.semester_id=?{scope_and}
        """, tuple([major_id, grade, cur] + scope_params)) or 0
        result_students = r.get("result_students") or 0
        failed_students = r.get("failed_students") or 0
        fail_rate_value = (
            round(failed_students * 100 / result_students, 1)
            if result_students else None
        )
        gradeDetail.append({
            "grade": f"{grade}级", "students": base["students"],
            "gpaAvg": round(r["gpa"], 2) if r.get("gpa") is not None else None,
            "failRate": _pct_value(failed_students, result_students),
            "failRateValue": fail_rate_value,
            "failedStudents": failed_students,
            "alertCount": acnt,
            "creditDone": _pct_number(
                r.get("passed_credits"), r.get("attempted_credits")),
            "studentsWithResults": r.get("result_students") or 0,
            "resultCoverageRate": _pct_number(
                r.get("result_students"), base["students"]),
            "courses": courses,
            "courseCount": course_count,
            "moreCourseCount": max(course_count - len(courses), 0),
        })
    risk_sorted = sorted(gradeDetail, key=lambda item: (
        -(item["failRateValue"] if item["failRateValue"] is not None else -1),
        item["resultCoverageRate"] if item["resultCoverageRate"] is not None else 101,
        -item["alertCount"],
        item["grade"],
    ))
    risk_rank = {
        row["grade"]: index
        for index, row in enumerate(risk_sorted, start=1)
    }
    for grade_row in gradeDetail:
        grade_row["riskRank"] = risk_rank[grade_row["grade"]]
        reasons = []
        if grade_row["failedStudents"]:
            reasons.append(
                f"{grade_row['failedStudents']}名学生本学期至少一门未通过")
        if (grade_row["resultCoverageRate"] is not None
                and grade_row["resultCoverageRate"] < 70):
            reasons.append(
                f"有效成绩覆盖率仅{grade_row['resultCoverageRate']}%")
        if grade_row["alertCount"]:
            reasons.append(f"{grade_row['alertCount']}名学生处于有效预警")
        grade_row["priorityReason"] = (
            "；".join(reasons) if reasons else "未发现需优先核查的集中问题")

    goalDistribution = {"升学读研": 0, "签约就业": 0, "灵活就业": 0, "待业": 0}
    for r in dbm.query(conn, f"""SELECT f.goal, COUNT(*) n FROM fact_graduation f
        JOIN dim_student s ON f.student_id=s.student_id
        WHERE s.major_id=?{scope_and} GROUP BY f.goal""", tuple([major_id] + scope_params)):
        if r["goal"] in goalDistribution:
            goalDistribution[r["goal"]] = r["n"]
    return ok({"name": mj["name"], "college": mj["college"], "collegeId": mj["college_id"],
               "kpi": kpi, "gradeDetail": gradeDetail, "goalDistribution": goalDistribution,
               "scope": {"restricted": restricted,
                         "label": "当前角色授权范围" if restricted else "本专业"},
               "period": {"semester": cur},
               "coverage": {
                   "rosterStudents": students,
                   "studentsWithValidResults": students_with_results,
                   "validResultCoverageRate": _pct_number(students_with_results, students),
               },
               "prototypeMetrics": {
                   "syntheticPlanCompletionRate": _pct_number(earned_avg, total_req),
                   "syntheticGraduationRate": (
                       round(grad_rate * 100, 1) if grad_rate is not None else None),
                   "syntheticGoalDistribution": goalDistribution,
                   "officialConclusion": False,
               },
               "definitionVersion": "dashboard-v3",
               "evidence": {"real": ["真实学籍、成绩、课程、当前有效预警、培养方案要求（仅覆盖专业）"],
                            "simulated": ["毕业结果、就业去向、毕业表已修学分"],
                            "limitation": "毕业率、就业去向和毕业表已修学分来自固定种子合成业务表；年级课程学分通过占比不等同于培养方案完成度。"}})


@router.get("/major/{major_id}/grade-courses")
def major_grade_courses(
    major_id: str,
    grade: str,
    semester: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    conn: sqlite3.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """专业年级的全部课程结果，包含零未通过课程。"""
    cur = semester or CUR
    grade_value = grade.removesuffix("级")
    if page < 1 or page_size < 1 or page_size > 100:
        raise ApiError("分页参数无效", code=400, status_code=400)
    major = dbm.query_one(
        conn,
        """SELECT m.name,c.name college
           FROM dim_major m LEFT JOIN dim_college c
             ON c.college_id=m.college_id
           WHERE m.major_id=?""",
        (major_id,),
    )
    if not major:
        raise ApiError("专业不存在", code=404, status_code=404)
    if not dbm.scalar(
        conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)
    ):
        raise ApiError("学期不存在", code=400, status_code=400)
    scope, scope_params = student_data_scope(user, conn, "s")
    scope_and = f" AND {scope}" if scope else ""
    allowed = dbm.scalar(conn, f"""
        SELECT 1 FROM dim_student s
        WHERE s.major_id=? AND s.grade=?{scope_and} LIMIT 1
    """, tuple([major_id, grade_value] + scope_params))
    if not allowed:
        raise ApiError("无权限查看该专业年级", code=403, status_code=403)

    filters = [
        "g.source='real'",
        "g.is_pass IS NOT NULL",
        "s.major_id=?",
        "s.grade=?",
        "g.semester_id=?",
    ]
    params: list = [major_id, grade_value, cur]
    if scope:
        filters.append(scope)
        params.extend(scope_params)
    if q and q.strip():
        filters.append("(g.course_id LIKE ? OR co.name LIKE ?)")
        keyword = f"%{q.strip()}%"
        params.extend([keyword, keyword])
    where = " AND ".join(filters)
    ranked_sql = f"""
        SELECT g.course_id,g.student_id,g.is_pass,
               COALESCE(co.name,g.course_id) course_name,
               ROW_NUMBER() OVER (
                 PARTITION BY g.student_id,g.course_id
                 ORDER BY g.rowid DESC
               ) result_rank
        FROM fact_grade g
        JOIN dim_student s ON g.student_id=s.student_id
        LEFT JOIN dim_course co ON co.course_id=g.course_id
        WHERE {where}
    """
    total = dbm.scalar(conn, f"""
        SELECT COUNT(DISTINCT course_id)
        FROM ({ranked_sql}) ranked
        WHERE result_rank=1
    """, tuple(params)) or 0
    rows = dbm.query(conn, f"""
        SELECT course_id,MAX(course_name) course_name,
               COUNT(*) total_count,
               SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) fail_count
        FROM ({ranked_sql}) ranked
        WHERE result_rank=1
        GROUP BY course_id
        ORDER BY (fail_count*1.0/COUNT(*)) DESC,
                 total_count DESC,course_id
        LIMIT ? OFFSET ?
    """, tuple(params + [page_size, (page - 1) * page_size]))
    items = [{
        "courseId": row["course_id"],
        "courseName": row["course_name"],
        "failCount": row["fail_count"] or 0,
        "totalCount": row["total_count"] or 0,
        "failRate": _pct_number(
            row["fail_count"], row["total_count"]
        ),
    } for row in rows]
    return ok({
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "scope": {
            "majorId": major_id,
            "majorName": major["name"],
            "collegeName": major["college"],
            "grade": grade_value,
            "semester": cur,
        },
        "query": {"q": q or ""},
        "definitionVersion": "major-grade-courses-v1",
    })


# ------------------------------------------------------------------ course
@router.get("/course/{course_id}")
def course_detail(course_id: str, semester: Optional[str] = None,
                  college_id: Optional[str] = None,
                  major_id: Optional[str] = None,
                  grade: Optional[str] = None,
                  conn: sqlite3.Connection = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    cur = semester or CUR
    if not dbm.scalar(conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (cur,)):
        raise ApiError("学期不存在", code=400, status_code=400)
    co = dbm.query_one(conn, """
        SELECT course_id, name, credits, is_required, dept FROM dim_course WHERE course_id=?""",
        (course_id,))
    if not co:
        raise ApiError("课程不存在", code=404, status_code=404)
    student_scope, scope_params = student_data_scope(user, conn, "s")
    restricted = bool(student_scope)
    detail_conditions, detail_params = [], []
    if student_scope:
        detail_conditions.append(student_scope)
        detail_params.extend(scope_params)
    analysis_labels = []
    if college_id:
        college = dbm.query_one(
            conn, "SELECT name FROM dim_college WHERE college_id=?", (college_id,))
        if not college:
            raise ApiError("学院不存在", code=404, status_code=404)
        detail_conditions.append("s.college_id=?")
        detail_params.append(college_id)
        analysis_labels.append(college["name"])
    if major_id:
        major = dbm.query_one(
            conn, "SELECT name FROM dim_major WHERE major_id=?", (major_id,))
        if not major:
            raise ApiError("专业不存在", code=404, status_code=404)
        detail_conditions.append("s.major_id=?")
        detail_params.append(major_id)
        analysis_labels.append(major["name"])
    if grade:
        detail_conditions.append("s.grade=?")
        detail_params.append(grade)
        analysis_labels.append(f"{grade}级")
    detail_scope = " AND ".join(detail_conditions)
    detail_and = f" AND {detail_scope}" if detail_scope else ""
    scoped_student_ids = (
        [row["student_id"] for row in dbm.query(
            conn, f"SELECT s.student_id FROM dim_student s WHERE {detail_scope}",
            tuple(detail_params))]
        if detail_scope else None
    )
    if restricted and analysis_labels and not scoped_student_ids:
        raise ApiError("无权限查看该分析范围", code=403, status_code=403)
    if restricted:
        authorized = dbm.scalar(conn, f"""SELECT 1 FROM fact_grade g
            JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.course_id=? AND {student_scope} LIMIT 1""",
            tuple([course_id] + scope_params))
        if not authorized:
            raise ApiError("无权限查看该课程范围", code=403, status_code=403)
    cur_row = dbm.query_one(conn, f"""
        SELECT COUNT(*) total,
               SUM(CASE WHEN g.score IS NOT NULL THEN 1 ELSE 0 END) scored,
               AVG(g.score) av,
               SUM(CASE WHEN g.score>=90 THEN 1 ELSE 0 END) exc,
               SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.course_id=? AND g.semester_id=?
          AND g.is_pass IS NOT NULL{detail_and}""",
        tuple([course_id, cur] + detail_params)) or {}
    total = cur_row.get("total") or 0
    scored = cur_row.get("scored") or 0
    final_result = dbm.query_one(conn, f"""
        WITH ranked AS (
          SELECT g.student_id,g.score,g.gpa,g.is_pass,
                 ROW_NUMBER() OVER (
                   PARTITION BY g.student_id
                   ORDER BY g.rowid DESC
                 ) latest_rank
          FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
          WHERE g.source='real' AND g.course_id=? AND g.semester_id=?
            AND g.is_pass IS NOT NULL{detail_and}
        )
        SELECT COUNT(*) result_students,
               SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) failed_students,
               AVG(gpa) average_gp,
               SUM(CASE WHEN gpa IS NOT NULL THEN 1 ELSE 0 END) average_gp_students
        FROM ranked WHERE latest_rank=1
    """, tuple([course_id, cur] + detail_params)) or {}
    final_students = final_result.get("result_students") or 0
    failed_students = final_result.get("failed_students") or 0
    average_gp = final_result.get("average_gp")
    average_gp_students = final_result.get("average_gp_students") or 0
    kpi = [
        {"id": "valid_result_attempts", "label": "有效成绩人次", "value": str(total),
         "formula": "当前学期已发布且具有通过判定的有效成绩人次"},
        {"id": "average_score", "label": "平均分",
         "value": f"{round(cur_row['av'], 1)}" if cur_row.get("av") is not None else "—",
         "formula": "当前学期有百分制成绩记录的算术平均分", "detail": f"{scored}人次有分数"},
        {"id": "average_course_gp", "label": "平均 GPA",
         "value": f"{round(average_gp, 2)}" if average_gp is not None else "—",
         "formula": "当前课程、学期和分析范围内，每名学生最后一条真实有效课程 GP 的算术平均",
         "detail": f"{average_gp_students}名学生有最终有效课程绩点"},
        {"id": "excellent_rate", "label": "优秀率", "value": _pct_value(cur_row.get("exc"), scored),
         "formula": "当前学期成绩≥90分人次÷有百分制成绩人次",
         "detail": f"{cur_row.get('exc') or 0}人次≥90分"},
        {"id": "course_fail_student_rate", "label": "未通过率",
         "value": _pct_value(failed_students, final_students),
         "formula": "当前课程、学期和分析范围内，最终有效结果未通过学生数÷有最终有效结果学生数",
         "detail": f"{failed_students}/{final_students}名学生"},
    ]
    bands = [("90-100", "优秀", 90, 101), ("80-89", "良好", 80, 90), ("70-79", "中等", 70, 80),
             ("60-69", "及格", 60, 70), ("0-59", "不及格", 0, 60)]
    scoreDistribution = []
    for rng, label, lo, hi in bands:
        c = dbm.scalar(conn, f"""SELECT COUNT(*) FROM fact_grade g
            JOIN dim_student s ON g.student_id=s.student_id
            WHERE g.source='real' AND g.course_id=? AND g.semester_id=?
            AND g.is_pass IS NOT NULL AND g.score>=? AND g.score<?{detail_and}""",
            tuple([course_id, cur, lo, hi] + detail_params)) or 0
        scoreDistribution.append({"range": rng, "label": label, "count": c,
                                  "pct": _pct_number(c, scored)})
    history = []
    for r in dbm.query(conn, f"""
        SELECT g.semester_id, AVG(g.score) av,
               AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr, COUNT(*) total
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        WHERE g.source='real' AND g.course_id=? AND g.is_pass IS NOT NULL{detail_and}
        GROUP BY g.semester_id
        ORDER BY g.semester_id DESC LIMIT 6""", tuple([course_id] + detail_params)):
        history.append({"semester": r["semester_id"], "avgScore": round(r["av"] or 0, 1),
                        "failRate": _pct(r["fr"]), "totalStudents": r["total"]})
    history.reverse()
    classDetail = []
    for r in dbm.query(conn, f"""
        SELECT cl.name cls, COUNT(*) total, AVG(g.score) av,
               AVG(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END) fr,
               GROUP_CONCAT(DISTINCT t.name) teachers
        FROM fact_grade g JOIN dim_student s ON g.student_id=s.student_id
        JOIN dim_class cl ON s.class_id=cl.class_id
        LEFT JOIN fact_lesson l ON g.lesson_id=l.lesson_id AND g.semester_id=l.semester_id
        LEFT JOIN dim_teacher t ON l.teacher_id=t.teacher_id
        WHERE g.source='real' AND g.course_id=? AND g.semester_id=?
          AND g.is_pass IS NOT NULL{detail_and}
        GROUP BY s.class_id
        ORDER BY fr DESC, total DESC""",
        tuple([course_id, cur] + detail_params)):
        classDetail.append({"className": r["cls"], "students": r["total"],
                            "avgScore": round(r["av"] or 0, 1), "failRate": _pct(r["fr"]),
                            "teacher": (r["teachers"] or "—").replace(",", "、")})
    for index, row in enumerate(classDetail, start=1):
        row["riskRank"] = index
    nature = "专业必修" if co["is_required"] == 1 else "选修"
    return ok({"name": co["name"], "credits": co["credits"], "type": nature,
               "college": co["dept"] or "—", "kpi": kpi,
               "scoreDistribution": scoreDistribution, "history": history,
               "classDetail": classDetail,
               "classSummary": {
                   "totalAdministrativeClasses": len(classDetail),
                   "defaultDisplayLimit": None,
                   "sort": "按未通过人次率降序，同率按有效成绩人次降序",
               },
               "scope": {"restricted": restricted,
                         "label": "当前角色授权范围" if restricted else "全校"},
               "analysisScope": {
                   "collegeId": college_id,
                   "majorId": major_id,
                   "grade": grade,
                   "label": (
                       " / ".join(analysis_labels) + "修读范围"
                       if analysis_labels
                       else ("当前角色授权范围" if restricted else "全校该课程")
                   ),
                   "canExpandToSchool": not restricted and bool(analysis_labels),
               },
               "period": {"semester": cur},
               "coverage": {
                   "validResultAttempts": total,
                   "scoredAttempts": scored,
                   "scoreCoverageRate": _pct_number(scored, total),
               },
               "definitionVersion": "dashboard-v3",
               "evidence": {"real": ["真实成绩、学籍班级、教学任务与教师"],
                            "simulated": [],
                            "limitation": "课程可跨学院修读；本页全部成绩、趋势和班级明细均按当前角色可见学生范围统计。"}})

"""基础报表公共只读查询服务。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.etl.config import TS_DIR
from backend.etl.extract_ts import SEMESTERS

from .. import db as dbm, settings
from ..envelope import ApiError
from ..permission_context import has_action, v2_student_scope
from .catalog import ReportDefinition
from .rule_registry import RULE_VERSION, rules_for


FOCUS_ROSTER_REPORT_IDS = {"RPT-07", "RPT-08"}


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    return round(float(numerator) / float(denominator), 6) if denominator else None


def _rate_text(numerator: int, denominator: int) -> str:
    if not denominator:
        return "-"
    return f"{numerator}/{denominator}={numerator / denominator * 100:.2f}%"


def _count_rate_text(count: int, denominator: int) -> str:
    rate = _pct(count, denominator)
    return f"{count}（{'—' if rate is None else f'{rate * 100:.2f}%'}）"


def _source_mtime(path: str) -> str:
    return datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")


def _cet4_source_paths(semester_id: str, ts_dir: Path = TS_DIR) -> list[Path]:
    if semester_id not in SEMESTERS:
        raise ApiError("所选学期不在四级考试数据覆盖范围内", code=422, status_code=422)
    paths = [Path(ts_dir) / f"{semester}.db"
             for semester in SEMESTERS[:SEMESTERS.index(semester_id) + 1]]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise ApiError(
            "四级累计统计缺少历史学期源库：" + "、".join(missing),
            code=409, status_code=409,
        )
    return paths


def _cet4_source_fingerprint(semester_id: str, ts_dir: Path = TS_DIR) -> str:
    evidence = [
        (path.name, path.stat().st_size, path.stat().st_mtime_ns)
        for path in _cet4_source_paths(semester_id, ts_dir)
    ]
    raw = json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _focus_rule_metadata(conn: sqlite3.Connection, semester_id: str) -> dict:
    """Return the configured R2/R2W wording and the versions used by the snapshot."""
    items = []
    for row in dbm.query(conn, """SELECT rule_id,name,level,params,enabled
                                  FROM sys_alert_rule
                                  WHERE rule_id IN ('R2','R2W')
                                  ORDER BY CASE rule_id WHEN 'R2W' THEN 1 ELSE 2 END"""):
        try:
            params = json.loads(row.get("params") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            params = {}
        items.append({
            "ruleId": row["rule_id"], "name": row["name"], "level": row["level"],
            "description": params.get("text") or row["name"],
            "enabled": bool(row["enabled"]),
        })
    versions = [row["rule_version"] for row in dbm.query(conn, """
        SELECT DISTINCT rule_version FROM fact_alert
        WHERE semester_id=? AND is_active=1 AND rule_id IN ('R2','R2W')
          AND rule_version IS NOT NULL AND rule_version<>''
        ORDER BY rule_version
    """, (semester_id,))]
    return {
        "items": items,
        "versions": versions,
        "dedupDescription": "同一课程按课程去重；截至所选学期已有通过记录的课程不再计入。",
    }


def _rpt07_data_fingerprint(conn: sqlite3.Connection, semester_id: str) -> str:
    """Fingerprint every V1 source that can change either R2/R2W roster."""
    digest = hashlib.sha256()
    queries = [
        ("""SELECT student_id,rule_id,level,trigger_detail,semester_id,is_active,rule_version
             FROM fact_alert
             WHERE semester_id=? AND is_active=1 AND rule_id IN ('R2','R2W')
             ORDER BY student_id,rule_id""", (semester_id,)),
        ("""SELECT rule_id,name,level,params,enabled FROM sys_alert_rule
             WHERE rule_id IN ('R2','R2W') ORDER BY rule_id""", ()),
        ("""SELECT g.grade_id,g.student_id,g.course_id,g.semester_id,g.score,g.is_pass,g.credits,
                    c.name,c.credits
             FROM fact_grade g
             JOIN (SELECT DISTINCT student_id FROM fact_alert
                   WHERE semester_id=? AND is_active=1 AND rule_id IN ('R2','R2W')) a
               ON a.student_id=g.student_id
             LEFT JOIN dim_course c ON c.course_id=g.course_id
             WHERE g.semester_id<=?
             ORDER BY g.student_id,g.course_id,g.semester_id,g.grade_id""",
         (semester_id, semester_id)),
    ]
    for sql, params in queries:
        for row in conn.execute(sql, params).fetchall():
            digest.update(json.dumps(tuple(row), ensure_ascii=False,
                                     separators=(",", ":")).encode())
            digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def _v1_report_data_version(report: ReportDefinition, filters: dict) -> str:
    """只指纹化报表实际读取的V1业务记录，排除审计/控制写入造成的文件时间变化。"""
    if report.report_id not in {"RPT-06", *FOCUS_ROSTER_REPORT_IDS}:
        return "v1-not-used"
    if report.report_id == "RPT-06":
        return _cet4_source_fingerprint(filters["semesterId"])
    conn = dbm.get_conn()
    try:
        return _rpt07_data_fingerprint(conn, filters["semesterId"])
    finally:
        conn.close()


def _student_cte(context: dict, conn: sqlite3.Connection, *, entry_grade: int | None,
                 organization_id: str | None, major_code: str | None,
                 class_code: str | None,
                 additional_student_ids: set[str] | None = None) -> tuple[str, list[Any]]:
    scope_sql, scope_params = v2_student_scope(context, conn, "s")
    additional_student_ids = additional_student_ids or set()
    conditions = ["s.education_level='本科'", "s.student_status='在校'"]
    params: list[Any] = []
    if entry_grade is not None:
        grade_condition = "s.entry_grade=?"
        if additional_student_ids:
            grade_condition = f"(s.entry_grade=? OR s.student_id IN ({','.join('?' for _ in additional_student_ids)}))"
        conditions.append(grade_condition)
        params.extend([entry_grade, *sorted(additional_student_ids)])
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    for column, value in (("organization_id", organization_id),
                          ("major_code", major_code), ("class_code", class_code)):
        if value:
            conditions.append(f"s.{column}=?")
            params.append(value)
    sql = f"""
      students AS (
        SELECT s.student_id,s.display_name,s.gender,s.entry_grade,s.organization_id,
               COALESCE(o.name,s.organization_id,'未说明学院') organization_name,
               s.major_code,COALESCE(s.major_name,s.major_code,'未说明专业') major_name,
               COALESCE(s.class_code,'未说明班级') class_code
        FROM dim_student s
        LEFT JOIN dim_organization o ON o.organization_id=s.organization_id
        WHERE {' AND '.join(conditions)}
      )
    """
    return sql, params


def _students(conn: sqlite3.Connection, context: dict, filters: dict) -> list[dict]:
    cte, params = _student_cte(context, conn, **filters)
    return dbm.query(conn, f"WITH {cte} SELECT * FROM students ORDER BY organization_name,major_name,class_code,student_id", tuple(params))


def _title_scope_labels(conn: sqlite3.Connection, context: dict, filters: dict) -> dict[str, str]:
    """在结果为空时，仍按授权范围解析筛选项的学院、专业显示名。"""
    cte, params = _student_cte(
        context, conn, entry_grade=None,
        organization_id=filters.get("organization_id"),
        major_code=filters.get("major_code"), class_code=None,
    )
    row = dbm.query_one(
        conn,
        f"WITH {cte} SELECT organization_name,major_name FROM students LIMIT 1",
        tuple(params),
    ) or {}
    return {
        key: row[key]
        for key in ("organization_name", "major_name")
        if row.get(key)
    }


def _semester_cutoff(conn: sqlite3.Connection, semester_id: str) -> str:
    semester = conn.execute(
        "SELECT end_date FROM dim_semester WHERE semester_id=?",
        (semester_id,),
    ).fetchone()
    cutoff = semester["end_date"] if semester and semester["end_date"] else None
    if not cutoff:
        raise ApiError("所选学期未配置截止日期，无法计算留降级人数", code=422, status_code=422)
    return str(cutoff)


def _responsibility_grade(class_code: str | None, event_after_grade: Any) -> int | None:
    """优先取当前行政班中的严格年级段；缺失时回退正式异动后的年级。"""
    match = re.search(r"(?<!\d)(\d{2})(?=-\d)", str(class_code or ""))
    if match:
        return 2000 + int(match.group(1))
    try:
        return int(float(event_after_grade))
    except (TypeError, ValueError):
        return None


def _retained_demoted_students(conn: sqlite3.Connection, context: dict,
                                filters: dict, semester_id: str) -> list[dict]:
    """按当前责任年级归入报表括号口径的正式留/降级学生。"""
    cutoff = _semester_cutoff(conn, semester_id)
    scope_sql, scope_params = v2_student_scope(context, conn, "s")
    conditions = ["s.education_level='本科'", "s.student_status='在校'"]
    params: list[Any] = ["留级", "降级", cutoff]
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    for column, value in (("organization_id", filters.get("organization_id")),
                          ("major_code", filters.get("major_code")),
                          ("class_code", filters.get("class_code"))):
        if value:
            conditions.append(f"s.{column}=?")
            params.append(value)
    rows = dbm.query(conn, f"""
      WITH ranked_event AS (
        SELECT e.*,ROW_NUMBER() OVER (
          PARTITION BY e.student_id ORDER BY date(e.effective_at) DESC,e.source_row_no DESC
        ) rn
        FROM student_status_event e
        WHERE e.event_type IN (?,?) AND e.effective_at IS NOT NULL
          AND date(e.effective_at)<=date(?)
      )
      SELECT s.student_id,s.display_name,s.gender,s.entry_grade,s.organization_id,
             COALESCE(o.name,s.organization_id,'未说明学院') organization_name,
             s.major_code,COALESCE(s.major_name,s.major_code,'未说明专业') major_name,
             COALESCE(s.class_code,'未说明班级') class_code,e.after_grade
      FROM ranked_event e
      JOIN dim_student s ON s.student_id=e.student_id
      LEFT JOIN dim_organization o ON o.organization_id=s.organization_id
      WHERE e.rn=1 AND {' AND '.join(conditions)}
      ORDER BY organization_name,major_name,class_code,s.student_id
    """, tuple(params))
    target_grade = int(filters["entry_grade"])
    return [row for row in rows
            if _responsibility_grade(row.get("class_code"), row.get("after_grade")) == target_grade]


def _pair_states(conn: sqlite3.Connection, context: dict, filters: dict,
                 semester_id: str,
                 additional_student_ids: set[str] | None = None) -> list[dict]:
    student_cte, params = _student_cte(
        context, conn, **filters, additional_student_ids=additional_student_ids,
    )
    sql = f"""
      WITH {student_cte},
      valid AS (
        SELECT g.*,COALESCE(g.course_name,c.name,g.course_id) resolved_course_name,
               COALESCE(g.credits,c.credits,0) resolved_credits
        FROM grade_attempt g
        JOIN students s ON s.student_id=g.student_id
        LEFT JOIN dim_course c ON c.course_id=g.course_id
        WHERE g.semester_id=? AND g.is_published=1 AND g.is_void=0
          AND g.is_pass IS NOT NULL
      ),
      regular_ranked AS (
        SELECT v.*,ROW_NUMBER() OVER (
          PARTITION BY student_id,course_id ORDER BY source_row_no,attempt_id
        ) rn FROM valid v WHERE COALESCE(attempt_type,'regular') NOT IN ('makeup','retake')
      ),
      first_result AS (
        SELECT student_id,course_id,is_pass first_pass FROM regular_ranked WHERE rn=1
      ),
      effective_ranked AS (
        SELECT v.*,ROW_NUMBER() OVER (
          PARTITION BY student_id,course_id
          ORDER BY is_pass DESC,source_row_no DESC,attempt_id DESC
        ) rn FROM valid v
      ),
      effective_result AS (
        SELECT student_id,course_id,is_pass current_pass,
               COALESCE(total_score,score) effective_score,resolved_credits
        FROM effective_ranked WHERE rn=1
      ),
      pair_evidence AS (
        SELECT student_id,course_id,MAX(resolved_course_name) course_name,
               SUM(CASE WHEN attempt_type='makeup' THEN 1 ELSE 0 END) makeup_attempts,
               SUM(CASE WHEN attempt_type='makeup' AND is_pass=1 THEN 1 ELSE 0 END) makeup_pass
        FROM valid GROUP BY student_id,course_id
      )
      SELECT s.student_id studentId,s.display_name name,s.gender,
             s.organization_id organizationId,s.organization_name organizationName,
             s.major_code majorCode,s.major_name majorName,s.class_code classCode,
             p.course_id courseId,p.course_name courseName,
             f.first_pass firstPass,e.current_pass currentPass,
             e.effective_score effectiveScore,e.resolved_credits credits,
             p.makeup_attempts makeupAttempts,p.makeup_pass makeupPass
      FROM pair_evidence p
      JOIN students s ON s.student_id=p.student_id
      LEFT JOIN first_result f ON f.student_id=p.student_id AND f.course_id=p.course_id
      LEFT JOIN effective_result e ON e.student_id=p.student_id AND e.course_id=p.course_id
      ORDER BY s.organization_name,s.major_name,s.class_code,s.student_id,p.course_id
    """
    return dbm.query(conn, sql, tuple(params + [semester_id]))


def _group_students(students: list[dict], key_fn) -> dict[Any, list[dict]]:
    grouped: dict[Any, list[dict]] = defaultdict(list)
    for student in students:
        grouped[key_fn(student)].append(student)
    return grouped


def _failure_sets(pairs: list[dict]) -> tuple[set[str], set[str], dict[str, int]]:
    first, current = set(), set()
    doors: dict[str, int] = defaultdict(int)
    for row in pairs:
        if row.get("firstPass") == 0:
            first.add(row["studentId"])
        if row.get("currentPass") == 0:
            current.add(row["studentId"])
            doors[row["studentId"]] += 1
    return first, current, doors


def _report_01(students: list[dict], pairs: list[dict],
               retained_demoted_students: list[dict] | None = None) -> tuple[list[dict], dict]:
    first, current, _ = _failure_sets(pairs)
    retained_demoted_students = retained_demoted_students or []
    retained_demoted_ids = {student["student_id"] for student in retained_demoted_students}
    eligible = {row["studentId"] for row in pairs}
    all_ids = {student["student_id"] for student in students}
    if not all_ids:
        return [], {"studentCount": 0, "validGradeStudents": 0, "failedBeforeStudents": 0,
                    "failedBeforeRate": None, "failedAfterStudents": 0, "failedAfterRate": None,
                    "gradeCoverageRate": None, "retainedDemotedStudents": 0,
                    "failedBeforeRetainedDemotedStudents": 0,
                    "failedAfterRetainedDemotedStudents": 0, "unknownGenderStudents": 0}
    denominator = len(all_ids & eligible)
    categories = (
        ("total", "总人数", all_ids, retained_demoted_ids, None),
        ("failed-before", "已挂人数", all_ids & first, retained_demoted_ids & first, "已挂比例"),
        ("failed-after", "在挂人数", all_ids & current, retained_demoted_ids & current, "在挂比例"),
    )
    rows = []
    student_gender = {student["student_id"]: student.get("gender")
                      for student in [*students, *retained_demoted_students]}
    for category_key, label, ids, category_retained, rate_label in categories:
        category_rate = _pct(len(ids), denominator) if rate_label else None
        category = f"{label}（留降级）：{len(ids)}（{len(category_retained)}）"
        if rate_label:
            category += f"\n{rate_label}: {'—' if category_rate is None else f'{category_rate * 100:.2f}%'}"
        for gender in ("男", "女"):
            gender_ids = {student_id for student_id in ids
                          if student_gender.get(student_id) == gender}
            count = len(gender_ids)
            retained_count = sum(student_gender.get(student_id) == gender
                                 for student_id in category_retained)
            rows.append({"categoryKey": category_key, "category": category, "categoryRate": category_rate, "gender": gender,
                         "count": count, "retainedDemotedCount": retained_count,
                         "countDisplay": f"{count}（{retained_count}）",
                         "rate": _pct(count, denominator),
                         "rateDisplay": f"{count}/{denominator}="
                                        f"{'—' if not denominator else f'{count / denominator * 100:.2f}%'}"})
    summary = {"studentCount": len(all_ids), "validGradeStudents": denominator,
               "failedBeforeStudents": len(all_ids & first),
               "failedBeforeRate": _pct(len(all_ids & first), denominator),
               "failedAfterStudents": len(all_ids & current),
               "failedAfterRate": _pct(len(all_ids & current), denominator),
               "gradeCoverageRate": _pct(denominator, len(all_ids)),
               "retainedDemotedStudents": len(retained_demoted_ids),
               "failedBeforeRetainedDemotedStudents": len(retained_demoted_ids & first),
               "failedAfterRetainedDemotedStudents": len(retained_demoted_ids & current),
               "unknownGenderStudents": sum(gender not in {"男", "女"} for gender in student_gender.values())}
    return rows, summary


def _major_groups(students: list[dict]) -> dict[tuple, list[dict]]:
    return _group_students(students, lambda s: (
        s["organization_id"], s["organization_name"], s["major_code"], s["major_name"]))


def _report_02(students: list[dict], pairs: list[dict],
               retained_demoted_students: list[dict] | None = None) -> tuple[list[dict], dict]:
    # RPT-02 compares one closed cohort within the selected semester. A student
    # remains failed only when the same regular-first-failed student-course pair
    # is still failing after later valid attempts in that semester.
    first = {pair["studentId"] for pair in pairs if pair.get("firstPass") == 0}
    current = {
        pair["studentId"] for pair in pairs
        if pair.get("firstPass") == 0 and pair.get("currentPass") == 0
    }
    eligible = {pair["studentId"] for pair in pairs}
    retained_demoted_students = retained_demoted_students or []
    student_groups = _major_groups(students)
    retained_groups = _major_groups(retained_demoted_students)
    group_keys = list(student_groups)
    group_keys.extend(key for key in retained_groups if key not in student_groups)
    rows = []
    for key in group_keys:
        ids = {student["student_id"] for student in student_groups.get(key, [])}
        retained_ids = {student["student_id"] for student in retained_groups.get(key, [])}
        student_count = len(ids)
        failed_before = len(ids & first)
        failed_after = len(ids & current)
        retained_before = len(retained_ids & first)
        retained_after = len(retained_ids & current)
        rows.append({
            "organizationId": key[0], "organizationName": key[1],
            "majorCode": key[2], "majorName": key[3],
            "studentCount": student_count,
            "retainedDemotedStudents": len(retained_ids),
            "studentCountDisplay": f"{student_count}（{len(retained_ids)}）",
            "validGradeStudents": len(ids & eligible),
            "failedBeforeStudents": failed_before,
            "failedBeforeRetainedDemotedStudents": retained_before,
            "failedBeforeDisplay": f"{failed_before}（{retained_before}）",
            "failedBeforeRate": _pct(failed_before, student_count),
            "failedAfterStudents": failed_after,
            "failedAfterRetainedDemotedStudents": retained_after,
            "failedAfterDisplay": f"{failed_after}（{retained_after}）",
            "failedAfterRate": _pct(failed_after, student_count),
            "passRate": _pct(student_count - failed_after, student_count),
        })
    all_ids = {student["student_id"] for student in students}
    retained_ids = {student["student_id"] for student in retained_demoted_students}
    student_count = len(all_ids)
    failed_before = len(all_ids & first)
    failed_after = len(all_ids & current)
    retained_before = len(retained_ids & first)
    retained_after = len(retained_ids & current)
    summary = {
        "studentCount": student_count,
        "retainedDemotedStudents": len(retained_ids),
        "studentCountDisplay": f"{student_count}（{len(retained_ids)}）",
        "validGradeStudents": len(all_ids & eligible),
        "failedBeforeStudents": failed_before,
        "failedBeforeRetainedDemotedStudents": retained_before,
        "failedBeforeDisplay": f"{failed_before}（{retained_before}）",
        "failedBeforeRate": _pct(failed_before, student_count),
        "failedAfterStudents": failed_after,
        "failedAfterRetainedDemotedStudents": retained_after,
        "failedAfterDisplay": f"{failed_after}（{retained_after}）",
        "failedAfterRate": _pct(failed_after, student_count),
        "passRate": _pct(student_count - failed_after, student_count),
    }
    rows.sort(key=lambda row: (
        -(row["failedAfterRate"] or 0), -row["failedAfterStudents"], row["majorName"],
    ))
    if rows:
        rows.append({"majorName": "总体情况(留降级)", **summary, "isSummary": True})
    return rows, summary


def _report_03(students: list[dict], pairs: list[dict],
               retained_demoted_students: list[dict] | None = None) -> tuple[list[dict], dict]:
    _, current, _ = _failure_sets(pairs)
    eligible = {pair["studentId"] for pair in pairs}
    retained_demoted_students = retained_demoted_students or []
    student_groups = _major_groups(students)
    retained_groups = _major_groups(retained_demoted_students)
    group_keys = list(student_groups)
    group_keys.extend(key for key in retained_groups if key not in student_groups)
    rows = []
    for key in group_keys:
        members = student_groups.get(key, [])
        ids = {student["student_id"] for student in members}
        retained_ids = {student["student_id"] for student in retained_groups.get(key, [])}
        male = {student["student_id"] for student in members if student.get("gender") == "男"}
        female = {student["student_id"] for student in members if student.get("gender") == "女"}
        unknown = ids - male - female
        student_count = len(ids)
        retained_count = len(retained_ids)
        failed_students = len(ids & current)
        retained_failed = len(retained_ids & current)
        male_valid = len(male & eligible)
        male_failed = len(male & current)
        female_valid = len(female & eligible)
        female_failed = len(female & current)
        rows.append({
            "organizationName": key[1], "majorCode": key[2],
            "majorName": f"{key[3]}(留降级)",
            "studentCount": student_count,
            "retainedDemotedStudents": retained_count,
            "studentCountDisplay": f"{student_count}（{retained_count}）",
            "validGradeStudents": len(ids & eligible),
            "failedStudents": failed_students,
            "failedRetainedDemotedStudents": retained_failed,
            "failedStudentsDisplay": f"{failed_students}（{retained_failed}）",
            "failureRate": _pct(failed_students, len(ids & eligible)),
            "maleValidStudents": male_valid,
            "maleFailedStudents": male_failed,
            "maleFailureRate": _pct(male_failed, male_valid),
            "maleFailureDisplay": _rate_text(male_failed, male_valid),
            "femaleValidStudents": female_valid,
            "femaleFailedStudents": female_failed,
            "femaleFailureRate": _pct(female_failed, female_valid),
            "femaleFailureDisplay": _rate_text(female_failed, female_valid),
            "unknownGenderStudents": len(unknown),
        })
    all_ids = {student["student_id"] for student in students}
    retained_ids = {student["student_id"] for student in retained_demoted_students}
    all_eligible = all_ids & eligible
    male = {student["student_id"] for student in students if student.get("gender") == "男"}
    female = {student["student_id"] for student in students if student.get("gender") == "女"}
    failed_students = len(all_ids & current)
    retained_failed = len(retained_ids & current)
    summary = {
        "majorCount": len(rows),
        "studentCount": len(all_ids),
        "retainedDemotedStudents": len(retained_ids),
        "studentCountDisplay": f"{len(all_ids)}（{len(retained_ids)}）",
        "validGradeStudents": len(all_eligible),
        "failedStudents": failed_students,
        "failedRetainedDemotedStudents": retained_failed,
        "failedStudentsDisplay": f"{failed_students}（{retained_failed}）",
        "failureRate": _pct(failed_students, len(all_eligible)),
        "maleValidStudents": len(male & eligible),
        "maleFailedStudents": len(male & current),
        "maleFailureRate": _pct(len(male & current), len(male & eligible)),
        "maleFailureDisplay": _rate_text(len(male & current), len(male & eligible)),
        "femaleValidStudents": len(female & eligible),
        "femaleFailedStudents": len(female & current),
        "femaleFailureRate": _pct(len(female & current), len(female & eligible)),
        "femaleFailureDisplay": _rate_text(len(female & current), len(female & eligible)),
        "unknownGenderStudents": sum(student.get("gender") not in {"男", "女"} for student in students),
    }
    rows.sort(key=lambda row: (-(row["failureRate"] or 0), -row["failedStudents"], row["majorName"]))
    if rows:
        rows.append({"majorName": "总体情况(留降级)", **summary, "isSummary": True})
    return rows, summary


def _report_04a(students: list[dict], pairs: list[dict]) -> tuple[list[dict], dict]:
    _, _, doors = _failure_sets(pairs)
    groups = _group_students(students, lambda s: (s["organization_name"], s["major_name"], s["class_code"]))
    rows = []
    for key, members in groups.items():
        counts = [doors.get(s["student_id"], 0) for s in members]
        rows.append({"organizationName": key[0], "majorName": key[1], "classCode": key[2], "studentCount": len(counts),
                     "zeroCourse": sum(x == 0 for x in counts), "oneToTwo": sum(1 <= x <= 2 for x in counts),
                     "threeToFive": sum(3 <= x <= 5 for x in counts), "sixOrMore": sum(x >= 6 for x in counts)})
    all_counts = [doors.get(student["student_id"], 0) for student in students]
    summary = {"classCount": len(rows), "studentCount": len(students),
               "oneToTwo": sum(1 <= count <= 2 for count in all_counts),
               "threeToFive": sum(3 <= count <= 5 for count in all_counts),
               "sixOrMore": sum(count >= 6 for count in all_counts),
               "failedStudents": sum(count > 0 for count in all_counts)}
    if students:
        rows.append({"classCode": "总体情况", **summary, "isSummary": True})
    return rows, summary


def _report_04b(students: list[dict], pairs: list[dict]) -> tuple[list[dict], dict]:
    score_parts: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for p in pairs:
        if p.get("effectiveScore") is not None:
            score_parts[p["studentId"]].append((float(p["effectiveScore"]), float(p.get("credits") or 0)))
    averages = {}
    for sid, values in score_parts.items():
        credit_sum = sum(c for _, c in values)
        averages[sid] = (sum(score * credit for score, credit in values) / credit_sum
                         if credit_sum else sum(score for score, _ in values) / len(values))
    # 先在专业总体内排名，再回填到班级统计；不能在每个班内分别切20/30/30/20。
    major_groups = _group_students(students, lambda s: (s["organization_id"], s["major_code"]))
    rank_bucket: dict[str, int] = {}
    for members in major_groups.values():
        ranked = sorted(((averages[s["student_id"]], s["student_id"]) for s in members if s["student_id"] in averages), key=lambda x: (-x[0], x[1]))
        for index, (_, sid) in enumerate(ranked, 1):
            ratio = index / len(ranked)
            rank_bucket[sid] = 0 if ratio <= .2 else 1 if ratio <= .5 else 2 if ratio <= .8 else 3
    groups = _group_students(students, lambda s: (s["organization_name"], s["major_name"], s["class_code"]))
    rows = []
    for key, members in groups.items():
        ranked = [s for s in members if s["student_id"] in rank_bucket]
        buckets = [0, 0, 0, 0]
        for student in ranked:
            buckets[rank_bucket[student["student_id"]]] += 1
        rows.append({"organizationName": key[0], "majorName": key[1], "classCode": key[2], "studentCount": len(members), "rankedStudents": len(ranked),
                     "top20": buckets[0], "top20Rate": _pct(buckets[0], len(ranked)), "top20To50": buckets[1], "top20To50Rate": _pct(buckets[1], len(ranked)),
                     "top50To80": buckets[2], "top50To80Rate": _pct(buckets[2], len(ranked)), "bottom20": buckets[3], "bottom20Rate": _pct(buckets[3], len(ranked)),
                     "top20Display": _count_rate_text(buckets[0], len(ranked)), "top20To50Display": _count_rate_text(buckets[1], len(ranked)),
                     "top50To80Display": _count_rate_text(buckets[2], len(ranked)), "bottom20Display": _count_rate_text(buckets[3], len(ranked)),
                     "noGradeStudents": len(members) - len(ranked)})
    return rows, {"classCount": len(rows), "studentCount": len(students), "rankedStudents": len(averages)}


def _report_05(students: list[dict], pairs: list[dict]) -> tuple[list[dict], dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for p in pairs:
        groups[(p["organizationName"], p["majorCode"], p["majorName"], p["courseId"], p["courseName"])].append(p)
    major_populations: dict[tuple[str, str], int] = defaultdict(int)
    for student in students:
        major_populations[(student["organization_name"], student["major_code"])] += 1
    course_stats: dict[tuple[str, str], dict] = {}
    for pair in pairs:
        course_key = (pair["courseId"], pair["courseName"])
        stats = course_stats.setdefault(course_key, {"eligible": set(), "before": set(), "after": set()})
        if pair.get("firstPass") is not None:
            stats["eligible"].add(pair["studentId"])
        if pair.get("firstPass") == 0:
            stats["before"].add(pair["studentId"])
            if pair.get("currentPass") != 1:
                stats["after"].add(pair["studentId"])
    rows = []
    for key, items in groups.items():
        first_valid = [p for p in items if p.get("firstPass") is not None]
        first_fail = [p for p in first_valid if p["firstPass"] == 0]
        after_fail = [p for p in first_fail if p.get("currentPass") != 1]
        course_key = (key[3], key[4]); totals = course_stats[course_key]
        credits = max((float(p.get("credits") or 0) for p in items), default=0)
        makeup_passed = {p["studentId"] for p in items if p.get("firstPass") == 0 and int(p.get("makeupPass") or 0) > 0}
        rows.append({"organizationName": key[0], "majorCode": key[1], "majorName": key[2],
                     "courseId": key[3], "courseName": key[4], "courseKey": f"{key[3]}::{key[4]}",
                     "course": f"{key[4]}\n[{credits:g} 学分]", "majorStudentCount": major_populations[(key[0], key[1])],
                     "firstValidStudents": len(first_valid), "failedBeforeStudents": len(first_fail), "failedBeforeRate": _pct(len(first_fail), len(first_valid)),
                     "failedAfterStudents": len(after_fail), "failedAfterRate": _pct(len(after_fail), len(first_valid)),
                     "failedBeforeCourseTotal": len(totals["before"]),
                     "failedBeforeCourseRate": _pct(len(totals["before"]), len(totals["eligible"])),
                     "failedAfterCourseTotal": len(totals["after"]),
                     "failedAfterCourseRate": _pct(len(totals["after"]), len(totals["eligible"])),
                     "makeupPassedStudents": len(makeup_passed)})
    rows.sort(key=lambda row: (-row["failedAfterCourseTotal"], -row["failedBeforeCourseTotal"],
                               row["courseId"], row["organizationName"], row["majorName"]))
    return rows, {"courseMajorRows": len(rows), "courseCount": len(course_stats),
                  "failedAfterStudents": len({pair["studentId"] for pair in pairs if pair.get("currentPass") == 0})}


def _chunks(values: list[str], size: int = 800):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _r2_unresolved_evidence(conn: sqlite3.Connection, student_ids: set[str],
                            semester_id: str) -> dict[str, list[dict]]:
    """复算R2/R2W同口径课程：最近两学期失败，且截至所选学期没有通过记录。"""
    evidence: dict[str, list[dict]] = defaultdict(list)
    if not student_ids:
        return evidence
    if semester_id not in SEMESTERS:
        raise ApiError("所选学期不在重点关注规则覆盖范围内", code=422, status_code=422)
    semester_index = SEMESTERS.index(semester_id)
    recent_semesters = SEMESTERS[max(0, semester_index - 1):semester_index + 1]
    for part in _chunks(sorted(student_ids)):
        student_placeholders = ",".join("?" * len(part))
        semester_placeholders = ",".join("?" * len(recent_semesters))
        rows = dbm.query(conn, f"""
          WITH valid AS (
            SELECT g.*,COALESCE(c.name,g.course_id) resolved_course_name,
                   COALESCE(g.credits,c.credits,0) resolved_credits
            FROM fact_grade g
            LEFT JOIN dim_course c ON c.course_id=g.course_id
            WHERE g.student_id IN ({student_placeholders}) AND g.semester_id<=?
              AND g.is_pass IS NOT NULL
          ),
          passed AS (
            SELECT DISTINCT student_id,course_id FROM valid WHERE is_pass=1
          ),
          unresolved_ranked AS (
            SELECT v.*,ROW_NUMBER() OVER (
              PARTITION BY v.student_id,v.course_id
              ORDER BY v.semester_id DESC,v.grade_id DESC
            ) rn
            FROM valid v
            WHERE v.semester_id IN ({semester_placeholders}) AND v.is_pass=0
              AND NOT EXISTS (
                SELECT 1 FROM passed p
                WHERE p.student_id=v.student_id AND p.course_id=v.course_id
              )
          )
          SELECT student_id studentId,course_id courseId,
                 resolved_course_name courseName,resolved_credits credits,
                 score effectiveScore,semester_id semesterId
          FROM unresolved_ranked WHERE rn=1
          ORDER BY student_id,course_id
        """, tuple([*part, semester_id, *recent_semesters]))
        for row in rows:
            evidence[row["studentId"]].append(row)
    return evidence


def _cet4_passed_ids_as_of(student_ids: set[str], semester_id: str,
                           ts_dir: Path = TS_DIR) -> set[str]:
    """读取各学期真实考试明细，返回截至所选学期至少通过一次四级的学生。"""
    if not student_ids:
        return set()
    passed: set[str] = set()
    for path in _cet4_source_paths(semester_id, ts_dir):
        source = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro", uri=True,
        )
        try:
            rows = source.execute(
                """SELECT DISTINCT CAST(student_id AS TEXT)
                   FROM external_exams
                   WHERE exam_type=? AND is_passed=1""",
                ("全国大学英语四级",),
            ).fetchall()
            passed.update(str(row[0]) for row in rows if str(row[0]) in student_ids)
        except sqlite3.Error as exc:
            raise ApiError(
                f"读取四级考试学期源库失败（{path.name}）：{exc}",
                code=409, status_code=409,
            ) from exc
        finally:
            source.close()
    return passed


def _rank_cet4_rows(rows: list[dict]) -> None:
    """保持原行顺序并做稠密排名；同率同名次，空值不参与排名。"""
    rates = sorted({row["cet4PassRate"] for row in rows
                    if row.get("cet4PassRate") is not None}, reverse=True)
    rank_by_rate = {rate: index for index, rate in enumerate(rates, 1)}
    for row in rows:
        rate = row.get("cet4PassRate")
        row["cet4PassRateRank"] = rank_by_rate.get(rate) if rate is not None else None


def _report_06(students: list[dict], semester_id: str,
               ts_dir: Path = TS_DIR) -> tuple[list[dict], dict]:
    ids = {s["student_id"] for s in students}
    passed = _cet4_passed_ids_as_of(ids, semester_id, ts_dir)
    groups = _group_students(students, lambda s: (s["organization_name"], s["major_name"], s["class_code"]))
    rows = []
    for key, members in groups.items():
        member_ids = {s["student_id"] for s in members}; count = len(member_ids & passed)
        rows.append({"organizationName": key[0], "majorName": key[1], "classCode": key[2], "studentCount": len(member_ids), "cet4PassedStudents": count, "cet4PassRate": _pct(count, len(member_ids))})
    _rank_cet4_rows(rows)
    summary = {"studentCount": len(ids), "cet4PassedStudents": len(ids & passed),
               "cet4PassRate": _pct(len(ids & passed), len(ids)),
               "cumulativeThroughSemester": semester_id}
    if students:
        rows.append({"classCode": "年级总情况", **summary, "isSummary": True})
    return rows, summary


def _report_07(v1: sqlite3.Connection, v2: sqlite3.Connection, user: dict,
               students: list[dict], semester_id: str) -> tuple[list[dict], dict, str]:
    if not dbm.query_one(v1, "SELECT 1 FROM fact_alert WHERE semester_id=? LIMIT 1", (semester_id,)):
        return [], {}, "source_unavailable"
    allowed_ids = {s["student_id"] for s in students}; alert_rows = []
    for part in _chunks(sorted(allowed_ids)):
        placeholders = ",".join("?" * len(part))
        alert_rows.extend(dbm.query(v1, f"""SELECT student_id,rule_id,level,trigger_detail,rule_version
          FROM fact_alert WHERE semester_id=? AND is_active=1 AND rule_id IN ('R2','R2W')
          AND student_id IN ({placeholders}) ORDER BY student_id,rule_id""", tuple([semester_id] + part)))
    if not has_action(user, "student.detail"):
        return [], {"focusStudentCount": len({r['student_id'] for r in alert_rows})}, "detail_forbidden"
    alerts = {r["student_id"]: r for r in alert_rows}; student_map = {s["student_id"]: s for s in students}
    failures = _r2_unresolved_evidence(v1, set(alerts), semester_id)
    mentors: dict[str, str] = {}
    focus_ids = sorted(alerts)
    for part in _chunks(focus_ids):
        placeholders = ",".join("?" * len(part))
        for row in dbm.query(v2, f"""SELECT x.student_id,GROUP_CONCAT(DISTINCT COALESCE(f.display_name,x.staff_id)) mentor
          FROM staff_student_scope x LEFT JOIN dim_staff f ON f.staff_id=x.staff_id
          WHERE x.student_id IN ({placeholders}) AND x.relation_type IN ('学业导师','导师','mentor')
            AND COALESCE(x.status,'active')='active' GROUP BY x.student_id""", tuple(part)):
            mentors[row["student_id"]] = row.get("mentor") or "—"
    rows = []
    for sid in focus_ids:
        s = student_map[sid]; a = alerts[sid]
        evidence = sorted(failures.get(sid, []), key=lambda row: row["courseId"])
        failed_credits = round(sum(float(row.get("credits") or 0) for row in evidence), 2)
        evidence_lines = []
        for row in evidence:
            score_text = "" if row.get("effectiveScore") is None else f" {float(row['effectiveScore']):g}分"
            evidence_lines.append(
                f"{row['semesterId']} {row['courseId']} {row['courseName']}"
                f"（{float(row.get('credits') or 0):g}学分）{score_text}"
            )
        evidence_text = "\n".join(evidence_lines)
        rows.append({"studentId": sid, "name": s["display_name"], "organizationName": s["organization_name"],
                     "majorName": s["major_name"], "classCode": s["class_code"], "majorClass": f"{s['major_name']} {s['class_code']}",
                     "mentor": mentors.get(sid, "—"), "failedCredits": failed_credits,
                     "ruleId": a["rule_id"], "level": a["level"], "ruleVersion": a["rule_version"],
                     "unresolvedCourseCount": len(failures.get(sid, [])),
                     "courseEvidence": evidence_text, "triggerDetail": a["trigger_detail"]})
    rows.sort(key=lambda row: (-row["unresolvedCourseCount"], -row["failedCredits"], row["studentId"]))
    for index, row in enumerate(rows, 1):
        row["sequence"] = index
    return rows, {"focusStudentCount": len(rows), "seriousCount": sum(r["ruleId"] == "R2" for r in rows), "watchCount": sum(r["ruleId"] == "R2W" for r in rows)}, "available"


def options(v2: sqlite3.Connection, user: dict) -> dict:
    context = user["permission_context"]
    scope_sql, scope_params = v2_student_scope(context, v2, "s")
    where = ["s.education_level='本科'", "s.student_status='在校'"]
    if scope_sql: where.append(scope_sql)
    students = dbm.query(v2, f"""SELECT DISTINCT s.entry_grade entryGrade,s.organization_id organizationId,
      COALESCE(o.name,s.organization_id) organizationName,s.major_code majorCode,
      COALESCE(s.major_name,s.major_code) majorName,s.class_code classCode
      FROM dim_student s LEFT JOIN dim_organization o ON o.organization_id=s.organization_id
      WHERE {' AND '.join(where)} AND s.entry_grade IS NOT NULL
      ORDER BY s.entry_grade DESC,organizationName,majorName,classCode""", tuple(scope_params))
    semesters = dbm.query(v2, f"""SELECT DISTINCT g.semester_id value FROM grade_attempt g JOIN dim_student s ON s.student_id=g.student_id
      WHERE {' AND '.join(where)} AND g.is_published=1 AND g.is_void=0 AND g.is_pass IS NOT NULL
      ORDER BY g.semester_id DESC""", tuple(scope_params))
    return {"semesters": [r["value"] for r in semesters], "entryGrades": sorted({r["entryGrade"] for r in students}, reverse=True),
            "organizations": sorted({(r["organizationId"], r["organizationName"]) for r in students if r["organizationId"]}),
            "majors": [{"organizationId": r["organizationId"], "majorCode": r["majorCode"], "majorName": r["majorName"]} for r in students if r["majorCode"]],
            "classes": [{"majorCode": r["majorCode"], "classCode": r["classCode"]} for r in students if r["classCode"]],
            "identity": {"id": context["activeIdentityId"], "role": context["activeRoleName"], "scope": context["detailScope"]},
            "capabilities": {"export": has_action(user, "export.authorized"),
                             "studentDetail": has_action(user, "student.detail")}}


def _token(report: ReportDefinition, user: dict, filters: dict) -> str:
    payload = {"report": report.report_id, "scope": user["permission_context"]["scopeFingerprint"], "filters": filters,
               "v1Business": _v1_report_data_version(report, filters), "v2": _source_mtime(settings.V2_DB_PATH), "rules": RULE_VERSION}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(settings.JWT_SECRET.encode(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + b"." + signature).decode().rstrip("=")


def validate_token(token: str, report: ReportDefinition, user: dict, filters: dict) -> None:
    if not token or not hmac.compare_digest(token, _token(report, user, filters)):
        raise ApiError("查询快照已变化，请重新查询后导出", code=409, status_code=409)


def _report_title(report: ReportDefinition, semester_id: str, entry_grade: int | None,
                  students: list[dict], filters: dict) -> str:
    if report.report_id == "RPT-01":
        return f"本科{entry_grade} 级总体挂科情况"
    if report.report_id not in {"RPT-02", "RPT-04A", "RPT-04B", "RPT-05", "RPT-06", *FOCUS_ROSTER_REPORT_IDS}:
        return f"{semester_id} 学期本科 {entry_grade} 级{report.title}"
    parts: list[str] = []
    if filters.get("organization_id"):
        parts.append(filters.get("organization_name") or next(
            (row["organization_name"] for row in students if row.get("organization_name")),
            filters["organization_id"],
        ))
    if filters.get("major_code"):
        parts.append(filters.get("major_name") or next(
            (row["major_name"] for row in students if row.get("major_name")),
            filters["major_code"],
        ))
    if report.report_id not in {"RPT-02", "RPT-04A", "RPT-05"} and filters.get("class_code"):
        parts.append(str(filters["class_code"]))
    scope_text = (" " + " ".join(parts)) if parts else ""
    grade_text = f" {entry_grade} 级" if entry_grade is not None else ""
    if report.report_id == "RPT-02":
        return f"{semester_id} 学期 {entry_grade} 级{scope_text} 各专业补考前后挂科率比较"
    if report.report_id == "RPT-04A":
        return f"{semester_id} 学期 {entry_grade} 级{scope_text} 各班级挂科门数具体情况"
    if report.report_id == "RPT-04B":
        report_name = "成绩分布" if filters.get("class_code") else "各班级成绩分布"
        return f"{semester_id} 学期 {entry_grade} 级{scope_text} {report_name}"
    if report.report_id == "RPT-05":
        return f"{semester_id} 学期{grade_text}{scope_text} 补考前后课程通过情况对比"
    if report.report_id in FOCUS_ROSTER_REPORT_IDS:
        return f"{semester_id} 学期{grade_text}{scope_text} {report.title}"
    report_name = "大学英语四级通过情况" if filters.get("class_code") else "各班大学英语四级通过情况"
    return f"{semester_id} 学期{grade_text}{scope_text} {report_name}"


def build_report(v1: sqlite3.Connection, v2: sqlite3.Connection, user: dict,
                 report: ReportDefinition, *, semester_id: str, entry_grade: int | None,
                 organization_id: str | None = None, major_code: str | None = None,
                 class_code: str | None = None) -> dict:
    context = user["permission_context"]
    if report.menu_path not in set(context.get("menuPermissions") or []):
        raise ApiError("当前工作身份没有该报表菜单权限", code=403, status_code=403)
    supplied = {"semesterId": semester_id, "entryGrade": entry_grade, "organizationId": organization_id,
                "majorCode": major_code, "classCode": class_code}
    labels = {"semesterId": "学年学期", "entryGrade": "年级" if report.report_id in {"RPT-02", "RPT-03", "RPT-04A", "RPT-04B", "RPT-05", "RPT-06", *FOCUS_ROSTER_REPORT_IDS} else "入学年级", "organizationId": "学院",
              "majorCode": "专业", "classCode": "班级"}
    missing = [labels[key] for key in report.required_filters if supplied.get(key) in {None, "", 0}]
    if missing:
        raise ApiError(f"必选查询条件不能为空：{'、'.join(missing)}", code=422, status_code=422)
    filters = {"entry_grade": entry_grade, "organization_id": organization_id, "major_code": major_code, "class_code": class_code}
    students = _students(v2, context, filters)
    title_filters = filters
    if report.report_id in {"RPT-02", "RPT-04A", "RPT-04B"} and not students:
        title_filters = {**filters, **_title_scope_labels(v2, context, filters)}
    retained_demoted_students = (
        _retained_demoted_students(v2, context, filters, semester_id)
        if report.report_id in {"RPT-01", "RPT-02", "RPT-03"} else []
    )
    additional_student_ids = {student["student_id"] for student in retained_demoted_students}
    pairs = [] if report.report_id in {"RPT-06", "RPT-07", "RPT-08"} else _pair_states(
        v2, context, filters, semester_id,
        additional_student_ids=additional_student_ids if report.report_id in {"RPT-01", "RPT-02", "RPT-03"} else None,
    )
    status = "available"
    if report.report_id == "RPT-01":
        rows, summary = _report_01(students, pairs, retained_demoted_students)
    elif report.report_id == "RPT-02": rows, summary = _report_02(students, pairs, retained_demoted_students)
    elif report.report_id == "RPT-03": rows, summary = _report_03(students, pairs, retained_demoted_students)
    elif report.report_id == "RPT-04A": rows, summary = _report_04a(students, pairs)
    elif report.report_id == "RPT-04B": rows, summary = _report_04b(students, pairs)
    elif report.report_id == "RPT-05": rows, summary = _report_05(students, pairs)
    elif report.report_id == "RPT-06": rows, summary = _report_06(students, semester_id)
    elif report.report_id in FOCUS_ROSTER_REPORT_IDS: rows, summary, status = _report_07(v1, v2, user, students, semester_id)
    else:
        rows, summary, status = [], {}, "source_unavailable"
    total = len(rows)
    token_filters = {"semesterId": semester_id, "entryGrade": entry_grade, "organizationId": organization_id, "majorCode": major_code, "classCode": class_code}
    boundary = ["只读报表，不产生或回写业务数据", "成绩采用已发布、未作废且通过状态明确的记录"]
    if report.report_id == "RPT-06": boundary.append(
        "四级通过人数按 external_exams 真实考试明细累计：截至所选学期至少存在一次“全国大学英语四级”明确通过记录的学生去重计数；重复通过不重复累计"
    )
    if report.report_id == "RPT-01": boundary.append(
        "留降级人数取 student_status_event 中截至所选学期末已生效的“留级/降级”正式异动，"
        "按当前行政班责任年级归入括号口径，再分别计算总人数、已挂、在挂及男女分组；“保留学籍”不计入"
    )
    if report.report_id == "RPT-02": boundary.append(
        "专业人数、已挂人数、在挂人数括号内分别显示同范围留降级人数；留降级沿用正式异动和责任年级口径，"
        "不并入主人数及比率分母；补考前后限定同一所选学期、同一普通考试首次不及格学生课程集合，"
        "在挂人数不得大于已挂人数；补考前后挂科率分别为已挂人数、在挂人数除以专业人数，"
        "通过率为（专业人数－在挂人数）除以专业人数"
    )
    if report.report_id == "RPT-03": boundary.append(
        "专业名称标注留降级口径；专业人数、整体挂科人数括号内分别显示同专业留降级人数，"
        "留降级沿用正式异动和责任年级口径，不并入主人数及比率分母；男、女生挂科率按各自有效成绩人数计算，"
        "分母为0时显示“-”"
    )
    if report.report_id == "RPT-04A": boundary.append("原表列名保留为“5科以上”；计算按大于5科，即6科及以上，避免与3-5科重复")
    if report.report_id in FOCUS_ROSTER_REPORT_IDS: boundary.append(
        "名单成员复用R2/R2W已发布活动预警；课程证据按截至所选学期的最近2学期复算，"
        "不同课程去重，已有通过记录的课程不再计入"
    )
    if report.report_id in FOCUS_ROSTER_REPORT_IDS and status == "source_unavailable": boundary.append(
        "所选学期没有已接入的预警快照，不能把数据缺失解释为0名名单学生"
    )
    if status == "detail_forbidden": boundary.append("当前身份缺少 student.detail，仅返回授权范围内人数汇总")
    focus_rule = _focus_rule_metadata(v1, semester_id) if report.report_id in FOCUS_ROSTER_REPORT_IDS else None
    return {"reportId": report.report_id,
            "title": _report_title(report, semester_id, entry_grade, students, title_filters),
            "status": status,
            "context": {"identity": context["activeRoleName"], "scope": context["detailScope"], **token_filters,
                        "dataCutoff": {"grades": _source_mtime(settings.V2_DB_PATH), "control": _source_mtime(settings.DB_PATH)}, "ruleVersion": RULE_VERSION},
            "rows": rows, "summary": summary, "total": total,
            "snapshotToken": _token(report, user, token_filters), "rules": rules_for(report.report_id), "boundary": boundary,
            "focusRule": focus_rule,
            "capabilities": {"export": has_action(user, "export.authorized") and status not in {"source_unavailable", "detail_forbidden"},
                             "studentDetail": has_action(user, "student.detail")}}

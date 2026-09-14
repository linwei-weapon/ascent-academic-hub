"""学生成长与学业变化的可解释管理口径。

本模块只基于当前授权范围内的学籍、真实成绩、课程有效结果和预警事件，
形成相邻学期变化、管理关注分组和组织汇总。它不生成综合风险分。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Optional

from . import db as dbm
from .deps import student_data_scope
from .envelope import ApiError
from .historical_roster import read_historical_roster

GPA_CHANGE_THRESHOLD = 0.3
RULE_VERSION = "student-growth-v2"
ENROLLED_STATUSES = {"在校", "在籍"}


def resolve_semester_pair(
    conn: sqlite3.Connection,
    from_semester: Optional[str],
    to_semester: Optional[str],
) -> tuple[str, str]:
    semesters = [
        row["semester_id"] for row in dbm.query(conn, """
            SELECT DISTINCT semester_id FROM fact_grade
            WHERE source='real' AND is_pass IS NOT NULL
            ORDER BY semester_id""")
    ]
    if len(semesters) < 2:
        raise ApiError("当前数据不足两个可比较学期", code=422, status_code=422)
    start = from_semester or semesters[-2]
    target = to_semester or semesters[-1]
    if start not in semesters or target not in semesters or start >= target:
        raise ApiError("起始学期必须早于目标学期，且均有真实成绩数据",
                       code=400, status_code=400)
    return start, target


def _scope_students(
    conn: sqlite3.Connection,
    user: dict,
    college: Optional[str] = None,
    major: Optional[str] = None,
    grade: Optional[str] = None,
    class_id: Optional[str] = None,
) -> list[dict]:
    conds, params = [], []
    for field, value in (
        ("college_id", college), ("major_id", major),
        ("grade", grade), ("class_id", class_id),
    ):
        if value:
            conds.append(f"{field}=?")
            params.append(value)
    scope_frag, scope_params = student_data_scope(user, conn, "dim_student")
    if scope_frag:
        conds.append(scope_frag)
        params.extend(scope_params)
    where = " WHERE " + " AND ".join(conds) if conds else ""
    return [dict(row) for row in dbm.query(conn, f"""
        SELECT student_id,name,college_id,major_id,class_id,grade,status
        FROM dim_student{where} ORDER BY student_id""", tuple(params))]


def _comparison_cohort(
    conn: sqlite3.Connection,
    students: list[dict],
    start: str,
    target: str,
    roster_dir: Optional[Path],
) -> tuple[set[str], set[str]]:
    """Return the in-school roster union and intersection for two terms."""
    authorized_ids = [str(row["student_id"]) for row in students]
    term_ids: list[set[str]] = []
    for semester in (start, target):
        roster = read_historical_roster(
            conn,
            semester,
            scope_type="school",
            authorized_student_ids=authorized_ids,
            scope_fingerprint="student-growth-comparison",
            ts_dir=roster_dir,
        )
        if not roster.get("available"):
            reason = roster.get("unavailableReason") or "对应学期在籍名单不可用"
            raise ApiError(
                f"{semester}在籍学生名单不可用，无法计算可比较学生：{reason}",
                code=422,
                status_code=422,
            )
        term_ids.append({
            str(row["studentId"])
            for row in roster.get("students", [])
            if str(row.get("status") or "").strip() in ENROLLED_STATUSES
        })
    return term_ids[0] | term_ids[1], term_ids[0] & term_ids[1]


def _term_facts(
    conn: sqlite3.Connection,
    semesters: tuple[str, str],
) -> dict[str, dict[str, dict]]:
    facts: dict[str, dict[str, dict]] = defaultdict(dict)
    rows = dbm.query(conn, """
        SELECT g.student_id,g.semester_id,g.weighted_gpa gpa,
               g.grade_count,g.fail_count
        FROM agg_student_term_growth g
        JOIN temp_student_growth_scope scope
          ON scope.student_id=g.student_id
        WHERE g.semester_id IN (?,?)""", semesters)
    for row in rows:
        facts[row["student_id"]][row["semester_id"]] = {
            "gpa": row["gpa"],
            "gradeCount": row["grade_count"] or 0,
            "failCount": row["fail_count"] or 0,
        }
    return facts


def _historical_failed_students(
    conn: sqlite3.Connection,
    before_semester: str,
) -> set[str]:
    return {row["student_id"] for row in dbm.query(conn, """
        SELECT DISTINCT g.student_id FROM fact_grade g
        JOIN temp_student_growth_scope scope ON scope.student_id=g.student_id
        WHERE g.source='real' AND g.is_pass=0 AND g.semester_id<?
    """, (before_semester,))}


def _open_alert_counts(
    conn: sqlite3.Connection,
) -> dict[str, int]:
    return {row["student_id"]: row["n"] for row in dbm.query(conn, """
        SELECT event.student_id,COUNT(*) n FROM alert_event event
        JOIN temp_student_growth_scope scope
          ON scope.student_id=event.student_id
        WHERE event.workflow_status NOT IN ('resolved','closed')
        GROUP BY event.student_id
    """)}


def _unresolved_course_outcomes(conn: sqlite3.Connection) -> dict:
    result: dict[str, dict[str, dict]] = {}
    rows = dbm.query(conn, """
        SELECT outcome.student_id,outcome.course_id,
               outcome.latest_semester semester_id,
               outcome.latest_credits credits,outcome.latest_score score,
               outcome.latest_gpa gpa,outcome.fail_count,
               outcome.fail_semesters
        FROM agg_student_course_outcome outcome
        JOIN temp_student_growth_scope scope
          ON scope.student_id=outcome.student_id
        WHERE outcome.latest_is_pass=0 AND outcome.fail_count>0
        ORDER BY outcome.student_id,outcome.course_id
    """)
    for row in rows:
        result.setdefault(row["student_id"], {})[row["course_id"]] = {
            "courseId": row["course_id"],
            "failCount": row["fail_count"],
            "failSemesters": (
                row["fail_semesters"].split(",")
                if row["fail_semesters"] else []
            ),
            "latestSemester": row["semester_id"],
            "status": "当前未解决",
            "repeatedUnresolved": row["fail_count"] >= 2,
        }
    return result


def _classification(gpa_delta: Optional[float], fail_delta: int) -> str:
    gpa_improved = gpa_delta is not None and gpa_delta >= GPA_CHANGE_THRESHOLD
    gpa_declined = gpa_delta is not None and gpa_delta <= -GPA_CHANGE_THRESHOLD
    improved = (
        (gpa_improved and fail_delta <= 0)
        or (fail_delta <= -1 and not gpa_declined)
    )
    declined = (
        (gpa_declined and fail_delta >= 0)
        or (fail_delta >= 1 and not gpa_improved)
    )
    if improved and declined:
        return "mixed"
    if improved:
        return "improved"
    if declined:
        return "declined"
    return "stable"


def _metric(
    key: str,
    label: str,
    count: int,
    denominator: int,
    meaning: str,
    tone: str,
) -> dict:
    rate = round(count / denominator * 100, 1) if denominator else None
    return {
        "key": key, "label": label, "count": count,
        "denominator": denominator, "rate": rate, "tone": tone,
        "value": f"{count:,}人",
        "sub": f"{count:,}/{denominator:,}人"
               + (f" · {rate}%" if rate is not None else " · 暂不可计算"),
        "meaning": meaning,
    }


def _organization_rows(
    rows: list[dict],
    group_level: str,
    names: dict[str, dict[str, str]],
) -> tuple[str, list[dict]]:
    if group_level == "college":
        field, label = "collegeId", "学院"
        name_map = names["college"]
    elif group_level == "major":
        field, label = "majorId", "专业"
        name_map = names["major"]
    else:
        field, label = "classId", "行政班"
        name_map = names["class"]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.get(field) or "UNASSIGNED"].append(row)
    result = []
    for org_id, members in grouped.items():
        total = len(members)
        comparable = sum(bool(item["comparable"]) for item in members)
        grade_evidence_comparable = sum(
            bool(item["hasGradeEvidenceInBothTerms"]) for item in members
        )
        declined = sum(item["category"] == "declined" for item in members)
        result.append({
            "organizationId": org_id,
            "organizationName": name_map.get(
                org_id, "未分配" if org_id == "UNASSIGNED" else org_id),
            "studentCount": total,
            "comparableCount": comparable,
            "gradeEvidenceComparableCount": grade_evidence_comparable,
            "coverageRate": round(comparable / total * 100, 1) if total else None,
            "declinedCount": declined,
            "declinedRate": round(
                declined / grade_evidence_comparable * 100, 1
            ) if grade_evidence_comparable else None,
            "continuousCount": sum(item["continuous"] for item in members),
            "firstSetbackCount": sum(item["firstSetback"] for item in members),
            "repeatedUnresolvedCount": sum(
                item["repeatedUnresolved"] for item in members),
            "openAlertCount": sum(bool(item["openAlerts"]) for item in members),
        })
    result.sort(key=lambda item: (
        -item["repeatedUnresolvedCount"], -item["continuousCount"],
        -item["declinedCount"], item["organizationName"],
    ))
    return label, result


def build_growth_snapshot(
    conn: sqlite3.Connection,
    user: dict,
    from_semester: Optional[str] = None,
    to_semester: Optional[str] = None,
    college: Optional[str] = None,
    major: Optional[str] = None,
    grade: Optional[str] = None,
    class_id: Optional[str] = None,
    roster_dir: Optional[Path] = None,
) -> dict:
    start, target = resolve_semester_pair(conn, from_semester, to_semester)
    students = _scope_students(
        conn, user, college=college, major=major, grade=grade,
        class_id=class_id,
    )
    cohort_ids, comparable_ids = _comparison_cohort(
        conn, students, start, target, roster_dir,
    )
    students = [
        row for row in students if str(row["student_id"]) in cohort_ids
    ]
    ids = [row["student_id"] for row in students]
    conn.execute("DROP TABLE IF EXISTS temp_student_growth_scope")
    conn.execute(
        "CREATE TEMP TABLE temp_student_growth_scope("
        "student_id TEXT PRIMARY KEY)"
    )
    conn.executemany(
        "INSERT INTO temp_student_growth_scope(student_id) VALUES(?)",
        [(student_id,) for student_id in ids],
    )
    try:
        facts = _term_facts(conn, (start, target))
        historical_failed = _historical_failed_students(conn, target)
        course_outcomes = _unresolved_course_outcomes(conn)
        open_alerts = _open_alert_counts(conn)
    finally:
        conn.execute("DROP TABLE IF EXISTS temp_student_growth_scope")
    course_names = {
        row["course_id"]: row["name"] for row in dbm.query(
            conn, "SELECT course_id,name FROM dim_course")
    }
    college_names = {
        row["college_id"]: row["name"] for row in dbm.query(
            conn, "SELECT college_id,name FROM dim_college")
    }
    major_names = {
        row["major_id"]: row["name"] for row in dbm.query(
            conn, "SELECT major_id,name FROM dim_major")
    }
    class_names = {
        row["class_id"]: row["name"] for row in dbm.query(
            conn, "SELECT class_id,name FROM dim_class")
    }
    low_grades = set(sorted(
        {str(row["grade"]) for row in students if row.get("grade")},
        reverse=True,
    )[:2])

    rows = []
    for student in students:
        sid = student["student_id"]
        old = facts.get(sid, {}).get(start)
        new = facts.get(sid, {}).get(target)
        comparable = sid in comparable_ids
        has_grade_evidence_in_both_terms = bool(old and new)
        old_gpa = old.get("gpa") if old else None
        new_gpa = new.get("gpa") if new else None
        gpa_delta = (
            new_gpa - old_gpa
            if old_gpa is not None and new_gpa is not None else None
        )
        old_fail = old.get("failCount", 0) if old else 0
        new_fail = new.get("failCount", 0) if new else 0
        fail_delta = (
            new_fail - old_fail if has_grade_evidence_in_both_terms else None
        )
        category = (
            _classification(gpa_delta, fail_delta)
            if has_grade_evidence_in_both_terms and fail_delta is not None
            else "insufficient"
        )
        outcomes = course_outcomes.get(sid, {})
        unresolved = list(outcomes.values())
        repeated = [
            item for item in unresolved if item["repeatedUnresolved"]
        ]
        continuous = bool(
            has_grade_evidence_in_both_terms
            and old_fail > 0
            and new_fail > 0
        )
        first_setback = bool(
            student.get("grade") in low_grades
            and new_fail > 0 and sid not in historical_failed
        )
        triggers = []
        if category == "declined":
            triggers.append("明确恶化")
        if continuous:
            triggers.append("连续受挫")
        if first_setback:
            triggers.append("低年级首次受挫")
        if repeated:
            triggers.append("重复未解决")
        if continuous and repeated:
            priority = 1
        elif first_setback:
            priority = 2
        elif category == "declined" and (fail_delta or 0) > 0:
            priority = 3
        elif category == "declined":
            priority = 4
        else:
            priority = 5
        rows.append({
            "sid": sid, "name": student["name"] or sid,
            "collegeId": student["college_id"],
            "college": college_names.get(student["college_id"],
                                         student["college_id"]),
            "majorId": student["major_id"],
            "major": major_names.get(student["major_id"], student["major_id"]),
            "classId": student["class_id"] or "",
            "className": class_names.get(student["class_id"],
                                         student["class_id"] or "未分班"),
            "grade": student["grade"],
            "comparable": comparable,
            "hasGradeEvidenceInBothTerms": has_grade_evidence_in_both_terms,
            "category": category,
            "fromGpa": round(old_gpa, 2) if old_gpa is not None else None,
            "toGpa": round(new_gpa, 2) if new_gpa is not None else None,
            "gpaDelta": round(gpa_delta, 2) if gpa_delta is not None else None,
            "fromFailCount": old_fail if old else None,
            "toFailCount": new_fail if new else None,
            "failDelta": fail_delta,
            "continuous": continuous, "firstSetback": first_setback,
            "repeatedUnresolved": bool(repeated),
            "unresolvedCourseCount": len(unresolved),
            "unresolvedCourses": [
                course_names.get(item["courseId"], item["courseId"])
                for item in unresolved[:5]
            ],
            "repeatedCourses": [
                course_names.get(item["courseId"], item["courseId"])
                for item in repeated[:5]
            ],
            "openAlerts": open_alerts.get(sid, 0),
            "triggers": triggers, "priority": priority,
        })

    total = len(rows)
    comparable = sum(item["comparable"] for item in rows)
    grade_evidence_comparable = sum(
        item["hasGradeEvidenceInBothTerms"] for item in rows
    )
    improved = sum(item["category"] == "improved" for item in rows)
    declined = sum(item["category"] == "declined" for item in rows)
    continuous = sum(item["continuous"] for item in rows)
    first_setback = sum(item["firstSetback"] for item in rows)
    repeated = sum(item["repeatedUnresolved"] for item in rows)
    metrics = [
        _metric(
            "comparable", "可比较学生", comparable, total,
            "两个参与学期均在籍；用于判断参与学期学生的可比较覆盖。",
            "primary",
        ),
        _metric(
            "improved", "明确改善学生", improved,
            grade_evidence_comparable,
            "GPA明显上升且挂科未增加，或挂科减少且GPA未明显下降。",
            "teal",
        ),
        _metric(
            "declined", "明确恶化学生", declined,
            grade_evidence_comparable,
            "GPA明显下降且挂科未减少，或挂科增加且GPA未明显上升。",
            "danger",
        ),
        _metric(
            "continuous", "连续受挫学生", continuous,
            grade_evidence_comparable,
            "起始学期和目标学期均至少有1门未通过课程。",
            "amber",
        ),
        _metric(
            "first_setback", "低年级首次受挫", first_setback, total,
            "当前两个低年级群体在目标学期首次出现可观测未通过记录。",
            "danger",
        ),
        _metric(
            "repeated_unresolved", "重复未解决", repeated, total,
            "同一课程至少两次未通过且最新有效结果仍未通过",
            "danger",
        ),
    ]
    groups = [
        {
            "key": "declined", "label": "明确恶化", "count": declined,
            "description": "相邻学期GPA或未通过课程出现明确负向变化",
        },
        {
            "key": "continuous", "label": "连续受挫", "count": continuous,
            "description": "起始和目标学期均有未通过课程",
        },
        {
            "key": "first_setback", "label": "低年级首次受挫",
            "count": first_setback,
            "description": "低年级学生首次出现可观测未通过记录",
        },
        {
            "key": "repeated_unresolved", "label": "重复未解决",
            "count": repeated,
            "description": "同一课程至少两次未通过且最新有效结果仍未通过",
        },
    ]
    detail_type = (
        (user.get("permission_context") or {}).get("detailScope") or {}
    ).get("type") or "all"
    if class_id or major:
        organization_level = "class"
    elif college:
        organization_level = "major"
    elif detail_type == "all":
        organization_level = "college"
    elif detail_type == "college":
        organization_level = "major"
    else:
        organization_level = "class"
    org_label, organizations = _organization_rows(
        rows, organization_level,
        {"college": college_names, "major": major_names, "class": class_names},
    )
    aggregate_meta_row = conn.execute("""
        SELECT refreshed_at,source_grade_rows,source_student_count,
               semester_min,semester_max,rule_version
        FROM agg_student_growth_meta WHERE singleton_id=1
    """).fetchone()
    aggregate_meta = dict(aggregate_meta_row) if aggregate_meta_row else {}
    return {
        "period": {"fromSemester": start, "toSemester": target},
        "comparisonBoard": {
            "title": "可比较学生情况看板",
            "fromSemester": start,
            "toSemester": target,
            "comparableCount": comparable,
            "studentCount": total,
            "rate": round(comparable / total * 100, 1) if total else None,
        },
        "rule": {
            "version": RULE_VERSION,
            "gpaThreshold": GPA_CHANGE_THRESHOLD,
            "description": "GPA变化与未通过课程变化联合判断；不使用综合风险分。",
        },
        "metrics": metrics,
        "groups": groups,
        "organizationLabel": org_label,
        "organizations": organizations,
        "rows": rows,
        "evidence": {
            "sources": [
                "dim_student",
                "所选两学期源库students（在校学生名单）",
                "agg_student_term_growth（源自fact_grade）",
                "agg_student_course_outcome（源自fact_grade）",
                "alert_event",
            ],
            "aggregateRefreshedAt": aggregate_meta.get("refreshed_at"),
            "sourceGradeRows": aggregate_meta.get("source_grade_rows", 0),
            "sourceStudentCount": aggregate_meta.get(
                "source_student_count", 0),
            "sourceSemesterRange": {
                "from": aggregate_meta.get("semester_min"),
                "to": aggregate_meta.get("semester_max"),
            },
            "courseOutcomeBoundary": (
                "当前未解决与重复未解决按最新有效修读结果识别；"
                "课程替代和学分认定仍以培养质量模块为正式核验依据。"
            ),
            "overlapNotice": "关注分组允许重叠，各组人数不能直接相加。",
        },
    }


def filter_growth_rows(
    snapshot: dict,
    group: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> list[dict]:
    valid_groups = {
        "all", "comparable", "improved", "declined", "continuous",
        "first_setback", "repeated_unresolved",
    }
    selected = group or "all"
    if selected not in valid_groups:
        raise ApiError("无效的学生成长关注分组", code=400, status_code=400)
    rows = snapshot["rows"]
    if organization_id:
        rows = [
            row for row in rows
            if organization_id in (
                row["collegeId"], row["majorId"], row["classId"])
        ]
    if selected == "all":
        rows = [row for row in rows if row["triggers"]]
    elif selected == "comparable":
        rows = [row for row in rows if row["comparable"]]
    elif selected in ("improved", "declined"):
        rows = [row for row in rows if row["category"] == selected]
    elif selected == "continuous":
        rows = [row for row in rows if row["continuous"]]
    elif selected == "first_setback":
        rows = [row for row in rows if row["firstSetback"]]
    elif selected == "repeated_unresolved":
        rows = [row for row in rows if row["repeatedUnresolved"]]
    return sorted(rows, key=lambda item: (
        item["priority"], -item["openAlerts"],
        -(item["toFailCount"] or 0),
        item["sid"],
    ))

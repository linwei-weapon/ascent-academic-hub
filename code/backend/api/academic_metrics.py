"""学生学业指标公共计算。

本模块只负责可复用的事实口径，不负责页面分组或管理结论：

- GPA 使用课程学分加权，缺少有效学分的成绩不参与 GPA；
- 已获学分按学生—课程去重，同一课程多条通过记录只计一次；
- 本学期未通过学生率以“本学期具有有效成绩的学生”为分母；
- 课程有效结果以最新学期、最新记录为准，用于区分当前未解决与历史已解决。
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Optional

from . import db as dbm


def weighted_gpa_expression(alias: str = "") -> str:
    """返回 SQLite 学分加权 GPA 聚合表达式。"""
    prefix = f"{alias}." if alias else ""
    return (
        f"SUM(CASE WHEN {prefix}gpa IS NOT NULL AND {prefix}credits>0 "
        f"THEN {prefix}gpa*{prefix}credits END)"
        f"/NULLIF(SUM(CASE WHEN {prefix}gpa IS NOT NULL AND {prefix}credits>0 "
        f"THEN {prefix}credits END),0)"
    )


def _chunks(values: list[str], size: int = 800):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def per_student_weighted_gpa(
    conn: sqlite3.Connection,
    student_ids: Iterable[str],
    semester_ids: Optional[Iterable[str]] = None,
) -> dict[str, float]:
    """按学生计算学分加权 GPA，支持跨学期汇总。"""
    ids = list(dict.fromkeys(student_ids))
    semesters = list(dict.fromkeys(semester_ids or []))
    if not ids:
        return {}
    result: dict[str, float] = {}
    for chunk in _chunks(ids):
        params: list = list(chunk)
        where = [
            "source='real'",
            "gpa IS NOT NULL",
            "credits>0",
            "student_id IN (" + ",".join("?" * len(chunk)) + ")",
        ]
        if semesters:
            where.append("semester_id IN (" + ",".join("?" * len(semesters)) + ")")
            params.extend(semesters)
        rows = dbm.query(
            conn,
            f"""SELECT student_id,{weighted_gpa_expression()} gpa
                FROM fact_grade WHERE {' AND '.join(where)}
                GROUP BY student_id""",
            tuple(params),
        )
        result.update({
            row["student_id"]: row["gpa"]
            for row in rows if row["gpa"] is not None
        })
    return result


def cumulative_gpa_summaries(
    conn: sqlite3.Connection,
    student_ids: Iterable[str],
) -> dict[str, dict]:
    """按学生返回跨学期、按课程最新真实有效结果计算的总 GPA。

    同一课程只取 ``semester_id、rowid`` 最大的一条真实有效结果。最新结果缺少
    GP 或有效学分时不计入总 GPA，并通过 ``excludedCourses`` 明确披露。
    """
    ids = list(dict.fromkeys(str(value) for value in student_ids))
    if not ids:
        return {}
    result: dict[str, dict] = {}
    for chunk in _chunks(ids):
        placeholders = ",".join("?" * len(chunk))
        rows = dbm.query(conn, f"""
            WITH ranked AS (
                SELECT student_id,course_id,gpa,credits,
                       ROW_NUMBER() OVER (
                           PARTITION BY student_id,course_id
                           ORDER BY semester_id DESC,rowid DESC
                       ) latest_rank
                FROM fact_grade
                WHERE source='real' AND is_pass IS NOT NULL
                  AND course_id IS NOT NULL
                  AND student_id IN ({placeholders})
            )
            SELECT student_id,
                   SUM(CASE WHEN latest_rank=1 AND gpa IS NOT NULL AND credits>0
                            THEN gpa*credits END) numerator,
                   SUM(CASE WHEN latest_rank=1 AND gpa IS NOT NULL AND credits>0
                            THEN credits END) denominator,
                   SUM(CASE WHEN latest_rank=1 THEN 1 ELSE 0 END) latest_courses,
                   SUM(CASE WHEN latest_rank=1
                                  AND (gpa IS NULL OR credits IS NULL OR credits<=0)
                            THEN 1 ELSE 0 END) excluded_courses
            FROM ranked
            GROUP BY student_id
        """, tuple(chunk))
        for row in rows:
            numerator = (
                float(row["numerator"])
                if row["numerator"] is not None else None
            )
            denominator = (
                float(row["denominator"])
                if row["denominator"] is not None else 0.0
            )
            result[row["student_id"]] = {
                "gpa": (
                    round(numerator / denominator, 4)
                    if numerator is not None and denominator > 0 else None
                ),
                "numerator": numerator,
                "includedCredits": denominator,
                "includedCourses": (
                    int(row["latest_courses"] or 0)
                    - int(row["excluded_courses"] or 0)
                ),
                "excludedCourses": int(row["excluded_courses"] or 0),
                "ruleVersion": "cumulative-gpa-v1",
                "formula": "Σ（课程绩点×课程学分）÷Σ计入GPA课程学分",
                "boundary": (
                    "每门课程只取最新真实有效结果；缺少课程绩点或有效学分的"
                    "课程不计入总GPA。"
                ),
            }
    return result


def earned_credit_map(
    conn: sqlite3.Connection,
    student_ids: Iterable[str],
) -> dict[str, float]:
    """按学生—课程去重计算已获学分。

    同一课程存在多条通过记录时取该课程有效通过记录中的最大学分，
    避免补考、重修或重复导入造成学分重复累计。
    """
    ids = list(dict.fromkeys(student_ids))
    if not ids:
        return {}
    result: dict[str, float] = {}
    for chunk in _chunks(ids):
        placeholders = ",".join("?" * len(chunk))
        rows = dbm.query(conn, f"""
            SELECT student_id,SUM(course_credits) earned_credits
            FROM (
                SELECT student_id,course_id,MAX(COALESCE(credits,0)) course_credits
                FROM fact_grade
                WHERE source='real' AND is_pass=1 AND credits>0
                  AND student_id IN ({placeholders})
                GROUP BY student_id,course_id
            ) effective_pass
            GROUP BY student_id""", tuple(chunk))
        result.update({
            row["student_id"]: float(row["earned_credits"] or 0)
            for row in rows
        })
    return result


def term_earned_credit_map(
    conn: sqlite3.Connection,
    student_ids: Iterable[str],
    semester: str,
) -> dict[str, float]:
    """计算指定学期内按课程去重的通过学分。"""
    ids = list(dict.fromkeys(student_ids))
    if not ids or not semester:
        return {}
    result: dict[str, float] = {}
    for chunk in _chunks(ids):
        placeholders = ",".join("?" * len(chunk))
        rows = dbm.query(conn, f"""
            SELECT student_id,SUM(course_credits) earned_credits
            FROM (
                SELECT student_id,course_id,MAX(COALESCE(credits,0)) course_credits
                FROM fact_grade
                WHERE source='real' AND is_pass=1 AND credits>0
                  AND semester_id=?
                  AND student_id IN ({placeholders})
                GROUP BY student_id,course_id
            ) effective_pass
            GROUP BY student_id""", (semester, *chunk))
        result.update({
            row["student_id"]: float(row["earned_credits"] or 0)
            for row in rows
        })
    return result


def term_grade_and_failed_students(
    conn: sqlite3.Connection,
    student_ids: Iterable[str],
    semester: str,
) -> tuple[set[str], set[str]]:
    """返回（本学期有有效成绩学生，本学期至少一门未通过学生）。"""
    ids = list(dict.fromkeys(student_ids))
    if not ids or not semester:
        return set(), set()
    graded: set[str] = set()
    failed: set[str] = set()
    for chunk in _chunks(ids):
        placeholders = ",".join("?" * len(chunk))
        for row in dbm.query(conn, f"""
            SELECT student_id,
                   MAX(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) has_fail
            FROM fact_grade
            WHERE source='real' AND is_pass IS NOT NULL AND semester_id=?
              AND student_id IN ({placeholders})
            GROUP BY student_id""", (semester, *chunk)):
            graded.add(row["student_id"])
            if row["has_fail"]:
                failed.add(row["student_id"])
    return graded, failed


def effective_course_outcomes_for_students(
    conn: sqlite3.Connection,
    student_ids: Iterable[str],
) -> dict[str, dict[str, dict]]:
    """批量返回学生各课程的最新有效结果和历史未通过次数。

    原型阶段以 semester_id、grade_id/rowid 的顺序确定最新记录。
    课程替代和学分认定仍由培养质量模块负责，调用方必须披露此边界。
    """
    ids = list(dict.fromkeys(student_ids))
    result: dict[str, dict[str, dict]] = {}
    for chunk in _chunks(ids):
        placeholders = ",".join("?" * len(chunk))
        rows = dbm.query(conn, f"""
            SELECT rowid record_order,student_id,course_id,semester_id,
                   is_pass,credits,score,gpa
            FROM fact_grade
            WHERE student_id IN ({placeholders})
              AND course_id IS NOT NULL AND is_pass IS NOT NULL
            ORDER BY student_id,course_id,semester_id,rowid""", tuple(chunk))
        for row in rows:
            student_id = row["student_id"]
            course_id = row["course_id"]
            outcomes = result.setdefault(student_id, {})
            item = outcomes.setdefault(course_id, {
                "courseId": course_id,
                "failCount": 0,
                "failSemesters": [],
                "resolvedSemester": None,
                "latestSemester": None,
                "latestPassed": None,
                "latestCredits": 0.0,
                "latestScore": None,
                "latestGpa": None,
            })
            if row["is_pass"] == 0:
                item["failCount"] += 1
                if row["semester_id"] not in item["failSemesters"]:
                    item["failSemesters"].append(row["semester_id"])
                # 后续再次未通过时，之前的解决节点不再代表当前状态。
                item["resolvedSemester"] = None
            elif item["failCount"] and item["resolvedSemester"] is None:
                # 最后一次未通过之后首次取得有效通过结果的学期。
                item["resolvedSemester"] = row["semester_id"]
            item.update({
                "latestSemester": row["semester_id"],
                "latestPassed": row["is_pass"] == 1,
                "latestCredits": float(row["credits"] or 0),
                "latestScore": row["score"],
                "latestGpa": row["gpa"],
            })
    for outcomes in result.values():
        for item in outcomes.values():
            item["status"] = (
                "历史已解决" if item["failCount"] and item["latestPassed"]
                else "当前未解决" if item["failCount"] else "已通过"
            )
            item["repeatedUnresolved"] = (
                item["failCount"] >= 2 and not item["latestPassed"]
            )
    return result


def effective_course_outcomes(
    conn: sqlite3.Connection,
    student_id: str,
) -> dict[str, dict]:
    """单生兼容封装，口径与批量计算完全一致。"""
    return effective_course_outcomes_for_students(
        conn, [student_id]
    ).get(student_id, {})


def unresolved_course_outcomes_for_students(
    conn: sqlite3.Connection,
    student_ids: Iterable[str],
) -> dict[str, dict[str, dict]]:
    """批量读取当前未解决课程，避免管理首屏装载全部已通过历史。

    只返回历史上至少一次未通过、且最新有效修读结果仍未通过的课程。
    与 ``effective_course_outcomes_for_students`` 的状态判断一致，但传输和
    Python 处理规模显著更小，适用于全校成长概览。
    """
    ids = list(dict.fromkeys(student_ids))
    result: dict[str, dict[str, dict]] = {}
    for chunk in _chunks(ids):
        placeholders = ",".join("?" * len(chunk))
        rows = dbm.query(conn, f"""
            WITH failed_courses AS (
                SELECT student_id,course_id,COUNT(*) fail_count,
                       GROUP_CONCAT(DISTINCT semester_id) fail_semesters
                FROM fact_grade
                WHERE is_pass=0
                  AND student_id IN ({placeholders})
                GROUP BY student_id,course_id
            ),
            ranked AS (
                SELECT g.student_id,g.course_id,g.semester_id,g.is_pass,
                       g.credits,g.score,g.gpa,
                       ROW_NUMBER() OVER (
                           PARTITION BY g.student_id,g.course_id
                           ORDER BY g.semester_id DESC,g.rowid DESC
                       ) latest_rank
                FROM fact_grade g
                JOIN failed_courses f
                  ON f.student_id=g.student_id AND f.course_id=g.course_id
                WHERE g.is_pass IS NOT NULL
            )
            SELECT r.student_id,r.course_id,r.semester_id,r.credits,r.score,r.gpa,
                   f.fail_count,f.fail_semesters
            FROM ranked r
            JOIN failed_courses f
              ON f.student_id=r.student_id AND f.course_id=r.course_id
            WHERE r.latest_rank=1 AND r.is_pass=0
            ORDER BY r.student_id,r.course_id""", tuple(chunk))
        for row in rows:
            result.setdefault(row["student_id"], {})[row["course_id"]] = {
                "courseId": row["course_id"],
                "failCount": row["fail_count"],
                "failSemesters": (
                    row["fail_semesters"].split(",")
                    if row["fail_semesters"] else []
                ),
                "resolvedSemester": None,
                "latestSemester": row["semester_id"],
                "latestPassed": False,
                "latestCredits": float(row["credits"] or 0),
                "latestScore": row["score"],
                "latestGpa": row["gpa"],
                "status": "当前未解决",
                "repeatedUnresolved": row["fail_count"] >= 2,
            }
    return result

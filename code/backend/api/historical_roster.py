"""按学期只读访问源库学生名单。

该模块只消费 ``datasource/构造数据/{semester}.db`` 中已有的 ``students``
表，不执行 DDL/DML，也不向分析库回填历史学籍。缓存仅存在于当前进程内，
源文件修改后通过 mtime 自动失效。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from backend.etl.config import TS_DIR
from backend.etl.extract_ts import SEMESTERS


REQUIRED_COLUMNS = {
    "student_id",
    "college",
    "major",
    "grade_year",
    "class_name",
    "status",
}
_CACHE_TTL_SECONDS = 120
_ROSTER_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_MAX_ITEMS = 96


def _read_only_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _scope_names(
    conn: sqlite3.Connection,
    scope_type: str,
    scope_id: Optional[str],
) -> tuple[Optional[str], Optional[str], str]:
    if scope_type == "school":
        return None, None, "全校"
    if not scope_id:
        raise ValueError("学院或专业范围必须提供 scopeId")
    if scope_type == "college":
        row = conn.execute(
            "SELECT name FROM dim_college WHERE college_id=?",
            (scope_id,),
        ).fetchone()
        if not row:
            raise ValueError("学院不存在")
        return row["name"], None, row["name"]
    if scope_type == "major":
        row = conn.execute(
            """SELECT m.name major_name,c.name college_name
               FROM dim_major m
               LEFT JOIN dim_college c ON c.college_id=m.college_id
               WHERE m.major_id=?""",
            (scope_id,),
        ).fetchone()
        if not row:
            raise ValueError("专业不存在")
        return row["college_name"], row["major_name"], row["major_name"]
    raise ValueError("scopeType 仅支持 school、college、major")


def clear_roster_cache() -> None:
    """测试和数据文件切换时清空进程内缓存。"""
    _ROSTER_CACHE.clear()


def read_historical_roster(
    conn: sqlite3.Connection,
    semester: str,
    *,
    scope_type: str = "school",
    scope_id: Optional[str] = None,
    authorized_student_ids: Optional[list[str]] = None,
    scope_fingerprint: str = "",
    ts_dir: Optional[Path] = None,
) -> dict:
    """读取某学期、某组织及当前授权交集内的真实学生名单。

    ``authorized_student_ids=None`` 表示当前身份明确拥有全校范围；空列表表示
    没有任何授权学生，不能与全校含义混用。
    """
    root = Path(ts_dir or TS_DIR)
    source_path = root / f"{semester}.db"
    college_name, major_name, scope_label = _scope_names(
        conn, scope_type, scope_id
    )
    if semester not in SEMESTERS or not source_path.is_file():
        return {
            "semester": semester,
            "studentIds": [],
            "students": [],
            "scopeLabel": scope_label,
            "available": False,
            "status": "unavailable",
            "unavailableReason": "对应学期学生源库不存在",
            "source": str(source_path),
            "mapping": {"matched": 0, "excludedByAuthorization": 0},
        }

    stat = source_path.stat()
    authorization_key = (
        "all"
        if authorized_student_ids is None
        else tuple(sorted({str(value) for value in authorized_student_ids}))
    )
    cache_key = (
        str(source_path.resolve()),
        stat.st_mtime_ns,
        semester,
        scope_type,
        scope_id or "",
        scope_fingerprint,
        authorization_key,
    )
    cached = _ROSTER_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return dict(cached[1])

    source_conn = _read_only_connection(source_path)
    try:
        columns = {
            row["name"]
            for row in source_conn.execute("PRAGMA table_info(students)")
        }
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            result = {
                "semester": semester,
                "studentIds": [],
                "students": [],
                "scopeLabel": scope_label,
                "available": False,
                "status": "unavailable",
                "unavailableReason": (
                    "对应学期 students 表缺少字段：" + "、".join(missing)
                ),
                "source": str(source_path),
                "mapping": {"matched": 0, "excludedByAuthorization": 0},
            }
        else:
            where = []
            params: list[str] = []
            if college_name:
                where.append("college=?")
                params.append(college_name)
            if major_name:
                where.append("major=?")
                params.append(major_name)
            sql = """SELECT student_id,college,major,grade_year,class_name,status
                     FROM students"""
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY student_id"
            source_rows = [dict(row) for row in source_conn.execute(sql, params)]
            authorized = (
                None
                if authorized_student_ids is None
                else {str(value) for value in authorized_student_ids}
            )
            rows = [
                row for row in source_rows
                if authorized is None or str(row["student_id"]) in authorized
            ]
            duplicate_count = len(rows) - len({
                str(row["student_id"]) for row in rows
            })
            students_by_id = {
                str(row["student_id"]): {
                    "studentId": str(row["student_id"]),
                    "college": row["college"],
                    "major": row["major"],
                    "grade": (
                        str(row["grade_year"])
                        if row["grade_year"] is not None else None
                    ),
                    "className": row["class_name"],
                    "status": row["status"],
                }
                for row in rows
            }
            normalized = list(students_by_id.values())
            result = {
                "semester": semester,
                "studentIds": sorted(students_by_id),
                "students": normalized,
                "scopeLabel": scope_label,
                "available": True,
                "status": "available",
                "unavailableReason": None,
                "source": str(source_path),
                "mapping": {
                    "matched": len(normalized),
                    "sourceRows": len(source_rows),
                    "excludedByAuthorization": len(source_rows) - len(rows),
                    "duplicateRows": duplicate_count,
                    "collegeName": college_name,
                    "majorName": major_name,
                },
            }
    except sqlite3.Error as exc:
        result = {
            "semester": semester,
            "studentIds": [],
            "students": [],
            "scopeLabel": scope_label,
            "available": False,
            "status": "unavailable",
            "unavailableReason": f"读取对应学期学生源库失败：{exc}",
            "source": str(source_path),
            "mapping": {"matched": 0, "excludedByAuthorization": 0},
        }
    finally:
        source_conn.close()

    if len(_ROSTER_CACHE) >= _CACHE_MAX_ITEMS:
        oldest_key = min(_ROSTER_CACHE, key=lambda key: _ROSTER_CACHE[key][0])
        _ROSTER_CACHE.pop(oldest_key, None)
    _ROSTER_CACHE[cache_key] = (time.monotonic(), result)
    return dict(result)

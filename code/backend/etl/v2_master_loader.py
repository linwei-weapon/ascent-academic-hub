"""V2 首批主数据装载：学期、组织、课程、楼宇、房间和节次。"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from . import config
from .init_v2 import init_v2


@dataclass(frozen=True)
class MasterSpec:
    code: str
    filename: str
    preferred_part: str
    header_markers: tuple[str, ...]
    target: str
    transform: Callable[[pd.DataFrame], list[tuple]]
    columns: tuple[str, ...]


def _text(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    value = str(value).strip()
    return value or None


def _code(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def _date(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _clock(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, time)):
        return value.strftime("%H:%M")
    return str(value).strip()[:5]


def _first(row: pd.Series, *names: str):
    for name in names:
        if name in row.index and not pd.isna(row[name]):
            return row[name]
    return None


def _semester_rows(df: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, r in df.iterrows():
        semester_id = _text(_first(r, "学期名称", "学年学期"))
        if not semester_id:
            continue
        rows.append((semester_id, semester_id, _text(r.get("年份")), _text(r.get("季节")),
                     _date(r.get("开始日期")), _date(r.get("结束日期")),
                     _text(_first(r, "状态", "是否启用")), "real"))
    return rows


def _organization_rows(df: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, r in df.iterrows():
        oid = _code(_first(r, "部门代码", "组织机构代码"))
        name = _text(_first(r, "中文名称", "组织机构名称"))
        if oid and name:
            parent = _code(_first(r, "上级部门", "上级组织机构代码"))
            otype = "学院" if _text(r.get("是否院系")) == "是" else _text(r.get("所在单位类型"))
            rows.append((oid, name, parent, otype, "启用", None, None, "real"))
    return rows


def _course_rows(df: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, r in df.iterrows():
        cid = _code(_first(r, "代码", "课程代码"))
        name = _text(_first(r, "中文名", "课程名称"))
        if cid and name:
            rows.append((cid, name, _text(r.get("课程分类")), _text(r.get("课程类别")),
                         _number(r.get("学分")), _number(r.get("总学时")),
                         _number(r.get("理论学时")), _number(r.get("实验学时")),
                         (_number(r.get("集中实践学时")) or 0) + (_number(r.get("分散实践学时")) or 0),
                         _text(_first(r, "默认考核方式", "考核方式")),
                         _text(_first(r, "管理院系", "默认开课部门")),
                         _text(_first(r, "是否启用", "状态")), "real"))
    return rows


def _building_rows(df: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, r in df.iterrows():
        bid = _code(_first(r, "楼宇编号", "楼宇代码"))
        name = _text(r.get("楼宇名称"))
        if bid and name:
            rows.append((bid, name, _text(r.get("校区")), _text(r.get("状态")), "real"))
    return rows


def _room_rows(df: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, r in df.iterrows():
        rid = _code(_first(r, "代码", "房间代码"))
        if not rid:
            continue
        building_name = _text(_first(r, "楼宇", "楼宇名称"))
        rows.append((rid, building_name, _text(_first(r, "中文名称", "房间名称")),
                     _text(r.get("教室类型")), int(_number(_first(r, "上课用座位数", "座位数")) or 0),
                     1 if _text(r.get("是否虚拟教室")) == "是" else 0,
                     1 if _text(r.get("是否可用")) == "可用" else 0,
                     None, None, "real"))
    return rows


def _period_rows(df: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, r in df.iterrows():
        pid = _code(_first(r, "#", "节次代码"))
        if pid:
            rows.append((pid, _text(_first(r, "中文名称", "节次名称")), _text(r.get("大节")),
                         _clock(r.get("开始时间")), _clock(r.get("结束时间")), "real"))
    return rows


SPECS = (
    MasterSpec("semester", "学年学期.xlsx", "20260712", ("学期名称", "学期代码"), "dim_semester", _semester_rows,
               ("semester_id", "name", "academic_year", "season", "start_date", "end_date", "status", "source")),
    MasterSpec("organization", "组织机构.xlsx", "20260712", ("部门代码", "中文名称"), "dim_organization", _organization_rows,
               ("organization_id", "name", "parent_id", "organization_type", "status", "valid_from", "valid_to", "source")),
    MasterSpec("course", "课程信息.xlsx", "20260712", ("代码", "中文名"), "dim_course", _course_rows,
               ("course_id", "name", "category", "nature", "credits", "total_hours", "theory_hours", "experiment_hours", "practice_hours", "assessment_type", "organization_id", "status", "source")),
    MasterSpec("building", "楼宇.xlsx", "20260712", ("楼宇编号", "楼宇名称"), "dim_building", _building_rows,
               ("building_id", "name", "campus", "status", "source")),
    MasterSpec("room", "房间.xlsx", "新增数据", ("代码", "中文名称"), "dim_room", _room_rows,
               ("room_id", "building_id", "name", "room_type", "seats", "is_virtual", "is_available", "valid_from", "valid_to", "source")),
    MasterSpec("period", "课表时间.xlsx", "20260712", ("#", "中文名称"), "dim_period", _period_rows,
               ("period_id", "name", "major_period", "start_time", "end_time", "source")),
)


def locate_file(root: Path, spec: MasterSpec) -> Path:
    matches = list(root.rglob(spec.filename))
    preferred = [p for p in matches if spec.preferred_part in str(p)]
    selected = preferred or matches
    if len(selected) != 1:
        raise FileNotFoundError(f"{spec.code} 文件不唯一或不存在: {selected}")
    return selected[0]


def read_with_header(path: Path, markers: tuple[str, ...]) -> pd.DataFrame:
    preview = pd.read_excel(path, header=None, nrows=10)
    header_row = None
    for idx, row in preview.iterrows():
        values = {str(v).strip() for v in row if not pd.isna(v)}
        if all(marker in values for marker in markers):
            header_row = idx
            break
    if header_row is None:
        raise ValueError(f"无法识别表头: {path.name}, markers={markers}")
    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    return df.dropna(how="all")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _upsert(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], rows: list[tuple]) -> None:
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{c}=excluded.{c}" for c in columns[1:])
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT({columns[0]}) DO UPDATE SET {updates}"
    conn.executemany(sql, rows)


def load_master_data(root: Path | None = None, db_path: Path | None = None) -> dict:
    root = Path(root or config.V2_SOURCE_ROOT)
    conn = init_v2(db_path)
    report = {"datasets": {}, "quality": {}}
    now = datetime.now(timezone.utc).isoformat()
    try:
        for spec in SPECS:
            path = locate_file(root, spec)
            frame = read_with_header(path, spec.header_markers)
            rows = spec.transform(frame)
            file_hash = _hash(path)
            batch_id = f"{spec.code}-{file_hash[:16]}"
            _upsert(conn, spec.target, spec.columns, rows)
            conn.execute(
                "INSERT INTO data_batch(batch_id,source_code,source_file,file_hash,ingested_at,row_count,accepted_count,quality_status) "
                "VALUES(?,?,?,?,?,?,?,'accepted') ON CONFLICT(batch_id) DO UPDATE SET ingested_at=excluded.ingested_at,row_count=excluded.row_count,accepted_count=excluded.accepted_count,quality_status='accepted'",
                (batch_id, spec.code, str(path), file_hash, now, len(frame), len(rows)),
            )
            report["datasets"][spec.code] = {"file": str(path), "source_rows": len(frame), "loaded_rows": len(rows), "target": spec.target}

        # 房间中的 building_id 当前是楼宇名称，先按名称转换为正式楼宇代码。
        conn.execute("UPDATE dim_room SET building_id=(SELECT b.building_id FROM dim_building b WHERE b.name=dim_room.building_id) WHERE EXISTS(SELECT 1 FROM dim_building b WHERE b.name=dim_room.building_id)")
        # 课程文件提供管理院系名称，组织主数据提供代码；精确按名称转为标准代码。
        conn.execute("UPDATE dim_course SET organization_id=(SELECT o.organization_id FROM dim_organization o WHERE o.name=dim_course.organization_id) WHERE EXISTS(SELECT 1 FROM dim_organization o WHERE o.name=dim_course.organization_id)")

        # 无法自动映射的源代码/名称写入待治理表，供管理员核对，不静默丢弃。
        conn.execute("DELETE FROM code_mapping WHERE source_system='v2_master_loader' AND domain IN ('course_organization','room_building')")
        conn.execute("INSERT OR IGNORE INTO code_mapping(domain,source_system,source_code,mapping_status,note) SELECT 'course_organization','v2_master_loader',organization_id,'pending','课程管理院系未匹配组织机构' FROM dim_course WHERE organization_id IS NOT NULL AND organization_id NOT IN (SELECT organization_id FROM dim_organization)")
        conn.execute("INSERT OR IGNORE INTO code_mapping(domain,source_system,source_code,mapping_status,note) SELECT 'room_building','v2_master_loader',building_id,'pending','房间楼宇未匹配楼宇主数据' FROM dim_room WHERE building_id IS NOT NULL AND building_id NOT IN (SELECT building_id FROM dim_building)")
        report["quality"] = {
            "course_missing_org_mapping": conn.execute("SELECT COUNT(*) FROM dim_course WHERE organization_id IS NOT NULL AND organization_id NOT IN (SELECT organization_id FROM dim_organization)").fetchone()[0],
            "room_missing_building_mapping": conn.execute("SELECT COUNT(*) FROM dim_room WHERE building_id IS NOT NULL AND building_id NOT IN (SELECT building_id FROM dim_building)").fetchone()[0],
            "usable_rooms": conn.execute("SELECT COUNT(*) FROM dim_room WHERE is_available=1 AND is_virtual=0 AND seats>0").fetchone()[0],
            "duplicate_source_batches": conn.execute("SELECT COUNT(*) FROM (SELECT source_code,file_hash,COUNT(*) c FROM data_batch GROUP BY source_code,file_hash HAVING c>1)").fetchone()[0],
            "pending_code_mappings": conn.execute("SELECT COUNT(*) FROM code_mapping WHERE mapping_status='pending'").fetchone()[0],
        }
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def main() -> None:
    report = load_master_data()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

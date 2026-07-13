"""实际教室占用数据接入。

原型口径：导入真实占用事件，建立已观测教室集合；不把已观测教室数解释为学校正式可用教室数。
活动原文只计算哈希，入库前移除联系人、联系方式、手机号和电子邮箱。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config

DEFAULT_ROOT = Path(r"D:\AI教育\AI学业助手\15-原始数据\数据\20260712\20260712")
REQUIRED_COLUMNS = {"ACTIVITY_NAME", "DATE_", "START_TIME", "END_TIME", "ROOM_NAME", "SEMESTER_NAME"}
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CONTACT_RE = re.compile(r"(?:联系人|联系方式|联系电话|手机)[：:\s]*[^\n]*", re.I)
COURSE_RE = re.compile(r"^([A-Za-z0-9]+)\.(\d+)\b")


def hhmm(value) -> tuple[str, int]:
    text = str(int(value)).zfill(4)
    hour, minute = int(text[:2]), int(text[2:])
    if hour > 23 or minute > 59:
        raise ValueError(f"非法时间 {value}")
    return f"{hour:02d}:{minute:02d}", hour * 60 + minute


def sanitize_activity(value: str) -> tuple[str, int, str]:
    raw = str(value or "").replace("_x000D_", "\n").replace("\r", "\n")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    redacted = int(bool(PHONE_RE.search(raw) or EMAIL_RE.search(raw) or CONTACT_RE.search(raw)))
    text = CONTACT_RE.sub("", raw)
    text = PHONE_RE.sub("[已脱敏]", text)
    text = EMAIL_RE.sub("[已脱敏]", text)
    text = re.sub(r"\s+", " ", text).strip(" ,，;；")
    return (text[:240] or "未命名活动"), redacted, digest


def classify_activity(text: str, matched_course: bool) -> str:
    if matched_course:
        return "course"
    if re.search(r"考试|考务|四六级|资格考试", text):
        return "exam"
    if re.search(r"自习|学习空间", text):
        return "self_study"
    if re.search(r"复试|面试|答辩|招生", text):
        return "admission_review"
    if re.search(r"会议|培训|党课|宣讲|讲座|竞赛|比赛|活动|夏令营", text):
        return "event"
    if re.search(r"补课|课程设计|实验|实训", text):
        return "teaching_other"
    return "other"


def load_buildings(path: Path) -> tuple[list[str], dict[str, str]]:
    frame = pd.read_excel(path, sheet_name="Sheet1", header=1)
    names = sorted({str(x).strip() for x in frame["楼宇名称"].dropna()}, key=len, reverse=True)
    aliases = {"主楼B": "主楼B座", "润洁公寓": "润杰公寓"}
    return names, aliases


def map_building(room: str, names: list[str], aliases: dict[str, str]) -> tuple[str | None, str]:
    room = str(room).strip()
    for name in names:
        if room.startswith(name):
            return name, "matched"
    for prefix, name in aliases.items():
        if room.startswith(prefix):
            return name, "alias"
    return None, "pending"


def load_periods(path: Path) -> list[dict]:
    frame = pd.read_excel(path, sheet_name="Sheet1")
    result = []
    for _, row in frame.iterrows():
        start, end = row["开始时间"], row["结束时间"]
        result.append({"index": int(row["#"]), "band": str(row["区间"]),
                       "start": start.hour * 60 + start.minute, "end": end.hour * 60 + end.minute})
    return result


def ensure_schema(conn: sqlite3.Connection) -> None:
    sql_path = Path(__file__).with_name("schema_room_occupancy.sql")
    conn.executescript(sql_path.read_text(encoding="utf-8"))


def import_usage(source: Path, building_file: Path, period_file: Path,
                 db_path: Path = config.DB_PATH) -> dict:
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    batch_id = f"room-occ-{source_hash[:16]}"
    frame = pd.read_excel(source, sheet_name="Sheet1")
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"实际教室使用缺少字段: {sorted(missing)}")
    buildings, aliases = load_buildings(building_file)
    periods = load_periods(period_file)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    course_ids = {row[0] for row in conn.execute("SELECT course_id FROM dim_course")}

    records, period_records, invalid = [], [], []
    overlap_index: dict[tuple[str, str], list[tuple[int, int, str]]] = defaultdict(list)
    for index, row in frame.iterrows():
        source_row = index + 2
        try:
            activity_date = pd.to_datetime(row["DATE_"]).date().isoformat()
            start_time, start_minute = hhmm(row["START_TIME"])
            end_time, end_minute = hhmm(row["END_TIME"])
            if end_minute <= start_minute:
                raise ValueError("结束时间不晚于开始时间")
            room_name = str(row["ROOM_NAME"]).strip()
            semester = str(row["SEMESTER_NAME"]).strip()
            masked, pii_redacted, raw_hash = sanitize_activity(row["ACTIVITY_NAME"])
            match = COURSE_RE.match(str(row["ACTIVITY_NAME"]).strip())
            activity_code = match.group(1) if match else None
            course_id = activity_code if activity_code in course_ids else None
            activity_type = classify_activity(masked, bool(course_id))
            building_name, mapping_status = map_building(room_name, buildings, aliases)
            overlaps = [p for p in periods if min(end_minute, p["end"]) > max(start_minute, p["start"])]
            period_start = min((p["index"] for p in overlaps), default=None)
            period_end = max((p["index"] for p in overlaps), default=None)
            is_evening = int(start_minute >= 18 * 60 or any(p["band"] == "晚上" for p in overlaps))
            time_band = "evening" if is_evening else ("morning" if start_minute < 12 * 60 else "afternoon")
            identity = "|".join([semester, activity_date, str(start_minute), str(end_minute), room_name, raw_hash])
            occupancy_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
            records.append({"occupancy_id": occupancy_id, "semester_id": semester,
                "activity_date": activity_date, "weekday": pd.Timestamp(activity_date).isoweekday(),
                "start_time": start_time, "end_time": end_time, "start_minute": start_minute,
                "end_minute": end_minute, "duration_minutes": end_minute-start_minute,
                "time_band": time_band, "period_start": period_start, "period_end": period_end,
                "room_name": room_name, "building_name": building_name,
                "building_mapping_status": mapping_status, "activity_type": activity_type,
                "activity_name_masked": masked, "source_activity_code": activity_code,
                "course_id": course_id, "is_evening": is_evening, "overlap_count": 0,
                "pii_redacted": pii_redacted, "raw_activity_hash": raw_hash,
                "source_file": source.name, "source_row_number": source_row,
                "import_batch_id": batch_id, "imported_at": imported_at})
            for period in overlaps:
                minutes = min(end_minute, period["end"]) - max(start_minute, period["start"])
                period_records.append((occupancy_id, period["index"], minutes))
            overlap_index[(room_name, activity_date)].append((start_minute, end_minute, occupancy_id))
        except Exception as exc:
            invalid.append({"source_row": source_row, "reason": str(exc)})

    overlap_counts = defaultdict(int)
    for entries in overlap_index.values():
        active = []
        for start, end, occupancy_id in sorted(entries):
            active = [(active_end, active_id) for active_end, active_id in active if active_end > start]
            for _, active_id in active:
                overlap_counts[occupancy_id] += 1
                overlap_counts[active_id] += 1
            active.append((end, occupancy_id))
    for record in records:
        record["overlap_count"] = overlap_counts[record["occupancy_id"]]

    fields = list(records[0]) if records else []
    semesters = sorted({record["semester_id"] for record in records})
    quality = {"invalid_rows": invalid[:50],
        "mapping_status": {str(k): int(v) for k, v in pd.Series([r["building_mapping_status"] for r in records]).value_counts().items()},
        "activity_types": {str(k): int(v) for k, v in pd.Series([r["activity_type"] for r in records]).value_counts().items()},
        "denominator_boundary": "房间集合来自本文件曾发生占用的已观测教室，不等于学校正式可用教室全集"}
    try:
        conn.execute("BEGIN")
        for semester in semesters:
            old_ids = [row[0] for row in conn.execute(
                "SELECT occupancy_id FROM fact_room_occupancy WHERE semester_id=? AND source_file=?",
                (semester, source.name))]
            if old_ids:
                conn.executemany("DELETE FROM fact_room_occupancy_period WHERE occupancy_id=?", [(x,) for x in old_ids])
            conn.execute("DELETE FROM fact_room_occupancy WHERE semester_id=? AND source_file=?", (semester, source.name))
        if records:
            marks = ",".join("?" for _ in fields)
            conn.executemany(f"INSERT INTO fact_room_occupancy ({','.join(fields)}) VALUES ({marks})",
                             [tuple(record[field] for field in fields) for record in records])
            conn.executemany("INSERT INTO fact_room_occupancy_period VALUES (?,?,?)", period_records)
        conn.execute("DELETE FROM dim_observed_room")
        conn.execute("""INSERT INTO dim_observed_room
            SELECT room_name,MAX(building_name),
              CASE WHEN SUM(building_mapping_status='pending')>0 THEN 'pending'
                   WHEN SUM(building_mapping_status='alias')>0 THEN 'alias' ELSE 'matched' END,
              MIN(activity_date),MAX(activity_date),COUNT(DISTINCT activity_date),COUNT(*),?,?
            FROM fact_room_occupancy GROUP BY room_name""", ("actual_room_usage", imported_at))
        conn.execute("DELETE FROM etl_room_occupancy_batch WHERE import_batch_id=?", (batch_id,))
        batch_rows = []
        for semester in semesters:
            semester_records = [r for r in records if r["semester_id"] == semester]
            batch_rows.append((batch_id if len(semesters)==1 else f"{batch_id}-{semester}", source.name,
                source_hash, semester, imported_at, len(frame), len(semester_records),
                len({r["room_name"] for r in semester_records}),
                sum(r["building_mapping_status"] != "pending" for r in semester_records),
                sum(r["building_mapping_status"] == "pending" for r in semester_records),
                sum(r["pii_redacted"] for r in semester_records),
                sum(r["overlap_count"] > 0 for r in semester_records), len(invalid),
                json.dumps(quality, ensure_ascii=False)))
        conn.executemany("INSERT INTO etl_room_occupancy_batch VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch_rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"batch_id": batch_id, "source_rows": len(frame), "loaded_rows": len(records),
        "period_rows": len(period_records), "invalid_rows": len(invalid),
        "observed_rooms": len({r["room_name"] for r in records}), "semesters": semesters,
        "pii_redacted_rows": sum(r["pii_redacted"] for r in records),
        "overlap_rows": sum(r["overlap_count"] > 0 for r in records), "quality": quality}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(os.environ.get("ROOM_OCCUPANCY_SOURCE", DEFAULT_ROOT / "实际教室使用.xlsx")))
    parser.add_argument("--buildings", type=Path, default=DEFAULT_ROOT / "楼宇.xlsx")
    parser.add_argument("--periods", type=Path, default=DEFAULT_ROOT / "课表时间.xlsx")
    parser.add_argument("--db", type=Path, default=config.DB_PATH)
    args = parser.parse_args()
    print(json.dumps(import_usage(args.source, args.buildings, args.periods, args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

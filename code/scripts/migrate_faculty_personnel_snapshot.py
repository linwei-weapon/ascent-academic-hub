"""幂等创建师资保障真实在岗人员学期快照表。

本迁移只建立生产数据接入契约，不生成、推导或回填教职工与年龄数据。
真实数据未装载时，师资首页相应KPI按“待接入”展示。

用法：cd code && python -X utf8 scripts/migrate_faculty_personnel_snapshot.py [db_path]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl import config


DDL = """
CREATE TABLE IF NOT EXISTS dim_staff_employment_snapshot (
    semester_id       TEXT NOT NULL,
    staff_id          TEXT NOT NULL,
    college_id        TEXT,
    dept              TEXT,
    staff_category    TEXT,
    employment_status TEXT NOT NULL,
    title             TEXT,
    age_band          TEXT,
    is_under_35       INTEGER CHECK (is_under_35 IN (0,1) OR is_under_35 IS NULL),
    source            TEXT NOT NULL DEFAULT 'real',
    source_batch_id   TEXT NOT NULL CHECK (TRIM(source_batch_id) <> ''),
    updated_at        TEXT NOT NULL CHECK (TRIM(updated_at) <> ''),
    PRIMARY KEY (semester_id,staff_id)
);
CREATE INDEX IF NOT EXISTS idx_staff_snapshot_scope
ON dim_staff_employment_snapshot(semester_id,college_id,employment_status);
CREATE TRIGGER IF NOT EXISTS trg_staff_snapshot_trace_insert
BEFORE INSERT ON dim_staff_employment_snapshot
WHEN NULLIF(TRIM(NEW.source_batch_id),'') IS NULL
  OR NULLIF(TRIM(NEW.updated_at),'') IS NULL
BEGIN
    SELECT RAISE(ABORT, 'staff snapshot requires source_batch_id and updated_at');
END;
CREATE TRIGGER IF NOT EXISTS trg_staff_snapshot_trace_update
BEFORE UPDATE OF source_batch_id,updated_at ON dim_staff_employment_snapshot
WHEN NULLIF(TRIM(NEW.source_batch_id),'') IS NULL
  OR NULLIF(TRIM(NEW.updated_at),'') IS NULL
BEGIN
    SELECT RAISE(ABORT, 'staff snapshot requires source_batch_id and updated_at');
END;
"""


def migrate(db_path: Path | None = None) -> dict:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(DDL)
        conn.commit()
        columns = [row[1] for row in conn.execute(
            "PRAGMA table_info(dim_staff_employment_snapshot)"
        )]
        return {
            "table": "dim_staff_employment_snapshot",
            "columns": columns,
            "rows": conn.execute(
                "SELECT COUNT(*) FROM dim_staff_employment_snapshot"
            ).fetchone()[0],
        }
    finally:
        conn.close()


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    result = migrate(db_path)
    print(f"== 师资保障人员快照迁移: {db_path or config.DB_PATH} ==")
    print(f"表: {result['table']}")
    print(f"字段数: {len(result['columns'])}")
    print(f"现有真实快照记录: {result['rows']}")
    print("迁移完成，可安全重复执行；本脚本不生成教职工或年龄数据。")


if __name__ == "__main__":
    main()

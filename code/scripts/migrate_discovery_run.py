"""幂等迁移：增加规则自发现后台运行与用户确认审计表。

用法：cd code && python -X utf8 scripts/migrate_discovery_run.py [analytics_db_path]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DB = (
    Path(__file__).resolve().parent.parent / "backend" / "db" / "analytics.sqlite"
)

DDL = """
CREATE TABLE IF NOT EXISTS sys_discovery_run (
    run_id TEXT PRIMARY KEY,
    semester_id TEXT NOT NULL,
    status TEXT NOT NULL,
    manifest_fingerprint TEXT NOT NULL,
    table_count INTEGER NOT NULL,
    total_rows INTEGER NOT NULL,
    analyzable_students INTEGER NOT NULL,
    consent_by TEXT NOT NULL,
    consent_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    candidate_count INTEGER DEFAULT 0,
    superseded_count INTEGER DEFAULT 0,
    engine_mode TEXT NOT NULL,
    model_status TEXT,
    model_summary TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_sys_discovery_run_created
    ON sys_discovery_run(created_at DESC);
"""


def migrate(db_path: Path | None = None) -> dict:
    path = Path(db_path or DEFAULT_DB).resolve()
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(DDL)
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM sys_discovery_run").fetchone()[0]
    finally:
        conn.close()
    return {"db_path": str(path), "run_rows": count}


def main() -> None:
    result = migrate(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print("规则自发现运行审计表迁移完成，可安全重复执行。")
    print(f"数据库：{result['db_path']}")
    print(f"现有运行记录：{result['run_rows']}")


if __name__ == "__main__":
    main()

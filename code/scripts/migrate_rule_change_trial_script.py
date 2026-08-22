"""幂等迁移：为规则变更单增加试算脚本维护字段。

用法：cd code && python -X utf8 scripts/migrate_rule_change_trial_script.py [analytics_db_path]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DB = (
    Path(__file__).resolve().parent.parent / "backend" / "db" / "analytics.sqlite"
)

COLUMNS = {
    "trial_script_type": "TEXT",
    "trial_script_content": "TEXT",
    "trial_script_updated_by": "TEXT",
    "trial_script_updated_at": "TEXT",
}


def migrate(db_path: Path | None = None) -> dict:
    path = Path(db_path or DEFAULT_DB).resolve()
    conn = sqlite3.connect(str(path))
    try:
        exists = conn.execute("""SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='alert_rule_change'""").fetchone()
        if not exists:
            raise RuntimeError("数据库中不存在 alert_rule_change，请先初始化规则治理表")
        columns = {row[1] for row in conn.execute(
            "PRAGMA table_info(alert_rule_change)"
        )}
        added = []
        for name, definition in COLUMNS.items():
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE alert_rule_change ADD COLUMN {name} {definition}"
                )
                added.append(name)
        conn.commit()
        final_columns = {row[1] for row in conn.execute(
            "PRAGMA table_info(alert_rule_change)"
        )}
    finally:
        conn.close()
    return {
        "db_path": str(path),
        "added": added,
        "ready": all(name in final_columns for name in COLUMNS),
    }


def main() -> None:
    result = migrate(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print("规则变更单试算脚本字段迁移完成，可安全重复执行。")
    print(f"数据库：{result['db_path']}")
    print(f"本次新增字段：{', '.join(result['added']) or '无'}")


if __name__ == "__main__":
    main()

"""M4 幂等迁移：etl_run 运行历史表 + etl.trigger 动作授权 + 采集频率参数。

三件事均可安全重复执行：
1. V2 库：init_v2 按 schema_v2.sql 幂等创建 etl_run 及索引（含 running 唯一约束）。
2. V1 库：sys_role_action 为系统管理员角色（dean）补齐 etl.trigger 动作授权
   （动作目录定义见 backend/permission_catalog.py）。
3. V1 库：_ensure_system_tables 幂等登记 data.refresh_cron 采集频率说明参数。

用法：cd code && python -X utf8 scripts/migrate_etl_run.py [v2_db_path] [v1_db_path]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl import config
from backend.etl.init_v2 import init_v2

ADMIN_ROLE = "dean"
TRIGGER_ACTION = "etl.trigger"


def migrate(v2_db_path: Path | None = None, v1_db_path: Path | None = None) -> dict:
    v2_path = Path(v2_db_path or config.V2_DB_PATH)
    conn = init_v2(v2_path)
    try:
        etl_run_ready = bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='etl_run'"
        ).fetchone())
        indexes = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='etl_run'"
        )]
        run_count = conn.execute("SELECT COUNT(*) FROM etl_run").fetchone()[0]
    finally:
        conn.close()

    v1_path = Path(v1_db_path or config.DB_PATH)
    v1 = sqlite3.connect(str(v1_path))
    v1.row_factory = sqlite3.Row
    try:
        action_grants = 0
        if v1.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sys_role_action'"
        ).fetchone():
            v1.execute(
                "INSERT OR IGNORE INTO sys_role_action(role_id,action_id) VALUES(?,?)",
                (ADMIN_ROLE, TRIGGER_ACTION))
            v1.commit()
            action_grants = v1.execute(
                "SELECT COUNT(*) FROM sys_role_action WHERE action_id=?",
                (TRIGGER_ACTION,)).fetchone()[0]

        from backend.api.routers.system_management import _ensure_system_tables
        _ensure_system_tables(v1)
        v1.commit()
        refresh_param = v1.execute(
            "SELECT value_json FROM sys_system_parameter"
            " WHERE parameter_key='data.refresh_cron'").fetchone()
    finally:
        v1.close()

    return {
        "v2_path": str(v2_path),
        "etl_run_ready": etl_run_ready,
        "etl_run_indexes": sorted(indexes),
        "etl_run_rows": run_count,
        "trigger_action_grants": action_grants,
        "refresh_cron": refresh_param[0] if refresh_param else None,
    }


def main() -> None:
    v2 = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    v1 = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    result = migrate(v2, v1)
    print(f"== M4 ETL运行历史迁移 ==")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main()

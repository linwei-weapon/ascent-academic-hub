"""P5幂等迁移：补齐八个系统管理模块的数据结构和菜单。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_system_management.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.ai_experts import get_expert
from backend.api.routers.admin_rbac import AUTH_IDENTITY_DDL
from backend.api.routers.ai_experts import _ensure_tables
from backend.api.routers.settings import _ensure_kpi_config
from backend.api.routers.system_management import _ensure_system_tables
from backend.etl import config
from scripts.migrate_menu import migrate as migrate_menu


def migrate(conn: sqlite3.Connection) -> dict:
    migrate_menu(conn)
    conn.executescript(AUTH_IDENTITY_DDL)
    _ensure_tables(conn)
    _ensure_kpi_config(conn)
    _ensure_system_tables(conn)

    schemes = conn.execute("""
        SELECT scheme_id,expert_id FROM sys_ai_analysis_scheme
        ORDER BY scheme_id
    """).fetchall()
    for scheme_id, expert_id in schemes:
        exists = conn.execute("""
            SELECT 1 FROM sys_ai_analysis_scheme_role WHERE scheme_id=? LIMIT 1
        """, (scheme_id,)).fetchone()
        if exists:
            continue
        expert = get_expert(expert_id)
        if not expert:
            continue
        for role_id in expert["applicableRoles"]:
            conn.execute("""
                INSERT OR IGNORE INTO sys_ai_analysis_scheme_role(scheme_id,role_id)
                VALUES(?,?)
            """, (scheme_id, role_id))
    conn.commit()
    return {
        "systemMenus": conn.execute("""
            SELECT COUNT(*) FROM sys_menu WHERE parent_id='/admin/system'
        """).fetchone()[0],
        "authMappings": conn.execute(
            "SELECT COUNT(*) FROM sys_auth_identity"
        ).fetchone()[0],
        "systemParameters": conn.execute(
            "SELECT COUNT(*) FROM sys_system_parameter"
        ).fetchone()[0],
        "analysisSchemes": len(schemes),
        "schemeRoleBindings": conn.execute(
            "SELECT COUNT(*) FROM sys_ai_analysis_scheme_role"
        ).fetchone()[0],
        "registeredKpis": conn.execute(
            "SELECT COUNT(*) FROM sys_kpi_config"
        ).fetchone()[0],
    }


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        result = migrate(conn)
    finally:
        conn.close()
    print(f"== P5系统管理迁移: {path} ==")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

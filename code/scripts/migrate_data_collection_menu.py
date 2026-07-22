"""M4幂等迁移：为系统管理新增「数据采集监控」菜单。

- 菜单行 upsert 到 sys_menu（parent=/admin/system，sort_order=310）；
- 授权与现有系统管理页一致：仅系统管理员角色（dean）持有，其他角色
  对该菜单的历史授权一并清除（与 migrate_menu 对系统页的处理一致）；
- 菜单定义已同时并入 migrate_menu.TARGET_MENUS，以后重跑 migrate_menu
  不会把该菜单当作非目标菜单清除。

只修改 sys_menu / sys_role_menu。可重复执行。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_data_collection_menu.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl import config

# menu_id, parent_id, title, path, icon, sort_order（与 migrate_menu.TARGET_MENUS 一致）
MENU_ROW = ("/admin/system/data-collection", "/admin/system", "数据采集监控",
            "/admin/system/data-collection", "Monitor", 310)
MENU_ID = MENU_ROW[0]
ADMIN_ROLE = "dean"


def migrate(conn: sqlite3.Connection) -> dict:
    conn.execute("""
        INSERT INTO sys_menu(menu_id,parent_id,title,path,icon,sort_order)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(menu_id) DO UPDATE SET
            parent_id=excluded.parent_id,
            title=excluded.title,
            path=excluded.path,
            icon=excluded.icon,
            sort_order=excluded.sort_order
    """, MENU_ROW)
    conn.execute("DELETE FROM sys_role_menu WHERE menu_id=? AND role_id<>?",
                 (MENU_ID, ADMIN_ROLE))
    conn.execute("INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id) VALUES(?,?)",
                 (ADMIN_ROLE, MENU_ID))
    conn.commit()
    menu = conn.execute(
        "SELECT menu_id,parent_id,title,sort_order FROM sys_menu WHERE menu_id=?",
        (MENU_ID,)).fetchone()
    granted = [row[0] for row in conn.execute(
        "SELECT role_id FROM sys_role_menu WHERE menu_id=? ORDER BY role_id",
        (MENU_ID,))]
    return {"menu": dict(menu), "grantedRoles": granted}


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        result = migrate(conn)
    finally:
        conn.close()
    print(f"== M4数据采集监控菜单迁移: {path} ==")
    menu = result["menu"]
    print(f"菜单: {menu['menu_id']}  parent={menu['parent_id']}  "
          f"title={menu['title']}  sort={menu['sort_order']}")
    print(f"授权角色: {', '.join(result['grantedRoles'])}")
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

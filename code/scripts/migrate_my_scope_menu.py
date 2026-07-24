"""M3兼容迁移：把旧「我的班级/学生」菜单收口到统一学生工作区。

- 确保「学生成长与学业分析」目标菜单存在；
- 将旧菜单既有授权迁移到目标菜单；
- 为 counselor / class_adviser / mentor 与系统管理员补齐目标授权；
- 删除旧菜单授权和菜单记录，旧 URL 仅由前端兼容重定向。

只修改 sys_menu / sys_role_menu，不触碰业务事实数据。可重复执行。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_my_scope_menu.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入

from backend.etl import config
from scripts.migrate_menu import STUDENT_WORKSPACE_ROLES

# menu_id, parent_id, title, path, icon, sort_order（与 migrate_menu.TARGET_MENUS 一致）
MENU_ROW = ("/admin/students/analysis", "/admin/analysis", "学生成长与学业分析",
            "/admin/students/analysis", "DataLine", 106)
MENU_ID = MENU_ROW[0]
LEGACY_MENU_ID = "/admin/students/my"
def migrate(conn: sqlite3.Connection) -> dict:
    legacy_roles = [row[0] for row in conn.execute(
        "SELECT role_id FROM sys_role_menu WHERE menu_id=? ORDER BY role_id",
        (LEGACY_MENU_ID,))]
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
    for role_id in (*legacy_roles, *STUDENT_WORKSPACE_ROLES):
        conn.execute("""INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id)
                        VALUES(?,?)""", (role_id, MENU_ID))
    conn.execute("DELETE FROM sys_role_menu WHERE menu_id=?", (LEGACY_MENU_ID,))
    conn.execute("DELETE FROM sys_menu WHERE menu_id=?", (LEGACY_MENU_ID,))
    conn.commit()
    menu = conn.execute(
        "SELECT menu_id,parent_id,title,sort_order FROM sys_menu WHERE menu_id=?",
        (MENU_ID,)).fetchone()
    granted = [row[0] for row in conn.execute(
        "SELECT role_id FROM sys_role_menu WHERE menu_id=? ORDER BY role_id",
        (MENU_ID,))]
    return {
        "menu": dict(menu),
        "grantedRoles": granted,
        "transferredRoles": legacy_roles,
    }


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        result = migrate(conn)
    finally:
        conn.close()
    print(f"== M3学生成长与学业分析单入口迁移: {path} ==")
    menu = result["menu"]
    print(f"菜单: {menu['menu_id']}  parent={menu['parent_id']}  "
          f"title={menu['title']}  sort={menu['sort_order']}")
    print(f"授权角色: {', '.join(result['grantedRoles'])}")
    print(f"旧入口转移角色: {', '.join(result['transferredRoles']) or '无'}")
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

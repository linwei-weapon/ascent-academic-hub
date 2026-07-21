"""决策简报菜单迁移：把 /admin/reports/decision 挂到 AI管理决策 分组并授权。

幂等：只插入/更新 sys_menu 一行并补齐 sys_role_menu 授权，不触碰其他菜单。
角色范围与 管理要情 一致（管理决策受众）。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_decision_menu.py
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入

from backend.etl import config

MENU = ("/admin/reports/decision", "/admin/decision", "决策简报",
        "/admin/reports/decision", "DataBoard", 200)
ROLES = ("school_leader", "dean", "dept_research", "dept_practice",
         "quality_office", "college_dean", "college_secretary")


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("""
        INSERT INTO sys_menu(menu_id,parent_id,title,path,icon,sort_order)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(menu_id) DO UPDATE SET
            parent_id=excluded.parent_id,
            title=excluded.title,
            path=excluded.path,
            icon=excluded.icon,
            sort_order=excluded.sort_order
    """, MENU)
    for role_id in ROLES:
        conn.execute("""INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id)
                        VALUES(?,?)""", (role_id, MENU[0]))
    conn.commit()


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    migrate(conn)
    row = conn.execute(
        "SELECT menu_id,parent_id,title,sort_order FROM sys_menu WHERE menu_id=?",
        (MENU[0],)).fetchone()
    grants = [r[0] for r in conn.execute(
        "SELECT role_id FROM sys_role_menu WHERE menu_id=? ORDER BY role_id",
        (MENU[0],))]
    print(f"== 决策简报菜单迁移: {path} ==")
    print(f"  菜单: {row}")
    print(f"  授权角色: {', '.join(grants)}")
    conn.close()
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

"""决策简报收口迁移（v2）：旧「管理要情」「决策研判」菜单与授权下线。

Skill链路决策简报（/admin/reports/decision，v1迁移已建）统一替代两个旧页面：
- 删除 sys_menu 中 management-briefing / decision-simulation 两行
- 删除 sys_role_menu 对应授权（旧角色受众已由决策简报菜单覆盖）

幂等。运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_decision_menu_v2.py
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入

from backend.etl import config

RETIRED = ("/admin/reports/management-briefing", "/admin/reports/decision-simulation")
KEEP = "/admin/reports/decision"


def migrate(conn: sqlite3.Connection) -> None:
    for menu_id in RETIRED:
        conn.execute("DELETE FROM sys_role_menu WHERE menu_id=?", (menu_id,))
        conn.execute("DELETE FROM sys_menu WHERE menu_id=?", (menu_id,))
    conn.commit()


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    migrate(conn)
    rows = conn.execute("""
        SELECT menu_id,title,sort_order FROM sys_menu
        WHERE parent_id='/admin/decision' ORDER BY sort_order
    """).fetchall()
    grants = [r[0] for r in conn.execute(
        "SELECT role_id FROM sys_role_menu WHERE menu_id=? ORDER BY role_id", (KEEP,))]
    print(f"== 决策简报收口迁移(v2): {path} ==")
    print(f"  AI管理决策分组剩余菜单: {[(r[0], r[1]) for r in rows]}")
    print(f"  决策简报授权角色: {', '.join(grants)}")
    conn.close()
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

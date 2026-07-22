# -*- coding: utf-8 -*-
"""专家问策菜单迁移（产品终稿 R5）：「AI管理决策」下新增二级菜单「专家问策」。

- 新增 sys_menu 行：/admin/reports/advice（父级 /admin/decision，排在决策简报之后）
- 授权角色与「决策简报」(/admin/reports/decision) 完全一致：
  问策与简报是同一能力（推/拉双形态），不引入新的授权维度
- 幂等：重复执行不产生重复行、不改变已有授权

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_decision_advice_menu.py
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入

from backend.etl import config

MENU_ID = "/admin/reports/advice"
PARENT_ID = "/admin/decision"
BRIEFING_MENU = "/admin/reports/decision"


def migrate(conn: sqlite3.Connection) -> None:
    # 菜单行：已存在则只更新标题/排序，不存在则插入
    row = conn.execute(
        "SELECT menu_id FROM sys_menu WHERE menu_id=?", (MENU_ID,)).fetchone()
    if row:
        conn.execute("""
            UPDATE sys_menu SET parent_id=?, title=?, path=?, sort_order=?
            WHERE menu_id=?
        """, (PARENT_ID, "专家问策", MENU_ID, 201, MENU_ID))
    else:
        # 复用决策简报菜单的其它列结构（icon/component 等允许为空则置空）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sys_menu)").fetchall()]
        base = {c: None for c in cols}
        base.update({
            "menu_id": MENU_ID, "parent_id": PARENT_ID,
            "title": "专家问策", "path": MENU_ID, "sort_order": 201,
        })
        # 若表含 enabled/visible 类标记列，默认启用
        for flag in ("enabled", "visible", "is_enabled"):
            if flag in base:
                base[flag] = 1
        names = ", ".join(base.keys())
        marks = ", ".join("?" for _ in base)
        conn.execute(f"INSERT INTO sys_menu({names}) VALUES({marks})",
                     tuple(base.values()))

    # 授权：与决策简报完全一致
    roles = [r[0] for r in conn.execute(
        "SELECT DISTINCT role_id FROM sys_role_menu WHERE menu_id=?",
        (BRIEFING_MENU,)).fetchall()]
    for role_id in roles:
        exists = conn.execute("""
            SELECT 1 FROM sys_role_menu WHERE role_id=? AND menu_id=?
        """, (role_id, MENU_ID)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO sys_role_menu(role_id, menu_id) VALUES(?,?)",
                (role_id, MENU_ID))
    conn.commit()


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    migrate(conn)
    rows = conn.execute("""
        SELECT menu_id, title, sort_order FROM sys_menu
        WHERE parent_id=? ORDER BY sort_order
    """, (PARENT_ID,)).fetchall()
    grants = [r[0] for r in conn.execute(
        "SELECT role_id FROM sys_role_menu WHERE menu_id=? ORDER BY role_id",
        (MENU_ID,)).fetchall()]
    print(f"== 专家问策菜单迁移(R5): {path} ==")
    print(f"  AI管理决策二级菜单: {[(r[0], r[1]) for r in rows]}")
    print(f"  专家问策授权角色: {', '.join(grants)}")
    conn.close()
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

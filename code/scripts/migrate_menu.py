"""一次性幂等迁移：对齐侧边栏菜单 + 新增「系统管理」三页菜单并绑定到管理员(dean)。

只动 sys_menu / sys_role_menu，不重 seed、不碰其他演示数据。可重复执行。

运行：cd 平台管理端-0618 && python -X utf8 scripts/migrate_menu.py
"""
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入

from backend.etl import config

ADMIN_ROLE = "dean"
RULE_GOVERNANCE_ROLES = ("dean", "quality_office", "school_leader")

# 期望的最终顺序（menu_id == path）。去实践教学；教学运行分析升到培养质量上方；
# 报表中心移到系统设置上方（系统管理三页其后、系统设置收尾）。
MENU_ORDER = [
    "/admin/dashboard",
    "/admin/alert",
    "/admin/operation/courses",
    "/admin/curriculum",
    "/admin/faculty",
    "/admin/students/analysis",
    "/admin/reports",
    "/admin/system/accounts",
    "/admin/system/menus",
    "/admin/system/roles",
    "/admin/settings",
]

# 新增菜单：menu_id, title, icon
NEW_MENUS = [
    ("/admin/system/accounts", "账号管理", "User"),
    ("/admin/system/menus", "菜单管理", "Menu"),
    ("/admin/system/roles", "角色管理", "UserFilled"),
]

# 历史残留（如存在则清掉，幂等）：school/sync + 已下线的实践教学分析
OBSOLETE = ["/admin/school", "/admin/sync", "/admin/practice"]


def main() -> None:
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # 1) 清掉历史残留菜单
    for mid in OBSOLETE:
        cur.execute("DELETE FROM sys_role_menu WHERE menu_id=?", (mid,))
        cur.execute("DELETE FROM sys_menu WHERE menu_id=?", (mid,))

    # 2) UPSERT 新增菜单（菜单管理三页）
    for mid, title, icon in NEW_MENUS:
        cur.execute("""
            INSERT INTO sys_menu (menu_id, parent_id, title, path, icon, sort_order)
            VALUES (?, NULL, ?, ?, ?, 0)
            ON CONFLICT(menu_id) DO UPDATE SET title=excluded.title, icon=excluded.icon
        """, (mid, title, mid, icon))

    # 3) 统一排序
    for order, mid in enumerate(MENU_ORDER, start=1):
        cur.execute("UPDATE sys_menu SET sort_order=? WHERE menu_id=?", (order, mid))

    # 4) 新菜单绑定到管理员角色（幂等）
    for mid, _, _ in NEW_MENUS:
        cur.execute("""
            INSERT OR IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (?, ?)
        """, (ADMIN_ROLE, mid))

    # 瑙勫垯娌荤悊鑱岃矗鍒嗙锛氳川閲忓姙瀹℃牳銆佹牎棰嗗婵€娲伙紝闇€鍏卞悓璁块棶绯荤粺璁剧疆銆?    for role_id in RULE_GOVERNANCE_ROLES:
    for governance_role in RULE_GOVERNANCE_ROLES:
        cur.execute("""INSERT OR IGNORE INTO sys_role_menu (role_id,menu_id)
                       VALUES (?, '/admin/settings')""", (governance_role,))
    cur.execute("""INSERT OR IGNORE INTO sys_role_menu (role_id,menu_id)
                   VALUES ('school_leader', '/admin/curriculum')""")

    conn.commit()

    print("== 迁移后 sys_menu ==")
    for r in conn.execute(
            "SELECT sort_order, menu_id, title FROM sys_menu ORDER BY sort_order"):
        print(f"  {r[0]:>2}  {r[1]:<28} {r[2]}")
    n = conn.execute(
        "SELECT COUNT(*) FROM sys_role_menu WHERE role_id=?", (ADMIN_ROLE,)).fetchone()[0]
    print(f"== 管理员({ADMIN_ROLE}) 可见菜单数: {n}")
    conn.close()
    print("迁移完成。")


if __name__ == "__main__":
    main()

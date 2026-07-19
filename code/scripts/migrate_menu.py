"""P1幂等迁移：把侧边栏统一为三个一级分组和业务模块二级菜单。

只修改 sys_menu / sys_role_menu，不重跑 seed，不触碰业务事实数据。
sys_role_menu 最终只保存叶子菜单权限；父菜单由登录接口按叶子授权补齐。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_menu.py
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入

from backend.etl import config

ADMIN_ROLE = "dean"

# menu_id, parent_id, title, path, icon, sort_order
TARGET_MENUS = [
    ("/admin/analysis", None, "教学管理分析", "/admin/analysis", "DataAnalysis", 1),
    ("/admin/decision", None, "AI管理决策", "/admin/decision", "MagicStick", 2),
    ("/admin/system", None, "系统管理", "/admin/system", "Setting", 3),

    ("/admin/dashboard", "/admin/analysis", "教学数据总览",
     "/admin/dashboard", "Odometer", 101),
    ("/admin/alert", "/admin/analysis", "学业预警监控",
     "/admin/alert", "Warning", 102),
    ("/admin/operation/courses", "/admin/analysis", "教学运行分析",
     "/admin/operation/courses", "Calendar", 103),
    ("/admin/curriculum", "/admin/analysis", "培养质量分析",
     "/admin/curriculum", "Reading", 104),
    ("/admin/faculty", "/admin/analysis", "师资保障分析",
     "/admin/faculty", "User", 105),
    ("/admin/students/analysis", "/admin/analysis", "学生成长与学业分析",
     "/admin/students/analysis", "DataLine", 106),

    ("/admin/reports/management-briefing", "/admin/decision", "管理要情",
     "/admin/reports/management-briefing", "Bell", 201),
    ("/admin/reports/decision-simulation", "/admin/decision", "决策研判",
     "/admin/reports/decision-simulation", "Opportunity", 202),

    ("/admin/system/accounts", "/admin/system", "账号管理",
     "/admin/system/accounts", "User", 301),
    ("/admin/system/roles", "/admin/system", "角色与功能权限",
     "/admin/system/roles", "UserFilled", 302),
    ("/admin/system/menus", "/admin/system", "菜单管理",
     "/admin/system/menus", "Menu", 303),
    ("/admin/system/permissions", "/admin/system", "数据权限",
     "/admin/system/permissions", "Key", 304),
    ("/admin/system/kpis", "/admin/system", "指标与口径管理",
     "/admin/system/kpis", "DataAnalysis", 305),
    ("/admin/system/schemes", "/admin/system", "分析方案管理",
     "/admin/system/schemes", "Management", 306),
    ("/admin/system/audit", "/admin/system", "审计日志",
     "/admin/system/audit", "Document", 307),
    ("/admin/settings", "/admin/system", "系统参数",
     "/admin/settings", "Setting", 308),
]

PARENT_IDS = {row[0] for row in TARGET_MENUS if row[1] is None}
LEAF_IDS = {row[0] for row in TARGET_MENUS if row[1] is not None}
SYSTEM_LEAF_IDS = {
    row[0] for row in TARGET_MENUS if row[1] == "/admin/system"
}

# 历史菜单权限转移到新的业务模块叶子。
LEGACY_GRANT_TRANSFER = {
    "/admin/operation": ("/admin/operation/courses",),
    "/admin/operation/classroom": ("/admin/operation/courses",),
    "/admin/operation/schedule-changes": ("/admin/operation/courses",),
    "/admin/operation/teacher-load": ("/admin/operation/courses",),
    "/admin/operation/schedule-analysis": ("/admin/operation/courses",),
    "/admin/students/list": ("/admin/students/analysis",),
    "/admin/reports": (
        "/admin/reports/management-briefing",
        "/admin/reports/decision-simulation",
    ),
}

OBSOLETE = {
    "/admin/school", "/admin/sync", "/admin/practice",
    "/admin/alert/monitor", "/admin/alert/rules", "/admin/alert/discovery",
    *LEGACY_GRANT_TRANSFER.keys(),
}


def snapshot(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("""
        SELECT menu_id,parent_id,title,path,sort_order
        FROM sys_menu ORDER BY sort_order,menu_id
    """).fetchall()


def migrate(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    transfers: list[tuple[str, str]] = []
    for old_id, targets in LEGACY_GRANT_TRANSFER.items():
        roles = [r[0] for r in cur.execute(
            "SELECT role_id FROM sys_role_menu WHERE menu_id=?", (old_id,))]
        transfers.extend((role_id, target) for role_id in roles for target in targets)

    # 先补齐目标菜单，保证转移角色授权时外键/引用始终有效。
    for row in TARGET_MENUS:
        cur.execute("""
            INSERT INTO sys_menu(menu_id,parent_id,title,path,icon,sort_order)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(menu_id) DO UPDATE SET
                parent_id=excluded.parent_id,
                title=excluded.title,
                path=excluded.path,
                icon=excluded.icon,
                sort_order=excluded.sort_order
        """, row)

    for role_id, target in transfers:
        cur.execute("""INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id)
                       VALUES(?,?)""", (role_id, target))

    # 校领导应能进入AI管理决策；系统管理员(dean)明确拥有全部叶子菜单。
    for target in (
        "/admin/reports/management-briefing",
        "/admin/reports/decision-simulation",
    ):
        cur.execute("""INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id)
                       VALUES('school_leader',?)""", (target,))
    for leaf_id in LEAF_IDS:
        cur.execute("""INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id)
                       VALUES(?,?)""", (ADMIN_ROLE, leaf_id))
    # 关系型学生管理角色可进入同一教学数据总览，接口仍按带班/带生范围过滤。
    for role_id in ("counselor", "class_adviser", "mentor"):
        cur.execute("""INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id)
                       VALUES(?, '/admin/dashboard')""", (role_id,))
    for leaf_id in SYSTEM_LEAF_IDS:
        cur.execute("""DELETE FROM sys_role_menu
                       WHERE menu_id=? AND role_id<>?""",
                    (leaf_id, ADMIN_ROLE))

    # sys_role_menu 只保存目标叶子；移除父级、旧Tab和历史残留授权。
    for menu_id in PARENT_IDS | OBSOLETE:
        cur.execute("DELETE FROM sys_role_menu WHERE menu_id=?", (menu_id,))

    # 删除不再作为侧栏真值的旧菜单。保留业务路由，不保留菜单记录。
    for menu_id in OBSOLETE:
        if menu_id not in LEAF_IDS and menu_id not in PARENT_IDS:
            cur.execute("DELETE FROM sys_menu WHERE menu_id=?", (menu_id,))

    # 删除不属于目标结构的其他菜单，确保三组两级结构是唯一真值。
    placeholders = ",".join("?" for _ in TARGET_MENUS)
    cur.execute(
        f"DELETE FROM sys_role_menu WHERE menu_id NOT IN ({placeholders})",
        tuple(row[0] for row in TARGET_MENUS))
    cur.execute(
        f"DELETE FROM sys_menu WHERE menu_id NOT IN ({placeholders})",
        tuple(row[0] for row in TARGET_MENUS))
    conn.commit()


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    before = snapshot(conn)
    migrate(conn)
    after = snapshot(conn)

    print(f"== P1菜单迁移: {path} ==")
    print(f"迁移前 {len(before)} 项，迁移后 {len(after)} 项")
    for menu_id, parent_id, title, _, order in after:
        print(f"  {order:>3}  {menu_id:<42} {title}  parent={parent_id or '-'}")
    leaf_grants = conn.execute(
        "SELECT COUNT(*) FROM sys_role_menu WHERE role_id=?",
        (ADMIN_ROLE,)).fetchone()[0]
    print(f"系统管理员({ADMIN_ROLE}) 叶子菜单权限: {leaf_grants}")
    conn.close()
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

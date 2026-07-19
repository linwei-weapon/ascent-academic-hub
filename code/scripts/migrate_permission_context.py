"""P2幂等迁移：建立用户身份、人员映射、用户范围和动作权限底座。

旧表不会被删除。迁移会把每个现有账号的单角色和角色范围复制为一个
默认工作身份，供统一权限上下文双读和后续模块迁移使用。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_permission_context.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl import config
from backend.permission_catalog import ROLE_ACTIONS

RELATION_ROLES = {
    "class_adviser": ("班主任", "staff_relation"),
    "mentor": ("学业导师", "staff_relation"),
}

DDL = """
CREATE TABLE IF NOT EXISTS sys_user_staff (
    username TEXT NOT NULL,
    staff_id TEXT NOT NULL,
    valid_from TEXT NOT NULL DEFAULT '1970-01-01',
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'manual',
    source_updated_at TEXT,
    PRIMARY KEY(username, staff_id, valid_from)
);

CREATE TABLE IF NOT EXISTS sys_user_role (
    user_role_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    role_id TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'legacy_migration'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_role_default
    ON sys_user_role(username) WHERE is_default=1 AND status='active';
CREATE INDEX IF NOT EXISTS idx_user_role_active
    ON sys_user_role(username, status, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS sys_user_scope (
    user_scope_id TEXT PRIMARY KEY,
    user_role_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    valid_from TEXT NOT NULL DEFAULT '1970-01-01',
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'legacy_migration',
    UNIQUE(user_role_id, scope_type, scope_id, valid_from)
);
CREATE INDEX IF NOT EXISTS idx_user_scope_active
    ON sys_user_scope(user_role_id, status, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS sys_role_action (
    role_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    PRIMARY KEY(role_id, action_id)
);
"""


def _identity_id(username: str, role_id: str) -> str:
    return f"UR:{username}:{role_id}"


def migrate(conn: sqlite3.Connection) -> dict:
    conn.executescript(DDL)
    system_parent = conn.execute(
        "SELECT 1 FROM sys_menu WHERE menu_id='/admin/system'"
    ).fetchone()
    if system_parent:
        conn.execute("""
            INSERT INTO sys_menu(menu_id,parent_id,title,path,icon,sort_order)
            VALUES('/admin/system/permissions','/admin/system','数据权限',
                   '/admin/system/permissions','Key',304)
            ON CONFLICT(menu_id) DO UPDATE SET
              parent_id=excluded.parent_id,title=excluded.title,path=excluded.path,
              icon=excluded.icon,sort_order=excluded.sort_order
        """)
        conn.execute("""
            INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id)
            VALUES('dean','/admin/system/permissions')
        """)
    for role_id, (name, scope_type) in RELATION_ROLES.items():
        conn.execute("""
            INSERT INTO sys_role(role_id,name,data_scope_type) VALUES(?,?,?)
            ON CONFLICT(role_id) DO UPDATE SET
              name=excluded.name,data_scope_type=excluded.data_scope_type
        """, (role_id, name, scope_type))
        for menu_id in ("/admin/alert", "/admin/students/analysis"):
            if conn.execute(
                "SELECT 1 FROM sys_menu WHERE menu_id=?", (menu_id,)
            ).fetchone():
                conn.execute(
                    "INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id) VALUES(?,?)",
                    (role_id, menu_id),
                )
    users = conn.execute("""
        SELECT username,role_id FROM sys_user
        WHERE status='active' AND role_id IS NOT NULL
        ORDER BY username
    """).fetchall()
    for username, role_id in users:
        identity_id = _identity_id(username, role_id)
        conn.execute(
            "UPDATE sys_user_role SET is_default=0 WHERE username=?",
            (username,),
        )
        conn.execute("""
            INSERT INTO sys_user_role(
                user_role_id,username,role_id,is_default,status,source
            ) VALUES(?,?,?,1,'active','legacy_migration')
            ON CONFLICT(user_role_id) DO UPDATE SET
                username=excluded.username,
                role_id=excluded.role_id,
                status='active'
        """, (identity_id, username, role_id))
        scope_type_row = conn.execute(
            "SELECT data_scope_type FROM sys_role WHERE role_id=?", (role_id,)
        ).fetchone()
        scope_type = scope_type_row[0] if scope_type_row else None
        if scope_type and scope_type != "all":
            for (scope_id,) in conn.execute(
                "SELECT scope_id FROM sys_role_scope WHERE role_id=? ORDER BY scope_id",
                (role_id,),
            ):
                user_scope_id = f"US:{identity_id}:{scope_type}:{scope_id}"
                conn.execute("""
                    INSERT INTO sys_user_scope(
                        user_scope_id,user_role_id,scope_type,scope_id,status,source
                    ) VALUES(?,?,?,?, 'active','legacy_migration')
                    ON CONFLICT(user_scope_id) DO UPDATE SET
                        status='active',
                        source='legacy_migration'
                """, (user_scope_id, identity_id, scope_type, scope_id))
                if scope_type == "teacher":
                    conn.execute("""
                        INSERT OR IGNORE INTO sys_user_staff(
                            username,staff_id,status,source
                        ) VALUES(?,?,'active','legacy_migration')
                    """, (username, scope_id))

    available_roles = {
        row[0] for row in conn.execute("SELECT role_id FROM sys_role").fetchall()
    }
    for role_id, actions in ROLE_ACTIONS.items():
        if role_id not in available_roles:
            continue
        for action_id in actions:
            conn.execute(
                "INSERT OR IGNORE INTO sys_role_action(role_id,action_id) VALUES(?,?)",
                (role_id, action_id),
            )
    conn.commit()
    return {
        "identities": conn.execute("SELECT COUNT(*) FROM sys_user_role").fetchone()[0],
        "scopes": conn.execute("SELECT COUNT(*) FROM sys_user_scope").fetchone()[0],
        "staffMappings": conn.execute("SELECT COUNT(*) FROM sys_user_staff").fetchone()[0],
        "actions": conn.execute("SELECT COUNT(*) FROM sys_role_action").fetchone()[0],
    }


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    try:
        result = migrate(conn)
    finally:
        conn.close()
    print(f"== P2权限上下文迁移: {path} ==")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

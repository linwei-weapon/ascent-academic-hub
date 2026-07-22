"""M2幂等迁移：为班主任/学业导师生成演示账号并接通人员映射。

从 V2 dim_staff（staff_type IN ('mentor','class_adviser')，且仅有
active 人员—学生关系者）生成：
- sys_user：username=工号，name=姓名，role_id 按 staff_type，
  密码为现有演示约定（hash_password(DEMO_PASSWORD)，不硬编码哈希串）；
- sys_user_role：UR:{username}:{role}，is_default=1；
- sys_user_staff：username→staff_id 映射（权限范围解析的数据源）。

已存在的账号/身份/映射一律跳过，不覆盖已有密码。可重复执行。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_staff_accounts.py
"""
from __future__ import annotations

import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.api import db as dbm
from backend.etl import config
from backend.etl.seed import DEMO_PASSWORD, hash_password

SOURCE = "staff_migration"
ROLE_BY_STAFF_TYPE = {"mentor": "mentor", "class_adviser": "class_adviser"}


def _staff_with_active_relations(v2_conn: sqlite3.Connection) -> list[dict]:
    """仅取有 active 人员—学生关系的班主任/导师（账号没有数据范围则无意义）。"""
    return dbm.query(v2_conn, """
        SELECT DISTINCT s.staff_id, s.display_name, s.staff_type
        FROM dim_staff s
        JOIN staff_student_scope r ON r.staff_id=s.staff_id
          AND COALESCE(r.status,'active')='active'
          AND date(r.valid_from)<=date('now')
          AND (r.valid_to IS NULL OR date(r.valid_to)>=date('now'))
        WHERE s.staff_type IN ('mentor','class_adviser')
        ORDER BY s.staff_type, s.staff_id
    """)


def _earliest_relation_from(v2_conn: sqlite3.Connection, staff_id: str) -> str:
    row = dbm.query_one(v2_conn, """
        SELECT MIN(date(valid_from)) d FROM staff_student_scope
        WHERE staff_id=? AND COALESCE(status,'active')='active'
    """, (staff_id,))
    return (row["d"] if row and row["d"] else None) or "1970-01-01"


def migrate(conn: sqlite3.Connection, v2_conn: sqlite3.Connection) -> dict:
    stats = {"accountsCreated": 0, "accountsSkipped": 0,
             "identitiesCreated": 0, "staffMappingsCreated": 0,
             "mentorAccounts": 0, "classAdviserAccounts": 0}
    for staff in _staff_with_active_relations(v2_conn):
        role_id = ROLE_BY_STAFF_TYPE[staff["staff_type"]]
        username = staff["staff_id"]
        existing = dbm.query_one(conn,
            "SELECT username FROM sys_user WHERE username=?", (username,))
        if existing:
            stats["accountsSkipped"] += 1
        else:
            dbm.execute(conn, """INSERT INTO sys_user
                (username,password_hash,name,role_id,status)
                VALUES (?,?,?,?,'active')""",
                (username, hash_password(DEMO_PASSWORD),
                 staff["display_name"] or username, role_id))
            stats["accountsCreated"] += 1
            key = "mentorAccounts" if role_id == "mentor" else "classAdviserAccounts"
            stats[key] += 1
        cur = dbm.execute(conn, """INSERT OR IGNORE INTO sys_user_role
            (user_role_id,username,role_id,is_default,status,source)
            VALUES (?,?,?,1,'active',?)""",
            (f"UR:{username}:{role_id}", username, role_id, SOURCE))
        if cur.rowcount:
            stats["identitiesCreated"] += 1
        mapped = dbm.query_one(conn, """SELECT 1 FROM sys_user_staff
            WHERE username=? AND staff_id=? AND status='active'""",
            (username, staff["staff_id"]))
        if not mapped:
            dbm.execute(conn, """INSERT INTO sys_user_staff
                (username,staff_id,valid_from,valid_to,status,source,source_updated_at)
                VALUES (?,?,?,NULL,'active',?,datetime('now'))""",
                (username, staff["staff_id"],
                 _earliest_relation_from(v2_conn, staff["staff_id"]), SOURCE))
            stats["staffMappingsCreated"] += 1
    return stats


def main() -> None:
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    v2_conn = dbm.get_v2_conn()
    try:
        stats = migrate(conn, v2_conn)
        conn.commit()
    finally:
        v2_conn.close()
    total = conn.execute("""SELECT COUNT(*) FROM sys_user
        WHERE role_id IN ('mentor','class_adviser')""").fetchone()[0]
    print(f"班主任/导师账号迁移完成：{stats}；现有两类角色账号共 {total} 个")
    conn.close()


if __name__ == "__main__":
    main()

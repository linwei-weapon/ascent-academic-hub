"""预警事件责任人分派：按"学生 → 有效人员关系"匹配。

分派链（设计决策见 docs/91-管理分析增强实施计划.md M2）：
1. 主责任人：学生行政班命中 sys_user_scope(class) 的 active 辅导员。
2. 协同责任人：V2 staff_student_scope 中该生的 active 班主任 / 学业导师，
   经 sys_user_staff 反查登录账号。
3. 主责任回退：该生学院命中 sys_user_scope(college) 的学院教学秘书；
   再无则保底回退第一个 active 辅导员，保证事件始终有主责任人。
"""
from __future__ import annotations

import sqlite3
from datetime import date

from .. import db as dbm

# 协同责任人关系映射：V2 relation_type → (角色, 中文标签)
COLLABORATOR_RELATIONS = {
    "class_adviser": ("class_adviser", "班主任"),
    "学业导师": ("mentor", "学业导师"),
    "导师": ("mentor", "学业导师"),
    "mentor": ("mentor", "学业导师"),
}

def _valid(alias: str) -> str:
    return (f"{alias}.status='active' "
            f"AND ({alias}.valid_from IS NULL OR {alias}.valid_from<=?) "
            f"AND ({alias}.valid_to IS NULL OR {alias}.valid_to>=?)")


def _today() -> str:
    return date.today().isoformat()


def _scoped_users(conn: sqlite3.Connection, role_id: str,
                  scope_type: str, scope_id: str) -> list[str]:
    """指定角色中，工作身份范围命中 scope_type/scope_id 的 active 账号。"""
    today = _today()
    rows = dbm.query(conn, f"""
        SELECT DISTINCT u.username
        FROM sys_user u
        JOIN sys_user_role ur ON ur.username=u.username AND ur.role_id=?
          AND {_valid('ur')}
        JOIN sys_user_scope us ON us.user_role_id=ur.user_role_id
          AND us.scope_type=? AND us.scope_id=? AND {_valid('us')}
        WHERE u.status='active'
        ORDER BY u.username
    """, (role_id, today, today, scope_type, scope_id, today, today))
    return [row["username"] for row in rows]


def _first_active_counselor(conn: sqlite3.Connection) -> str | None:
    row = dbm.query_one(conn, """SELECT username FROM sys_user
        WHERE role_id='counselor' AND status='active' ORDER BY username LIMIT 1""")
    return row["username"] if row else None


def _collaborators(conn: sqlite3.Connection, student_id: str,
                   v2_conn: sqlite3.Connection) -> list[dict]:
    """该生的 active 班主任/学业导师账号（staff_student_scope → sys_user_staff）。"""
    today = _today()
    relations = dbm.query(v2_conn, """
        SELECT DISTINCT staff_id, relation_type FROM staff_student_scope
        WHERE student_id=? AND COALESCE(status,'active')='active'
          AND date(valid_from)<=date('now')
          AND (valid_to IS NULL OR date(valid_to)>=date('now'))
        ORDER BY relation_type, staff_id
    """, (student_id,))
    result, seen = [], set()
    for rel in relations:
        mapping = COLLABORATOR_RELATIONS.get(rel["relation_type"])
        if not mapping:
            continue
        role_id, label = mapping
        user = dbm.query_one(conn, f"""
            SELECT us.username FROM sys_user_staff us
            JOIN sys_user u ON u.username=us.username AND u.status='active'
            WHERE us.staff_id=? AND {_valid('us')}
            ORDER BY us.username LIMIT 1
        """, (rel["staff_id"], today, today))
        if not user or user["username"] in seen:
            continue
        seen.add(user["username"])
        result.append({
            "username": user["username"], "role_id": role_id,
            "responsibility": "collaborator",
            "reason": f"按学生人员关系匹配协同责任人（{label}）",
        })
    return result


def assignees_for_student(conn: sqlite3.Connection, student_id: str,
                          v2_conn: sqlite3.Connection | None = None) -> list[dict]:
    """返回该学生预警事件的责任人列表，主责任人在前。

    每项：{username, role_id, responsibility('primary'|'collaborator'), reason}
    """
    student = dbm.query_one(conn, """SELECT class_id, college_id FROM dim_student
        WHERE student_id=?""", (student_id,))
    class_id = student["class_id"] if student else None
    college_id = student["college_id"] if student else None

    primaries: list[dict] = []
    counselors = _scoped_users(conn, "counselor", "class", class_id) if class_id else []
    if counselors:
        primaries = [{
            "username": username, "role_id": "counselor",
            "responsibility": "primary",
            "reason": f"按学生行政班({class_id})匹配主责辅导员",
        } for username in counselors]
    else:
        secretaries = (_scoped_users(conn, "college_secretary", "college", college_id)
                       if college_id else [])
        if secretaries:
            primaries = [{
                "username": username, "role_id": "college_secretary",
                "responsibility": "primary",
                "reason": f"学生行政班未配置辅导员，回退学院({college_id})教学秘书主责",
            } for username in secretaries]
        else:
            # 保底：演示数据未覆盖全部学院的辅导员/秘书配置，仍须保证事件有主责任人。
            fallback = _first_active_counselor(conn)
            if fallback:
                primaries = [{
                    "username": fallback, "role_id": "counselor",
                    "responsibility": "primary",
                    "reason": "未匹配到班级辅导员/学院秘书，保底分派第一个辅导员",
                }]

    collaborators: list[dict] = []
    own_v2 = v2_conn is None
    if own_v2:
        v2_conn = dbm.get_v2_conn()
    try:
        collaborators = _collaborators(conn, student_id, v2_conn)
    finally:
        if own_v2:
            v2_conn.close()
    # 协同与主责去重（同一账号不重复出现）
    primary_usernames = {a["username"] for a in primaries}
    collaborators = [a for a in collaborators if a["username"] not in primary_usernames]
    return primaries + collaborators


def insert_event_assignees(conn: sqlite3.Connection, event_id: int,
                           assignees: list[dict], assigned_at: str,
                           reason_prefix: str = "") -> int:
    """把责任人写入 alert_assignee（已存在跳过），返回新增行数。"""
    inserted = 0
    for a in assignees:
        cur = dbm.execute(conn, """INSERT OR IGNORE INTO alert_assignee
            (event_id,username,role_id,assignment_reason,assigned_at,is_primary)
            VALUES (?,?,?,?,?,?)""",
            (event_id, a["username"], a["role_id"],
             f"{reason_prefix}{a['reason']}", assigned_at,
             1 if a["responsibility"] == "primary" else 0))
        inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return inserted

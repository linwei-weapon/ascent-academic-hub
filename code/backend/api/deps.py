"""FastAPI 依赖：DB 连接、当前用户、数据范围过滤。"""
import sqlite3
from typing import Generator, Optional

from fastapi import Depends, Header

from . import db as dbm
from .envelope import ApiError
from .permission_context import build_permission_context, has_action
from .security import decode_token


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = dbm.get_conn()
    try:
        yield conn
    finally:
        conn.close()


def get_db_rw() -> Generator[sqlite3.Connection, None, None]:
    """可写连接依赖：正常结束自动 commit，异常回滚。"""
    conn = dbm.get_conn_rw()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_v2_db() -> Generator[sqlite3.Connection, None, None]:
    """V2只读数据库依赖。鉴权仍由现有库的get_current_user完成。"""
    conn = dbm.get_v2_conn()
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(authorization: str = Header(default=""),
                     active_identity: str = Header(default="", alias="X-Active-Identity"),
                     conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """解析 Bearer token → 返回 sys_user 行（含 role_id）。失败 401。"""
    if not authorization.lower().startswith("bearer "):
        raise ApiError("未登录", code=401, status_code=401)
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload:
        raise ApiError("登录已过期，请重新登录", code=401, status_code=401)
    if payload.get("jti") and dbm.query_one(
            conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sys_revoked_token'"):
        if dbm.query_one(conn, "SELECT 1 FROM sys_revoked_token WHERE jti=?", (payload["jti"],)):
            raise ApiError("登录已失效，请重新登录", code=401, status_code=401)
    user = dbm.query_one(
        conn, "SELECT user_id,username,name,role_id,status FROM sys_user WHERE username=?",
        (payload.get("sub"),))
    if not user or user.get("status") != "active":
        raise ApiError("用户不存在或已停用", code=401, status_code=401)
    context = build_permission_context(
        conn, user, active_identity.strip() or None,
    )
    user["role_id"] = context["activeRole"]
    user["staff_id"] = context.get("staffId")
    user["active_identity_id"] = context["activeIdentityId"]
    user["permission_context"] = context
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """后台管理写接口守卫：仅管理员角色可用。"""
    if not has_action(user, "system.manage"):
        raise ApiError("无权限执行此操作", code=403, status_code=403)
    return user


# ── 数据范围过滤 ──

def _get_scope(conn: sqlite3.Connection, role_id: str) -> Optional[dict]:
    """旧表兼容解析。受限角色无范围时返回denied，不再回退全校。"""
    row = dbm.query_one(conn,
        "SELECT data_scope_type FROM sys_role WHERE role_id=?", (role_id,))
    if not row:
        return {"type": "denied"}
    if row["data_scope_type"] == "all":
        return None
    scope_ids = [r["scope_id"] for r in dbm.query(
        conn, "SELECT scope_id FROM sys_role_scope WHERE role_id=?", (role_id,))]
    if not scope_ids:
        return {"type": "denied"}
    stype = row["data_scope_type"]
    if stype == "college":
        return {"type": "college", "college_ids": scope_ids}
    elif stype == "major":
        return {"type": "major", "major_ids": scope_ids}
    elif stype == "class":
        return {"type": "class", "class_ids": scope_ids}
    elif stype == "teacher":
        return {"type": "teacher", "teacher_ids": scope_ids}
    return {"type": "denied"}


def _scope_for_user(user: dict, conn: sqlite3.Connection) -> Optional[dict]:
    context = user.get("permission_context") or {}
    if context:
        if not context.get("authorized"):
            return {"type": "denied"}
        detail = context.get("detailScope") or {}
        scope_type = detail.get("type")
        ids = detail.get("sourceScopeIds") or []
        if scope_type == "all":
            return None
        if scope_type == "college":
            return {"type": "college", "college_ids": ids}
        if scope_type == "major":
            return {"type": "major", "major_ids": ids}
        if scope_type == "class":
            return {"type": "class", "class_ids": ids}
        if scope_type == "teacher":
            return {"type": "teacher", "teacher_ids": ids}
        if scope_type == "staff_relation" and context.get("staffId"):
            return {
                "type": "staff_relation",
                "staff_id": context["staffId"],
                "role_id": context.get("activeRole"),
            }
        return {"type": "denied"}
    return _get_scope(conn, user["role_id"])


def _staff_student_ids(user: dict) -> list[str]:
    cached = user.get("_staff_student_ids")
    if cached is not None:
        return cached
    scope = (user.get("permission_context") or {}).get("detailScope") or {}
    if scope.get("type") != "staff_relation" or not user.get("staff_id"):
        user["_staff_student_ids"] = []
        return []
    relation_types = {
        "class_adviser": ["class_adviser"],
        "mentor": ["学业导师", "导师", "mentor"],
        "counselor": ["counselor"],
    }.get(user.get("role_id"))
    v2_conn = dbm.get_v2_conn()
    try:
        params: list = [user["staff_id"]]
        relation_sql = ""
        if relation_types:
            relation_sql = f" AND relation_type IN ({','.join('?' * len(relation_types))})"
            params.extend(relation_types)
        rows = dbm.query(v2_conn, f"""
            SELECT DISTINCT student_id FROM staff_student_scope
            WHERE staff_id=?{relation_sql}
              AND COALESCE(status,'active')='active'
              AND date(valid_from)<=date('now')
              AND (valid_to IS NULL OR date(valid_to)>=date('now'))
            ORDER BY student_id
        """, tuple(params))
    finally:
        v2_conn.close()
    user["_staff_student_ids"] = [row["student_id"] for row in rows]
    return user["_staff_student_ids"]


def student_data_scope(user: dict, conn: sqlite3.Connection,
                       alias: str = "s") -> tuple[str, list]:
    """返回 (WHERE片段, 参数列表)，限定 dim_student 的数据范围。
    用于涉及学生维度过滤的 API（dashboard/alert/students/list 等）。
    无范围限制（all 角色）时返回 ("", [])。

    使用方式:
        frag, params = student_data_scope(user, conn, "s")
        if frag:
            where_clause = " AND " + frag
    """
    scope = _scope_for_user(user, conn)
    if not scope:
        return ("", [])
    if scope["type"] == "denied":
        return ("1=0", [])
    if scope["type"] == "college":
        ids = scope["college_ids"]
        if len(ids) == 1:
            return (f"{alias}.college_id = ?", ids)
        return (f"{alias}.college_id IN ({','.join('?' * len(ids))})", ids)
    elif scope["type"] == "major":
        ids = scope["major_ids"]
        if len(ids) == 1:
            return (f"{alias}.major_id = ?", ids)
        return (f"{alias}.major_id IN ({','.join('?' * len(ids))})", ids)
    elif scope["type"] == "class":
        ph = ",".join("?" * len(scope["class_ids"]))
        return (f"{alias}.class_id IN ({ph})", scope["class_ids"])
    elif scope["type"] == "teacher":
        # 任课教师：只看自己授课班级的学生
        return (f"""{alias}.student_id IN (
            SELECT DISTINCT g.student_id FROM fact_grade g
            JOIN fact_lesson l ON g.lesson_id = l.lesson_id AND g.semester_id = l.semester_id
            WHERE l.teacher_id IN ({','.join('?' * len(scope["teacher_ids"]))}))""",
                scope["teacher_ids"])
    elif scope["type"] == "staff_relation":
        ids = _staff_student_ids(user)
        if not ids:
            return ("1=0", [])
        return (
            f"{alias}.student_id IN ({','.join('?' * len(ids))})",
            ids,
        )
    return ("1=0", [])


def college_data_scope(user: dict, conn: sqlite3.Connection) -> tuple[str, list]:
    """限定学院维度的数据范围（如学院详情页/师资本院过滤）。
    用于 API 层面限制可访问的学院 ID。无限制返回 ("", [])。
    """
    scope = _scope_for_user(user, conn)
    if not scope:
        return ("", [])
    if scope["type"] == "denied":
        return ("1=0", [])
    if scope["type"] == "college":
        ids = scope["college_ids"]
        if len(ids) == 1:
            return ("college_id = ?", ids)
        return (f"college_id IN ({','.join('?' * len(ids))})", ids)
    elif scope["type"] == "major":
        # major 角色 → 关联查询该专业所属学院
        ids = scope["major_ids"]
        if len(ids) == 1:
            return (
                "college_id = (SELECT college_id FROM dim_major WHERE major_id = ?)",
                ids,
            )
        return (
            f"college_id IN (SELECT college_id FROM dim_major WHERE major_id IN "
            f"({','.join('?' * len(ids))}))",
            ids,
        )
    elif scope["type"] == "class":
        # class 角色 → 关联查询班级所属学院
        ph = ",".join("?" * len(scope["class_ids"]))
        return (f"college_id IN (SELECT DISTINCT college_id FROM dim_student "
                f"WHERE class_id IN ({ph}))", scope["class_ids"])
    elif scope["type"] == "staff_relation":
        ids = _staff_student_ids(user)
        if not ids:
            return ("1=0", [])
        return (
            f"college_id IN (SELECT DISTINCT college_id FROM dim_student "
            f"WHERE student_id IN ({','.join('?' * len(ids))}))",
            ids,
        )
    return ("1=0", [])


def major_data_scope(user: dict, conn: sqlite3.Connection) -> tuple[str, list]:
    """限定专业维度的数据范围。无限制返回 ("", [])。"""
    scope = _scope_for_user(user, conn)
    if not scope:
        return ("", [])
    if scope["type"] == "denied":
        return ("1=0", [])
    if scope["type"] == "major":
        ids = scope["major_ids"]
        if len(ids) == 1:
            return ("major_id = ?", ids)
        return (f"major_id IN ({','.join('?' * len(ids))})", ids)
    if scope["type"] == "class":
        ph = ",".join("?" * len(scope["class_ids"]))
        return (f"major_id IN (SELECT DISTINCT major_id FROM dim_student "
                f"WHERE class_id IN ({ph}))", scope["class_ids"])
    if scope["type"] == "college":
        ids = scope["college_ids"]
        if len(ids) == 1:
            return (
                "major_id IN (SELECT major_id FROM dim_major WHERE college_id = ?)",
                ids,
            )
        return (
            f"major_id IN (SELECT major_id FROM dim_major WHERE college_id IN "
            f"({','.join('?' * len(ids))}))",
            ids,
        )
    if scope["type"] == "staff_relation":
        ids = _staff_student_ids(user)
        if not ids:
            return ("1=0", [])
        return (
            f"major_id IN (SELECT DISTINCT major_id FROM dim_student "
            f"WHERE student_id IN ({','.join('?' * len(ids))}))",
            ids,
        )
    return ("1=0", [])

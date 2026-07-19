"""鉴权路由：登录/当前用户/登出。仅菜单权限（sys_role_menu）。"""
import sqlite3

from fastapi import APIRouter, Depends, Request, Header
from pydantic import BaseModel, Field

from .. import db as dbm
from ..deps import get_db, get_db_rw, get_current_user
from ..envelope import ok, ApiError
from ..security import verify_password, create_token, decode_token
from ..security_governance import (client_key, login_is_limited, record_login,
                                   write_audit)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


def _menus_for_role(conn: sqlite3.Connection, role_id: str) -> list[dict]:
    """返回角色获授权的叶子菜单及其父菜单。

    sys_role_menu 只保存叶子权限；父菜单只是导航分组，不能作为获得全部
    子菜单权限的凭据。登录响应自动补齐至少有一个授权子项的父菜单。
    """
    return dbm.query(conn, """
        WITH granted_leaf AS (
            SELECT m.menu_id, m.parent_id
            FROM sys_role_menu rm
            JOIN sys_menu m ON m.menu_id = rm.menu_id
            WHERE rm.role_id = ?
        ),
        visible_id AS (
            SELECT menu_id FROM granted_leaf
            UNION
            SELECT parent_id FROM granted_leaf WHERE parent_id IS NOT NULL
        )
        SELECT m.menu_id, m.parent_id, m.title, m.path, m.icon, m.sort_order
        FROM sys_menu m
        JOIN visible_id v ON v.menu_id = m.menu_id
        ORDER BY m.sort_order, m.menu_id
    """, (role_id,))


def _user_payload(conn: sqlite3.Connection, user: dict) -> dict:
    role = dbm.query_one(conn, "SELECT role_id, name, data_scope_type FROM sys_role WHERE role_id=?",
                         (user["role_id"],))
    payload = {
        "username": user["username"],
        "name": user["name"],
        "role": user["role_id"],
        "roleName": role["name"] if role else user["role_id"],
        "menus": _menus_for_role(conn, user["role_id"]),
    }
    # 附加数据范围（college/major/class），供前端切换视角
    scopes = dbm.query(conn, "SELECT scope_id FROM sys_role_scope WHERE role_id=?", (user["role_id"],))
    scope_ids = [s["scope_id"] for s in scopes]
    if scope_ids:
        # 学院级：取第一个 scope_id 作为学院
        college = dbm.query_one(conn, "SELECT college_id, name FROM dim_college WHERE college_id=?",
                                (scope_ids[0],))
        if college:
            payload["scope"] = {"collegeId": college["college_id"], "collegeName": college["name"]}
        # 专业级：scope_id 是 major_id
        major = dbm.query_one(conn, "SELECT major_id, name FROM dim_major WHERE major_id=?",
                              (scope_ids[0],))
        if major:
            if "scope" in payload:
                payload["scope"]["majorId"] = major["major_id"]
            else:
                payload["scope"] = {"majorId": major["major_id"]}
        # 班级级：全量 class_ids（辅导员）
        if not college and not major and scope_ids:
            payload["scope"] = {"classIds": scope_ids}
    return payload


@router.post("/login")
def login(body: LoginIn, request: Request,
          conn: sqlite3.Connection = Depends(get_db_rw)):
    username = body.username.strip()
    client = client_key(request)
    if login_is_limited(conn, username, client):
        write_audit(conn, username or None, "auth.login", "user", username,
                    result="rate_limited", client=client)
        conn.commit()
        raise ApiError("登录尝试过于频繁，请15分钟后再试", code=429, status_code=429)
    user = dbm.query_one(
        conn, "SELECT username, name, role_id, status, password_hash "
        "FROM sys_user WHERE username=?", (username,))
    if not user or user["status"] != "active" or not verify_password(body.password, user["password_hash"]):
        record_login(conn, username, client, False)
        write_audit(conn, username or None, "auth.login", "user", username,
                    result="failed", client=client)
        conn.commit()
        raise ApiError("用户名或密码错误", code=401, status_code=401)
    record_login(conn, username, client, True)
    write_audit(conn, username, "auth.login", "user", username,
                result="success", client=client, detail={"roleId": user["role_id"]})
    token = create_token(user["username"], user["role_id"])
    return ok({"token": token, "user": _user_payload(conn, user)})


@router.get("/me")
def me(user: dict = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)):
    return ok(_user_payload(conn, user))


@router.post("/logout")
def logout(request: Request, authorization: str = Header(default=""),
           user: dict = Depends(get_current_user),
           conn: sqlite3.Connection = Depends(get_db_rw)):
    token = authorization.split(" ", 1)[1].strip() if authorization.lower().startswith("bearer ") else ""
    payload = decode_token(token) or {}
    if payload.get("jti") and payload.get("exp"):
        from ..security_governance import ensure_security_tables, now_iso
        ensure_security_tables(conn)
        dbm.execute(conn, """INSERT OR REPLACE INTO sys_revoked_token(jti,expires_at,revoked_at)
            VALUES (?,?,?)""", (payload["jti"], int(payload["exp"]), now_iso()))
    write_audit(conn, user["username"], "auth.logout", "user", user["username"],
                client=client_key(request))
    return ok(msg="已登出")

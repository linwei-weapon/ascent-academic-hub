"""后台管理：账号 / 角色 / 菜单 / 角色-菜单（菜单级权限）CRUD。
读走只读连接(get_db)，写走可写连接(get_db_rw)+管理员守卫(require_admin)。
"""
import json
import sqlite3
import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import db as dbm
from ..deps import get_db, get_db_rw, require_admin, student_data_scope
from ..envelope import ok, ApiError
from ..permission_context import build_permission_context, v2_student_scope
from ..security import hash_password
from ..security_governance import ensure_security_tables, write_audit

router = APIRouter(prefix="/api/admin/rbac", tags=["rbac"])

VALID_STATUS = {"active", "disabled"}
VALID_SCOPE_TYPES = {"all", "college", "major", "class", "teacher", "staff_relation"}


def _permission_tables_ready(conn: sqlite3.Connection) -> bool:
    return bool(dbm.query_one(
        conn,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sys_user_role'",
    ))


def _require_permission_tables(conn: sqlite3.Connection) -> None:
    if not _permission_tables_ready(conn):
        raise ApiError(
            "统一权限表尚未初始化，请先执行权限迁移",
            code=503,
            status_code=503,
        )


def _ensure_default_identity(conn: sqlite3.Connection, username: str,
                             role_id: str, source: str = "rbac") -> str:
    identity_id = f"UR:{username}:{role_id}"
    if not _permission_tables_ready(conn):
        return identity_id
    dbm.execute(conn, "UPDATE sys_user_role SET is_default=0 WHERE username=?",
                (username,))
    dbm.execute(conn, """
        INSERT INTO sys_user_role(
          user_role_id,username,role_id,is_default,status,source
        ) VALUES(?,?,?,1,'active',?)
        ON CONFLICT(user_role_id) DO UPDATE SET
          role_id=excluded.role_id,is_default=1,status='active',source=excluded.source
    """, (identity_id, username, role_id, source))
    return identity_id


def _validate_password(password: str, username: str = "") -> str:
    if len(password) < 12 or len(password) > 128:
        raise ApiError("密码长度必须为12~128位", code=400, status_code=400)
    checks = [re.search(r"[a-z]", password), re.search(r"[A-Z]", password),
              re.search(r"\d", password), re.search(r"[^A-Za-z0-9]", password)]
    if not all(checks):
        raise ApiError("密码必须同时包含大小写字母、数字和特殊字符", code=400, status_code=400)
    if username and username.lower() in password.lower():
        raise ApiError("密码不能包含用户名", code=400, status_code=400)
    return password


def _validate_status(status: str) -> str:
    if status not in VALID_STATUS:
        raise ApiError("账号状态必须为 active 或 disabled", code=400, status_code=400)
    return status


# ============================ 账号 ============================
class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    name: str = Field(default="", max_length=80)
    role_id: str = Field(min_length=1, max_length=80)
    status: str = "active"
    password: str = Field(min_length=12, max_length=128)


class UserUpdateIn(BaseModel):
    name: str | None = None
    role_id: str | None = None
    status: str | None = None


class ResetPwdIn(BaseModel):
    password: str = Field(min_length=12, max_length=128)


@router.get("/users")
def list_users(_: dict = Depends(require_admin),
               conn: sqlite3.Connection = Depends(get_db)):
    rows = dbm.query(conn, """
        SELECT u.user_id, u.username, u.name, u.role_id, u.status,
               r.name AS role_name
        FROM sys_user u LEFT JOIN sys_role r ON u.role_id = r.role_id
        ORDER BY u.user_id""")
    return ok(rows)


@router.post("/users")
def create_user(body: UserIn, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if dbm.query_one(conn, "SELECT 1 FROM sys_user WHERE username=?", (body.username,)):
        raise ApiError("用户名已存在")
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (body.role_id,)):
        raise ApiError("角色不存在")
    pwd = _validate_password(body.password, body.username)
    _validate_status(body.status)
    cur = dbm.execute(conn, """
        INSERT INTO sys_user (username, password_hash, name, role_id, status)
        VALUES (?,?,?,?,?)""",
        (body.username, hash_password(pwd), body.name, body.role_id, body.status))
    identity_id = _ensure_default_identity(
        conn, body.username, body.role_id, "rbac_create",
    )
    write_audit(conn, admin["username"], "rbac.user.create", "user",
                str(cur.lastrowid), detail={"username": body.username,
                                            "roleId": body.role_id,
                                            "identityId": identity_id})
    return ok({"user_id": cur.lastrowid}, msg="账号已创建")


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    user = dbm.query_one(conn, "SELECT user_id,username,role_id,status FROM sys_user WHERE user_id=?", (user_id,))
    if not user:
        raise ApiError("账号不存在", status_code=404)
    fields, params = [], []
    if body.name is not None:
        fields.append("name=?"); params.append(body.name)
    if body.role_id is not None:
        if user["username"] == admin["username"] and body.role_id != user["role_id"]:
            raise ApiError("不能修改当前登录账号的角色", code=400, status_code=400)
        if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (body.role_id,)):
            raise ApiError("角色不存在")
        fields.append("role_id=?"); params.append(body.role_id)
    if body.status is not None:
        _validate_status(body.status)
        if user["username"] == admin["username"] and body.status != "active":
            raise ApiError("不能停用当前登录账号", code=400, status_code=400)
        fields.append("status=?"); params.append(body.status)
    if fields:
        params.append(user_id)
        dbm.execute(conn, f"UPDATE sys_user SET {','.join(fields)} WHERE user_id=?", params)
        if body.role_id is not None:
            _ensure_default_identity(
                conn, user["username"], body.role_id, "rbac_update",
            )
        write_audit(conn, admin["username"], "rbac.user.update", "user", str(user_id),
                    detail={"fields": [f.split("=")[0] for f in fields]})
    return ok(msg="账号已更新")


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    user = dbm.query_one(conn, "SELECT username FROM sys_user WHERE user_id=?", (user_id,))
    if not user:
        raise ApiError("账号不存在", status_code=404)
    if user["username"] == admin["username"]:
        raise ApiError("不能删除当前登录账号")
    if _permission_tables_ready(conn):
        identity_ids = [
            row["user_role_id"] for row in dbm.query(
                conn, "SELECT user_role_id FROM sys_user_role WHERE username=?",
                (user["username"],),
            )
        ]
        if identity_ids:
            placeholders = ",".join("?" * len(identity_ids))
            dbm.execute(
                conn,
                f"DELETE FROM sys_user_scope WHERE user_role_id IN ({placeholders})",
                tuple(identity_ids),
            )
        dbm.execute(conn, "DELETE FROM sys_user_role WHERE username=?",
                    (user["username"],))
        dbm.execute(conn, "DELETE FROM sys_user_staff WHERE username=?",
                    (user["username"],))
    dbm.execute(conn, "DELETE FROM sys_user WHERE user_id=?", (user_id,))
    write_audit(conn, admin["username"], "rbac.user.delete", "user", str(user_id),
                detail={"username": user["username"]})
    return ok(msg="账号已删除")


@router.post("/users/{user_id}/reset-pwd")
def reset_pwd(user_id: int, body: ResetPwdIn, admin: dict = Depends(require_admin),
              conn: sqlite3.Connection = Depends(get_db_rw)):
    user = dbm.query_one(conn, "SELECT username FROM sys_user WHERE user_id=?", (user_id,))
    if not user:
        raise ApiError("账号不存在", status_code=404)
    pwd = _validate_password(body.password, user["username"])
    dbm.execute(conn, "UPDATE sys_user SET password_hash=? WHERE user_id=?",
                (hash_password(pwd), user_id))
    write_audit(conn, admin["username"], "rbac.user.password_reset", "user", str(user_id))
    return ok(msg="密码已重置")


# ============================ 角色 ============================
class RoleIn(BaseModel):
    role_id: str
    name: str
    data_scope_type: str = "all"


class RoleUpdateIn(BaseModel):
    name: str | None = None
    data_scope_type: str | None = None


@router.get("/roles")
def list_roles(_: dict = Depends(require_admin),
               conn: sqlite3.Connection = Depends(get_db)):
    cnt = {r["role_id"]: r["n"] for r in dbm.query(
        conn, "SELECT role_id, COUNT(*) n FROM sys_user GROUP BY role_id")}
    mcnt = {r["role_id"]: r["n"] for r in dbm.query(
        conn, "SELECT role_id, COUNT(*) n FROM sys_role_menu GROUP BY role_id")}
    rows = []
    for r in dbm.query(conn,
            "SELECT role_id, name, data_scope_type FROM sys_role ORDER BY role_id"):
        rows.append({**r,
                     "user_count": cnt.get(r["role_id"], 0),
                     "menu_count": mcnt.get(r["role_id"], 0)})
    return ok(rows)


@router.post("/roles")
def create_role(body: RoleIn, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (body.role_id,)):
        raise ApiError("角色 ID 已存在")
    if body.data_scope_type not in VALID_SCOPE_TYPES:
        raise ApiError("无效的数据范围类型", code=400, status_code=400)
    dbm.execute(conn, "INSERT INTO sys_role (role_id, name, data_scope_type) VALUES (?,?,?)",
                (body.role_id, body.name, body.data_scope_type))
    write_audit(conn, admin["username"], "rbac.role.create", "role", body.role_id,
                detail={"scopeType": body.data_scope_type})
    return ok(msg="角色已创建")


@router.put("/roles/{role_id}")
def update_role(role_id: str, body: RoleUpdateIn, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (role_id,)):
        raise ApiError("角色不存在", status_code=404)
    fields, params = [], []
    if body.name is not None:
        fields.append("name=?"); params.append(body.name)
    if body.data_scope_type is not None:
        if body.data_scope_type not in VALID_SCOPE_TYPES:
            raise ApiError("无效的数据范围类型", code=400, status_code=400)
        fields.append("data_scope_type=?"); params.append(body.data_scope_type)
    if fields:
        params.append(role_id)
        dbm.execute(conn, f"UPDATE sys_role SET {','.join(fields)} WHERE role_id=?", params)
        write_audit(conn, admin["username"], "rbac.role.update", "role", role_id,
                    detail={"fields": [f.split("=")[0] for f in fields]})
    return ok(msg="角色已更新")


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (role_id,)):
        raise ApiError("角色不存在", status_code=404)
    if dbm.scalar(conn, "SELECT COUNT(*) FROM sys_user WHERE role_id=?", (role_id,)):
        raise ApiError("该角色下仍有账号，无法删除")
    if _permission_tables_ready(conn) and dbm.scalar(
            conn, "SELECT COUNT(*) FROM sys_user_role WHERE role_id=?", (role_id,)):
        raise ApiError("该角色仍绑定工作身份，无法删除")
    dbm.execute(conn, "DELETE FROM sys_role_menu WHERE role_id=?", (role_id,))
    dbm.execute(conn, "DELETE FROM sys_role_scope WHERE role_id=?", (role_id,))
    dbm.execute(conn, "DELETE FROM sys_role WHERE role_id=?", (role_id,))
    write_audit(conn, admin["username"], "rbac.role.delete", "role", role_id)
    return ok(msg="角色已删除")


# ============================ 菜单 ============================
class MenuIn(BaseModel):
    menu_id: str
    parent_id: str | None = None
    title: str
    path: str | None = None
    icon: str | None = None
    sort_order: int = 0


class MenuUpdateIn(BaseModel):
    parent_id: str | None = None
    title: str | None = None
    path: str | None = None
    icon: str | None = None
    sort_order: int | None = None


def _menu_update_fields(body: MenuUpdateIn) -> set[str]:
    """兼容 Pydantic v1/v2，区分“未传字段”和“明确传 null”."""
    return set(getattr(body, "model_fields_set",
                       getattr(body, "__fields_set__", set())))


def _assert_valid_parent(conn: sqlite3.Connection, menu_id: str,
                         parent_id: str | None) -> None:
    """只允许两级菜单，并阻止自身/后代成为父菜单。"""
    if not parent_id:
        return
    if parent_id == menu_id:
        raise ApiError("菜单不能以自身作为父菜单", code=400, status_code=400)
    parent = dbm.query_one(
        conn, "SELECT menu_id,parent_id FROM sys_menu WHERE menu_id=?",
        (parent_id,))
    if not parent:
        raise ApiError("父菜单不存在", code=400, status_code=400)
    if parent["parent_id"]:
        raise ApiError("系统仅支持两级菜单，不能挂到二级菜单下",
                       code=400, status_code=400)
    if dbm.scalar(conn, "SELECT COUNT(*) FROM sys_menu WHERE parent_id=?",
                  (menu_id,)):
        raise ApiError("含有子菜单的一级菜单不能再挂到其他菜单下",
                       code=400, status_code=400)


def _leaf_menu_ids(conn: sqlite3.Connection,
                   menu_ids: list[str]) -> list[str]:
    """校验菜单ID并仅保留叶子节点；父菜单本身不授予业务权限。"""
    requested = list(dict.fromkeys(menu_ids))
    unknown = [mid for mid in requested
               if not dbm.query_one(
                   conn, "SELECT 1 FROM sys_menu WHERE menu_id=?", (mid,))]
    if unknown:
        raise ApiError(f"菜单不存在: {', '.join(unknown)}",
                       code=400, status_code=400)
    return [
        mid for mid in requested
        if not dbm.scalar(
            conn, "SELECT COUNT(*) FROM sys_menu WHERE parent_id=?", (mid,))
    ]


@router.get("/menus")
def list_menus(_: dict = Depends(require_admin),
               conn: sqlite3.Connection = Depends(get_db)):
    rows = dbm.query(conn, """
        SELECT menu_id, parent_id, title, path, icon, sort_order
        FROM sys_menu ORDER BY sort_order, menu_id""")
    return ok(rows)


@router.post("/menus")
def create_menu(body: MenuIn, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if dbm.query_one(conn, "SELECT 1 FROM sys_menu WHERE menu_id=?", (body.menu_id,)):
        raise ApiError("菜单 ID 已存在")
    _assert_valid_parent(conn, body.menu_id, body.parent_id)
    if body.path and not body.path.startswith("/admin/"):
        raise ApiError("菜单路径必须位于 /admin/ 下", code=400, status_code=400)
    dbm.execute(conn, """
        INSERT INTO sys_menu (menu_id, parent_id, title, path, icon, sort_order)
        VALUES (?,?,?,?,?,?)""",
        (body.menu_id, body.parent_id, body.title, body.path, body.icon, body.sort_order))
    write_audit(conn, admin["username"], "rbac.menu.create", "menu", body.menu_id,
                detail={"path": body.path})
    return ok(msg="菜单已创建")


@router.put("/menus/{menu_id}")
def update_menu(menu_id: str, body: MenuUpdateIn, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_menu WHERE menu_id=?", (menu_id,)):
        raise ApiError("菜单不存在", status_code=404)
    fields, params = [], []
    provided = _menu_update_fields(body)
    if "parent_id" in provided:
        _assert_valid_parent(conn, menu_id, body.parent_id)
    if "path" in provided and body.path and not body.path.startswith("/admin/"):
        raise ApiError("菜单路径必须位于 /admin/ 下", code=400, status_code=400)
    for col in ("parent_id", "title", "path", "icon", "sort_order"):
        if col in provided:
            fields.append(f"{col}=?"); params.append(getattr(body, col))
    if fields:
        params.append(menu_id)
        dbm.execute(conn, f"UPDATE sys_menu SET {','.join(fields)} WHERE menu_id=?", params)
        write_audit(conn, admin["username"], "rbac.menu.update", "menu", menu_id,
                    detail={"fields": [f.split("=")[0] for f in fields]})
    return ok(msg="菜单已更新")


@router.delete("/menus/{menu_id}")
def delete_menu(menu_id: str, admin: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_menu WHERE menu_id=?", (menu_id,)):
        raise ApiError("菜单不存在", status_code=404)
    if dbm.scalar(conn, "SELECT COUNT(*) FROM sys_menu WHERE parent_id=?", (menu_id,)):
        raise ApiError("该菜单仍有子菜单，无法删除", code=409, status_code=409)
    dbm.execute(conn, "DELETE FROM sys_role_menu WHERE menu_id=?", (menu_id,))
    dbm.execute(conn, "DELETE FROM sys_menu WHERE menu_id=?", (menu_id,))
    write_audit(conn, admin["username"], "rbac.menu.delete", "menu", menu_id)
    return ok(msg="菜单已删除")


# ======================= 角色-菜单绑定 =======================
class RoleMenusIn(BaseModel):
    menu_ids: list[str]


@router.get("/roles/{role_id}/menus")
def get_role_menus(role_id: str, _: dict = Depends(require_admin),
                   conn: sqlite3.Connection = Depends(get_db)):
    rows = dbm.query(conn, """
        SELECT rm.menu_id
        FROM sys_role_menu rm
        WHERE rm.role_id=?
          AND NOT EXISTS (
              SELECT 1 FROM sys_menu child WHERE child.parent_id=rm.menu_id
          )
        ORDER BY rm.menu_id
    """, (role_id,))
    return ok([r["menu_id"] for r in rows])


@router.put("/roles/{role_id}/menus")
def set_role_menus(role_id: str, body: RoleMenusIn, admin: dict = Depends(require_admin),
                   conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (role_id,)):
        raise ApiError("角色不存在", status_code=404)
    leaf_ids = _leaf_menu_ids(conn, body.menu_ids)
    dbm.execute(conn, "DELETE FROM sys_role_menu WHERE role_id=?", (role_id,))
    for mid in leaf_ids:
        dbm.execute(conn, "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (?,?)",
                    (role_id, mid))
    write_audit(conn, admin["username"], "rbac.role.menus_update", "role", role_id,
                detail={"requestedMenuIds": list(dict.fromkeys(body.menu_ids)),
                        "leafMenuIds": leaf_ids})
    return ok(msg="菜单权限已保存")


# ======================= 统一数据权限 =======================
class StaffBindingIn(BaseModel):
    staff_id: str = Field(min_length=1, max_length=80)
    valid_from: str = "1970-01-01"
    valid_to: str | None = None
    source: str = "manual"


class IdentityIn(BaseModel):
    role_id: str = Field(min_length=1, max_length=80)
    is_default: bool = False
    valid_from: str | None = None
    valid_to: str | None = None


class IdentityUpdateIn(BaseModel):
    is_default: bool | None = None
    status: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


class ScopeItemIn(BaseModel):
    scope_type: str
    scope_id: str
    valid_from: str = "1970-01-01"
    valid_to: str | None = None


class IdentityScopesIn(BaseModel):
    scopes: list[ScopeItemIn] = []


def _identity_detail(conn: sqlite3.Connection, username: str) -> dict:
    user = dbm.query_one(conn, """
        SELECT user_id,username,name,role_id,status
        FROM sys_user WHERE username=?
    """, (username,))
    if not user:
        raise ApiError("账号不存在", code=404, status_code=404)
    staff = dbm.query(conn, """
        SELECT staff_id,valid_from,valid_to,status,source,source_updated_at
        FROM sys_user_staff WHERE username=?
        ORDER BY status='active' DESC,valid_from DESC,staff_id
    """, (username,))
    identities = dbm.query(conn, """
        SELECT ur.user_role_id identity_id,ur.role_id,r.name role_name,
               r.data_scope_type,ur.is_default,ur.valid_from,ur.valid_to,
               ur.status,ur.source
        FROM sys_user_role ur
        LEFT JOIN sys_role r ON r.role_id=ur.role_id
        WHERE ur.username=?
        ORDER BY ur.status='active' DESC,ur.is_default DESC,ur.user_role_id
    """, (username,))
    for identity in identities:
        identity["is_default"] = bool(identity["is_default"])
        identity["scopes"] = dbm.query(conn, """
            SELECT user_scope_id,scope_type,scope_id,valid_from,valid_to,status,source
            FROM sys_user_scope WHERE user_role_id=?
            ORDER BY status='active' DESC,scope_type,scope_id
        """, (identity["identity_id"],))
    return {**user, "staffBindings": staff, "identities": identities}


@router.get("/data-permissions")
def list_data_permissions(keyword: str | None = None,
                          _: dict = Depends(require_admin),
                          conn: sqlite3.Connection = Depends(get_db)):
    _require_permission_tables(conn)
    params: list = []
    where = ""
    if keyword:
        where = "WHERE u.username LIKE ? OR u.name LIKE ?"
        token = f"%{keyword.strip()}%"
        params.extend([token, token])
    users = dbm.query(conn, f"""
        SELECT u.user_id,u.username,u.name,u.status,u.role_id,
               COUNT(DISTINCT ur.user_role_id) identity_count,
               COUNT(DISTINCT CASE WHEN us.status='active' THEN us.user_scope_id END) scope_count,
               COUNT(DISTINCT CASE WHEN ss.status='active' THEN ss.staff_id END) staff_count
        FROM sys_user u
        LEFT JOIN sys_user_role ur ON ur.username=u.username
        LEFT JOIN sys_user_scope us ON us.user_role_id=ur.user_role_id
        LEFT JOIN sys_user_staff ss ON ss.username=u.username
        {where}
        GROUP BY u.user_id,u.username,u.name,u.status,u.role_id
        ORDER BY u.user_id
    """, tuple(params))
    today = date.today().isoformat()
    for user in users:
        identities = dbm.query(conn, """
            SELECT ur.user_role_id,ur.role_id,r.name role_name,r.data_scope_type
            FROM sys_user_role ur
            LEFT JOIN sys_role r ON r.role_id=ur.role_id
            WHERE ur.username=? AND ur.status='active'
              AND (ur.valid_from IS NULL OR ur.valid_from<=?)
              AND (ur.valid_to IS NULL OR ur.valid_to>=?)
            ORDER BY ur.is_default DESC,ur.user_role_id
        """, (user["username"], today, today))
        identity = identities[0] if identities else None
        user["defaultIdentity"] = identity
        active_staff = dbm.query(conn, """
            SELECT staff_id FROM sys_user_staff
            WHERE username=? AND status='active'
              AND valid_from<=? AND (valid_to IS NULL OR valid_to>=?)
        """, (user["username"], today, today))
        issues = []
        if not identities:
            issues.append("没有有效工作身份")
        if len(active_staff) > 1:
            issues.append("存在多个同时生效的人员关联")
        for item in identities:
            if item["data_scope_type"] == "all":
                continue
            if item["data_scope_type"] == "staff_relation":
                if not active_staff:
                    issues.append(f"{item['role_name']}未关联教职工号")
                continue
            scope_count = dbm.scalar(conn, """
                SELECT COUNT(*) FROM sys_user_scope
                WHERE user_role_id=? AND status='active'
                  AND valid_from<=? AND (valid_to IS NULL OR valid_to>=?)
            """, (item["user_role_id"], today, today)) or 0
            if not scope_count:
                issues.append(f"{item['role_name']}未配置{item['data_scope_type']}范围")
        user["issues"] = issues
        user["permissionStatus"] = "ready" if not issues else "needs_mapping"
    return ok(users)


@router.get("/data-permissions/options")
def data_permission_options(_: dict = Depends(require_admin),
                            conn: sqlite3.Connection = Depends(get_db)):
    _require_permission_tables(conn)
    return ok({
        "roles": dbm.query(conn, """
            SELECT role_id,name,data_scope_type FROM sys_role ORDER BY name,role_id
        """),
        "colleges": dbm.query(conn, """
            SELECT college_id value,name label FROM dim_college ORDER BY name
        """),
        "majors": dbm.query(conn, """
            SELECT major_id value,name label,college_id FROM dim_major ORDER BY name
        """),
        "classes": dbm.query(conn, """
            SELECT class_id value,class_id label,
                   MAX(college_id) college_id,MAX(major_id) major_id
            FROM dim_student WHERE class_id IS NOT NULL AND class_id<>''
            GROUP BY class_id ORDER BY label
        """),
        "teachers": dbm.query(conn, """
            SELECT teacher_id value,name label,dept organization_name
            FROM dim_teacher ORDER BY name,teacher_id
        """),
    })


@router.get("/data-permissions/{username}")
def get_data_permission(username: str, _: dict = Depends(require_admin),
                        conn: sqlite3.Connection = Depends(get_db)):
    _require_permission_tables(conn)
    return ok(_identity_detail(conn, username))


@router.put("/data-permissions/{username}/staff")
def set_staff_binding(username: str, body: StaffBindingIn,
                      admin: dict = Depends(require_admin),
                      conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_permission_tables(conn)
    if not dbm.query_one(conn, "SELECT 1 FROM sys_user WHERE username=?", (username,)):
        raise ApiError("账号不存在", code=404, status_code=404)
    dbm.execute(conn, "UPDATE sys_user_staff SET status='inactive' WHERE username=?",
                (username,))
    dbm.execute(conn, """
        INSERT INTO sys_user_staff(
          username,staff_id,valid_from,valid_to,status,source,source_updated_at
        ) VALUES(?,?,?,?, 'active',?,datetime('now'))
        ON CONFLICT(username,staff_id,valid_from) DO UPDATE SET
          valid_to=excluded.valid_to,status='active',source=excluded.source,
          source_updated_at=datetime('now')
    """, (username, body.staff_id.strip(), body.valid_from,
          body.valid_to, body.source))
    write_audit(conn, admin["username"], "rbac.permission.staff_update",
                "user", username, detail=body.model_dump())
    return ok(_identity_detail(conn, username), msg="人员绑定已保存")


@router.post("/data-permissions/{username}/identities")
def create_identity(username: str, body: IdentityIn,
                    admin: dict = Depends(require_admin),
                    conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_permission_tables(conn)
    if not dbm.query_one(conn, "SELECT 1 FROM sys_user WHERE username=?", (username,)):
        raise ApiError("账号不存在", code=404, status_code=404)
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (body.role_id,)):
        raise ApiError("角色不存在", code=404, status_code=404)
    identity_id = f"UR:{username}:{body.role_id}"
    if dbm.query_one(conn, "SELECT 1 FROM sys_user_role WHERE user_role_id=?",
                     (identity_id,)):
        raise ApiError("该账号已存在相同工作身份", code=409, status_code=409)
    has_identity = bool(dbm.query_one(
        conn, "SELECT 1 FROM sys_user_role WHERE username=? AND status='active'",
        (username,),
    ))
    is_default = body.is_default or not has_identity
    if is_default:
        dbm.execute(conn, "UPDATE sys_user_role SET is_default=0 WHERE username=?",
                    (username,))
    dbm.execute(conn, """
        INSERT INTO sys_user_role(
          user_role_id,username,role_id,is_default,valid_from,valid_to,status,source
        ) VALUES(?,?,?,?,?,?,'active','manual')
    """, (identity_id, username, body.role_id, int(is_default),
          body.valid_from, body.valid_to))
    write_audit(conn, admin["username"], "rbac.permission.identity_create",
                "identity", identity_id, detail=body.model_dump())
    return ok(_identity_detail(conn, username), msg="工作身份已添加")


@router.put("/data-permissions/{username}/identities/{identity_id}")
def update_identity(username: str, identity_id: str, body: IdentityUpdateIn,
                    admin: dict = Depends(require_admin),
                    conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_permission_tables(conn)
    identity = dbm.query_one(conn, """
        SELECT user_role_id,is_default FROM sys_user_role
        WHERE username=? AND user_role_id=?
    """, (username, identity_id))
    if not identity:
        raise ApiError("工作身份不存在", code=404, status_code=404)
    fields, params = [], []
    provided = set(getattr(body, "model_fields_set",
                           getattr(body, "__fields_set__", set())))
    if body.status is not None and body.status not in {"active", "inactive"}:
        raise ApiError("身份状态必须为 active 或 inactive", code=400, status_code=400)
    if body.is_default:
        dbm.execute(conn, "UPDATE sys_user_role SET is_default=0 WHERE username=?",
                    (username,))
    for field in ("is_default", "status", "valid_from", "valid_to"):
        if field in provided:
            fields.append(f"{field}=?")
            value = getattr(body, field)
            params.append(int(value) if field == "is_default" else value)
    if fields:
        params.extend([username, identity_id])
        dbm.execute(conn, f"""
            UPDATE sys_user_role SET {','.join(fields)}
            WHERE username=? AND user_role_id=?
        """, tuple(params))
    write_audit(conn, admin["username"], "rbac.permission.identity_update",
                "identity", identity_id, detail=body.model_dump(exclude_unset=True))
    return ok(_identity_detail(conn, username), msg="工作身份已更新")


@router.delete("/data-permissions/{username}/identities/{identity_id}")
def delete_identity(username: str, identity_id: str,
                    admin: dict = Depends(require_admin),
                    conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_permission_tables(conn)
    identity = dbm.query_one(conn, """
        SELECT is_default FROM sys_user_role WHERE username=? AND user_role_id=?
    """, (username, identity_id))
    if not identity:
        raise ApiError("工作身份不存在", code=404, status_code=404)
    if identity["is_default"]:
        raise ApiError("默认工作身份不能直接删除，请先设置其他默认身份",
                       code=409, status_code=409)
    dbm.execute(conn, "DELETE FROM sys_user_scope WHERE user_role_id=?", (identity_id,))
    dbm.execute(conn, "DELETE FROM sys_user_role WHERE user_role_id=?", (identity_id,))
    write_audit(conn, admin["username"], "rbac.permission.identity_delete",
                "identity", identity_id)
    return ok(_identity_detail(conn, username), msg="工作身份已删除")


@router.put("/data-permissions/{username}/identities/{identity_id}/scopes")
def set_identity_scopes(username: str, identity_id: str, body: IdentityScopesIn,
                        admin: dict = Depends(require_admin),
                        conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_permission_tables(conn)
    identity = dbm.query_one(conn, """
        SELECT ur.role_id,r.data_scope_type
        FROM sys_user_role ur JOIN sys_role r ON r.role_id=ur.role_id
        WHERE ur.username=? AND ur.user_role_id=?
    """, (username, identity_id))
    if not identity:
        raise ApiError("工作身份不存在", code=404, status_code=404)
    expected = identity["data_scope_type"]
    if expected == "all" and body.scopes:
        raise ApiError("全校范围身份不需要配置组织范围", code=400, status_code=400)
    for item in body.scopes:
        if item.scope_type not in VALID_SCOPE_TYPES - {"all", "staff_relation"}:
            raise ApiError("不支持的数据范围类型", code=400, status_code=400)
        if expected not in {"staff_relation", item.scope_type}:
            raise ApiError(
                f"角色要求配置 {expected} 范围，不能保存 {item.scope_type} 范围",
                code=400,
                status_code=400,
            )
    dbm.execute(conn, "DELETE FROM sys_user_scope WHERE user_role_id=?", (identity_id,))
    for item in body.scopes:
        scope_id = item.scope_id.strip()
        if not scope_id:
            continue
        user_scope_id = f"US:{identity_id}:{item.scope_type}:{scope_id}:{uuid.uuid4().hex[:8]}"
        dbm.execute(conn, """
            INSERT INTO sys_user_scope(
              user_scope_id,user_role_id,scope_type,scope_id,valid_from,
              valid_to,status,source
            ) VALUES(?,?,?,?,?,?,'active','manual')
        """, (user_scope_id, identity_id, item.scope_type, scope_id,
              item.valid_from, item.valid_to))
    write_audit(conn, admin["username"], "rbac.permission.scope_update",
                "identity", identity_id,
                detail={"scopes": [item.model_dump() for item in body.scopes]})
    return ok(_identity_detail(conn, username), msg="组织范围已保存")


@router.get("/data-permissions/{username}/preview/{identity_id}")
def preview_data_permission(username: str, identity_id: str,
                            _: dict = Depends(require_admin),
                            conn: sqlite3.Connection = Depends(get_db)):
    _require_permission_tables(conn)
    user = dbm.query_one(conn, """
        SELECT user_id,username,name,role_id,status FROM sys_user WHERE username=?
    """, (username,))
    if not user:
        raise ApiError("账号不存在", code=404, status_code=404)
    context = build_permission_context(conn, user, identity_id)
    scoped_user = {
        **user,
        "role_id": context["activeRole"],
        "staff_id": context.get("staffId"),
        "permission_context": context,
    }
    legacy_count = 0
    if context["authorized"]:
        fragment, params = student_data_scope(scoped_user, conn, "s")
        where = f"WHERE {fragment}" if fragment else ""
        legacy_count = dbm.scalar(
            conn, f"SELECT COUNT(*) FROM dim_student s {where}", tuple(params),
        ) or 0
    v2_count = None
    v2_issue = None
    try:
        v2_conn = dbm.get_v2_conn()
        try:
            fragment, params = v2_student_scope(context, v2_conn, "s")
            where = f"WHERE {fragment}" if fragment else ""
            v2_count = dbm.scalar(
                v2_conn, f"SELECT COUNT(*) FROM dim_student s {where}",
                tuple(params),
            ) or 0
        finally:
            v2_conn.close()
    except Exception as exc:
        v2_issue = str(getattr(exc, "message", None) or exc)
    return ok({
        "username": username,
        "identityId": identity_id,
        "permissionContext": context,
        "visibleStudents": {
            "currentPrototype": legacy_count,
            "realDataV2": v2_count,
            "v2Issue": v2_issue,
        },
    })


@router.get("/data-permissions/relationships/list")
def list_staff_relationships(relation_type: str | None = None,
                             keyword: str | None = None,
                             page: int = 1, page_size: int = 50,
                             _: dict = Depends(require_admin)):
    page, page_size = max(1, page), max(1, min(100, page_size))
    v2_conn = dbm.get_v2_conn()
    try:
        conditions, params = ["1=1"], []
        if relation_type:
            conditions.append("ss.relation_type=?")
            params.append(relation_type)
        if keyword:
            conditions.append(
                "(ss.staff_id LIKE ? OR ss.student_id LIKE ? OR ss.scope_ref LIKE ?)"
            )
            token = f"%{keyword.strip()}%"
            params.extend([token, token, token])
        where = " AND ".join(conditions)
        total = dbm.scalar(v2_conn, f"""
            SELECT COUNT(*) FROM staff_student_scope ss WHERE {where}
        """, tuple(params)) or 0
        rows = dbm.query(v2_conn, f"""
            SELECT ss.staff_id,ss.student_id,ss.relation_type,ss.scope_ref,
                   ss.valid_from,ss.valid_to,ss.status,ss.source_system,
                   ss.source_updated_at,
                   COALESCE(se.display_name,ss.student_id) student_name
            FROM staff_student_scope ss
            LEFT JOIN dim_student se ON se.student_id=ss.student_id
            WHERE {where}
            ORDER BY ss.status='active' DESC,ss.relation_type,ss.staff_id,ss.student_id
            LIMIT ? OFFSET ?
        """, tuple(params + [page_size, (page - 1) * page_size]))
        stats = dbm.query(v2_conn, """
            SELECT relation_type,COUNT(DISTINCT staff_id) staff_count,
                   COUNT(DISTINCT student_id) student_count,COUNT(*) relation_count
            FROM staff_student_scope
            WHERE COALESCE(status,'active')='active'
              AND date(valid_from)<=date('now')
              AND (valid_to IS NULL OR date(valid_to)>=date('now'))
            GROUP BY relation_type ORDER BY relation_type
        """)
        quality = {
            "temporaryStaff": dbm.scalar(v2_conn, """
                SELECT COUNT(DISTINCT staff_id) FROM staff_student_scope
                WHERE staff_id LIKE 'ADVISER-%'
            """) or 0,
            "expired": dbm.scalar(v2_conn, """
                SELECT COUNT(*) FROM staff_student_scope
                WHERE COALESCE(status,'active')<>'active'
                   OR (valid_to IS NOT NULL AND date(valid_to)<date('now'))
            """) or 0,
            "duplicateGroups": dbm.scalar(v2_conn, """
                SELECT COUNT(*) FROM (
                  SELECT staff_id,student_id,relation_type,valid_from
                  FROM staff_student_scope
                  GROUP BY staff_id,student_id,relation_type,valid_from
                  HAVING COUNT(*)>1
                )
            """) or 0,
            "missingSource": dbm.scalar(v2_conn, """
                SELECT COUNT(*) FROM staff_student_scope
                WHERE source_system IS NULL OR TRIM(source_system)=''
            """) or 0,
        }
    finally:
        v2_conn.close()
    return ok({
        "total": total, "page": page, "pageSize": page_size,
        "list": rows, "stats": stats, "quality": quality,
    })


@router.get("/security-audit")
def list_security_audit(action: str | None = None, page: int = 1, page_size: int = 50,
                        _: dict = Depends(require_admin),
                        conn: sqlite3.Connection = Depends(get_db_rw)):
    ensure_security_tables(conn)
    page, page_size = max(1, page), max(1, min(100, page_size))
    where, params = ("WHERE action=?", [action]) if action else ("", [])
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM sys_security_audit {where}", tuple(params)) or 0
    rows = dbm.query(conn, f"""SELECT audit_id,actor,action,target_type,target_id,
        result,client_key,detail_json,created_at FROM sys_security_audit {where}
        ORDER BY audit_id DESC LIMIT ? OFFSET ?""",
        tuple(params + [page_size, (page - 1) * page_size]))
    for row in rows:
        try:
            row["detail"] = json.loads(row.pop("detail_json") or "{}")
        except Exception:
            row["detail"] = {}
    return ok({"total": total, "page": page, "pageSize": page_size, "list": rows})

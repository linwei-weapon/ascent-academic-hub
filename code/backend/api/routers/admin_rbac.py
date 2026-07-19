"""后台管理：账号 / 角色 / 菜单 / 角色-菜单（菜单级权限）CRUD。
读走只读连接(get_db)，写走可写连接(get_db_rw)+管理员守卫(require_admin)。
"""
import json
import sqlite3
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import db as dbm
from ..deps import get_db, get_db_rw, require_admin
from ..envelope import ok, ApiError
from ..security import hash_password
from ..security_governance import ensure_security_tables, write_audit

router = APIRouter(prefix="/api/admin/rbac", tags=["rbac"])

VALID_STATUS = {"active", "disabled"}
VALID_SCOPE_TYPES = {"all", "college", "major", "class", "teacher"}


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
    write_audit(conn, admin["username"], "rbac.user.create", "user",
                str(cur.lastrowid), detail={"username": body.username, "roleId": body.role_id})
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

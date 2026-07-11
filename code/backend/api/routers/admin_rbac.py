"""后台管理：账号 / 角色 / 菜单 / 角色-菜单（菜单级权限）CRUD。
读走只读连接(get_db)，写走可写连接(get_db_rw)+管理员守卫(require_admin)。
"""
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db as dbm
from ..deps import get_db, get_db_rw, get_current_user, require_admin
from ..envelope import ok, ApiError
from ..security import hash_password

router = APIRouter(prefix="/api/admin/rbac", tags=["rbac"])

DEFAULT_PASSWORD = "Demo@2026"


# ============================ 账号 ============================
class UserIn(BaseModel):
    username: str
    name: str = ""
    role_id: str
    status: str = "active"
    password: str | None = None  # 仅新建时可选；空则用默认密码


class UserUpdateIn(BaseModel):
    name: str | None = None
    role_id: str | None = None
    status: str | None = None


class ResetPwdIn(BaseModel):
    password: str | None = None  # 空则重置为默认密码


@router.get("/users")
def list_users(_: dict = Depends(get_current_user),
               conn: sqlite3.Connection = Depends(get_db)):
    rows = dbm.query(conn, """
        SELECT u.user_id, u.username, u.name, u.role_id, u.status,
               r.name AS role_name
        FROM sys_user u LEFT JOIN sys_role r ON u.role_id = r.role_id
        ORDER BY u.user_id""")
    return ok(rows)


@router.post("/users")
def create_user(body: UserIn, _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if dbm.query_one(conn, "SELECT 1 FROM sys_user WHERE username=?", (body.username,)):
        raise ApiError("用户名已存在")
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (body.role_id,)):
        raise ApiError("角色不存在")
    pwd = body.password or DEFAULT_PASSWORD
    cur = dbm.execute(conn, """
        INSERT INTO sys_user (username, password_hash, name, role_id, status)
        VALUES (?,?,?,?,?)""",
        (body.username, hash_password(pwd), body.name, body.role_id, body.status))
    return ok({"user_id": cur.lastrowid}, msg="账号已创建")


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    user = dbm.query_one(conn, "SELECT user_id FROM sys_user WHERE user_id=?", (user_id,))
    if not user:
        raise ApiError("账号不存在", status_code=404)
    fields, params = [], []
    if body.name is not None:
        fields.append("name=?"); params.append(body.name)
    if body.role_id is not None:
        if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (body.role_id,)):
            raise ApiError("角色不存在")
        fields.append("role_id=?"); params.append(body.role_id)
    if body.status is not None:
        fields.append("status=?"); params.append(body.status)
    if fields:
        params.append(user_id)
        dbm.execute(conn, f"UPDATE sys_user SET {','.join(fields)} WHERE user_id=?", params)
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
    return ok(msg="账号已删除")


@router.post("/users/{user_id}/reset-pwd")
def reset_pwd(user_id: int, body: ResetPwdIn, _: dict = Depends(require_admin),
              conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_user WHERE user_id=?", (user_id,)):
        raise ApiError("账号不存在", status_code=404)
    pwd = body.password or DEFAULT_PASSWORD
    dbm.execute(conn, "UPDATE sys_user SET password_hash=? WHERE user_id=?",
                (hash_password(pwd), user_id))
    return ok({"password": pwd if not body.password else None}, msg="密码已重置")


# ============================ 角色 ============================
class RoleIn(BaseModel):
    role_id: str
    name: str
    data_scope_type: str | None = None


class RoleUpdateIn(BaseModel):
    name: str | None = None
    data_scope_type: str | None = None


@router.get("/roles")
def list_roles(_: dict = Depends(get_current_user),
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
def create_role(body: RoleIn, _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (body.role_id,)):
        raise ApiError("角色 ID 已存在")
    dbm.execute(conn, "INSERT INTO sys_role (role_id, name, data_scope_type) VALUES (?,?,?)",
                (body.role_id, body.name, body.data_scope_type))
    return ok(msg="角色已创建")


@router.put("/roles/{role_id}")
def update_role(role_id: str, body: RoleUpdateIn, _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (role_id,)):
        raise ApiError("角色不存在", status_code=404)
    fields, params = [], []
    if body.name is not None:
        fields.append("name=?"); params.append(body.name)
    if body.data_scope_type is not None:
        fields.append("data_scope_type=?"); params.append(body.data_scope_type)
    if fields:
        params.append(role_id)
        dbm.execute(conn, f"UPDATE sys_role SET {','.join(fields)} WHERE role_id=?", params)
    return ok(msg="角色已更新")


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (role_id,)):
        raise ApiError("角色不存在", status_code=404)
    if dbm.scalar(conn, "SELECT COUNT(*) FROM sys_user WHERE role_id=?", (role_id,)):
        raise ApiError("该角色下仍有账号，无法删除")
    dbm.execute(conn, "DELETE FROM sys_role_menu WHERE role_id=?", (role_id,))
    dbm.execute(conn, "DELETE FROM sys_role WHERE role_id=?", (role_id,))
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


@router.get("/menus")
def list_menus(_: dict = Depends(get_current_user),
               conn: sqlite3.Connection = Depends(get_db)):
    rows = dbm.query(conn, """
        SELECT menu_id, parent_id, title, path, icon, sort_order
        FROM sys_menu ORDER BY sort_order, menu_id""")
    return ok(rows)


@router.post("/menus")
def create_menu(body: MenuIn, _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if dbm.query_one(conn, "SELECT 1 FROM sys_menu WHERE menu_id=?", (body.menu_id,)):
        raise ApiError("菜单 ID 已存在")
    dbm.execute(conn, """
        INSERT INTO sys_menu (menu_id, parent_id, title, path, icon, sort_order)
        VALUES (?,?,?,?,?,?)""",
        (body.menu_id, body.parent_id, body.title, body.path, body.icon, body.sort_order))
    return ok(msg="菜单已创建")


@router.put("/menus/{menu_id}")
def update_menu(menu_id: str, body: MenuUpdateIn, _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_menu WHERE menu_id=?", (menu_id,)):
        raise ApiError("菜单不存在", status_code=404)
    fields, params = [], []
    for col in ("parent_id", "title", "path", "icon", "sort_order"):
        val = getattr(body, col)
        if val is not None:
            fields.append(f"{col}=?"); params.append(val)
    if fields:
        params.append(menu_id)
        dbm.execute(conn, f"UPDATE sys_menu SET {','.join(fields)} WHERE menu_id=?", params)
    return ok(msg="菜单已更新")


@router.delete("/menus/{menu_id}")
def delete_menu(menu_id: str, _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_menu WHERE menu_id=?", (menu_id,)):
        raise ApiError("菜单不存在", status_code=404)
    dbm.execute(conn, "DELETE FROM sys_role_menu WHERE menu_id=?", (menu_id,))
    dbm.execute(conn, "DELETE FROM sys_menu WHERE menu_id=?", (menu_id,))
    return ok(msg="菜单已删除")


# ======================= 角色-菜单绑定 =======================
class RoleMenusIn(BaseModel):
    menu_ids: list[str]


@router.get("/roles/{role_id}/menus")
def get_role_menus(role_id: str, _: dict = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    rows = dbm.query(conn, "SELECT menu_id FROM sys_role_menu WHERE role_id=?", (role_id,))
    return ok([r["menu_id"] for r in rows])


@router.put("/roles/{role_id}/menus")
def set_role_menus(role_id: str, body: RoleMenusIn, _: dict = Depends(require_admin),
                   conn: sqlite3.Connection = Depends(get_db_rw)):
    if not dbm.query_one(conn, "SELECT 1 FROM sys_role WHERE role_id=?", (role_id,)):
        raise ApiError("角色不存在", status_code=404)
    dbm.execute(conn, "DELETE FROM sys_role_menu WHERE role_id=?", (role_id,))
    for mid in dict.fromkeys(body.menu_ids):  # 去重保序
        if dbm.query_one(conn, "SELECT 1 FROM sys_menu WHERE menu_id=?", (mid,)):
            dbm.execute(conn, "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (?,?)",
                        (role_id, mid))
    return ok(msg="菜单权限已保存")

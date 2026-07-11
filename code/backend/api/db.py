"""DB 访问助手：只读连接 + 查询便捷函数（返回 dict 列表）。"""
import sqlite3

from . import settings


def get_conn() -> sqlite3.Connection:
    """每请求一个只读连接（WAL 允许并发读）。"""
    conn = sqlite3.connect(f"file:{settings.DB_PATH}?mode=ro", uri=True,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_conn_rw() -> sqlite3.Connection:
    """可写连接：仅供后台管理（sys_* 增删改）使用。WAL 下与只读并发不冲突。"""
    conn = sqlite3.connect(f"file:{settings.DB_PATH}?mode=rw", uri=True,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_one(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def scalar(conn: sqlite3.Connection, sql: str, params=()):
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None


def execute(conn: sqlite3.Connection, sql: str, params=()) -> sqlite3.Cursor:
    """执行写语句并返回游标（调用方负责 commit，或用 get_db_rw 依赖自动 commit）。"""
    return conn.execute(sql, params)

"""平台安全治理：登录限流与统一安全审计。"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone


SECURITY_DDL = """
CREATE TABLE IF NOT EXISTS sys_login_attempt (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    client_key TEXT NOT NULL,
    success INTEGER NOT NULL,
    attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempt_lookup
ON sys_login_attempt(username,client_key,attempted_at);
CREATE TABLE IF NOT EXISTS sys_security_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    result TEXT NOT NULL,
    client_key TEXT,
    detail_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_security_audit_time
ON sys_security_audit(created_at,action);
CREATE TABLE IF NOT EXISTS sys_revoked_token (
    jti TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL,
    revoked_at TEXT NOT NULL
);
"""

LOGIN_WINDOW_MINUTES = 15
LOGIN_MAX_FAILURES = 8


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_security_tables(conn: sqlite3.Connection) -> None:
    # execute() keeps DDL inside the caller's transaction; executescript() would
    # implicitly commit a preceding RBAC mutation before its audit row is written.
    for statement in SECURITY_DDL.split(";"):
        if statement.strip():
            conn.execute(statement)


def client_key(request) -> str:
    # Do not trust a caller-supplied X-Forwarded-For value. A production reverse
    # proxy should normalize the peer address before the request reaches the app.
    return request.client.host if request.client else "unknown"


def login_is_limited(conn: sqlite3.Connection, username: str, client: str) -> bool:
    ensure_security_tables(conn)
    cutoff = (datetime.now(timezone.utc).astimezone()
              - timedelta(minutes=LOGIN_WINDOW_MINUTES)).isoformat(timespec="seconds")
    count = conn.execute("""SELECT COUNT(*) FROM sys_login_attempt
        WHERE username=? AND client_key=? AND success=0 AND attempted_at>=?""",
        (username, client, cutoff)).fetchone()[0]
    return count >= LOGIN_MAX_FAILURES


def record_login(conn: sqlite3.Connection, username: str, client: str,
                 success: bool) -> None:
    ensure_security_tables(conn)
    timestamp = now_iso()
    conn.execute("""INSERT INTO sys_login_attempt(username,client_key,success,attempted_at)
        VALUES (?,?,?,?)""", (username, client, int(success), timestamp))
    if success:
        conn.execute("""DELETE FROM sys_login_attempt
            WHERE username=? AND client_key=? AND success=0""", (username, client))


def write_audit(conn: sqlite3.Connection, actor: str | None, action: str,
                target_type: str | None = None, target_id: str | None = None,
                result: str = "success", client: str | None = None,
                detail: dict | None = None) -> None:
    ensure_security_tables(conn)
    conn.execute("""INSERT INTO sys_security_audit
        (actor,action,target_type,target_id,result,client_key,detail_json,created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (actor, action, target_type, target_id, result, client,
         json.dumps(detail or {}, ensure_ascii=False), now_iso()))

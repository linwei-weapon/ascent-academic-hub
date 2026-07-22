"""决策简报快照存储（存于 legacy 库，与配置存储同库）。

- sys_ai_briefing_snapshot：每次生成的简报本体+信号摘要，按 scope_key 分链。
  指纹命中时直接复用，保证"同数据必同简报"。
- 建议追踪（sys_ai_action_tracking）已于产品终稿 R1 退役：AI决策不形成
  办理闭环。历史数据保留在库中，应用不再读写；迁移脚本
  code/scripts/migrate_decision_tracking_retire.py 负责标记。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

STORE_DDL = """
CREATE TABLE IF NOT EXISTS sys_ai_briefing_snapshot (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key TEXT NOT NULL,
    semester TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    generation_method TEXT NOT NULL,
    briefing_json TEXT NOT NULL,
    signals_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_briefing_snapshot_scope
ON sys_ai_briefing_snapshot(scope_key, snapshot_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_tables(conn: sqlite3.Connection) -> None:
    for statement in STORE_DDL.split(";"):
        if statement.strip():
            conn.execute(statement)


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------

def latest_snapshot(conn: sqlite3.Connection, scope_key: str) -> dict | None:
    ensure_tables(conn)
    row = conn.execute("""
        SELECT snapshot_id, scope_key, semester, fingerprint, generation_method,
               briefing_json, signals_json, created_by, created_at
        FROM sys_ai_briefing_snapshot
        WHERE scope_key=? ORDER BY snapshot_id DESC LIMIT 1
    """, (scope_key,)).fetchone()
    if not row:
        return None
    cols = ["snapshot_id", "scope_key", "semester", "fingerprint",
            "generation_method", "briefing_json", "signals_json",
            "created_by", "created_at"]
    data = dict(zip(cols, row))
    data["briefing"] = json.loads(data.pop("briefing_json"))
    data["signals"] = json.loads(data.pop("signals_json"))
    return data


def save_snapshot(conn: sqlite3.Connection, scope_key: str, semester: str,
                  fingerprint: str, generation_method: str,
                  briefing: dict, signal_digests: list[dict],
                  username: str) -> int:
    ensure_tables(conn)
    cur = conn.execute("""
        INSERT INTO sys_ai_briefing_snapshot(
            scope_key, semester, fingerprint, generation_method,
            briefing_json, signals_json, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?)
    """, (scope_key, semester, fingerprint, generation_method,
          json.dumps(briefing, ensure_ascii=False, sort_keys=True),
          json.dumps(signal_digests, ensure_ascii=False, sort_keys=True),
          username, _now()))
    return cur.lastrowid


# ---------------------------------------------------------------------------
# 建议追踪（已退役，R1）：函数保留为空实现会误导调用方，故直接移除。
# 历史表 sys_ai_action_tracking 由迁移脚本标记退役，数据不删除。
# ---------------------------------------------------------------------------

ADVICE_DDL = """
CREATE TABLE IF NOT EXISTS sys_ai_advice_session (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    context_signal_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_advice_session_user
ON sys_ai_advice_session(username, skill_id, updated_at);
CREATE TABLE IF NOT EXISTS sys_ai_advice_message (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_advice_message_session
ON sys_ai_advice_message(session_id, message_id);
"""


def ensure_advice_tables(conn: sqlite3.Connection) -> None:
    for statement in ADVICE_DDL.split(";"):
        if statement.strip():
            conn.execute(statement)


def create_session(conn: sqlite3.Connection, username: str, skill_id: str,
                   title: str = "", context_signal_id: str = "") -> int:
    ensure_advice_tables(conn)
    now = _now()
    cur = conn.execute("""
        INSERT INTO sys_ai_advice_session(
            username, skill_id, title, context_signal_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?)
    """, (username, skill_id, title[:80], context_signal_id, now, now))
    return cur.lastrowid


def touch_session(conn: sqlite3.Connection, session_id: int,
                  title: str = "") -> None:
    if title:
        conn.execute("""
            UPDATE sys_ai_advice_session SET title=?, updated_at=?
            WHERE session_id=?
        """, (title[:80], _now(), session_id))
    else:
        conn.execute("""
            UPDATE sys_ai_advice_session SET updated_at=? WHERE session_id=?
        """, (_now(), session_id))


def get_session(conn: sqlite3.Connection, session_id: int,
                username: str) -> dict | None:
    """按归属校验取会话：他人会话返回 None（对外表现为不存在）。"""
    ensure_advice_tables(conn)
    row = conn.execute("""
        SELECT session_id, username, skill_id, title, context_signal_id,
               created_at, updated_at
        FROM sys_ai_advice_session WHERE session_id=?
    """, (session_id,)).fetchone()
    if not row or row[1] != username:
        return None
    cols = ["session_id", "username", "skill_id", "title",
            "context_signal_id", "created_at", "updated_at"]
    return dict(zip(cols, row))


def list_sessions(conn: sqlite3.Connection, username: str,
                  skill_id: str = "", limit: int = 50) -> list[dict]:
    ensure_advice_tables(conn)
    if skill_id:
        rows = conn.execute("""
            SELECT session_id, username, skill_id, title, context_signal_id,
                   created_at, updated_at
            FROM sys_ai_advice_session
            WHERE username=? AND skill_id=?
            ORDER BY updated_at DESC LIMIT ?
        """, (username, skill_id, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT session_id, username, skill_id, title, context_signal_id,
                   created_at, updated_at
            FROM sys_ai_advice_session
            WHERE username=? ORDER BY updated_at DESC LIMIT ?
        """, (username, limit)).fetchall()
    cols = ["session_id", "username", "skill_id", "title",
            "context_signal_id", "created_at", "updated_at"]
    return [dict(zip(cols, r)) for r in rows]


def append_message(conn: sqlite3.Connection, session_id: int, role: str,
                   content: str, payload: dict | None = None) -> int:
    cur = conn.execute("""
        INSERT INTO sys_ai_advice_message(session_id, role, content, payload_json, created_at)
        VALUES (?,?,?,?,?)
    """, (session_id, role, content,
          json.dumps(payload or {}, ensure_ascii=False), _now()))
    return cur.lastrowid


def list_messages(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute("""
        SELECT message_id, role, content, payload_json, created_at
        FROM sys_ai_advice_message WHERE session_id=? ORDER BY message_id
    """, (session_id,)).fetchall()
    out = []
    for mid, role, content, payload_json, created_at in rows:
        out.append({
            "message_id": mid, "role": role, "content": content,
            "payload": json.loads(payload_json or "{}"),
            "created_at": created_at,
        })
    return out

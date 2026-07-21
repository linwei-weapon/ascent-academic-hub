"""决策简报快照存储与建议追踪（存于 legacy 库，与配置存储同库）。

- sys_ai_briefing_snapshot：每次生成的简报本体+信号摘要，按 scope_key 分链。
  指纹命中时直接复用，保证"同数据必同简报"。
- sys_ai_action_tracking：管理者对信号动作的手动标记（一期为手动闭环）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

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
CREATE TABLE IF NOT EXISTS sys_ai_action_tracking (
    tracking_id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    skill_id TEXT NOT NULL,
    entity_json TEXT NOT NULL DEFAULT '{}',
    headline TEXT NOT NULL,
    action_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','in_progress','done','dismissed')),
    assignee TEXT,
    note TEXT,
    scope_key TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_action_tracking_status
ON sys_ai_action_tracking(status, updated_at);
"""

TRACKING_STATUSES = ("open", "in_progress", "done", "dismissed")


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
# 建议追踪
# ---------------------------------------------------------------------------

def list_tracking(conn: sqlite3.Connection, scope_key: str,
                  statuses: tuple[str, ...] | None = None,
                  limit: int = 100) -> list[dict]:
    ensure_tables(conn)
    where = "WHERE (scope_key=? OR scope_key='')"
    params: list[Any] = [scope_key]
    if statuses:
        where += f" AND status IN ({','.join('?' * len(statuses))})"
        params.extend(statuses)
    rows = conn.execute(f"""
        SELECT tracking_id, signal_id, skill_id, entity_json, headline,
               action_json, status, assignee, note, scope_key,
               created_by, created_at, updated_by, updated_at
        FROM sys_ai_action_tracking {where}
        ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'open' THEN 1
                 WHEN 'done' THEN 2 ELSE 3 END, updated_at DESC
        LIMIT ?
    """, tuple(params + [limit])).fetchall()
    cols = ["tracking_id", "signal_id", "skill_id", "entity_json", "headline",
            "action_json", "status", "assignee", "note", "scope_key",
            "created_by", "created_at", "updated_by", "updated_at"]
    out = []
    for row in rows:
        item = dict(zip(cols, row))
        item["entity"] = json.loads(item.pop("entity_json") or "{}")
        item["action"] = json.loads(item.pop("action_json") or "{}")
        out.append(item)
    return out


def upsert_tracking(conn: sqlite3.Connection, signal: dict, status: str,
                    username: str, scope_key: str,
                    assignee: str = "", note: str = "") -> dict:
    """按 signal_id 幂等创建/更新追踪记录。"""
    if status not in TRACKING_STATUSES:
        raise ValueError(f"状态必须为 {'/'.join(TRACKING_STATUSES)}")
    ensure_tables(conn)
    now = _now()
    existing = conn.execute(
        "SELECT tracking_id, status FROM sys_ai_action_tracking WHERE signal_id=?",
        (signal["signal_id"],)).fetchone()
    if existing:
        conn.execute("""
            UPDATE sys_ai_action_tracking
            SET status=?, assignee=?, note=?, updated_by=?, updated_at=?,
                headline=?, action_json=?, entity_json=?
            WHERE signal_id=?
        """, (status, assignee.strip() or None, note.strip() or None,
              username, now,
              signal.get("headline", ""),
              json.dumps(signal.get("action") or {}, ensure_ascii=False),
              json.dumps(signal.get("entity") or {}, ensure_ascii=False),
              signal["signal_id"]))
        return {"trackingId": existing[0], "status": status, "updated": True}
    cur = conn.execute("""
        INSERT INTO sys_ai_action_tracking(
            signal_id, skill_id, entity_json, headline, action_json,
            status, assignee, note, scope_key, created_by, created_at,
            updated_by, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (signal["signal_id"], signal.get("skill_id", ""),
          json.dumps(signal.get("entity") or {}, ensure_ascii=False),
          signal.get("headline", ""),
          json.dumps(signal.get("action") or {}, ensure_ascii=False),
          status, assignee.strip() or None, note.strip() or None,
          scope_key, username, now, username, now))
    return {"trackingId": cur.lastrowid, "status": status, "updated": False}

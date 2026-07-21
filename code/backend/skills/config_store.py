"""Skill 配置存储：产品默认值 + 学校版本化覆写。

存储于 legacy 库（与 sys_ai_expert_version 同库），skill 维度独立版本链。
学校覆写只允许落在 Skill.config_bounds 声明的范围内。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS sys_ai_skill_config (
    config_id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL,
    version_no TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','published','retired')),
    config_json TEXT NOT NULL DEFAULT '{}',
    change_reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT,
    UNIQUE(skill_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_ai_skill_config_lookup
ON sys_ai_skill_config(skill_id, status, config_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_tables(conn: sqlite3.Connection) -> None:
    for statement in CONFIG_DDL.split(";"):
        if statement.strip():
            conn.execute(statement)


def _query_one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute(sql + " LIMIT 0").description]
    return dict(zip(cols, row))


def active_override(conn: sqlite3.Connection, skill_id: str) -> tuple[dict, str]:
    """返回 (覆写配置, 生效版本号)。无学校配置时返回 ({}, 'product_default')。"""
    ensure_tables(conn)
    row = conn.execute("""
        SELECT config_json, version_no FROM sys_ai_skill_config
        WHERE skill_id=? AND status='published'
        ORDER BY config_id DESC LIMIT 1
    """, (skill_id,)).fetchone()
    if not row:
        return {}, "product_default"
    try:
        override = json.loads(row[0] or "{}")
    except (TypeError, ValueError):
        override = {}
    return (override if isinstance(override, dict) else {}), row[1]


def resolve_config(conn: sqlite3.Connection, skill) -> tuple[dict, str]:
    """产品默认 + 学校覆写（已校验）→ (生效配置, 版本号)。"""
    override, version = active_override(conn, skill.skill_id)
    config = dict(skill.default_config)
    if override:
        errors = skill.validate_override(override)
        if not errors:
            config.update(override)
    return config, version


def list_versions(conn: sqlite3.Connection, skill_id: str) -> list[dict]:
    ensure_tables(conn)
    rows = conn.execute("""
        SELECT config_id, skill_id, version_no, status, change_reason,
               created_by, created_at, published_by, published_at
        FROM sys_ai_skill_config WHERE skill_id=? ORDER BY config_id DESC
    """, (skill_id,)).fetchall()
    cols = ["config_id", "skill_id", "version_no", "status", "change_reason",
            "created_by", "created_at", "published_by", "published_at"]
    return [dict(zip(cols, r)) for r in rows]


def create_draft(conn: sqlite3.Connection, skill, override: dict,
                 change_reason: str, username: str) -> dict:
    errors = skill.validate_override(override)
    if errors:
        raise ValueError("；".join(errors))
    ensure_tables(conn)
    serial = (conn.execute(
        "SELECT COUNT(*) FROM sys_ai_skill_config WHERE skill_id=?",
        (skill.skill_id,)).fetchone()[0] or 0) + 1
    version_no = f"{serial}.0-school"
    cur = conn.execute("""
        INSERT INTO sys_ai_skill_config(
            skill_id, version_no, status, config_json, change_reason, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?)
    """, (skill.skill_id, version_no, "draft",
          json.dumps(override, ensure_ascii=False, sort_keys=True),
          change_reason.strip(), username, _now()))
    return {"configId": cur.lastrowid, "version": version_no, "status": "draft"}


def publish(conn: sqlite3.Connection, skill_id: str, config_id: int,
            username: str) -> dict:
    ensure_tables(conn)
    row = conn.execute("""
        SELECT config_id, version_no, status FROM sys_ai_skill_config
        WHERE config_id=? AND skill_id=?
    """, (config_id, skill_id)).fetchone()
    if not row:
        raise ValueError("配置版本不存在")
    if row[2] != "draft":
        raise ValueError("只有草稿可以发布")
    now = _now()
    conn.execute("""
        UPDATE sys_ai_skill_config SET status='retired'
        WHERE skill_id=? AND status='published'
    """, (skill_id,))
    conn.execute("""
        UPDATE sys_ai_skill_config
        SET status='published', published_by=?, published_at=?
        WHERE config_id=?
    """, (username, now, config_id))
    return {"configId": config_id, "version": row[1], "status": "published"}


def rollback(conn: sqlite3.Connection, skill_id: str, config_id: int,
             username: str, change_reason: str = "") -> dict:
    """回滚到任一历史版本：以其内容为蓝本创建新草稿并直接发布。"""
    ensure_tables(conn)
    row = conn.execute("""
        SELECT config_json FROM sys_ai_skill_config
        WHERE config_id=? AND skill_id=? AND status IN ('published','retired')
    """, (config_id, skill_id)).fetchone()
    if not row:
        raise ValueError("只能回滚到已发布或已退役版本")
    serial = (conn.execute(
        "SELECT COUNT(*) FROM sys_ai_skill_config WHERE skill_id=?",
        (skill_id,)).fetchone()[0] or 0) + 1
    version_no = f"{serial}.0-school"
    now = _now()
    conn.execute("""
        UPDATE sys_ai_skill_config SET status='retired'
        WHERE skill_id=? AND status='published'
    """, (skill_id,))
    cur = conn.execute("""
        INSERT INTO sys_ai_skill_config(
            skill_id, version_no, status, config_json, change_reason,
            created_by, created_at, published_by, published_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
    """, (skill_id, version_no, "published", row[0],
          (change_reason or "回滚到历史版本").strip(), username, now, username, now))
    return {"configId": cur.lastrowid, "version": version_no, "status": "published"}

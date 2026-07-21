"""管理专家学校覆写的版本存储与生效解析。

历史说明：旧 `/api/admin/ai/experts` HTTP 端点族已随「管理要情/决策研判」
页面下线（阶段6收口）。本模块保留其共享部分——版本表 DDL 与生效配置解析，
供 ai.py 学生洞察端点与 system_management.py 配置治理继续使用。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .registry import apply_school_override

EXPERT_CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS sys_ai_expert_version (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id TEXT NOT NULL,
    version_no TEXT NOT NULL,
    base_definition_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','published','retired')),
    override_json TEXT NOT NULL DEFAULT '{}',
    change_reason TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'override',
    source_version_id INTEGER,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT,
    UNIQUE(expert_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_ai_expert_version_lookup
ON sys_ai_expert_version(expert_id,status,version_id);
CREATE TABLE IF NOT EXISTS sys_ai_analysis_scheme (
    scheme_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id TEXT NOT NULL,
    name TEXT NOT NULL,
    expert_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','published','retired')),
    parameters_json TEXT NOT NULL,
    scope_policy_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_scheme_lookup
ON sys_ai_analysis_scheme(expert_id,status,scheme_id);
CREATE TABLE IF NOT EXISTS sys_ai_analysis_scheme_role (
    scheme_id INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    PRIMARY KEY(scheme_id,role_id)
);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_scheme_role
ON sys_ai_analysis_scheme_role(role_id,scheme_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_tables(conn: sqlite3.Connection) -> None:
    for statement in EXPERT_CONFIG_DDL.split(";"):
        if statement.strip():
            conn.execute(statement)


def active_version(conn: sqlite3.Connection, expert_id: str) -> dict | None:
    ensure_tables(conn)
    row = conn.execute("""
        SELECT * FROM sys_ai_expert_version
        WHERE expert_id=? AND status='published'
        ORDER BY version_id DESC LIMIT 1
    """, (expert_id,)).fetchone()
    return dict(row) if row else None


def decode_override(row: dict | None) -> dict:
    if not row:
        return {}
    try:
        value = json.loads(row.get("override_json") or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def resolve_effective_expert(conn: sqlite3.Connection,
                             expert: dict) -> tuple[dict, dict]:
    """产品定义 + 学校已发布覆写 → (生效定义, 版本元信息)。"""
    active = active_version(conn, expert["expertId"])
    effective = apply_school_override(expert, decode_override(active))
    effective["effectiveVersion"] = active["version_no"] if active else expert["version"]
    effective["productDefinitionVersion"] = expert["version"]
    version_meta = {
        "versionId": active["version_id"] if active else None,
        "version": effective["effectiveVersion"],
        "status": active["status"] if active else "product_default",
        "source": "school_override" if active else "product_default",
        "publishedAt": active.get("published_at") if active else None,
    }
    return effective, version_meta

"""学校分析方案存储：产品默认值 + 学校版本化覆写。

运行真值统一为 ``sys_ai_skill_config``。学校方案只保存 Skill 声明允许覆写的参数
和适用角色；组织、学院、班级及学生范围仍由当前工作身份实时计算。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .protocol import PROTOCOL_VERSION


ANALYSIS_ROLE_IDS = [
    "school_leader", "dean", "dept_research", "dept_practice",
    "quality_office", "college_dean", "college_secretary",
]

CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS sys_ai_skill_config (
    config_id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL,
    version_no TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','published','retired')),
    scheme_name TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    change_reason TEXT NOT NULL,
    base_protocol_version TEXT NOT NULL DEFAULT 'decision-skill/1.0',
    test_status TEXT NOT NULL DEFAULT 'untested',
    test_result_json TEXT NOT NULL DEFAULT '{}',
    tested_by TEXT,
    tested_at TEXT,
    action TEXT NOT NULL DEFAULT 'override',
    source_config_id INTEGER,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT,
    UNIQUE(skill_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_ai_skill_config_lookup
ON sys_ai_skill_config(skill_id, status, config_id);
CREATE TABLE IF NOT EXISTS sys_ai_skill_config_role (
    config_id INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    PRIMARY KEY(config_id, role_id)
);
CREATE INDEX IF NOT EXISTS idx_ai_skill_config_role
ON sys_ai_skill_config_role(role_id, config_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _decode(value: Any, fallback: Any) -> Any:
    try:
        decoded = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return decoded if isinstance(decoded, type(fallback)) else fallback


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(CONFIG_DDL)
    # 兼容早期仅包含 config_json 的版本表；迁移可安全重复执行。
    columns = _column_names(conn, "sys_ai_skill_config")
    additions = {
        "scheme_name": "TEXT NOT NULL DEFAULT ''",
        "base_protocol_version": (
            "TEXT NOT NULL DEFAULT 'decision-skill/1.0'"
        ),
        "test_status": "TEXT NOT NULL DEFAULT 'untested'",
        "test_result_json": "TEXT NOT NULL DEFAULT '{}'",
        "tested_by": "TEXT",
        "tested_at": "TEXT",
        "action": "TEXT NOT NULL DEFAULT 'override'",
        "source_config_id": "INTEGER",
    }
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE sys_ai_skill_config ADD COLUMN {name} {declaration}"
            )
    conn.execute("""
        UPDATE sys_ai_skill_config
        SET scheme_name=CASE
            WHEN trim(coalesce(scheme_name,''))='' THEN skill_id || ' 学校方案'
            ELSE scheme_name END
    """)
    # 旧版本没有角色映射时视为适用于全部管理决策角色。
    ids = [
        row[0] for row in conn.execute("""
            SELECT c.config_id FROM sys_ai_skill_config c
            WHERE NOT EXISTS (
                SELECT 1 FROM sys_ai_skill_config_role r
                WHERE r.config_id=c.config_id
            )
        """).fetchall()
    ]
    for config_id in ids:
        for role_id in ANALYSIS_ROLE_IDS:
            conn.execute("""
                INSERT OR IGNORE INTO sys_ai_skill_config_role(config_id,role_id)
                VALUES(?,?)
            """, (config_id, role_id))


def _normalize_roles(role_ids: list[str] | None) -> list[str]:
    roles = list(dict.fromkeys(role_ids or ANALYSIS_ROLE_IDS))
    if not roles:
        raise ValueError("适用角色不能为空")
    invalid = [role for role in roles if role not in ANALYSIS_ROLE_IDS]
    if invalid:
        raise ValueError("存在不适用的角色：" + "、".join(invalid))
    return roles


def _role_ids(conn: sqlite3.Connection, config_id: int) -> list[str]:
    return [
        row[0] for row in conn.execute("""
            SELECT role_id FROM sys_ai_skill_config_role
            WHERE config_id=? ORDER BY role_id
        """, (config_id,)).fetchall()
    ]


def _active_row(conn: sqlite3.Connection, skill_id: str,
                role_id: str | None = None):
    ensure_tables(conn)
    params: list[Any] = [skill_id]
    role_clause = ""
    if role_id:
        role_clause = """
          AND EXISTS (
            SELECT 1 FROM sys_ai_skill_config_role r
            WHERE r.config_id=c.config_id AND r.role_id=?
          )
        """
        params.append(role_id)
    return conn.execute(f"""
        SELECT c.* FROM sys_ai_skill_config c
        WHERE c.skill_id=? AND c.status='published' {role_clause}
        ORDER BY c.config_id DESC LIMIT 1
    """, tuple(params)).fetchone()


def active_override(conn: sqlite3.Connection, skill_id: str,
                    role_id: str | None = None) -> tuple[dict, str]:
    """返回适用当前角色的 (覆写配置, 生效版本号)。"""
    row = _active_row(conn, skill_id, role_id)
    if not row:
        return {}, "product_default"
    data = dict(row)
    return _decode(data.get("config_json"), {}), data["version_no"]


def active_metadata(conn: sqlite3.Connection, skill_id: str,
                    role_id: str | None = None) -> dict | None:
    row = _active_row(conn, skill_id, role_id)
    if not row:
        return None
    data = dict(row)
    data["config"] = _decode(data.pop("config_json"), {})
    data["testResult"] = _decode(data.pop("test_result_json"), {})
    data["roleIds"] = _role_ids(conn, data["config_id"])
    return data


def resolve_config(conn: sqlite3.Connection, skill,
                   role_id: str | None = None) -> tuple[dict, str]:
    """产品默认 + 当前角色适用的学校方案 → (生效配置, 版本号)。"""
    override, version = active_override(conn, skill.skill_id, role_id)
    config = dict(skill.default_config)
    if override:
        errors = skill.validate_override(override)
        if not errors:
            config.update(override)
    return config, version


def get_version(conn: sqlite3.Connection, skill_id: str,
                config_id: int) -> dict | None:
    ensure_tables(conn)
    row = conn.execute("""
        SELECT * FROM sys_ai_skill_config
        WHERE skill_id=? AND config_id=?
    """, (skill_id, config_id)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["config"] = _decode(data.pop("config_json"), {})
    data["testResult"] = _decode(data.pop("test_result_json"), {})
    data["roleIds"] = _role_ids(conn, config_id)
    return data


def list_versions(conn: sqlite3.Connection, skill_id: str) -> list[dict]:
    ensure_tables(conn)
    ids = [
        row[0] for row in conn.execute("""
            SELECT config_id FROM sys_ai_skill_config
            WHERE skill_id=? ORDER BY config_id DESC
        """, (skill_id,)).fetchall()
    ]
    return [item for item in (
        get_version(conn, skill_id, config_id) for config_id in ids
    ) if item]


def _next_version(conn: sqlite3.Connection, skill_id: str) -> str:
    serial = (conn.execute(
        "SELECT COUNT(*) FROM sys_ai_skill_config WHERE skill_id=?",
        (skill_id,)).fetchone()[0] or 0) + 1
    return f"{serial}.0-school"


def _replace_roles(conn: sqlite3.Connection, config_id: int,
                   role_ids: list[str] | None) -> list[str]:
    roles = _normalize_roles(role_ids)
    conn.execute(
        "DELETE FROM sys_ai_skill_config_role WHERE config_id=?",
        (config_id,),
    )
    for role_id in roles:
        conn.execute("""
            INSERT INTO sys_ai_skill_config_role(config_id,role_id)
            VALUES(?,?)
        """, (config_id, role_id))
    return roles


def create_draft(conn: sqlite3.Connection, skill, override: dict,
                 change_reason: str, username: str, scheme_name: str = "",
                 role_ids: list[str] | None = None,
                 source_config_id: int | None = None) -> dict:
    errors = skill.validate_override(override)
    if errors:
        raise ValueError("；".join(errors))
    ensure_tables(conn)
    roles = _normalize_roles(role_ids)
    version_no = _next_version(conn, skill.skill_id)
    display_name = (scheme_name or f"{skill.name}学校方案").strip()
    cur = conn.execute("""
        INSERT INTO sys_ai_skill_config(
            skill_id,version_no,status,scheme_name,config_json,change_reason,
            base_protocol_version,test_status,test_result_json,action,
            source_config_id,created_by,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        skill.skill_id, version_no, "draft", display_name,
        json.dumps(override, ensure_ascii=False, sort_keys=True),
        change_reason.strip(), PROTOCOL_VERSION, "untested", "{}",
        "copy" if source_config_id else "override", source_config_id,
        username, _now(),
    ))
    config_id = int(cur.lastrowid)
    _replace_roles(conn, config_id, roles)
    return {
        "configId": config_id, "version": version_no, "status": "draft",
        "schemeName": display_name, "roleIds": roles,
    }


def update_draft(conn: sqlite3.Connection, skill, config_id: int,
                 override: dict, change_reason: str, scheme_name: str,
                 role_ids: list[str] | None) -> dict:
    row = get_version(conn, skill.skill_id, config_id)
    if not row:
        raise ValueError("分析方案草稿不存在")
    if row["status"] != "draft":
        raise ValueError("只有草稿方案可以修改")
    errors = skill.validate_override(override)
    if errors:
        raise ValueError("；".join(errors))
    display_name = (scheme_name or row["scheme_name"]).strip()
    conn.execute("""
        UPDATE sys_ai_skill_config
        SET scheme_name=?,config_json=?,change_reason=?,
            test_status='untested',test_result_json='{}',
            tested_by=NULL,tested_at=NULL
        WHERE config_id=?
    """, (
        display_name,
        json.dumps(override, ensure_ascii=False, sort_keys=True),
        change_reason.strip(), config_id,
    ))
    roles = _replace_roles(conn, config_id, role_ids)
    return {
        "configId": config_id, "version": row["version_no"],
        "status": "draft", "schemeName": display_name, "roleIds": roles,
    }


def save_test_result(conn: sqlite3.Connection, skill_id: str, config_id: int,
                     result: dict, username: str) -> dict:
    row = get_version(conn, skill_id, config_id)
    if not row:
        raise ValueError("分析方案草稿不存在")
    if row["status"] != "draft":
        raise ValueError("只有草稿方案需要发布前检查")
    status = "passed" if result.get("passed") else "failed"
    tested_at = _now()
    conn.execute("""
        UPDATE sys_ai_skill_config
        SET test_status=?,test_result_json=?,tested_by=?,tested_at=?
        WHERE config_id=?
    """, (
        status, json.dumps(result, ensure_ascii=False, sort_keys=True),
        username, tested_at, config_id,
    ))
    return {"configId": config_id, "testStatus": status, "testedAt": tested_at}


def publish(conn: sqlite3.Connection, skill_id: str, config_id: int,
            username: str, require_test: bool = False) -> dict:
    ensure_tables(conn)
    row = conn.execute("""
        SELECT config_id,version_no,status,test_status
        FROM sys_ai_skill_config
        WHERE config_id=? AND skill_id=?
    """, (config_id, skill_id)).fetchone()
    if not row:
        raise ValueError("配置版本不存在")
    if row[2] != "draft":
        raise ValueError("只有草稿可以发布")
    if require_test and row[3] != "passed":
        raise ValueError("方案尚未通过发布前检查")
    now = _now()
    conn.execute("""
        UPDATE sys_ai_skill_config SET status='retired'
        WHERE skill_id=? AND status='published'
    """, (skill_id,))
    conn.execute("""
        UPDATE sys_ai_skill_config
        SET status='published',published_by=?,published_at=?
        WHERE config_id=?
    """, (username, now, config_id))
    return {"configId": config_id, "version": row[1], "status": "published"}


def retire(conn: sqlite3.Connection, skill_id: str, config_id: int) -> dict:
    row = get_version(conn, skill_id, config_id)
    if not row:
        raise ValueError("分析方案不存在")
    if row["status"] != "published":
        raise ValueError("只有生效中的学校方案可以停用")
    conn.execute(
        "UPDATE sys_ai_skill_config SET status='retired' WHERE config_id=?",
        (config_id,),
    )
    return {
        "configId": config_id, "version": row["version_no"],
        "status": "retired",
    }


def rollback(conn: sqlite3.Connection, skill_id: str, config_id: int,
             username: str, change_reason: str = "") -> dict:
    """以历史版本为蓝本生成新的已发布版本，保留完整审计链。"""
    source = get_version(conn, skill_id, config_id)
    if not source or source["status"] not in {"published", "retired"}:
        raise ValueError("只能回滚到已发布或已退役版本")
    version_no = _next_version(conn, skill_id)
    now = _now()
    conn.execute("""
        UPDATE sys_ai_skill_config SET status='retired'
        WHERE skill_id=? AND status='published'
    """, (skill_id,))
    cur = conn.execute("""
        INSERT INTO sys_ai_skill_config(
            skill_id,version_no,status,scheme_name,config_json,change_reason,
            base_protocol_version,test_status,test_result_json,tested_by,
            tested_at,action,source_config_id,created_by,created_at,
            published_by,published_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        skill_id, version_no, "published", source["scheme_name"],
        json.dumps(source["config"], ensure_ascii=False, sort_keys=True),
        (change_reason or "回滚到历史版本").strip(),
        source["base_protocol_version"], "passed",
        json.dumps(source["testResult"], ensure_ascii=False, sort_keys=True),
        username, now, "rollback", config_id, username, now, username, now,
    ))
    new_id = int(cur.lastrowid)
    _replace_roles(conn, new_id, source["roleIds"])
    return {"configId": new_id, "version": version_no, "status": "published"}

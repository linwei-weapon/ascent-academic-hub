"""LLM 编排层配置：存 legacy 库 sys_ai_decision_llm_config（与决策模块其他表同库）。

决策点 D2：供应商抽象为 OpenAI 兼容协议（国内模型API/私有化均可接入），
配置驱动、可热切换；默认关闭——关闭时系统就是完整的规则版产品。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

CONFIG_KEY = "decision.llm"

CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS sys_ai_decision_llm_config (
    config_key TEXT PRIMARY KEY,
    config_value TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT
);
"""

DEFAULTS: dict = {
    "enabled": False,
    "provider": "openai_compatible",   # 国内模型API/私有化统一走 OpenAI Chat Completions 协议
    "base_url": "",                    # 如 https://dashscope.aliyuncs.com/compatible-mode/v1 或私有化网关
    "api_key": "",
    "model": "",
    "timeout_seconds": 20,
    "max_retries": 1,                  # 稳定性防线：重试≤1次
    "narrative_enabled": True,         # 简报叙事增强开关（独立于对话）
    "chat_enabled": True,              # 对话编排开关
}

_EDITABLE = set(DEFAULTS) - {"provider"}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_tables(conn: sqlite3.Connection) -> None:
    for statement in CONFIG_DDL.split(";"):
        if statement.strip():
            conn.execute(statement)


def load_config(rw: sqlite3.Connection) -> dict:
    """读取生效配置：库内值覆盖默认值；库缺失时返回默认（关闭）。"""
    ensure_tables(rw)
    row = rw.execute(
        "SELECT config_value FROM sys_ai_decision_llm_config WHERE config_key=?",
        (CONFIG_KEY,)).fetchone()
    cfg = dict(DEFAULTS)
    if row:
        try:
            stored = json.loads(row[0] or "{}")
            for key in DEFAULTS:
                if key in stored:
                    cfg[key] = stored[key]
        except (TypeError, ValueError):
            pass
    return cfg


def save_config(rw: sqlite3.Connection, patch: dict, username: str = "") -> dict:
    """更新允许编辑的键；返回生效配置。非法键被忽略。"""
    current = load_config(rw)
    for key, value in (patch or {}).items():
        if key in _EDITABLE:
            current[key] = value
    ensure_tables(rw)
    rw.execute("""
        INSERT INTO sys_ai_decision_llm_config(config_key, config_value, updated_by, updated_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(config_key) DO UPDATE SET
            config_value=excluded.config_value,
            updated_by=excluded.updated_by,
            updated_at=excluded.updated_at
    """, (CONFIG_KEY, json.dumps(current, ensure_ascii=False), username, _now()))
    rw.commit()
    return current


def llm_ready(cfg: dict) -> bool:
    """配置是否达到可调用状态（未配齐时走规则版，不算故障）。"""
    return bool(cfg.get("enabled") and cfg.get("base_url")
                and cfg.get("api_key") and cfg.get("model"))

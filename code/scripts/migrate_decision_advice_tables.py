# -*- coding: utf-8 -*-
"""R4 专家问策：创建问策会话/消息表（幂等，可重复执行）。

用法：cd code && python -X utf8 scripts/migrate_decision_advice_tables.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api.settings import DB_PATH as LEGACY_DB_PATH  # noqa: E402
from backend.skills.store import ADVICE_DDL  # noqa: E402


def main() -> None:
    conn = sqlite3.connect(LEGACY_DB_PATH)
    try:
        for statement in ADVICE_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sys_ai_advice%'")}
        conn.commit()
        assert "sys_ai_advice_session" in tables and "sys_ai_advice_message" in tables
        print(f"[ok] 问策会话表就绪: {sorted(tables)} @ {LEGACY_DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

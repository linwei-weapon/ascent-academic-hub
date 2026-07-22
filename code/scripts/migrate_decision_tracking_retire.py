"""建议追踪功能退役迁移（产品终稿 R1）：AI决策不形成办理闭环。

- 历史表 sys_ai_action_tracking 数据保留、不再读写；
- 建立 sys_ai_retired_feature 标记表并登记，供审计与后续清理依据；
- 幂等，可重复执行。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_decision_tracking_retire.py
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入

from backend.etl import config

FEATURE = "decision_action_tracking"
NOTE = ("建议追踪（处理中/完成/忽略、指派、上期跟进）已下线："
        "AI决策不形成办理闭环。接口返回410，历史数据保留不删。")


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sys_ai_retired_feature (
            feature TEXT PRIMARY KEY,
            retired_at TEXT NOT NULL,
            note TEXT NOT NULL
        )
    """)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO sys_ai_retired_feature(feature, retired_at, note) "
        "VALUES(?,?,?) ON CONFLICT(feature) DO NOTHING",
        (FEATURE, now, NOTE))
    # 历史表存在性检查（不修改数据）
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='sys_ai_action_tracking'").fetchone()
    count = 0
    if row:
        count = conn.execute(
            "SELECT COUNT(*) FROM sys_ai_action_tracking").fetchone()[0]
    conn.commit()
    print(f"✓ 已登记退役标记：{FEATURE}")
    print(f"✓ 历史追踪数据保留 {count} 条（不再读写）")


def main(db_path: Path | None = None) -> None:
    path = db_path or config.DB_PATH
    if not Path(path).exists():
        print(f"[X] 未找到分析库 {path}，请先运行初始化")
        sys.exit(1)
    conn = sqlite3.connect(str(path))
    try:
        migrate(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

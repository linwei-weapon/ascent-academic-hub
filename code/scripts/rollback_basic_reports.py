"""仅撤销基础报表自有控制数据；不触碰业务表或其他菜单。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from backend.api.basic_reports.catalog import REPORTS
from backend.api.basic_reports.rule_registry import RULES
from backend.etl import config


def rollback(conn: sqlite3.Connection) -> None:
    leaves = [item.menu_path for item in REPORTS.values()]
    placeholders = ",".join("?" * len(leaves))
    conn.execute(f"DELETE FROM sys_role_menu WHERE menu_id IN ({placeholders})", tuple(leaves))
    conn.execute(f"DELETE FROM sys_menu WHERE menu_id IN ({placeholders})", tuple(leaves))
    conn.execute("DELETE FROM sys_menu WHERE menu_id='/admin/basic-reports'")
    conn.execute("DELETE FROM sys_metric_page_binding WHERE page_path LIKE '/admin/basic-reports/%'")
    metric_ids = [rule_id for rule_id in RULES]
    conn.execute(f"DELETE FROM sys_metric_definition WHERE metric_id IN ({','.join('?' * len(metric_ids))})", tuple(metric_ids))
    conn.execute("DELETE FROM sys_system_parameter WHERE parameter_key LIKE 'basic_reports.%'")
    conn.execute("UPDATE sys_menu SET sort_order=3 WHERE menu_id='/admin/system'")
    conn.execute("UPDATE sys_menu SET sort_order=300 + CAST(substr(sort_order,2) AS INTEGER) WHERE parent_id='/admin/system' AND sort_order BETWEEN 401 AND 409")
    conn.commit()


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(config.DB_PATH)
    connection = sqlite3.connect(str(path)); rollback(connection); connection.close()
    print(f"基础报表控制数据已撤销：{path}")

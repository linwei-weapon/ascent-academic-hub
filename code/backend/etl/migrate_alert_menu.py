"""将预警规则治理入口迁移到学业预警监控模块；可重复执行。"""
import sqlite3

from . import config


def migrate(db_path=config.DB_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE sys_menu SET title=? WHERE menu_id=?", ("学业预警监控", "/admin/alert"))
        child_ids = ("/admin/alert/monitor", "/admin/alert/rules", "/admin/alert/discovery")
        conn.executemany("DELETE FROM sys_role_menu WHERE menu_id=?", [(x,) for x in child_ids])
        conn.executemany("DELETE FROM sys_menu WHERE menu_id=?", [(x,) for x in child_ids])
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
    print("alert menu migration complete")

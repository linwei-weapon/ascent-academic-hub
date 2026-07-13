"""将师资模块菜单更新为教学保障定位；可重复执行。"""
import sqlite3

from . import config


def migrate(db_path=config.DB_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE sys_menu SET title=? WHERE menu_id=?",
            ("师资保障分析", "/admin/faculty"),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
    print("faculty menu migration complete")

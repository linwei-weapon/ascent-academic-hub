"""分析库连接与建表。阶段2 ETL / 阶段3 后端共用。"""
import sqlite3
from . import config


def get_conn(db_path=None) -> sqlite3.Connection:
    """打开 SQLite 连接（WAL）。"""
    path = str(db_path or config.DB_PATH)
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = OFF;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """执行 schema.sql 重建全部表（幂等：内部 DROP+CREATE）。"""
    sql = config.SCHEMA_SQL.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def table_count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


if __name__ == "__main__":
    # 直接运行：建库 + 打印表清单（验证 schema 可用）
    c = get_conn()
    init_schema(c)
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print(f"分析库已建：{config.DB_PATH}")
    print(f"共 {len(rows)} 张表：")
    for (name,) in rows:
        print(f"  - {name}")
    c.close()

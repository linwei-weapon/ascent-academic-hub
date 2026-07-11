"""一次性幂等迁移：创建 sys_discovered_rule 表。"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "backend" / "db" / "analytics.sqlite"

def main():
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sys_discovered_rule (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            semester_id   TEXT NOT NULL,
            name          TEXT NOT NULL,
            conditions    TEXT NOT NULL,
            level         TEXT,
            confidence    REAL,
            risk_ratio    REAL,
            sample_size   INTEGER,
            detail_json   TEXT,
            status        TEXT DEFAULT 'pending',
            created_at    TEXT DEFAULT (datetime('now','localtime')),
            approved_at   TEXT
        );
    """)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM sys_discovered_rule").fetchone()[0]
    print(f"sys_discovered_rule 表已就绪，当前 {n} 条记录")
    conn.close()

if __name__ == "__main__":
    main()

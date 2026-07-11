"""修正教室星期/节次模拟分布的证据来源标记。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.settings import DB_PATH

if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    changed = conn.execute("UPDATE agg_classroom_util SET source='sim' WHERE source<>'sim'").rowcount
    conn.commit()
    counts = conn.execute("SELECT source,COUNT(*) FROM agg_classroom_util GROUP BY source").fetchall()
    conn.close()
    print("updated", changed)
    print("source counts", counts)

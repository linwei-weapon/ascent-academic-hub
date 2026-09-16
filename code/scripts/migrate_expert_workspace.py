"""Idempotent expert-team migration only; never modifies a teaching source DB."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.expert_team import storage


def main():
    target=storage.path()
    if not target.is_file(): raise SystemExit('专家团独立库尚未初始化，请先完成首期准备。')
    backup=target.with_name('expert_team.before-v1.3.sqlite')
    conn=storage.connect()
    try:
        if not backup.exists():
            with sqlite3.connect(backup) as saved: conn.backup(saved)
        storage.migrate(conn)
        conn.execute("INSERT OR REPLACE INTO team_meta VALUES('workspace_schema_version','2')")
        conn.commit()
        print('EXPERT_WORKSPACE_SCHEMA_2_READY; backup:',backup)
    finally: conn.close()


if __name__=='__main__':main()

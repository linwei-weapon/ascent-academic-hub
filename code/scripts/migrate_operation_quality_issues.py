"""生成教学运行数据质量问题清单，可重复执行。"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.settings import DB_PATH

CAP = 200
DDL = """CREATE TABLE IF NOT EXISTS data_quality_issue (
 issue_id TEXT PRIMARY KEY, domain TEXT NOT NULL, issue_type TEXT NOT NULL, semester_id TEXT,
 entity_type TEXT, entity_id TEXT, affected_rows INTEGER NOT NULL DEFAULT 0, severity TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open', detail TEXT, recommendation TEXT, detected_at TEXT NOT NULL,
 source TEXT NOT NULL DEFAULT 'derived');"""

if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)
    rows = conn.execute("""SELECT semester_id,teacher_id,COUNT(*) n FROM fact_lesson
        GROUP BY semester_id,teacher_id HAVING COUNT(*)>?""", (CAP,)).fetchall()
    now = datetime.now().isoformat(timespec="seconds")
    for sem, teacher, count in rows:
        issue_id = f"operation:teacher_lesson_overflow:{sem}:{teacher}"
        conn.execute("""INSERT INTO data_quality_issue
            (issue_id,domain,issue_type,semester_id,entity_type,entity_id,affected_rows,severity,status,
             detail,recommendation,detected_at,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(issue_id) DO UPDATE SET affected_rows=excluded.affected_rows,
            detail=excluded.detail,recommendation=excluded.recommendation,detected_at=excluded.detected_at""",
            (issue_id,"operation","teacher_lesson_overflow",sem,"teacher",teacher,count,"high","open",
             f"单教师单学期关联 {count} 条教学班，超过质量阈值 {CAP}",
             "核对源系统教师工号映射和通识课拆班逻辑；确认前继续排除统计",now,"derived"))
    conn.commit()
    print("quality issues", conn.execute("SELECT COUNT(*) FROM data_quality_issue WHERE domain='operation'").fetchone()[0])
    conn.close()

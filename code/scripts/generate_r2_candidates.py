"""生成 R2/R2W 新口径候选结果，不覆盖现有预警和处理闭环。"""
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl.config import DB_PATH


DDL = """
CREATE TABLE IF NOT EXISTS alert_rule_candidate (
  batch_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  level TEXT NOT NULL,
  trigger_detail TEXT NOT NULL,
  old_r2_match INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  PRIMARY KEY (batch_id, student_id, rule_id)
);
CREATE INDEX IF NOT EXISTS idx_alert_candidate_batch
ON alert_rule_candidate(batch_id, rule_id);
"""


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(DDL)
    recent = {r[0] for r in conn.execute(
        "SELECT semester_id FROM dim_semester ORDER BY semester_id DESC LIMIT 2")}
    passed = set()
    recent_failed = set()
    for sid, cid, sem, is_pass in conn.execute(
        """SELECT student_id,course_id,semester_id,is_pass FROM fact_grade
           WHERE source='real' AND course_id IS NOT NULL"""
    ):
        pair = (sid, cid)
        if is_pass == 1:
            passed.add(pair)
        elif is_pass == 0 and sem in recent:
            recent_failed.add(pair)
    counts = {}
    for sid, cid in recent_failed - passed:
        counts[sid] = counts.get(sid, 0) + 1
    old = {r[0] for r in conn.execute(
        "SELECT DISTINCT student_id FROM fact_alert WHERE rule_id='R2'")}
    batch = datetime.now().strftime("r2v2_%Y%m%d_%H%M%S")
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for sid, count in counts.items():
        if count >= 3:
            rule_id, level = "R2", "严重"
        elif count == 2:
            rule_id, level = "R2W", "警告"
        else:
            continue
        rows.append((batch, sid, rule_id, level,
                     f"近2学期尚未通过课程 {count} 门（按不同课程去重）",
                     int(sid in old), created))
    conn.executemany("""INSERT INTO alert_rule_candidate
        (batch_id,student_id,rule_id,level,trigger_detail,old_r2_match,created_at)
        VALUES (?,?,?,?,?,?,?)""", rows)
    conn.commit()
    new_students = {r[1] for r in rows}
    print(f"候选批次 {batch}")
    print(f"R2W警告: {sum(1 for r in rows if r[2]=='R2W')}")
    print(f"R2严重: {sum(1 for r in rows if r[2]=='R2')}")
    print(f"旧R2仍命中: {len(old & new_students)}")
    print(f"旧R2不再命中: {len(old - new_students)}")
    print(f"新口径新增关注: {len(new_students - old)}")
    conn.close()


if __name__ == "__main__":
    main()

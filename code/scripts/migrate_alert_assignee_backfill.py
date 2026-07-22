"""M2幂等回填：存量 alert_assignee 按"学生→人员关系"重挂责任人。

对每条预警事件：
- 按学生关系重算责任人（辅导员=主责，班主任/导师=协同，
  回退学院秘书/保底辅导员，规则见 routers/alert_assignment.py）；
- 旧主责不在新主责集合中的硬编码分派记录保留备查：
  is_primary 置 0，assignment_reason 追加"（原硬编码分派）"，不物理删除；
- 新责任人 INSERT OR IGNORE（主责 is_primary=1，协同 is_primary=0）。

可重复执行：重算结果稳定、标记带重复检测、插入按主键去重。

运行（仓库根目录）：
    python -X utf8 code/scripts/migrate_alert_assignee_backfill.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.api import db as dbm
from backend.api.routers.alert_assignment import assignees_for_student
from backend.etl import config

LEGACY_MARK = "（原硬编码分派）"


def backfill(conn: sqlite3.Connection, v2_conn: sqlite3.Connection) -> dict:
    stats = {"events": 0, "primaryReassigned": 0, "legacyMarked": 0,
             "collaboratorsAdded": 0, "primariesAdded": 0}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    events = dbm.query(conn,
        "SELECT event_id, student_id FROM alert_event ORDER BY event_id")
    cache: dict[str, list[dict]] = {}
    for event in events:
        stats["events"] += 1
        sid = event["student_id"]
        if sid not in cache:
            cache[sid] = assignees_for_student(conn, sid, v2_conn)
        assignees = cache[sid]
        if not assignees:
            continue
        new_primary_usernames = {a["username"] for a in assignees
                                 if a["responsibility"] == "primary"}
        existing = {row["username"]: row for row in dbm.query(conn,
            "SELECT * FROM alert_assignee WHERE event_id=?",
            (event["event_id"],))}
        reassigned = False
        # 1) 旧主责已被关系匹配取代 → 降级并标记备查（不删除）
        for username, row in existing.items():
            if not row["is_primary"] or username in new_primary_usernames:
                continue
            reason = row["assignment_reason"] or ""
            if LEGACY_MARK not in reason:
                reason = f"{reason}{LEGACY_MARK}"
            dbm.execute(conn, """UPDATE alert_assignee
                SET is_primary=0, assignment_reason=?
                WHERE event_id=? AND username=?""",
                (reason, event["event_id"], username))
            stats["legacyMarked"] += 1
            reassigned = True
        # 2) 写入新责任人（已存在则仅修正 is_primary）
        for a in assignees:
            is_primary = 1 if a["responsibility"] == "primary" else 0
            row = existing.get(a["username"])
            if row is None:
                dbm.execute(conn, """INSERT INTO alert_assignee
                    (event_id,username,role_id,assignment_reason,assigned_at,is_primary)
                    VALUES (?,?,?,?,?,?)""",
                    (event["event_id"], a["username"], a["role_id"], a["reason"],
                     now, is_primary))
                stats["primariesAdded" if is_primary else "collaboratorsAdded"] += 1
                reassigned = reassigned or bool(is_primary)
            elif is_primary and not row["is_primary"]:
                dbm.execute(conn, """UPDATE alert_assignee SET is_primary=1
                    WHERE event_id=? AND username=?""",
                    (event["event_id"], a["username"]))
                reassigned = True
        if reassigned:
            stats["primaryReassigned"] += 1
    return stats


def main() -> None:
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    v2_conn = dbm.get_v2_conn()
    try:
        stats = backfill(conn, v2_conn)
        conn.commit()
    finally:
        v2_conn.close()
    rows = conn.execute("""SELECT is_primary, COUNT(*) FROM alert_assignee
        GROUP BY is_primary""").fetchall()
    print(f"存量分派回填完成：{stats}；当前分派记录分布 {dict(rows)}")
    conn.close()


if __name__ == "__main__":
    main()

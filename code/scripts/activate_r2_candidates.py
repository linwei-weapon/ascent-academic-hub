"""受控激活 R2/R2W 候选批次，保留既有预警事件及全部跟进历史。

默认仅预演；传入 --apply 后在单一事务中执行。脚本幂等：同一批次只允许成功激活一次。
"""
import argparse
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl.config import DB_PATH


DDL = """
CREATE TABLE IF NOT EXISTS alert_rule_activation (
  activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL UNIQUE,
  rule_version TEXT NOT NULL,
  status TEXT NOT NULL,
  retained_count INTEGER NOT NULL DEFAULT 0,
  transitioned_count INTEGER NOT NULL DEFAULT 0,
  closed_count INTEGER NOT NULL DEFAULT 0,
  created_count INTEGER NOT NULL DEFAULT 0,
  activated_at TEXT NOT NULL,
  operator TEXT NOT NULL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS alert_rule_activation_item (
  activation_id INTEGER NOT NULL,
  student_id TEXT NOT NULL,
  action TEXT NOT NULL,
  old_alert_id INTEGER,
  new_alert_id INTEGER,
  old_rule_id TEXT,
  new_rule_id TEXT,
  PRIMARY KEY (activation_id, student_id)
);
"""


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(fact_alert)")}
    additions = {
        "is_active": "INTEGER NOT NULL DEFAULT 1",
        "rule_version": "TEXT",
        "activation_batch_id": "TEXT",
        "closed_at": "TEXT",
        "close_reason": "TEXT",
    }
    for name, definition in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE fact_alert ADD COLUMN {name} {definition}")


def plan(conn: sqlite3.Connection, batch: str) -> dict:
    candidates = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        """SELECT student_id,rule_id,level,trigger_detail
           FROM alert_rule_candidate WHERE batch_id=?""", (batch,))}
    if not candidates:
        raise SystemExit(f"候选批次不存在或为空：{batch}")
    old = {r[1]: r for r in conn.execute(
        """SELECT alert_id,student_id,rule_id,level,trigger_detail,status
           FROM fact_alert WHERE rule_id='R2' AND COALESCE(is_active,1)=1""")}
    retained = sum(1 for sid in old if sid in candidates and candidates[sid][0] == "R2")
    transitioned = sum(1 for sid in old if sid in candidates and candidates[sid][0] == "R2W")
    closed = len(set(old) - set(candidates))
    created = len(set(candidates) - set(old))
    return {"candidates": candidates, "old": old, "retained": retained,
            "transitioned": transitioned, "closed": closed, "created": created}


def activate(conn: sqlite3.Connection, batch: str, operator: str, info: dict) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    version = "R2-v2.0"
    cur = conn.execute(
        """INSERT INTO alert_rule_activation
           (batch_id,rule_version,status,retained_count,transitioned_count,
            closed_count,created_count,activated_at,operator,note)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (batch, version, "activated", info["retained"], info["transitioned"],
         info["closed"], info["created"], now, operator,
         "2门警告、3门及以上严重；未解决课程按课程去重并排除后续已通过课程"))
    activation_id = cur.lastrowid
    candidates, old = info["candidates"], info["old"]

    for sid, row in old.items():
        alert_id, _, old_rule, _, _, old_status = row
        candidate = candidates.get(sid)
        if candidate:
            new_rule, level, detail = candidate
            action = "retain" if new_rule == old_rule else "transition"
            conn.execute(
                """UPDATE fact_alert SET rule_id=?,type=?,level=?,trigger_detail=?,
                   is_active=1,rule_version=?,activation_batch_id=?,closed_at=NULL,
                   close_reason=NULL WHERE alert_id=?""",
                (new_rule, "未解决挂科累积" if new_rule == "R2" else "未解决挂科关注",
                 level, detail, version, batch, alert_id))
            conn.execute(
                """UPDATE alert_event SET rule_id=?,last_detected_at=?,updated_at=?
                   WHERE alert_id=?""", (new_rule, now, now, alert_id))
            conn.execute(
                """INSERT INTO alert_rule_activation_item
                   VALUES (?,?,?,?,?,?,?)""",
                (activation_id, sid, action, alert_id, alert_id, old_rule, new_rule))
        else:
            conn.execute(
                """UPDATE fact_alert SET is_active=0,activation_batch_id=?,closed_at=?,
                   close_reason=? WHERE alert_id=?""",
                (batch, now, "R2-v2规则重新计算后不再命中", alert_id))
            event = conn.execute(
                "SELECT event_id,workflow_status FROM alert_event WHERE alert_id=?", (alert_id,)).fetchone()
            if event and event[1] != "resolved":
                conn.execute(
                    "UPDATE alert_event SET workflow_status='resolved',updated_at=? WHERE event_id=?",
                    (now, event[0]))
                conn.execute(
                    """INSERT INTO alert_status_history
                       (event_id,from_status,to_status,operator,reason,changed_at)
                       VALUES (?,?,'resolved',?,?,?)""",
                    (event[0], event[1], operator, "规则升级后不再命中，系统自动关闭", now))
            conn.execute("INSERT INTO alert_rule_activation_item VALUES (?,?,?,?,?,?,?)",
                         (activation_id, sid, "close", alert_id, None, old_rule, None))

    counselor = conn.execute(
        "SELECT username,role_id FROM sys_user WHERE role_id='counselor' AND status='active' LIMIT 1"
    ).fetchone()
    semester = conn.execute(
        "SELECT semester_id FROM dim_semester ORDER BY semester_id DESC LIMIT 1").fetchone()[0]
    for sid in sorted(set(candidates) - set(old)):
        rule_id, level, detail = candidates[sid]
        cur = conn.execute(
            """INSERT INTO fact_alert
               (student_id,rule_id,type,level,trigger_detail,status,created_at,
                semester_id,source,is_active,rule_version,activation_batch_id)
               VALUES (?,?,?,?,?,'待处理',?,?,'real',1,?,?)""",
            (sid, rule_id, "未解决挂科累积" if rule_id == "R2" else "未解决挂科关注",
             level, detail, now, semester, version, batch))
        alert_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO alert_event
               (alert_id,student_id,rule_id,workflow_status,first_detected_at,
                last_detected_at,updated_at,source) VALUES (?,?,?,'new',?,?,?,'engine')""",
            (alert_id, sid, rule_id, now, now, now))
        event_id = cur.lastrowid
        if counselor:
            conn.execute(
                """INSERT INTO alert_assignee
                   (event_id,username,role_id,assignment_reason,assigned_at,is_primary)
                   VALUES (?,?,?,?,?,1)""",
                (event_id, counselor[0], counselor[1], "R2-v2候选激活自动分派", now))
        conn.execute("INSERT INTO alert_rule_activation_item VALUES (?,?,?,?,?,?,?)",
                     (activation_id, sid, "create", None, alert_id, None, rule_id))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", help="候选批次；默认取最新批次")
    parser.add_argument("--apply", action="store_true", help="正式执行；默认仅预演")
    parser.add_argument("--operator", default="system:migration")
    args = parser.parse_args()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executescript(DDL)
        ensure_columns(conn)
        batch = args.batch or conn.execute(
            "SELECT MAX(batch_id) FROM alert_rule_candidate").fetchone()[0]
        if conn.execute("SELECT 1 FROM alert_rule_activation WHERE batch_id=?", (batch,)).fetchone():
            raise SystemExit(f"该批次已激活，拒绝重复执行：{batch}")
        info = plan(conn, batch)
        print(f"批次：{batch}")
        print(f"保留严重事件：{info['retained']}")
        print(f"原事件转为警告：{info['transitioned']}")
        print(f"不再命中并关闭：{info['closed']}")
        print(f"新增事件：{info['created']}")
        if args.apply:
            activate(conn, batch, args.operator, info)
            conn.commit()
            print("激活完成")
        else:
            conn.rollback()
            print("预演完成，数据库未变更；传入 --apply 后正式执行")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

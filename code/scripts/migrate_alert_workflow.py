"""幂等迁移：创建预警处理闭环表，并从 fact_alert 初始化事件。"""
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl.config import DB_PATH


DDL = """
CREATE TABLE IF NOT EXISTS alert_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER UNIQUE,
    student_id TEXT NOT NULL,
    rule_id TEXT,
    workflow_status TEXT NOT NULL DEFAULT 'new',
    first_detected_at TEXT,
    last_detected_at TEXT,
    updated_at TEXT,
    source TEXT NOT NULL DEFAULT 'engine'
);
CREATE TABLE IF NOT EXISTS alert_assignee (
    event_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    role_id TEXT,
    assignment_reason TEXT,
    assigned_at TEXT,
    is_primary INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (event_id, username)
);
CREATE TABLE IF NOT EXISTS alert_followup (
    followup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    operator TEXT NOT NULL,
    action_type TEXT NOT NULL,
    content TEXT NOT NULL,
    next_action_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_status_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    operator TEXT NOT NULL,
    reason TEXT,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_event_student ON alert_event(student_id);
CREATE INDEX IF NOT EXISTS idx_alert_event_status ON alert_event(workflow_status);
CREATE INDEX IF NOT EXISTS idx_alert_followup_event ON alert_followup(event_id, created_at);
"""

STATUS_MAP = {
    "待处理": "new",
    "未处理": "new",
    "已通知": "notified",
    "已约谈": "supporting",
    "已解决": "resolved",
}


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(DDL)
    alerts = conn.execute(
        """SELECT alert_id, student_id, rule_id, status, created_at
           FROM fact_alert ORDER BY alert_id"""
    ).fetchall()
    for alert_id, student_id, rule_id, old_status, created_at in alerts:
        status = STATUS_MAP.get(old_status, "new")
        conn.execute(
            """INSERT OR IGNORE INTO alert_event
               (alert_id,student_id,rule_id,workflow_status,first_detected_at,
                last_detected_at,updated_at,source)
               VALUES (?,?,?,?,?,?,?,?)""",
            (alert_id, student_id, rule_id, status, created_at, created_at,
             created_at, "engine"),
        )
    # 演示环境只有一个辅导员账号；初始化为主责任人，后续再按班级关系精细分派。
    counselor = conn.execute(
        "SELECT username,role_id FROM sys_user WHERE role_id='counselor' AND status='active' LIMIT 1"
    ).fetchone()
    if counselor:
        conn.execute(
            """INSERT OR IGNORE INTO alert_assignee
               (event_id,username,role_id,assignment_reason,assigned_at,is_primary)
               SELECT event_id,?,?,?,COALESCE(first_detected_at,datetime('now')),1
               FROM alert_event""",
            (counselor[0], counselor[1], "按辅导员角色初始化分派"),
        )
    conn.commit()
    events = conn.execute("SELECT COUNT(*) FROM alert_event").fetchone()[0]
    assignees = conn.execute("SELECT COUNT(*) FROM alert_assignee").fetchone()[0]
    print(f"预警闭环迁移完成：事件 {events}，责任人关系 {assignees}")
    conn.close()


if __name__ == "__main__":
    main()

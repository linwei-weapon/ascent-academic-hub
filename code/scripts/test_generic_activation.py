"""在指定数据库副本上验证通用规则变更激活闭环；禁止指向生产库。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.routers.settings import (
    RuleChangeCreateIn, RuleChangeReviewIn, activate_rule_change,
    create_rule_change, evaluate_rule_change, publish_rule_change,
    review_rule_change, submit_rule_change,
)
from backend.etl.config import DB_PATH


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_generic_activation.py <copied-db>")
    path = Path(sys.argv[1]).resolve()
    if path == Path(DB_PATH).resolve():
        raise SystemExit("拒绝在生产数据库执行专项激活测试")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    before = conn.execute("SELECT COUNT(*) FROM alert_followup").fetchone()[0]
    created = create_rule_change(
        "R1", RuleChangeCreateIn(values={"gpa_drop": 0.4}, reason="通用激活专项验证"),
        {"username": "admin", "role_id": "dean"}, conn)
    change_id = created["data"]["changeId"]
    impact = evaluate_rule_change(change_id, {"username": "admin", "role_id": "dean"}, conn)["data"]
    submit_rule_change(change_id, {"username": "admin", "role_id": "dean"}, conn)
    review_rule_change(
        change_id, RuleChangeReviewIn(action="approve", comment="副本专项验证"),
        {"username": "quality_office", "role_id": "quality_office"}, conn)
    publish_rule_change(change_id, {"username": "dean", "role_id": "dean"}, conn)
    activation = activate_rule_change(
        change_id, {"username": "school_leader", "role_id": "school_leader"}, conn)["data"]
    after = conn.execute("SELECT COUNT(*) FROM alert_followup").fetchone()[0]
    active = conn.execute("""SELECT COUNT(DISTINCT student_id) FROM fact_alert
        WHERE rule_id='R1' AND COALESCE(is_active,1)=1""").fetchone()[0]
    closed_history = conn.execute("""SELECT COUNT(*) FROM alert_status_history
        WHERE reason LIKE '规则变更单#%自动关闭'""").fetchone()[0]
    conn.commit()
    print({"impact": impact, "activation": activation, "activeR1": active,
           "followupsBefore": before, "followupsAfter": after,
           "autoCloseHistory": closed_history})
    conn.close()


if __name__ == "__main__":
    main()

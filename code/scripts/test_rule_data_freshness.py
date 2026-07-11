"""在数据库副本验证规则试算数据指纹及过期门禁。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.envelope import ApiError
from backend.api.routers.settings import (
    RuleChangeCreateIn, create_rule_change, evaluate_rule_change,
    submit_rule_change,
)
from backend.etl.config import DB_PATH


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_rule_data_freshness.py <copied-db>")
    path = Path(sys.argv[1]).resolve()
    if path == Path(DB_PATH).resolve():
        raise SystemExit("拒绝在生产数据库执行数据新鲜度测试")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    created = create_rule_change(
        "R1", RuleChangeCreateIn(values={"gpa_drop": 0.4}, reason="数据新鲜度专项验证"),
        {"username": "admin", "role_id": "dean"}, conn)
    change_id = created["data"]["changeId"]
    impact = evaluate_rule_change(change_id, {"username": "admin", "role_id": "dean"}, conn)["data"]
    # 模拟成绩源发生最小变化；事务最后回滚，不保留测试修改。
    row = conn.execute("SELECT rowid AS rid,score FROM fact_grade WHERE score IS NOT NULL LIMIT 1").fetchone()
    conn.execute("UPDATE fact_grade SET score=? WHERE rowid=?", (float(row["score"]) + 0.01, row["rid"]))
    blocked = False
    code = None
    try:
        submit_rule_change(change_id, {"username": "admin", "role_id": "dean"}, conn)
    except ApiError as exc:
        blocked = True
        code = exc.code
    conn.rollback()
    print({"fingerprint": impact["dataFingerprint"], "staleBlocked": blocked,
           "errorCode": code})
    if not blocked or code != 409:
        raise SystemExit("数据变化后未正确阻止旧试算提交")
    conn.close()


if __name__ == "__main__":
    main()

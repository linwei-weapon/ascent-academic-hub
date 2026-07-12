"""规则自发现方向、引擎特征契约与治理采纳的只读/内存回归。"""
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api.routers.settings import DiscoveredRuleAction, review_discovered
from backend.etl.alert_engine import _compute_features, _evaluate_generic_rules
from backend.etl.rule_discovery import _risk_ratio, discover


def test_direction() -> None:
    rows = [{"x": -0.6, "label": 1}, {"x": -0.2, "label": 0},
            {"x": 4, "label": 1}, {"x": 1, "label": 0}]
    assert _risk_ratio(rows[:2], "x", -0.5, "<=")[1:] == (1, 1)
    assert _risk_ratio(rows[2:], "x", 4, ">=")[1:] == (1, 1)


def test_feature_contract() -> None:
    supported = {"gpa_trend", "gpa_drop_count", "total_fail", "core_fail",
                 "credit_ratio", "freshman_fail", "repeat_fail", "consecutive_drop"}
    rules = discover()
    assert rules
    for rule in rules:
        assert all(c["key"] in supported for c in rule["conditions"])
        for condition in rule["conditions"]:
            if condition["key"] == "credit_ratio":
                assert condition["value"] > 1
                assert 0 <= condition["engineValue"] <= 1


def test_unknown_feature_fails_closed() -> None:
    grade = pd.DataFrame([
        {"student_id": "S1", "semester_id": "2024-1", "course_id": "C1",
         "gpa": 2.0, "is_pass": 1, "credits": 3, "source": "real"},
    ])
    students = pd.DataFrame([{"student_id": "S1", "major_id": "M1", "grade": "2024"}])
    features = _compute_features(grade, students, None)
    rules = {"DRX": {"trigger_type": "discovered", "enabled": 1,
                      "params": json.dumps({"unknown_feature": 1}),
                      "name": "未知特征", "level": "警告"}}
    result = _evaluate_generic_rules(rules, features, students, None, grade, {})
    assert result == []


def test_adoption_creates_draft() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE alert_event (event_id INTEGER PRIMARY KEY);
        CREATE TABLE sys_discovered_rule (
            id INTEGER PRIMARY KEY, semester_id TEXT, name TEXT, conditions TEXT,
            level TEXT, confidence REAL, risk_ratio REAL, sample_size INTEGER,
            detail_json TEXT, status TEXT, source TEXT, created_at TEXT, approved_at TEXT);
        CREATE TABLE sys_alert_rule (
            rule_id TEXT PRIMARY KEY,name TEXT,level TEXT,trigger_type TEXT,params TEXT,enabled INTEGER);
        INSERT INTO sys_discovered_rule VALUES
            (1,'2025-2026-2','GPA下降','[{"key":"gpa_trend","value":-0.5,"op":"≤"}]',
             '提醒',0.2,2.1,100,'{}','pending','ml','2026-01-01',NULL);
    """)
    response = review_discovered(
        1, DiscoveredRuleAction(action="approve"),
        {"username": "dean", "role_id": "dean"}, conn)
    assert response["data"]["changeId"]
    rule = conn.execute("SELECT enabled FROM sys_alert_rule WHERE rule_id='DR1'").fetchone()
    change = conn.execute("SELECT status,proposed_enabled FROM alert_rule_change").fetchone()
    status = conn.execute("SELECT status FROM sys_discovered_rule WHERE id=1").fetchone()[0]
    assert rule["enabled"] == 0
    assert (change["status"], change["proposed_enabled"]) == ("draft", 1)
    assert status == "adopted"


if __name__ == "__main__":
    test_direction()
    test_feature_contract()
    test_unknown_feature_fails_closed()
    test_adoption_creates_draft()
    print("rule discovery contract: PASS")

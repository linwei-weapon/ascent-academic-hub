import inspect
import sqlite3
import unittest

from backend.api.routers.ai import operation_schedule_changes_insight
from backend.api.routers.operation import (
    _nearest_rank,
    _teacher_anomaly_ids,
    schedule_changes,
    teacher_load,
)


class OperationIndicatorTrustTest(unittest.TestCase):
    def test_teacher_anomalies_merge_registered_and_heuristic_rules(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE data_quality_issue(
            entity_id TEXT,domain TEXT,issue_type TEXT,status TEXT,semester_id TEXT
        )""")
        conn.execute("""CREATE TABLE agg_teacher_load(
            teacher_id TEXT,semester_id TEXT,classes INTEGER,hours REAL,courses INTEGER
        )""")
        conn.execute(
            "INSERT INTO data_quality_issue VALUES(?,?,?,?,?)",
            ("T-REGISTERED", "operation", "teacher_lesson_overflow", "open", "2025-2026-2"),
        )
        conn.executemany(
            "INSERT INTO agg_teacher_load VALUES(?,?,?,?,?)",
            [
                ("T-NORMAL", "2025-2026-2", 4, 64, 2),
                ("T-CLASSES", "2025-2026-2", 201, 64, 2),
                ("T-HOURS", "2025-2026-2", 4, 1001, 2),
                ("T-COURSES", "2025-2026-2", 4, 64, 21),
            ],
        )
        ids = _teacher_anomaly_ids(conn, ["2025-2026-2"])
        conn.close()
        self.assertEqual(
            {"T-REGISTERED", "T-CLASSES", "T-HOURS", "T-COURSES"},
            ids,
        )

    def test_nearest_rank_percentiles_are_deterministic(self):
        self.assertEqual(3.0, _nearest_rank([1, 2, 3, 4, 5], .5))
        self.assertEqual(5.0, _nearest_rank([1, 2, 3, 4, 5], .9))
        self.assertEqual(0, _nearest_rank([], .9))

    def test_schedule_change_outputs_do_not_use_derived_workflow_fields(self):
        source = inspect.getsource(schedule_changes)
        ai_source = inspect.getsource(operation_schedule_changes_insight)
        for forbidden in ("AVG(auto_approved)", "AVG(review_days)", "院系自动审核"):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, ai_source)
        self.assertIn('"evidenceLevel": "actual_source_event"', source)

    def test_teacher_load_does_not_claim_compliance_or_overload(self):
        source = inspect.getsource(teacher_load)
        for forbidden in ("✓达标", "未达标(需", '"过载教师"'):
            self.assertNotIn(forbidden, source)
        self.assertIn("_teacher_anomaly_ids", source)
        self.assertIn('"configured": False', source)


if __name__ == "__main__":
    unittest.main()

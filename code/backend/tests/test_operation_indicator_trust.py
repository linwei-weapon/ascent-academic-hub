import inspect
import sqlite3
import unittest

from backend.api.routers.ai import operation_schedule_changes_insight
from backend.api.routers.operation import (
    _nearest_rank,
    _teacher_anomaly_ids,
    courses,
    schedule_changes,
    teacher_load,
)
from backend.api.envelope import ApiError


class OperationIndicatorTrustTest(unittest.TestCase):
    def build_course_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE dim_college(college_id TEXT,name TEXT)")
        conn.execute("""CREATE TABLE dim_course(
            course_id TEXT,name TEXT,dept TEXT,course_nature TEXT,category TEXT
        )""")
        conn.execute("""CREATE TABLE fact_lesson(
            lesson_id TEXT,semester_id TEXT,course_id TEXT,teacher_id TEXT,
            campus TEXT,enrolled INTEGER,class_names TEXT
        )""")
        conn.execute("CREATE TABLE dim_teacher(teacher_id TEXT,name TEXT,dept TEXT)")
        conn.execute("""CREATE TABLE data_quality_issue(
            issue_id TEXT,domain TEXT,issue_type TEXT,semester_id TEXT,
            entity_type TEXT,entity_id TEXT,affected_rows INTEGER,severity TEXT,
            status TEXT,detail TEXT,recommendation TEXT
        )""")
        conn.executemany("INSERT INTO dim_college VALUES(?,?)", [
            ("C01", "甲学院"), ("C02", "乙学院"),
        ])
        conn.executemany("INSERT INTO dim_course VALUES(?,?,?,?,?)", [
            ("A1", "甲课程一", "甲学院", "必修", "理论"),
            ("A2", "甲课程二", "甲学院", "必修", "理论"),
            ("B1", "乙课程一", "乙学院", "必修", "理论"),
        ])
        conn.executemany("INSERT INTO dim_teacher VALUES(?,?,?)", [
            ("BAD-A", "异常甲", "甲学院"),
            ("BAD-B", "异常乙", "乙学院"),
            ("GOOD-A", "正常甲", "甲学院"),
            ("GOOD-B", "正常乙", "乙学院"),
        ])
        conn.executemany("INSERT INTO fact_lesson VALUES(?,?,?,?,?,?,?)", [
            ("L1", "2025-2026-2", "A1", "BAD-A", "北校区", 100, "甲班"),
            ("L2", "2025-2026-2", "A1", "BAD-A", "南校区", 40, "乙班"),
            ("L3", "2025-2026-2", "A2", "GOOD-A", "北校区", 90, "丙班"),
            ("L4", "2025-2026-2", "B1", "BAD-B", "北校区", 90, "丁班"),
            ("L5", "2025-2026-2", "B1", "GOOD-B", "北校区", 20, "戊班"),
        ])
        conn.executemany("INSERT INTO data_quality_issue VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
            ("Q-A", "operation", "teacher_lesson_overflow", "2025-2026-2",
             "teacher", "BAD-A", 2, "high", "open", "异常甲说明", "复核甲"),
            ("Q-A-DUP", "operation", "teacher_lesson_overflow", "2025-2026-2",
             "teacher", "BAD-A", 2, "high", "reviewing", "异常甲重复", "复核甲"),
            ("Q-B", "operation", "teacher_lesson_overflow", "2025-2026-2",
             "teacher", "BAD-B", 1, "high", "reviewing", "异常乙说明", "复核乙"),
            ("Q-CLOSED", "operation", "teacher_lesson_overflow", "2025-2026-2",
             "teacher", "GOOD-A", 1, "high", "closed", "已关闭", "无需处理"),
        ])
        return conn

    def test_course_supply_filters_drive_every_result_and_quality_count(self):
        conn = self.build_course_conn()
        user = {"permission_context": {
            "authorized": True, "detailScope": {"type": "all"},
        }}
        payload = courses(
            college="C01", semester="2025-2026-2", campus="北校区",
            course_nature="必修", category="理论", size="大班(60-120)",
            user=user, conn=conn,
        )["data"]
        conn.close()

        self.assertEqual(1, payload["dataQuality"]["excludedTeachers"])
        self.assertEqual(1, payload["dataQuality"]["excludedLessons"])
        self.assertEqual(1, len(payload["qualityIssues"]))
        self.assertEqual("BAD-A", payload["qualityIssues"][0]["entity_id"])
        self.assertEqual(1, payload["qualityIssues"][0]["affected_rows"])
        self.assertEqual(1, payload["totalCourses"])
        self.assertEqual(["A2"], [row["course_id"] for row in payload["focusCourses"]])
        self.assertEqual(["甲学院"], [row["name"] for row in payload["deptCourses"]])
        self.assertEqual("C01", payload["filters"]["college"])

    def test_course_supply_rejects_explicit_college_outside_scope(self):
        conn = self.build_course_conn()
        user = {"permission_context": {
            "authorized": True,
            "detailScope": {"type": "college", "sourceScopeIds": ["C01"]},
        }}
        with self.assertRaises(ApiError) as raised:
            courses(
                college="C02", semester="2025-2026-2", user=user, conn=conn,
            )
        conn.close()
        self.assertEqual(403, raised.exception.status_code)

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

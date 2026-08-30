import inspect
import sqlite3
import unittest

from backend.api.routers.ai import (
    _teacher_scope_filter,
    operation_course_offering_insight,
    operation_schedule_changes_insight,
    operation_teacher_load_teacher_insight,
)
from backend.api.routers.operation import (
    _nearest_rank,
    _teacher_anomaly_ids,
    _teacher_anomaly_rows,
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
        kpis = {row["label"]: row for row in payload["kpis"]}
        self.assertNotIn("开课门数", kpis)
        self.assertNotIn("合班率", kpis)
        self.assertEqual(
            "教学任务中成功关联课程主数据的去重课程数",
            kpis["已关联课程"]["formula"],
        )
        self.assertEqual(
            "触发大班额、单班集中或单一教师多班覆盖提示的去重课程数",
            kpis["需关注课程"]["formula"],
        )

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

    def test_teacher_anomalies_use_only_heuristic_thresholds(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE data_quality_issue(
            entity_id TEXT,domain TEXT,issue_type TEXT,status TEXT,semester_id TEXT
        )""")
        conn.execute("""CREATE TABLE agg_teacher_load(
            teacher_id TEXT,semester_id TEXT,classes INTEGER,hours REAL,courses INTEGER
        )""")
        conn.execute("CREATE TABLE dim_teacher(teacher_id TEXT,name TEXT)")
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
        rows = _teacher_anomaly_rows(conn, ["2025-2026-2"])
        conn.close()
        self.assertEqual(
            {"T-CLASSES", "T-HOURS", "T-COURSES"},
            ids,
        )
        self.assertEqual(3, len(rows))
        self.assertEqual(3, len({row["entity_id"] for row in rows}))
        self.assertEqual(
            {"semester_id", "entity_id", "entity_name", "detail", "recommendation"},
            {"semester_id", "entity_id", "entity_name", "detail", "recommendation"}
            & set(rows[0]),
        )
        source = inspect.getsource(teacher_load)
        self.assertIn("scoped_anomaly_rows", source)
        self.assertIn('len(scoped_anomaly_rows)', source)
        self.assertIn('"qualityIssues": scoped_anomaly_rows', source)
        self.assertIn('"formula": "命中教学班>200、学时>1000、课程>20"', source)

    def test_nearest_rank_percentiles_are_deterministic(self):
        self.assertEqual(3.0, _nearest_rank([1, 2, 3, 4, 5], .5))
        self.assertEqual(5.0, _nearest_rank([1, 2, 3, 4, 5], .9))
        self.assertEqual(0, _nearest_rank([], .9))

    def test_teacher_ai_scope_preserves_denied_and_multi_college_ranges(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE dim_college(college_id TEXT,name TEXT)")
        conn.executemany("INSERT INTO dim_college VALUES(?,?)", [
            ("C01", "甲学院"), ("C02", "乙学院"), ("C03", "丙学院"),
        ])
        multi_user = {"permission_context": {
            "authorized": True,
            "detailScope": {"type": "college", "sourceScopeIds": ["C01", "C02"]},
        }}
        college_id, college_name, allowed = _teacher_scope_filter(None, multi_user, conn)
        self.assertIsNone(college_id)
        self.assertIsNone(college_name)
        self.assertEqual({"甲学院", "乙学院"}, allowed)
        with self.assertRaises(ApiError):
            _teacher_scope_filter("C03", multi_user, conn)

        denied_user = {"permission_context": {
            "authorized": True,
            "detailScope": {"type": "denied"},
        }}
        _, _, denied_allowed = _teacher_scope_filter(None, denied_user, conn)
        conn.close()
        self.assertEqual(set(), denied_allowed)
        source = inspect.getsource(operation_teacher_load_teacher_insight)
        self.assertIn("teacher_dept not in allowed_college_names", source)

    def test_schedule_change_outputs_do_not_use_derived_workflow_fields(self):
        source = inspect.getsource(schedule_changes)
        ai_source = inspect.getsource(operation_schedule_changes_insight)
        for forbidden in ("AVG(auto_approved)", "AVG(review_days)", "院系自动审核"):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, ai_source)
        self.assertIn('"evidenceLevel": "actual_source_event"', source)
        self.assertIn("COUNT(DISTINCT s.change_id)", source)

    def test_schedule_change_rejects_explicit_college_outside_scope(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE dim_college(college_id TEXT,name TEXT)")
        conn.executemany("INSERT INTO dim_college VALUES(?,?)", [
            ("C01", "甲学院"), ("C02", "乙学院"),
        ])
        user = {"permission_context": {
            "authorized": True,
            "detailScope": {"type": "college", "sourceScopeIds": ["C01"]},
        }}
        with self.assertRaises(ApiError) as raised:
            schedule_changes(
                college="C02", semester="2025-2026-2", user=user, conn=conn,
            )
        conn.close()
        self.assertEqual(403, raised.exception.status_code)

    def test_teacher_load_does_not_claim_compliance_or_overload(self):
        source = inspect.getsource(teacher_load)
        for forbidden in ("✓达标", "未达标(需", '"过载教师"'):
            self.assertNotIn(forbidden, source)
        self.assertIn("_teacher_anomaly_rows", source)
        self.assertIn('"configured": False', source)

    def test_course_offering_ai_falls_back_to_page_legacy_snapshot(self):
        v2_conn = sqlite3.connect(":memory:")
        v2_conn.row_factory = sqlite3.Row
        v2_conn.execute("""CREATE TABLE dim_course(
            course_id TEXT,name TEXT,category TEXT,nature TEXT,organization_id TEXT
        )""")
        v2_conn.execute("""CREATE TABLE agg_course_offering(
            semester_id TEXT,course_id TEXT,lesson_count INTEGER,
            teacher_count INTEGER,capacity INTEGER,enrolled INTEGER
        )""")
        v2_conn.execute("""CREATE TABLE teaching_lesson(
            lesson_id TEXT,semester_id TEXT,course_id TEXT,course_name TEXT,
            organization_id TEXT,capacity INTEGER,enrolled INTEGER
        )""")
        v2_conn.execute("CREATE TABLE lesson_teacher(lesson_id TEXT,staff_id TEXT)")
        v2_conn.execute("""CREATE TABLE course_meeting(
            meeting_id TEXT,lesson_id TEXT,weekday INTEGER,period_start INTEGER
        )""")
        v2_conn.execute("CREATE TABLE dim_staff(staff_id TEXT,display_name TEXT)")
        v2_conn.execute("""CREATE TABLE access_scope_mapping(
            role_id TEXT,scope_type TEXT,source_scope_id TEXT,
            organization_id TEXT,mapping_status TEXT
        )""")
        v2_conn.execute("""INSERT INTO access_scope_mapping VALUES(
            'college_dean','college','C02','ORG-2','mapped'
        )""")

        legacy_conn = sqlite3.connect(":memory:")
        legacy_conn.row_factory = sqlite3.Row
        legacy_conn.execute("CREATE TABLE dim_college(college_id TEXT,name TEXT)")
        legacy_conn.execute("""CREATE TABLE dim_course(
            course_id TEXT,name TEXT,dept TEXT,course_nature TEXT,category TEXT
        )""")
        legacy_conn.execute("""CREATE TABLE fact_lesson(
            lesson_id TEXT,semester_id TEXT,course_id TEXT,teacher_id TEXT,
            capacity INTEGER,enrolled INTEGER
        )""")
        legacy_conn.execute("CREATE TABLE dim_teacher(teacher_id TEXT,name TEXT,dept TEXT)")
        legacy_conn.execute("INSERT INTO dim_college VALUES('C01','甲学院')")
        legacy_conn.execute("INSERT INTO dim_course VALUES('LEGACY-1','同源课程','甲学院','必修','理论')")
        legacy_conn.execute("INSERT INTO dim_teacher VALUES('T01','甲教师','甲学院')")
        legacy_conn.executemany(
            "INSERT INTO fact_lesson VALUES(?,?,?,?,?,?)",
            [
                ("L1", "2025-2026-2", "LEGACY-1", "T01", 80, 70),
                ("L2", "2025-2026-2", "LEGACY-1", "T01", 80, 65),
            ],
        )
        user = {"permission_context": {
            "authorized": True, "detailScope": {"type": "all"},
        }}

        payload = operation_course_offering_insight(
            course_id="LEGACY-1", semester="2025-2026-2", user=user,
            conn=v2_conn, legacy_conn=legacy_conn,
        )["data"]

        self.assertEqual("LEGACY-1", payload["targetId"])
        self.assertEqual("同源课程", payload["targetName"])
        self.assertEqual("甲学院", payload["profile"]["college"])
        self.assertIn("2 个教学班", payload["summary"])
        self.assertEqual("甲教师", payload["evidence"][2]["detail"].split("：")[-1])
        self.assertIn("fact_lesson", payload["traceability"]["dataSources"])
        self.assertIn("没有结构化排课时段", payload["traceability"]["boundary"])

        scoped_user = {"permission_context": {
            "authorized": True,
            "activeRole": "college_dean",
            "detailScope": {"type": "college", "sourceScopeIds": ["C02"]},
        }}
        with self.assertRaises(ApiError):
            operation_course_offering_insight(
                course_id="LEGACY-1", semester="2025-2026-2", user=scoped_user,
                conn=v2_conn, legacy_conn=legacy_conn,
            )

        v2_conn.execute("INSERT INTO dim_course VALUES('V2-OTHER','他院课程','理论','必修','ORG-1')")
        v2_conn.execute("INSERT INTO agg_course_offering VALUES('2025-2026-2','V2-OTHER',1,1,60,55)")
        with self.assertRaises(ApiError):
            operation_course_offering_insight(
                course_id="V2-OTHER", semester="2025-2026-2", user=scoped_user,
                conn=v2_conn, legacy_conn=legacy_conn,
            )

        v2_conn.execute("INSERT INTO dim_course VALUES('V2-MIXED','跨院开课','理论','必修','ORG-2')")
        v2_conn.executemany(
            "INSERT INTO teaching_lesson VALUES(?,?,?,?,?,?,?)",
            [
                ("V2-L1", "2025-2026-2", "V2-MIXED", "跨院开课", "ORG-2", 60, 30),
                ("V2-L2", "2025-2026-2", "V2-MIXED", "跨院开课", "ORG-1", 220, 200),
            ],
        )
        v2_conn.executemany(
            "INSERT INTO lesson_teacher VALUES(?,?)",
            [("V2-L1", "T-AUTH"), ("V2-L2", "T-OTHER")],
        )
        mixed = operation_course_offering_insight(
            course_id="V2-MIXED", semester="2025-2026-2", user=scoped_user,
            conn=v2_conn, legacy_conn=legacy_conn,
        )["data"]
        self.assertIn("1 个教学班、1 名教师、30 人次选课", mixed["summary"])
        self.assertNotIn("230 人次选课", mixed["summary"])
        v2_conn.close()
        legacy_conn.close()


if __name__ == "__main__":
    unittest.main()

"""学业预警监控V2契约：学生口径、双状态、分页与数据范围。"""
import sqlite3
import unittest

from backend.api.envelope import ApiError
from backend.api.routers.ai import alert_summary as ai_alert_summary
from backend.api.routers.alert_monitor import (
    alert_distribution,
    alert_filter_options,
    alert_priority,
    alert_students,
    alert_summary,
    alert_time_distribution,
    export_alert_students,
)


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_student(
            student_id TEXT PRIMARY KEY,name TEXT,college_id TEXT,major_id TEXT,
            class_id TEXT,grade TEXT,status TEXT,source TEXT);
        CREATE TABLE dim_college(college_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE dim_major(major_id TEXT PRIMARY KEY,college_id TEXT,name TEXT);
        CREATE TABLE dim_class(class_id TEXT PRIMARY KEY,major_id TEXT,name TEXT);
        CREATE TABLE fact_alert(
            alert_id INTEGER PRIMARY KEY,student_id TEXT,rule_id TEXT,type TEXT,
            level TEXT,trigger_detail TEXT,status TEXT,created_at TEXT,
            semester_id TEXT,source TEXT,is_active INTEGER,rule_version TEXT,
            activation_batch_id TEXT,closed_at TEXT,close_reason TEXT);
        CREATE TABLE alert_event(
            event_id INTEGER PRIMARY KEY,alert_id INTEGER,student_id TEXT,
            rule_id TEXT,workflow_status TEXT,first_detected_at TEXT,
            last_detected_at TEXT,updated_at TEXT,source TEXT);
        CREATE TABLE alert_assignee(
            event_id INTEGER,username TEXT,role_id TEXT,assignment_reason TEXT,
            assigned_at TEXT,is_primary INTEGER);

        INSERT INTO dim_college VALUES ('C01','一院'),('C02','二院');
        INSERT INTO dim_major VALUES ('M01','C01','甲专业'),('M02','C02','乙专业');
        INSERT INTO dim_class VALUES ('B01','M01','甲班'),('B02','M02','乙班');
        INSERT INTO dim_student VALUES
            ('S01','学生1','C01','M01','B01','2023','在籍','real'),
            ('S02','学生2','C01','M01','B01','2023','在籍','real'),
            ('S03','学生3','C01','M01','B01','2023','在籍','real'),
            ('S04','学生4','C01','M01','B01','2023','在籍','real'),
            ('S05','学生5','C01','M01','B01','2023','在籍','real'),
            ('S06','学生6','C02','M02','B02','2022','在籍','real');

        INSERT INTO fact_alert VALUES
            (1,'S01','R1','GPA持续下降','严重','GPA下降0.8','待处理',
             '2026-07-01','2025-2026-2','real',1,'R1-v1',NULL,NULL,NULL),
            (2,'S01','R4','核心课风险','警告','核心课未通过','已解决',
             '2026-06-01','2025-2026-2','real',1,'R4-v1',NULL,NULL,NULL),
            (3,'S02','R2','挂科累积','严重','未通过3门','帮扶中',
             '2026-07-02','2025-2026-2','real',1,'R2-v2','batch-a',NULL,NULL),
            (4,'S03','R3','学分缺口','警告','缺口12学分','已解决',
             '2026-07-03','2025-2026-2','real',1,'R3-v1',NULL,NULL,NULL),
            (5,'S04','R4','核心课风险','提醒','核心课未通过','已关闭',
             '2026-07-04','2025-2026-2','real',1,'R4-v1',NULL,NULL,NULL),
            (6,'S06','R6','退学风险','严重','组合风险','待处理',
             '2026-07-05','2025-2026-2','real',1,'R6-v1',NULL,NULL,NULL);
        INSERT INTO alert_event VALUES
            (11,1,'S01','R1','new','2026-07-01','2026-07-01','2026-07-01','engine'),
            (12,2,'S01','R4','resolved','2026-06-01','2026-06-01','2026-07-02','engine'),
            (13,3,'S02','R2','supporting','2026-07-02','2026-07-02','2026-07-03','engine'),
            (14,4,'S03','R3','resolved','2026-07-03','2026-07-03','2026-07-04','engine'),
            (15,5,'S04','R4','closed','2026-07-04','2026-07-04','2026-07-05','engine'),
            (16,6,'S06','R6','new','2026-07-05','2026-07-05','2026-07-05','engine');
        INSERT INTO alert_assignee VALUES
            (11,'counselor_a','counselor','班级匹配','2026-07-01',1),
            (13,'counselor_a','counselor','班级匹配','2026-07-02',1);
    """)
    return conn


def user(role: str, scope_type: str, ids=None, username=None) -> dict:
    return {
        "username": username or role,
        "role_id": role,
        "permission_context": {
            "authorized": True,
            "activeRole": role,
            "detailScope": {
                "type": scope_type,
                "sourceScopeIds": ids or [],
            },
            "scopeFingerprint": f"test:{role}",
        },
    }


class AlertMonitorTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.dean = user("dean", "all")

    def tearDown(self):
        self.conn.close()

    def test_summary_uses_distinct_students_and_two_state_axes(self):
        data = alert_summary(user=self.dean, conn=self.conn)["data"]
        summary = data["summary"]
        self.assertEqual(5, summary["current_students"])
        self.assertEqual(6, summary["current_alert_records"])
        self.assertEqual(3, summary["critical_students"])
        self.assertEqual(2, summary["critical_pending_students"])
        self.assertEqual(2, summary["pending_students"])
        self.assertEqual(1, summary["in_review_students"])
        self.assertEqual(1, summary["recorded_students"])
        self.assertEqual(1, summary["closed_students"])
        self.assertEqual(6, summary["eligible_students"])
        self.assertEqual(83.3, summary["alert_student_rate"])
        self.assertFalse(data["meta"]["historyComparison"]["available"])

    def test_summary_denominator_follows_organization_and_grade_filters(self):
        college = alert_summary(
            college="C01", user=self.dean, conn=self.conn,
        )["data"]["summary"]
        self.assertEqual(4, college["current_students"])
        self.assertEqual(5, college["eligible_students"])
        self.assertEqual(80.0, college["alert_student_rate"])

        grade = alert_summary(
            grade="2022", user=self.dean, conn=self.conn,
        )["data"]["summary"]
        self.assertEqual(1, grade["current_students"])
        self.assertEqual(1, grade["eligible_students"])
        self.assertEqual(100.0, grade["alert_student_rate"])

    def test_student_rows_group_multiple_alerts(self):
        data = alert_students(
            page=1, page_size=10, user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual(5, data["pagination"]["total"])
        s01 = next(row for row in data["items"] if row["studentId"] == "S01")
        self.assertEqual(2, s01["alertCount"])
        self.assertEqual("严重", s01["highestLevel"])
        self.assertEqual("pending_review", s01["managementState"])
        self.assertEqual("仍有待核查", s01["managementLabel"])
        self.assertEqual(2, len(s01["signals"]))
        for field in (
            "highestLevel", "primaryType", "alertCount",
            "managementState", "latestAt", "signals",
        ):
            self.assertIn(field, s01)

    def test_management_filter_is_student_level(self):
        data = alert_students(
            page=1, page_size=10, management="recorded",
            user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual(["S03"], [row["studentId"] for row in data["items"]])

    def test_highest_level_filter_is_student_level(self):
        critical = alert_students(
            page=1, page_size=10, highest_level="严重",
            user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual(3, critical["pagination"]["total"])
        self.assertEqual({"S01", "S02", "S06"}, {
            row["studentId"] for row in critical["items"]
        })

        critical_pending = alert_students(
            page=1, page_size=10, highest_level="严重",
            management="pending_review", user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual(2, critical_pending["pagination"]["total"])

    def test_class_scope_and_inbox_are_enforced(self):
        counselor = user(
            "counselor", "class", ["B01"], username="counselor_a",
        )
        summary = alert_summary(user=counselor, conn=self.conn)["data"]["summary"]
        self.assertEqual(4, summary["current_students"])
        self.assertEqual(5, summary["eligible_students"])
        self.assertEqual(2, summary["inbox_students"])
        rows = alert_students(
            page=1, page_size=10, user=counselor, conn=self.conn,
        )["data"]["items"]
        self.assertEqual({"B01"}, {row["classId"] for row in rows})
        self.assertNotIn("S06", {row["studentId"] for row in rows})
        inbox = alert_students(
            page=1, page_size=10, assigned_to_me=True,
            user=counselor, conn=self.conn,
        )["data"]
        self.assertEqual({"S01", "S02"}, {
            row["studentId"] for row in inbox["items"]
        })

    def test_explicit_scope_probe_is_rejected(self):
        college = user("college_dean", "college", ["C01"])
        with self.assertRaises(ApiError) as ctx:
            alert_summary(college="C02", user=college, conn=self.conn)
        self.assertEqual(403, ctx.exception.status_code)

    def test_page_size_has_upper_bound(self):
        with self.assertRaises(ApiError) as ctx:
            alert_students(
                page=1, page_size=100, user=self.dean, conn=self.conn,
            )
        self.assertEqual(400, ctx.exception.status_code)

    def test_distribution_uses_rate_and_role_dimension(self):
        school = alert_distribution(
            user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual("college", school["dimension"])
        c01 = next(row for row in school["items"] if row["id"] == "C01")
        self.assertEqual(5, c01["eligibleStudents"])
        self.assertEqual(4, c01["alertStudents"])
        self.assertEqual(80.0, c01["alertStudentRate"])

        college = user("college_dean", "college", ["C01"])
        scoped = alert_distribution(
            user=college, conn=self.conn,
        )["data"]
        self.assertEqual("major", scoped["dimension"])
        self.assertEqual({"M01"}, {row["id"] for row in scoped["items"]})
        own_college = alert_distribution(
            dimension="college", college="C01", user=college, conn=self.conn,
        )["data"]
        self.assertEqual({"C01"}, {row["id"] for row in own_college["items"]})

    def test_time_distribution_discloses_snapshot_boundary(self):
        data = alert_time_distribution(
            user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual("snapshot_first_detected_month", data["mode"])
        self.assertFalse(data["comparison"]["available"])
        self.assertIn("不是各月历史新增趋势", data["definition"]["boundary"])
        self.assertEqual("2026-07-05", data["latestGeneratedDate"])

    def test_time_distribution_returns_latest_ten_data_months(self):
        for index in range(11):
            month = index + 1
            alert_id = 100 + index
            self.conn.execute(
                """INSERT INTO fact_alert VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    alert_id, "S05", f"RX{index}", "测试预警", "提醒",
                    "测试证据", "待处理", f"2025-{month:02d}-01",
                    "2025-2026-2", "real", 1, "test-v1", None, None, None,
                ),
            )
        data = alert_time_distribution(
            user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual(10, len(data["items"]))
        self.assertEqual("2025-04", data["items"][0]["month"])
        self.assertEqual("2026-07", data["items"][-1]["month"])
        self.assertEqual("2026-07-05", data["latestGeneratedDate"])

    def test_options_are_scoped_without_full_record_download(self):
        college = user("college_dean", "college", ["C01"])
        data = alert_filter_options(user=college, conn=self.conn)["data"]
        self.assertEqual("major", data["defaultDimension"])
        self.assertEqual({"C01"}, {
            row["value"] for row in data["organizations"]["college"]
        })
        self.assertEqual({"M01"}, {
            row["value"] for row in data["organizations"]["major"]
        })
        self.assertEqual({"2023"}, {
            row["value"] for row in data["organizations"]["grade"]
        })

        major_data = alert_filter_options(
            major="M01", user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual({"B01"}, {
            row["value"] for row in major_data["organizations"]["class"]
        })
        self.assertNotIn("退学风险", {
            row["value"] for row in major_data["types"]
        })

        grade_data = alert_filter_options(
            major="M01", grade="2023", user=self.dean, conn=self.conn,
        )["data"]
        self.assertEqual({"B01"}, {
            row["value"] for row in grade_data["organizations"]["class"]
        })

    def test_organization_options_include_authorized_groups_without_alerts(self):
        self.conn.execute("INSERT INTO dim_college VALUES ('C03','三院')")
        self.conn.execute("INSERT INTO dim_major VALUES ('M03','C03','丙专业')")
        self.conn.execute("INSERT INTO dim_class VALUES ('B03','M03','丙班')")
        self.conn.execute(
            "INSERT INTO dim_student VALUES (?,?,?,?,?,?,?,?)",
            ("S07", "学生7", "C03", "M03", "B03", "2024", "在籍", "real"),
        )
        data = alert_filter_options(user=self.dean, conn=self.conn)["data"]
        self.assertIn("C03", {
            row["value"] for row in data["organizations"]["college"]
        })
        self.assertIn("M03", {
            row["value"] for row in data["organizations"]["major"]
        })
        self.assertIn("B03", {
            row["value"] for row in data["organizations"]["class"]
        })

    def test_options_for_counselor_stay_inside_managed_student_scope(self):
        counselor = user(
            "counselor", "class", ["B01"], username="counselor_a",
        )
        data = alert_filter_options(user=counselor, conn=self.conn)["data"]
        organizations = data["organizations"]
        self.assertEqual({"C01"}, {
            row["value"] for row in organizations["college"]
        })
        self.assertEqual({"M01"}, {
            row["value"] for row in organizations["major"]
        })
        self.assertEqual({"B01"}, {
            row["value"] for row in organizations["class"]
        })

    def test_priority_queue_is_student_level_and_explainable(self):
        data = alert_priority(limit=3, user=self.dean, conn=self.conn)["data"]
        self.assertEqual("alert-priority-v2.0", data["definition"]["version"])
        self.assertEqual(3, len(data["items"]))
        first = data["items"][0]
        self.assertEqual("S01", first["studentId"])
        self.assertGreater(first["priorityScore"], data["items"][1]["priorityScore"])
        self.assertIn("2条当前规则同时命中", first["priorityReasons"])
        self.assertEqual(
            first["priorityScore"],
            sum(first["scoreBreakdown"].values()),
        )
        self.assertIn("不是学生评价", data["definition"]["boundary"])

    def test_csv_export_reuses_scope_and_current_filters(self):
        college = user("college_dean", "college", ["C01"])
        response = export_alert_students(
            management="pending_review", user=college, conn=self.conn,
        )
        content = response.body.decode("utf-8-sig")
        self.assertEqual("1", response.headers["x-export-count"])
        self.assertIn("S01", content)
        self.assertNotIn("S06", content)
        self.assertIn("核查状态", content)

        card_response = export_alert_students(
            highest_level="严重", management="pending_review",
            user=self.dean, conn=self.conn,
        )
        card_content = card_response.body.decode("utf-8-sig")
        self.assertEqual("2", card_response.headers["x-export-count"])
        self.assertIn("S01", card_content)
        self.assertIn("S06", card_content)
        self.assertNotIn("S02", card_content)

    def test_ai_group_insight_reuses_student_definition_and_trace(self):
        data = ai_alert_summary(user=self.dean, conn=self.conn)["data"]
        self.assertEqual("5 人", data["evidence"][0]["value"])
        self.assertEqual("3 人", data["evidence"][1]["value"])
        self.assertEqual("2 人", data["evidence"][2]["value"])
        self.assertEqual(
            len(data["focusItems"]),
            len({item["student_id"] for item in data["focusItems"]}),
        )
        trace = data["traceability"]
        self.assertEqual("alert-monitor-v2.0 / alert-priority-v2.0",
                         trace["ruleVersion"])
        self.assertIn("fact_alert", trace["businessDataSources"])
        self.assertIn("不是风险概率", trace["boundary"])


if __name__ == "__main__":
    unittest.main()

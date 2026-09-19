import sqlite3
import unittest

from backend.api.routers.faculty import (
    _faculty_analysis,
    _matches_structure_review,
    _priority_classification,
    management_course,
    management_kpi_details,
    management_overview,
    management_teacher,
)


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_college(
            college_id TEXT PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE dim_teacher(
            teacher_id TEXT PRIMARY KEY,
            name TEXT,
            dept TEXT,
            title TEXT,
            source TEXT DEFAULT 'real'
        );
        CREATE TABLE dim_staff_employment_snapshot(
            semester_id TEXT NOT NULL,
            staff_id TEXT NOT NULL,
            college_id TEXT,
            dept TEXT,
            staff_category TEXT,
            employment_status TEXT NOT NULL,
            title TEXT,
            age_band TEXT,
            is_under_35 INTEGER,
            source TEXT NOT NULL DEFAULT 'real',
            source_batch_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(semester_id,staff_id)
        );
        CREATE TABLE dim_course(
            course_id TEXT PRIMARY KEY,
            name TEXT,
            credits REAL,
            category TEXT,
            course_nature TEXT,
            is_required INTEGER,
            dept TEXT,
            source TEXT DEFAULT 'real'
        );
        CREATE TABLE fact_lesson(
            lesson_id TEXT,
            semester_id TEXT,
            course_id TEXT,
            teacher_id TEXT,
            teacher_ids TEXT,
            capacity INTEGER,
            enrolled INTEGER,
            total_hours REAL,
            class_names TEXT,
            PRIMARY KEY(lesson_id,semester_id)
        );
        CREATE TABLE data_quality_issue(
            issue_id TEXT PRIMARY KEY,
            domain TEXT,
            issue_type TEXT,
            semester_id TEXT,
            entity_type TEXT,
            entity_id TEXT,
            affected_rows INTEGER,
            severity TEXT,
            status TEXT,
            detail TEXT,
            recommendation TEXT,
            detected_at TEXT,
            source TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO dim_college(college_id,name) VALUES(?,?)",
        [("C1", "学院A"), ("C2", "学院B")],
    )
    conn.executemany(
        "INSERT INTO dim_teacher(teacher_id,name,dept,title) VALUES(?,?,?,?)",
        [
            ("T1", "教师1", "学院A", "讲师"),
            ("T2", "教师2", "学院A", "讲师"),
            ("TB", "外院教师", "学院B", "副教授"),
            ("TA", "异常教师", "学院A", "教授"),
        ],
    )
    conn.executemany(
        """INSERT INTO dim_staff_employment_snapshot(
            semester_id,staff_id,college_id,dept,staff_category,employment_status,
            title,age_band,is_under_35,source,source_batch_id,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            ("2025-2026-2", "T1", "C1", "学院A", "专任教师", "在岗",
             "讲师", "35岁以下", 1, "real", "B1", "2026-02-01"),
            ("2025-2026-2", "T2", "C1", "学院A", "专任教师", "在岗",
             "讲师", "35-44岁", 0, "real", "B1", "2026-02-01"),
            ("2025-2026-2", "TB", "C2", "学院B", "专任教师", "在岗",
             "副教授", "45-54岁", 0, "real", "B1", "2026-02-01"),
            ("2025-2026-2", "T3", "C2", "学院B", "行政人员", "在岗",
             None, "35-44岁", 0, "real", "B1", "2026-02-01"),
            ("2025-2026-2", "TA", "C1", "学院A", "专任教师", "在岗",
             "教授", "55岁及以上", 0, "real", "B1", "2026-02-01"),
        ],
    )
    conn.executemany(
        """INSERT INTO dim_course(
            course_id,name,category,course_nature,is_required,dept
        ) VALUES(?,?,?,?,?,?)""",
        [
            ("C_NORMAL", "普通必修课", "专业课", "必修", 1, "学院A"),
            ("C_PRIORITY", "重点必修课", "专业课", "必修", 1, "学院A"),
            ("C_ANOM", "异常任务课程", "专业课", "必修", 1, "学院A"),
            ("C_CROSS", "跨单位承担课程", "专业课", "必修", 1, "学院A"),
            ("C_TEAM", "团队结构课程", "专业课", "必修", 1, "学院A"),
        ],
    )

    def add_lessons(course_id, semester, teacher_id, count, enrolled,
                    teacher_ids=""):
        for index in range(count):
            conn.execute(
                """INSERT INTO fact_lesson(
                    lesson_id,semester_id,course_id,teacher_id,teacher_ids,
                    capacity,enrolled,total_hours,class_names
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    f"{course_id}-{semester}-{teacher_id}-{index}", semester, course_id,
                    teacher_id, teacher_ids, enrolled + 5, enrolled, 32,
                    f"{course_id}-{index + 1}班",
                ),
            )

    add_lessons("C_NORMAL", "2025-2026-2", "T1", 1, 20)
    for semester in ("2024-2025-2", "2025-2026-1", "2025-2026-2"):
        # 最近3次中允许1次联合授课；同一教师至少2次唯一授课即可命中。
        teacher_ids = "T1;T2" if semester == "2024-2025-2" else ""
        add_lessons("C_PRIORITY", semester, "T1", 4, 30, teacher_ids)
    add_lessons("C_ANOM", "2025-2026-2", "TA", 4, 40)
    add_lessons("C_CROSS", "2025-2026-2", "TB", 4, 30)
    add_lessons("C_TEAM", "2025-2026-2", "T1", 2, 30, "T1;T2")
    add_lessons("C_TEAM", "2025-2026-2", "T2", 2, 30, "T1;T2")
    conn.execute(
        """INSERT INTO data_quality_issue(
            issue_id,domain,issue_type,semester_id,entity_type,entity_id,
            affected_rows,severity,status,detail,recommendation,detected_at,source
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "I1", "operation", "teacher_lesson_overflow", "2025-2026-2",
            "teacher", "TA", 4, "high", "open", "异常任务",
            "确认前继续排除", "2026-07-24", "derived",
        ),
    )
    conn.commit()
    return conn


def college_user(college_id: str) -> dict:
    return {
        "role_id": "college_dean",
        "permission_context": {
            "authorized": True,
            "detailScope": {
                "type": "college",
                "sourceScopeIds": [college_id],
            },
        },
    }


def school_user() -> dict:
    return {
        "role_id": "dean",
        "permission_context": {
            "authorized": True,
            "detailScope": {"type": "all", "sourceScopeIds": []},
        },
    }


class FacultyAssuranceRuleTest(unittest.TestCase):
    def test_single_teacher_fact_does_not_alone_trigger_review(self):
        row = {
            "important_course": True,
            "lesson_count": 1,
            "enrolled": 20,
            "teacher_count": 1,
            "continuous_single": False,
            "high_concentration": False,
            "data_candidate": False,
            "title_completeness_rate": 100,
            "senior_title_teachers": 0,
        }
        review_type, reasons, _ = _priority_classification(row)
        self.assertEqual("general_observation", review_type)
        self.assertEqual([], reasons)

    def test_data_candidate_precedes_business_risk(self):
        row = {
            "important_course": True,
            "lesson_count": 10,
            "enrolled": 300,
            "teacher_count": 1,
            "continuous_single": True,
            "continuity_observations": 3,
            "high_concentration": True,
            "max_lesson_share": 100,
            "max_enrolled_share": 100,
            "data_candidate": True,
            "data_candidate_reasons": ["4条异常任务被排除"],
            "title_completeness_rate": 100,
            "senior_title_teachers": 1,
        }
        review_type, reasons, _ = _priority_classification(row)
        self.assertEqual("data_candidate", review_type)
        self.assertIn("4条异常任务被排除", reasons)

    def test_structure_rule_can_overlap_priority_classification(self):
        row = {
            "evaluable": True,
            "important_course": True,
            "lesson_count": 8,
            "enrolled": 240,
            "teacher_count": 2,
            "continuous_single": False,
            "high_concentration": True,
            "max_lesson_share": 90,
            "max_enrolled_share": 92,
            "data_candidate": False,
            "title_completeness_rate": 100,
            "senior_title_teachers": 0,
            "junior_title_only": True,
        }
        review_type, _, _ = _priority_classification(row)
        self.assertEqual("priority_review", review_type)
        self.assertTrue(_matches_structure_review(row))


class FacultyAssuranceIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def tearDown(self):
        self.conn.close()

    def test_anomaly_gate_continuity_and_course_responsibility(self):
        analysis = _faculty_analysis(self.conn, "2025-2026-2")
        courses = {row["course_id"]: row for row in analysis["courses"]}

        self.assertEqual("structure_review", courses["C_NORMAL"]["review_type"])
        self.assertTrue(courses["C_NORMAL"]["junior_title_only"])
        self.assertEqual("priority_review", courses["C_PRIORITY"]["review_type"])
        self.assertTrue(courses["C_PRIORITY"]["continuous_single"])
        self.assertEqual("data_candidate", courses["C_ANOM"]["review_type"])
        self.assertFalse(courses["C_ANOM"]["evaluable"])
        self.assertEqual(4, analysis["quality_gate"]["excluded_lesson_count"])
        # 责任学院按课程所属组织，而不是外院教师的人事归属。
        self.assertEqual("学院A", courses["C_CROSS"]["college_name"])

    def test_college_can_review_external_teacher_for_its_own_course(self):
        user = college_user("C1")
        detail = management_course(
            "C_CROSS", semester="2025-2026-2", user=user, conn=self.conn,
        )["data"]
        self.assertEqual("TB", detail["members"][0]["staff_id"])

        teacher = management_teacher(
            "TB", semester="2025-2026-2", course_id="C_CROSS",
            user=user, conn=self.conn,
        )["data"]
        self.assertEqual("外院教师", teacher["name"])
        self.assertNotIn("scoreTrend", teacher)
        self.assertNotIn("education", teacher)
        self.assertTrue(all("passRate" not in row for row in teacher["teachingHistory"]))
        self.assertEqual({"C_CROSS"}, {row["id"] for row in teacher["currentCourses"]})
        self.assertEqual({"C_CROSS"}, {row["courseId"] for row in teacher["teachingHistory"]})

    def test_other_college_cannot_open_course_team(self):
        with self.assertRaises(Exception) as caught:
            management_course(
                "C_CROSS", semester="2025-2026-2",
                user=college_user("C2"), conn=self.conn,
            )
        self.assertEqual(403, getattr(caught.exception, "status_code", None))

    def test_management_overview_exposes_five_drillable_kpis(self):
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
        )["data"]
        kpis = {item["key"]: item for item in payload["kpis"]}

        self.assertEqual(
            {
                "teaching_staff_coverage",
                "team_structure_exception",
                "continuous_single_teacher",
                "senior_title_teaching_rate",
                "young_teacher_teaching_rate",
            },
            set(kpis),
        )
        self.assertEqual("3 / 5 人", kpis["teaching_staff_coverage"]["value"])
        self.assertEqual(
            "1.授课教师总数：与当前学期 教学任务 里涉及的所有教师去重数\n"
            "2.教职工总数：当前学期 在职的教师数",
            kpis["teaching_staff_coverage"]["hint"],
        )
        self.assertEqual(4, kpis["team_structure_exception"]["numerator"])
        self.assertEqual("教师结构异常课程数", kpis["team_structure_exception"]["label"])
        self.assertEqual("", kpis["team_structure_exception"]["sub"])
        self.assertIn("职称仅包含助教或讲师", kpis["team_structure_exception"]["hint"])
        self.assertEqual(1, kpis["continuous_single_teacher"]["numerator"])
        self.assertEqual(
            "1. 同一教师在最近3次实际开课至少2次作为唯一授课教师（同一门课程），"
            "按教师工号去重（最近3次是实际开课记录，不是连续自然学期）",
            kpis["continuous_single_teacher"]["hint"],
        )
        self.assertEqual("33.3%", kpis["senior_title_teaching_rate"]["value"])
        self.assertEqual(
            "高职称教师授课占比=教授或副教授实际授课教师去重人数÷授课教师总数×100%",
            kpis["senior_title_teaching_rate"]["hint"],
        )
        self.assertEqual(3, kpis["senior_title_teaching_rate"]["denominator"])
        self.assertEqual("33.3%", kpis["young_teacher_teaching_rate"]["value"])
        self.assertEqual(
            "青年教师授课占比=35岁以下青年教师授课去重人数÷授课教师总数×100%",
            kpis["young_teacher_teaching_rate"]["hint"],
        )
        self.assertEqual(3, kpis["young_teacher_teaching_rate"]["denominator"])
        self.assertTrue(all(item["hint"] and item["drilldown"] for item in kpis.values()))

    def test_college_course_total_is_evaluable_plus_data_candidates(self):
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
        )["data"]
        college = next(item for item in payload["colleges"] if item["college_id"] == "C1")

        self.assertEqual(
            college["evaluable_courses"] + college["data_candidate_courses"],
            college["course_total"],
        )

    def test_kpi_details_reuse_course_and_teacher_evidence(self):
        structure = management_kpi_details(
            "team_structure_exception", semester="2025-2026-2",
            user=school_user(), conn=self.conn,
        )["data"]
        self.assertEqual(4, structure["total"])
        self.assertIn("C_TEAM", {item["course_id"] for item in structure["items"]})

        continuous = management_kpi_details(
            "continuous_single_teacher", semester="2025-2026-2",
            user=school_user(), conn=self.conn,
        )["data"]
        self.assertEqual(1, continuous["summary"]["teacher_count"])
        self.assertEqual("T1", continuous["items"][0]["staff_id"])
        self.assertEqual("C_PRIORITY", continuous["items"][0]["course_id"])

        senior = management_kpi_details(
            "senior_title_teaching_rate", semester="2025-2026-2",
            user=school_user(), conn=self.conn,
        )["data"]
        self.assertEqual("TB", senior["items"][0]["staff_id"])
        self.assertEqual("副教授", senior["items"][0]["title"])
        self.assertGreater(senior["items"][0]["lesson_count"], 0)
        self.assertTrue(senior["breakdown"])

        young = management_kpi_details(
            "young_teacher_teaching_rate", semester="2025-2026-2",
            user=school_user(), conn=self.conn,
        )["data"]
        self.assertEqual("T1", young["items"][0]["staff_id"])
        self.assertEqual("35岁以下", young["items"][0]["age_band"])

    def test_personnel_metrics_disclose_missing_real_snapshot(self):
        self.conn.execute("DROP TABLE dim_staff_employment_snapshot")
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
        )["data"]
        kpis = {item["key"]: item for item in payload["kpis"]}
        self.assertEqual("partial", kpis["teaching_staff_coverage"]["status"])
        self.assertIn("—", kpis["teaching_staff_coverage"]["value"])
        self.assertEqual("", kpis["teaching_staff_coverage"]["sub"])
        self.assertEqual("unavailable", kpis["young_teacher_teaching_rate"]["status"])
        self.assertEqual("—", kpis["young_teacher_teaching_rate"]["value"])
        self.assertEqual(
            "青年教师数/授课教师总数",
            kpis["young_teacher_teaching_rate"]["sub"],
        )

    def test_personnel_snapshot_requires_trace_fields(self):
        self.conn.execute(
            "UPDATE dim_staff_employment_snapshot SET source_batch_id='' WHERE staff_id='T1'"
        )
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
        )["data"]
        kpis = {item["key"]: item for item in payload["kpis"]}
        self.assertEqual("partial", kpis["teaching_staff_coverage"]["status"])
        self.assertIn("缺少来源批次或更新时间", kpis["teaching_staff_coverage"]["sub"])

    def test_kpi_details_reject_other_college_scope(self):
        with self.assertRaises(Exception) as caught:
            management_kpi_details(
                "teaching_staff_coverage", college="C2", semester="2025-2026-2",
                user=college_user("C1"), conn=self.conn,
            )
        self.assertEqual(403, getattr(caught.exception, "status_code", None))


if __name__ == "__main__":
    unittest.main()

import sqlite3
import unittest

from backend.api.routers.faculty import (
    _faculty_analysis,
    _priority_classification,
    management_course,
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
        add_lessons("C_PRIORITY", semester, "T1", 4, 30)
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


class FacultyAssuranceIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def tearDown(self):
        self.conn.close()

    def test_anomaly_gate_continuity_and_course_responsibility(self):
        analysis = _faculty_analysis(self.conn, "2025-2026-2")
        courses = {row["course_id"]: row for row in analysis["courses"]}

        self.assertEqual("general_observation", courses["C_NORMAL"]["review_type"])
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

    def test_other_college_cannot_open_course_team(self):
        with self.assertRaises(Exception) as caught:
            management_course(
                "C_CROSS", semester="2025-2026-2",
                user=college_user("C2"), conn=self.conn,
            )
        self.assertEqual(403, getattr(caught.exception, "status_code", None))


if __name__ == "__main__":
    unittest.main()

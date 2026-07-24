import sqlite3
import unittest

from backend.api.student_growth import (
    build_growth_snapshot,
    filter_growth_rows,
)
from scripts.migrate_student_growth_indexes import rebuild_growth_aggregates


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_student(
            student_id TEXT PRIMARY KEY,name TEXT,college_id TEXT,
            major_id TEXT,class_id TEXT,grade TEXT,status TEXT);
        CREATE TABLE dim_college(college_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE dim_major(major_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE dim_class(class_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE dim_course(course_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE fact_grade(
            grade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,course_id TEXT,semester_id TEXT,
            score REAL,gpa REAL,is_pass INTEGER,credits REAL,source TEXT);
        CREATE TABLE alert_event(
            event_id TEXT,student_id TEXT,workflow_status TEXT);

        INSERT INTO dim_college VALUES('C1','工学院'),('C2','理学院');
        INSERT INTO dim_major VALUES('M1','工程专业'),('M2','数学专业');
        INSERT INTO dim_class VALUES('B1','工程一班'),('B2','数学一班');
        INSERT INTO dim_course VALUES
            ('K1','课程一'),('K2','课程二'),('K3','课程三'),
            ('K4','课程四'),('K5','课程五'),('K6','课程六');
        INSERT INTO dim_student VALUES
            ('S1','改善学生','C1','M1','B1','2023','在籍'),
            ('S2','持续学生','C1','M1','B1','2024','在籍'),
            ('S3','首次学生','C2','M2','B2','2025','在籍');

        INSERT INTO fact_grade(
            student_id,course_id,semester_id,score,gpa,is_pass,credits,source
        ) VALUES
            ('S1','K1','2024-2025-1',50,0,0,2,'real'),
            ('S1','K2','2024-2025-1',60,2,1,2,'real'),
            ('S1','K1','2024-2025-2',80,3,1,2,'real'),
            ('S1','K2','2024-2025-2',80,3,1,2,'real'),

            ('S2','K3','2024-2025-1',50,0,0,2,'real'),
            ('S2','K4','2024-2025-1',90,4,1,2,'real'),
            ('S2','K3','2024-2025-2',45,0,0,2,'real'),
            ('S2','K4','2024-2025-2',70,2,1,2,'real'),

            ('S3','K5','2024-2025-2',40,0,0,2,'real'),
            ('S3','K6','2024-2025-2',80,3,1,2,'real');
        INSERT INTO alert_event VALUES('E1','S2','assigned');
    """)
    rebuild_growth_aggregates(conn)
    return conn


ALL_USER = {
    "username": "dean",
    "role_id": "dean",
    "permission_context": {
        "authorized": True,
        "detailScope": {"type": "all", "sourceScopeIds": []},
    },
}


class StudentGrowthTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def tearDown(self):
        self.conn.close()

    def test_metrics_groups_and_transparent_priority_are_consistent(self):
        snapshot = build_growth_snapshot(
            self.conn, ALL_USER,
            from_semester="2024-2025-1",
            to_semester="2024-2025-2",
        )
        metrics = {item["key"]: item for item in snapshot["metrics"]}
        groups = {item["key"]: item for item in snapshot["groups"]}

        self.assertEqual(2, metrics["comparable"]["count"])
        self.assertEqual(1, metrics["improved"]["count"])
        self.assertEqual(1, metrics["declined"]["count"])
        self.assertEqual(1, metrics["continuous"]["count"])
        self.assertEqual(1, metrics["first_setback"]["count"])
        self.assertEqual(1, groups["repeated_unresolved"]["count"])
        self.assertEqual("student-growth-v1", snapshot["rule"]["version"])

        focus = filter_growth_rows(snapshot)
        self.assertEqual(["S2", "S3"], [row["sid"] for row in focus])
        self.assertEqual(1, focus[0]["priority"])
        self.assertEqual(
            ["明确恶化", "连续受挫", "重复未解决"],
            focus[0]["triggers"],
        )
        self.assertEqual(["课程三"], focus[0]["repeatedCourses"])
        self.assertEqual(1, focus[0]["openAlerts"])

    def test_organization_and_explicit_scope_do_not_expand_data(self):
        snapshot = build_growth_snapshot(
            self.conn, ALL_USER,
            from_semester="2024-2025-1",
            to_semester="2024-2025-2",
        )
        self.assertEqual("学院", snapshot["organizationLabel"])
        self.assertEqual(
            {"工学院", "理学院"},
            {row["organizationName"] for row in snapshot["organizations"]},
        )
        college = build_growth_snapshot(
            self.conn, ALL_USER,
            from_semester="2024-2025-1",
            to_semester="2024-2025-2",
            college="C1",
        )
        self.assertEqual(
            {"S1", "S2"},
            {row["sid"] for row in college["rows"]},
        )
        self.assertEqual(
            ["S2"],
            [row["sid"] for row in filter_growth_rows(
                snapshot, organization_id="C1")],
        )


if __name__ == "__main__":
    unittest.main()

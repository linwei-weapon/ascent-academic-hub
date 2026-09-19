import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.api.student_growth import (
    build_growth_snapshot,
    filter_growth_rows,
)
from backend.api.historical_roster import clear_roster_cache
from backend.api.envelope import ApiError
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
            ('S3','首次学生','C2','M2','B2','2025','在籍'),
            ('S4','非参与学期学生','C1','M1','B1','2022','在籍');

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


def write_roster(path: Path, students: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("""
            CREATE TABLE students(
                student_id TEXT,college TEXT,major TEXT,grade_year TEXT,
                class_name TEXT,status TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO students VALUES(?,?,?,?,?,?)",
            students,
        )
        conn.commit()
    finally:
        conn.close()


ALL_USER = {
    "username": "dean",
    "role_id": "dean",
    "permission_context": {
        "authorized": True,
        "detailScope": {"type": "all", "sourceScopeIds": []},
    },
}

COLLEGE_USER = {
    "username": "college",
    "role_id": "college",
    "permission_context": {
        "authorized": True,
        "detailScope": {"type": "college", "sourceScopeIds": ["C1"]},
    },
}


class StudentGrowthTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.roster_dir = Path(self.temp_dir.name)
        write_roster(self.roster_dir / "2024-2025-1.db", [
            ("S1", "工学院", "工程专业", "2023", "工程一班", "在校"),
            ("S2", "工学院", "工程专业", "2024", "工程一班", "在校"),
        ])
        write_roster(self.roster_dir / "2024-2025-2.db", [
            ("S1", "工学院", "工程专业", "2023", "工程一班", "在校"),
            ("S2", "工学院", "工程专业", "2024", "工程一班", "在校"),
            ("S3", "理学院", "数学专业", "2025", "数学一班", "在校"),
        ])
        clear_roster_cache()

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()
        clear_roster_cache()

    def test_metrics_groups_and_transparent_priority_are_consistent(self):
        snapshot = build_growth_snapshot(
            self.conn, ALL_USER,
            from_semester="2024-2025-1",
            to_semester="2024-2025-2",
            roster_dir=self.roster_dir,
        )
        metrics = {item["key"]: item for item in snapshot["metrics"]}
        groups = {item["key"]: item for item in snapshot["groups"]}

        self.assertEqual(2, metrics["comparable"]["count"])
        self.assertEqual(3, metrics["comparable"]["denominator"])
        self.assertEqual(66.7, metrics["comparable"]["rate"])
        self.assertEqual({
            "title": "可比较学生情况看板",
            "fromSemester": "2024-2025-1",
            "toSemester": "2024-2025-2",
            "comparableCount": 2,
            "studentCount": 3,
            "rate": 66.7,
        }, snapshot["comparisonBoard"])
        self.assertEqual(1, metrics["improved"]["count"])
        self.assertEqual(1, metrics["declined"]["count"])
        self.assertEqual(1, metrics["continuous"]["count"])
        self.assertEqual(1, metrics["first_setback"]["count"])
        self.assertEqual(2, metrics["first_setback"]["denominator"])
        self.assertEqual(50.0, metrics["first_setback"]["rate"])
        self.assertEqual(1, metrics["repeated_unresolved"]["count"])
        self.assertEqual(2, metrics["repeated_unresolved"]["denominator"])
        self.assertEqual(50.0, metrics["repeated_unresolved"]["rate"])
        self.assertEqual(
            "同一课程至少两次未通过且最新有效结果仍未通过",
            metrics["repeated_unresolved"]["meaning"],
        )
        self.assertEqual(
            [
                "comparable", "improved", "declined", "continuous",
                "first_setback", "repeated_unresolved",
            ],
            [item["key"] for item in snapshot["metrics"]],
        )
        self.assertEqual(1, groups["repeated_unresolved"]["count"])
        self.assertEqual("student-growth-v2", snapshot["rule"]["version"])
        self.assertEqual(
            {"S1", "S2"},
            {row["sid"] for row in filter_growth_rows(
                snapshot, group="comparable"
            )},
        )

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
            roster_dir=self.roster_dir,
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
            roster_dir=self.roster_dir,
        )
        self.assertEqual("专业", college["organizationLabel"])
        self.assertEqual(
            [("M1", "工程专业")],
            [
                (row["organizationId"], row["organizationName"])
                for row in college["organizations"]
            ],
        )
        self.assertEqual(
            {"S1", "S2"},
            {row["sid"] for row in college["rows"]},
        )
        major = build_growth_snapshot(
            self.conn,
            ALL_USER,
            from_semester="2024-2025-1",
            to_semester="2024-2025-2",
            college="C1",
            major="M1",
            roster_dir=self.roster_dir,
        )
        self.assertEqual("行政班", major["organizationLabel"])
        self.assertEqual(
            [("B1", "工程一班")],
            [
                (row["organizationId"], row["organizationName"])
                for row in major["organizations"]
            ],
        )
        class_scope = build_growth_snapshot(
            self.conn,
            ALL_USER,
            from_semester="2024-2025-1",
            to_semester="2024-2025-2",
            college="C1",
            major="M1",
            class_id="B1",
            roster_dir=self.roster_dir,
        )
        self.assertEqual("行政班", class_scope["organizationLabel"])
        self.assertEqual(
            [("B1", "工程一班")],
            [
                (row["organizationId"], row["organizationName"])
                for row in class_scope["organizations"]
            ],
        )
        self.assertEqual(
            ["S2"],
            [row["sid"] for row in filter_growth_rows(
                snapshot, organization_id="C1")],
        )

    def test_class_rows_recalculate_every_metric_for_each_class(self):
        self.conn.execute("INSERT INTO dim_class VALUES('B3','工程二班')")
        self.conn.execute(
            "INSERT INTO dim_student VALUES(?,?,?,?,?,?,?)",
            ("S5", "新增受挫学生", "C1", "M1", "B3", "2024", "在籍"),
        )
        self.conn.executemany(
            """INSERT INTO fact_grade(
                   student_id,course_id,semester_id,score,gpa,is_pass,credits,source
               ) VALUES(?,?,?,?,?,?,?,?)""",
            [
                ("S5", "K5", "2024-2025-1", 80, 3, 1, 2, "real"),
                ("S5", "K5", "2024-2025-2", 45, 0, 0, 2, "real"),
            ],
        )
        self.conn.commit()
        rebuild_growth_aggregates(self.conn)
        for semester in ("2024-2025-1", "2024-2025-2"):
            roster_conn = sqlite3.connect(self.roster_dir / f"{semester}.db")
            try:
                roster_conn.execute(
                    "INSERT INTO students VALUES(?,?,?,?,?,?)",
                    ("S5", "工学院", "工程专业", "2024", "工程二班", "在校"),
                )
                roster_conn.commit()
            finally:
                roster_conn.close()
        clear_roster_cache()

        snapshot = build_growth_snapshot(
            self.conn,
            ALL_USER,
            from_semester="2024-2025-1",
            to_semester="2024-2025-2",
            college="C1",
            major="M1",
            roster_dir=self.roster_dir,
        )
        rows = {row["organizationId"]: row for row in snapshot["organizations"]}

        self.assertEqual("行政班", snapshot["organizationLabel"])
        self.assertEqual({"B1", "B3"}, set(rows))
        self.assertEqual("工程一班", rows["B1"]["organizationName"])
        self.assertEqual("工程二班", rows["B3"]["organizationName"])
        self.assertEqual(
            {
                "studentCount": 2,
                "comparableCount": 2,
                "gradeEvidenceComparableCount": 2,
                "coverageRate": 100.0,
                "declinedCount": 1,
                "declinedRate": 50.0,
                "continuousCount": 1,
                "firstSetbackCount": 0,
                "repeatedUnresolvedCount": 1,
                "openAlertCount": 1,
            },
            {key: rows["B1"][key] for key in (
                "studentCount", "comparableCount",
                "gradeEvidenceComparableCount", "coverageRate",
                "declinedCount", "declinedRate", "continuousCount",
                "firstSetbackCount",
                "repeatedUnresolvedCount", "openAlertCount",
            )},
        )
        self.assertEqual(
            {
                "studentCount": 1,
                "comparableCount": 1,
                "gradeEvidenceComparableCount": 1,
                "coverageRate": 100.0,
                "declinedCount": 1,
                "declinedRate": 100.0,
                "continuousCount": 0,
                "firstSetbackCount": 1,
                "repeatedUnresolvedCount": 0,
                "openAlertCount": 0,
            },
            {key: rows["B3"][key] for key in (
                "studentCount", "comparableCount",
                "gradeEvidenceComparableCount", "coverageRate",
                "declinedCount", "declinedRate", "continuousCount",
                "firstSetbackCount",
                "repeatedUnresolvedCount", "openAlertCount",
            )},
        )

    def test_roster_requirement_and_identity_scope_are_enforced(self):
        college = build_growth_snapshot(
            self.conn,
            COLLEGE_USER,
            from_semester="2024-2025-1",
            to_semester="2024-2025-2",
            roster_dir=self.roster_dir,
        )
        self.assertEqual({"S1", "S2"}, {row["sid"] for row in college["rows"]})
        self.assertEqual(2, college["comparisonBoard"]["studentCount"])
        self.assertEqual(2, college["comparisonBoard"]["comparableCount"])

        missing_roster_dir = self.roster_dir / "missing"
        missing_roster_dir.mkdir()
        with self.assertRaises(ApiError) as caught:
            build_growth_snapshot(
                self.conn,
                ALL_USER,
                from_semester="2024-2025-1",
                to_semester="2024-2025-2",
                roster_dir=missing_roster_dir,
            )
        self.assertEqual(422, caught.exception.status_code)
        self.assertIn("在籍学生名单不可用", caught.exception.msg)


if __name__ == "__main__":
    unittest.main()

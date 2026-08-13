import sqlite3
import unittest

from backend.api.envelope import ApiError
from backend.api.routers.meta import college_comparison


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_semester(semester_id TEXT);
        CREATE TABLE dim_college(college_id TEXT,name TEXT);
        CREATE TABLE dim_student(
          student_id TEXT,college_id TEXT,major_id TEXT,class_id TEXT,grade INTEGER
        );
        CREATE TABLE fact_grade(
          student_id TEXT,semester_id TEXT,score REAL,credits REAL,gpa REAL,
          is_pass INTEGER,source TEXT
        );
        CREATE TABLE fact_alert(student_id TEXT,is_active INTEGER);
        INSERT INTO dim_semester VALUES('2025-2026-2');
        INSERT INTO dim_college VALUES('C01','甲学院'),('C02','乙学院');
    """)
    for college in ("C01", "C02"):
        for index in range(12):
            student = f"{college}-{index:02d}"
            conn.execute(
                "INSERT INTO dim_student VALUES(?,?,NULL,NULL,2022)",
                (student, college),
            )
            conn.execute(
                "INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?)",
                (student, "2025-2026-2", 80 + index % 3, 2, 3.0, index != 0, "real"),
            )
        conn.execute(
            "INSERT INTO fact_alert VALUES(?,1)", (f"{college}-00",),
        )
    return conn


class ComparisonScopeTest(unittest.TestCase):
    def test_college_can_compare_but_only_drill_into_own_college(self):
        conn = make_conn()
        user = {"permission_context": {
            "detailScope": {"type": "college", "sourceScopeIds": ["C01"]},
            "comparisonScope": {
                "allowOtherOrganizations": True, "minimumGroupSize": 10,
            },
        }}
        data = college_comparison("2025-2026-2", user, conn)["data"]
        rows = {row["collegeId"]: row for row in data["items"]}
        self.assertTrue(rows["C01"]["canDrillDown"])
        self.assertIsNotNone(rows["C01"]["detailRoute"])
        self.assertFalse(rows["C02"]["canDrillDown"])
        self.assertIsNone(rows["C02"]["detailRoute"])
        self.assertNotIn("studentId", rows["C02"])
        conn.close()

    def test_class_identity_cannot_use_college_comparison(self):
        conn = make_conn()
        user = {"permission_context": {
            "detailScope": {"type": "class", "sourceScopeIds": ["B01"]},
            "comparisonScope": {"allowOtherOrganizations": False},
        }}
        with self.assertRaises(ApiError):
            college_comparison("2025-2026-2", user, conn)
        conn.close()


if __name__ == "__main__":
    unittest.main()

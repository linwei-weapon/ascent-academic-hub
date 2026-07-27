# -*- coding: utf-8 -*-
"""教学数据总览历史指标、只读源学籍和权限契约测试。"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api.historical_roster import (
    clear_roster_cache,
    read_historical_roster,
)
from backend.api.routers.dashboard import (
    _METRIC_HISTORY_CACHE,
    metric_history,
)
from backend.api.envelope import ApiError


ALL_USER = {
    "username": "dean",
    "role_id": "academic",
    "permission_context": {
        "authorized": True,
        "activeIdentityId": "academic",
        "scopeFingerprint": "all-scope",
        "detailScope": {"type": "all", "sourceScopeIds": []},
    },
}

COLLEGE_USER = {
    "username": "college",
    "role_id": "college_dean",
    "permission_context": {
        "authorized": True,
        "activeIdentityId": "college",
        "scopeFingerprint": "college-c1",
        "detailScope": {"type": "college", "sourceScopeIds": ["C1"]},
    },
}


def make_analytics_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_semester(semester_id TEXT, year TEXT);
        CREATE TABLE dim_college(college_id TEXT, name TEXT);
        CREATE TABLE dim_major(major_id TEXT, name TEXT, college_id TEXT);
        CREATE TABLE dim_student(
          student_id TEXT,name TEXT,college_id TEXT,major_id TEXT,
          class_id TEXT,grade TEXT,status TEXT
        );
        CREATE TABLE fact_grade(
          student_id TEXT,course_id TEXT,semester_id TEXT,source TEXT,
          score REAL,gpa REAL,credits REAL,is_pass INTEGER
        );
        CREATE TABLE fact_alert(
          student_id TEXT,semester_id TEXT,is_active INTEGER
        );
        INSERT INTO dim_semester VALUES
          ('2025-2026-1','2025-2026'),('2025-2026-2','2025-2026');
        INSERT INTO dim_college VALUES('C1','甲学院'),('C2','乙学院');
        INSERT INTO dim_major VALUES
          ('M1','甲专业','C1'),('M2','乙专业','C2');
        INSERT INTO dim_student VALUES
          ('S1','学生1','C1','M1','B1','2022','在校'),
          ('S2','学生2','C1','M1','B1','2022','在校'),
          ('S3','学生3','C2','M2','B2','2022','在校');
        INSERT INTO fact_grade VALUES
          ('S1','K1','2025-2026-1','real',80,3.0,2,1),
          ('S1','K2','2025-2026-1','real',60,1.0,4,1),
          ('S3','K1','2025-2026-1','real',50,0.0,2,0);
        INSERT INTO fact_alert VALUES('S1','2025-2026-2',1);
    """)
    return conn


def make_source(path: Path, semester: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE students(
          student_id TEXT,college TEXT,major TEXT,grade_year INTEGER,
          class_name TEXT,status TEXT
        );
        INSERT INTO students VALUES
          ('S1','甲学院','甲专业',2022,'甲22-1','在校'),
          ('S2','甲学院','甲专业',2022,'甲22-1','在校'),
          ('S3','乙学院','乙专业',2022,'乙22-1','在校');
    """)
    conn.commit()
    conn.close()


class DashboardHistoryContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for semester in ("2025-2026-1", "2025-2026-2"):
            make_source(self.root / f"{semester}.db", semester)
        self.conn = make_analytics_conn()
        clear_roster_cache()
        _METRIC_HISTORY_CACHE.clear()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_roster_is_read_only_and_intersects_authorization(self):
        source = self.root / "2025-2026-1.db"
        before_mtime = source.stat().st_mtime_ns
        before_schema = self._schema(source)
        result = read_historical_roster(
            self.conn,
            "2025-2026-1",
            scope_type="college",
            scope_id="C1",
            authorized_student_ids=["S1"],
            scope_fingerprint="only-s1",
            ts_dir=self.root,
        )
        self.assertTrue(result["available"])
        self.assertEqual(["S1"], result["studentIds"])
        self.assertEqual(1, result["mapping"]["excludedByAuthorization"])
        self.assertEqual(before_mtime, source.stat().st_mtime_ns)
        self.assertEqual(before_schema, self._schema(source))

    def test_history_uses_source_roster_denominator_and_weighted_gpa(self):
        with patch("backend.api.historical_roster.TS_DIR", self.root):
            coverage = metric_history(
                metric_id="valid_result_coverage_rate",
                scope_type="college",
                scope_id="C1",
                start_semester="2025-2026-1",
                end_semester="2025-2026-1",
                conn=self.conn,
                user=ALL_USER,
            )["data"]["periods"][0]
            average_gpa = metric_history(
                metric_id="average_student_gpa",
                scope_type="college",
                scope_id="C1",
                start_semester="2025-2026-1",
                end_semester="2025-2026-1",
                conn=self.conn,
                user=ALL_USER,
            )["data"]["periods"][0]
        self.assertEqual(1, coverage["numerator"])
        self.assertEqual(2, coverage["denominator"])
        self.assertEqual(50.0, coverage["value"])
        self.assertEqual(1.67, average_gpa["value"])
        self.assertEqual(1, average_gpa["sampleCount"])

    def test_current_period_uses_dashboard_roster_denominator(self):
        source = self.root / "2025-2026-2.db"
        source_conn = sqlite3.connect(source)
        source_conn.execute(
            """INSERT INTO students VALUES
               ('S4','甲学院','甲专业',2022,'甲22-1','在校')"""
        )
        source_conn.commit()
        source_conn.close()
        with patch("backend.api.historical_roster.TS_DIR", self.root):
            period = metric_history(
                metric_id="valid_result_coverage_rate",
                scope_type="school",
                scope_id=None,
                start_semester="2025-2026-2",
                end_semester="2025-2026-2",
                conn=self.conn,
                user=ALL_USER,
            )["data"]["periods"][0]
        self.assertEqual(3, period["denominator"])
        self.assertIn("dim_student", period["rosterSource"])
        self.assertTrue(period["mapping"]["currentCardAligned"])

    def test_history_periods_and_labels_use_standard_descending_semesters(self):
        with patch("backend.api.historical_roster.TS_DIR", self.root):
            data = metric_history(
                metric_id="valid_result_coverage_rate",
                scope_type="school",
                scope_id=None,
                start_semester="2025-2026-1",
                end_semester="2025-2026-2",
                conn=self.conn,
                user=ALL_USER,
            )["data"]
        self.assertEqual(
            ["2025-2026-2", "2025-2026-1"],
            [period["semester"] for period in data["periods"]],
        )
        self.assertEqual(
            ["2025-2026-2", "2025-2026-1"],
            [period["semesterLabel"] for period in data["periods"]],
        )
        self.assertEqual(
            sorted(data["availableSemesters"], reverse=True),
            data["availableSemesters"],
        )

    def test_missing_alert_history_is_unavailable_not_zero(self):
        with patch("backend.api.historical_roster.TS_DIR", self.root):
            period = metric_history(
                metric_id="active_alert_student_rate",
                scope_type="school",
                scope_id=None,
                start_semester="2025-2026-1",
                end_semester="2025-2026-1",
                conn=self.conn,
                user=ALL_USER,
            )["data"]["periods"][0]
        self.assertIsNone(period["value"])
        self.assertEqual("unavailable", period["status"])
        self.assertIn("不按当前规则回算", period["unavailableReason"])

    def test_college_scope_cannot_open_other_college(self):
        with self.assertRaises(ApiError) as caught:
            metric_history(
                metric_id="current_fail_student_rate",
                scope_type="college",
                scope_id="C2",
                start_semester="2025-2026-1",
                end_semester="2025-2026-1",
                conn=self.conn,
                user=COLLEGE_USER,
            )
        self.assertEqual(403, caught.exception.status_code)

    @staticmethod
    def _schema(path: Path) -> list[tuple]:
        conn = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro", uri=True
        )
        try:
            return conn.execute(
                """SELECT type,name,sql FROM sqlite_master
                   WHERE name NOT LIKE 'sqlite_%'
                   ORDER BY type,name"""
            ).fetchall()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

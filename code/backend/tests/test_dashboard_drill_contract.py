# -*- coding: utf-8 -*-
"""教学数据总览下钻范围契约测试。"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.routers.dashboard import major_grade_courses
from backend.api.routers.students import student_list


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_semester(semester_id TEXT, year TEXT);
        CREATE TABLE dim_college(college_id TEXT, name TEXT);
        CREATE TABLE dim_major(major_id TEXT, college_id TEXT, name TEXT);
        CREATE TABLE dim_class(class_id TEXT, name TEXT);
        CREATE TABLE dim_course(course_id TEXT, name TEXT);
        CREATE TABLE dim_student(
          student_id TEXT, name TEXT, college_id TEXT, major_id TEXT,
          class_id TEXT, grade TEXT, status TEXT
        );
        CREATE TABLE fact_grade(
          student_id TEXT, course_id TEXT, semester_id TEXT, source TEXT,
          score REAL, gpa REAL, credits REAL, is_retake INTEGER, is_required INTEGER,
          is_pass INTEGER
        );
        CREATE TABLE fact_alert(
          student_id TEXT, level TEXT, status TEXT, is_active INTEGER
        );

        INSERT INTO dim_semester VALUES('S1','2024-2025'),('S2','2025-2026');
        INSERT INTO dim_college VALUES('COL','测试学院');
        INSERT INTO dim_major VALUES('M1','COL','测试专业');
        INSERT INTO dim_class VALUES('B1','测试班');
        INSERT INTO dim_course VALUES('C1','课程一'),('C2','课程二'),('C3','课程三');
        INSERT INTO dim_student VALUES
          ('OLD','历史学生','COL','M1','B1','2022','在校'),
          ('CUR','当前学生','COL','M1','B1','2022','在校'),
          ('OTHER','其他课程学生','COL','M1','B1','2022','在校');
        INSERT INTO fact_grade VALUES
          ('OLD','C1','S1','real',55,2.0,2,0,1,0),
          ('CUR','C1','S2','real',70,3.0,2,0,1,1),
          ('CUR','C1','S2','real',85,3.7,2,0,1,1),
          ('CUR','C3','S2','real',90,4.0,2,0,1,1),
          ('OTHER','C2','S2','real',90,3.5,2,0,1,1);
    """)
    return conn


ALL_USER = {
    "role_id": "academic",
    "permission_context": {
        "authorized": True,
        "detailScope": {"type": "all", "sourceScopeIds": []},
    },
}


class DashboardDrillContractTest(unittest.TestCase):
    def test_course_drill_intersects_selected_semester(self):
        conn = make_conn()
        result = student_list(
            semester="S2",
            college="COL",
            major="M1",
            course="C1",
            page=1,
            page_size=20,
            user=ALL_USER,
            conn=conn,
        )["data"]
        self.assertEqual(1, result["total"])
        self.assertEqual("CUR", result["students"][0]["sid"])
        self.assertEqual("S2", result["appliedFilters"]["semester"])
        self.assertEqual("C1", result["appliedFilters"]["course"])
        self.assertEqual(85, result["students"][0]["courseScore"])
        self.assertEqual(3.7, result["students"][0]["courseGp"])
        conn.close()

    def test_course_drill_without_period_is_explicitly_historical(self):
        conn = make_conn()
        result = student_list(
            college="COL",
            major="M1",
            course="C1",
            page=1,
            page_size=20,
            user=ALL_USER,
            conn=conn,
        )["data"]
        self.assertEqual(2, result["total"])
        self.assertIsNone(result["appliedFilters"]["semester"])
        conn.close()

    def test_grade_courses_include_zero_fail_and_use_latest_student_result(self):
        conn = make_conn()
        result = major_grade_courses(
            major_id="M1",
            grade="2022级",
            semester="S2",
            page=1,
            page_size=20,
            user=ALL_USER,
            conn=conn,
        )["data"]
        self.assertEqual(3, result["total"])
        by_course = {row["courseId"]: row for row in result["items"]}
        self.assertEqual(1, by_course["C1"]["totalCount"])
        self.assertEqual(0, by_course["C1"]["failCount"])
        self.assertEqual(0.0, by_course["C3"]["failRate"])
        conn.close()


if __name__ == "__main__":
    unittest.main()

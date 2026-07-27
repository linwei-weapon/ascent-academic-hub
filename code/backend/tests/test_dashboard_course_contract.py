# -*- coding: utf-8 -*-
"""课程详情最终有效结果与行政班展示契约。"""
import sqlite3
import unittest

from backend.api.routers.dashboard import course_detail


ALL_USER = {
    "role_id": "academic",
    "permission_context": {
        "authorized": True,
        "detailScope": {"type": "all", "sourceScopeIds": []},
    },
}


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_semester(semester_id TEXT);
        CREATE TABLE dim_college(college_id TEXT,name TEXT);
        CREATE TABLE dim_major(major_id TEXT,name TEXT);
        CREATE TABLE dim_class(class_id TEXT,name TEXT);
        CREATE TABLE dim_student(
          student_id TEXT,college_id TEXT,major_id TEXT,class_id TEXT,grade TEXT
        );
        CREATE TABLE dim_course(
          course_id TEXT,name TEXT,credits REAL,is_required INTEGER,dept TEXT
        );
        CREATE TABLE dim_teacher(teacher_id TEXT,name TEXT);
        CREATE TABLE fact_lesson(
          lesson_id TEXT,semester_id TEXT,teacher_id TEXT
        );
        CREATE TABLE fact_grade(
          student_id TEXT,course_id TEXT,semester_id TEXT,source TEXT,
          score REAL,gpa REAL,is_pass INTEGER,lesson_id TEXT
        );

        INSERT INTO dim_semester VALUES('S1');
        INSERT INTO dim_college VALUES('COL','测试学院');
        INSERT INTO dim_major VALUES('M1','测试专业');
        INSERT INTO dim_class VALUES('B1','一班'),('B2','二班');
        INSERT INTO dim_student VALUES
          ('A','COL','M1','B1','2023'),
          ('B','COL','M1','B2','2023');
        INSERT INTO dim_course VALUES('C1','测试课程',2,1,'测试学院');
        INSERT INTO dim_teacher VALUES('T1','教师甲');
        INSERT INTO fact_lesson VALUES('L1','S1','T1');
        INSERT INTO fact_grade VALUES
          ('A','C1','S1','real',55,1.0,0,'L1'),
          ('A','C1','S1','real',85,3.7,1,'L1'),
          ('B','C1','S1','real',50,1.0,0,'L1');
    """)
    return conn


class DashboardCourseContractTest(unittest.TestCase):
    def test_kpis_use_latest_student_result_and_classes_keep_attempt_semantics(self):
        conn = make_conn()
        data = course_detail(
            course_id="C1", semester="S1", user=ALL_USER, conn=conn,
        )["data"]
        kpis = {row["id"]: row for row in data["kpi"]}
        self.assertEqual("50.0%", kpis["course_fail_student_rate"]["value"])
        self.assertEqual("2.35", kpis["average_course_gp"]["value"])
        self.assertEqual("2名学生有最终有效课程绩点",
                         kpis["average_course_gp"]["detail"])
        self.assertEqual(3, data["coverage"]["validResultAttempts"])
        self.assertEqual("二班", data["classDetail"][0]["className"])
        self.assertEqual(
            "按未通过人次率降序，同率按有效成绩人次降序",
            data["classSummary"]["sort"],
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()

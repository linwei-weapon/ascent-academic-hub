"""规则变更影响分析：学院—专业—年级交叉分布。"""
import sqlite3
import unittest

from backend.api.routers.settings import _organization_grade_distribution


class RuleChangeAnalysisDistributionTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE alert_rule_change_candidate(
                change_id INTEGER, student_id TEXT, action TEXT);
            CREATE TABLE dim_student(
                student_id TEXT PRIMARY KEY, college_id TEXT,
                major_id TEXT, grade TEXT);
            CREATE TABLE dim_college(college_id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE dim_major(major_id TEXT PRIMARY KEY, name TEXT);
            INSERT INTO dim_college VALUES ('C1','A学院'),('C2','B学院');
            INSERT INTO dim_major VALUES ('M1','专业1'),('M2','专业2'),('M3','专业3');
            INSERT INTO dim_student VALUES
                ('S1','C1','M1','2021'),
                ('S2','C1','M1','2021级'),
                ('S3','C1','M1','2022'),
                ('S4','C1','M2','2022'),
                ('S5','C2','M3','2021');
            INSERT INTO alert_rule_change_candidate VALUES
                (9,'S1','new'),
                (9,'S2','retained'),
                (9,'S3','exited'),
                (9,'S4','new'),
                (9,'S5','retained'),
                (10,'S1','new');
        """)

    def tearDown(self):
        self.conn.close()

    def test_cross_distribution_contains_all_actions_and_subtotals(self):
        result = _organization_grade_distribution(self.conn, 9)
        self.assertEqual(["2021级", "2022级"], result["grades"])
        self.assertEqual(5, result["total"])
        self.assertEqual(
            ["major", "major", "collegeSubtotal", "major", "collegeSubtotal", "grandTotal"],
            [row["rowType"] for row in result["rows"]],
        )
        self.assertEqual([2, 1], result["rows"][0]["counts"])
        self.assertEqual(3, result["rows"][0]["collegeRowspan"])
        self.assertEqual([2, 2], result["rows"][2]["counts"])
        self.assertEqual([3, 2], result["rows"][-1]["counts"])

    def test_empty_change_returns_empty_matrix(self):
        result = _organization_grade_distribution(self.conn, 999)
        self.assertEqual({"grades": [], "rows": [], "total": 0}, result)


if __name__ == "__main__":
    unittest.main()

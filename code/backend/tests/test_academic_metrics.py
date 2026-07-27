"""学生学业公共指标口径测试。"""
import sqlite3
import unittest

from backend.api.academic_metrics import (
    cumulative_gpa_summaries,
    earned_credit_map,
    effective_course_outcomes,
    effective_course_outcomes_for_students,
    per_student_weighted_gpa,
    term_earned_credit_map,
    term_grade_and_failed_students,
    unresolved_course_outcomes_for_students,
)


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE fact_grade(
            grade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,course_id TEXT,semester_id TEXT,
            score REAL,gpa REAL,is_pass INTEGER,credits REAL,
            source TEXT DEFAULT 'real');
        INSERT INTO fact_grade
            (student_id,course_id,semester_id,score,gpa,is_pass,credits,source)
        VALUES
            ('S1','C1','2024-2025-1',70,2.0,1,2,'real'),
            ('S1','C2','2024-2025-1',90,4.0,1,4,'real'),
            ('S1','C2','2024-2025-2',92,4.2,1,4,'real'),
            ('S1','C3','2024-2025-1',50,0.0,0,3,'real'),
            ('S1','C3','2024-2025-2',75,2.5,1,3,'real'),
            ('S1','C4','2024-2025-1',45,0.0,0,2,'real'),
            ('S1','C4','2024-2025-2',48,0.0,0,2,'real'),
            ('S1','C5','2024-2025-2',60,NULL,1,0,'real'),
            ('S2','C1','2024-2025-1',80,3.0,1,2,'real'),
            ('S3','C9','2024-2025-2',NULL,NULL,NULL,2,'real');
    """)
    return conn


class AcademicMetricsTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def tearDown(self):
        self.conn.close()

    def test_weighted_gpa_uses_credits(self):
        result = per_student_weighted_gpa(
            self.conn, ["S1"], ["2024-2025-1"]
        )
        expected = (2.0 * 2 + 4.0 * 4 + 0.0 * 3 + 0.0 * 2) / 11
        self.assertAlmostEqual(expected, result["S1"], places=6)

    def test_earned_credits_deduplicate_course(self):
        earned = earned_credit_map(self.conn, ["S1"])
        # C1=2、C2=4（两次通过只计一次）、C3=3。
        self.assertEqual(9.0, earned["S1"])
        term = term_earned_credit_map(
            self.conn, ["S1"], "2024-2025-2"
        )
        self.assertEqual(7.0, term["S1"])

    def test_total_gpa_uses_latest_result_per_course_and_discloses_exclusions(self):
        summary = cumulative_gpa_summaries(self.conn, ["S1"])["S1"]
        expected = (2.0 * 2 + 4.2 * 4 + 2.5 * 3 + 0.0 * 2) / 11
        self.assertAlmostEqual(expected, summary["gpa"], places=4)
        self.assertEqual(11.0, summary["includedCredits"])
        self.assertEqual(4, summary["includedCourses"])
        self.assertEqual(1, summary["excludedCourses"])
        self.assertEqual("cumulative-gpa-v1", summary["ruleVersion"])

    def test_term_failed_rate_sets_use_graded_denominator(self):
        graded, failed = term_grade_and_failed_students(
            self.conn, ["S1", "S2", "S3"], "2024-2025-2"
        )
        self.assertEqual({"S1"}, graded)
        self.assertEqual({"S1"}, failed)

    def test_effective_outcome_separates_resolved_and_unresolved(self):
        outcomes = effective_course_outcomes(self.conn, "S1")
        self.assertEqual("历史已解决", outcomes["C3"]["status"])
        self.assertEqual("当前未解决", outcomes["C4"]["status"])
        self.assertTrue(outcomes["C4"]["repeatedUnresolved"])
        self.assertEqual(2, outcomes["C4"]["failCount"])
        batch = effective_course_outcomes_for_students(
            self.conn, ["S1", "S2"]
        )
        self.assertEqual(outcomes, batch["S1"])
        self.assertEqual("已通过", batch["S2"]["C1"]["status"])
        unresolved = unresolved_course_outcomes_for_students(
            self.conn, ["S1", "S2"]
        )
        self.assertEqual({"C4"}, set(unresolved["S1"]))
        self.assertTrue(unresolved["S1"]["C4"]["repeatedUnresolved"])
        self.assertNotIn("S2", unresolved)


if __name__ == "__main__":
    unittest.main()

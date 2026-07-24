import sqlite3
import unittest
from unittest.mock import patch

from backend.api import db as dbm
from backend.api.routers.alert import _curriculum_progress_evidence
from pathlib import Path


def make_v2_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE curriculum_plan(
            plan_id TEXT PRIMARY KEY,
            plan_name TEXT
        );
        CREATE TABLE student_plan_progress_summary(
            student_id TEXT,
            plan_id TEXT,
            completed_modules INTEGER,
            assessable_modules INTEGER,
            module_count INTEGER,
            rule_coverage_rate REAL,
            explicit_gap_modules INTEGER,
            candidate_modules INTEGER,
            failed_required_courses INTEGER,
            due_candidate_courses INTEGER,
            evidence_status TEXT,
            binding_status TEXT,
            rule_version TEXT,
            calculated_at TEXT
        );
        INSERT INTO curriculum_plan VALUES('P22-AI','2022级人工智能培养方案');
        INSERT INTO student_plan_progress_summary VALUES(
            'S1','P22-AI',6,8,9,88.9,1,2,2,3,
            'explicit_gap','matched','growth-v1','2026-07-24 12:00:00'
        );
    """)
    return conn


class StudentEvidenceTest(unittest.TestCase):
    def test_curriculum_progress_reuses_v2_summary(self):
        conn = make_v2_conn()
        with patch.object(dbm, "get_v2_conn", return_value=conn):
            result = _curriculum_progress_evidence("S1")

        self.assertEqual("matched", result["status"])
        self.assertEqual("2022级人工智能培养方案", result["planName"])
        self.assertEqual(6, result["completedModules"])
        self.assertEqual(8, result["assessableModules"])
        self.assertEqual(88.9, result["ruleCoverageRate"])
        self.assertEqual(1, result["explicitGapModules"])
        self.assertEqual(2, result["candidateModules"])
        self.assertEqual("growth-v1", result["ruleVersion"])
        self.assertIn("候选项不作为正式缺修结论", result["boundary"])

    def test_student_detail_reuses_growth_term_aggregate(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "api" / "routers" / "alert.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "FROM agg_student_term_growth",
            source,
        )
        detail_section = source.split("# V1.1：逐学期摘要", 1)[1].split(
            "# V1.1：学业统计摘要", 1
        )[0]
        self.assertNotIn("weighted_gpa_expression", detail_section)


if __name__ == "__main__":
    unittest.main()

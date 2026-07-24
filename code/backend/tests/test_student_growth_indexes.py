import sqlite3
import unittest

from scripts.migrate_student_growth_indexes import migrate


class StudentGrowthIndexMigrationTest(unittest.TestCase):
    def test_migration_is_idempotent(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE fact_grade(
                student_id TEXT,course_id TEXT,semester_id TEXT,
                is_pass INTEGER,source TEXT,credits REAL,score REAL,gpa REAL
            );
            INSERT INTO fact_grade VALUES
                ('S1','C1','2024-2025-1',0,'real',2,50,0),
                ('S1','C1','2024-2025-2',1,'real',2,75,2.5),
                ('S1','C2','2024-2025-2',0,'real',4,45,0),
                ('S2','C3','2024-2025-2',1,'real',3,85,3.5);
        """)
        first = migrate(conn)
        second = migrate(conn)
        self.assertEqual(
            [
                "idx_grade_real_effective_student_course_sem",
                "idx_grade_real_failed_student_sem_course",
                "idx_grade_student_course_sem",
                "idx_grade_student_sem",
            ],
            first,
        )
        self.assertEqual(first, second)
        term = conn.execute("""
            SELECT weighted_gpa,grade_count,fail_count
            FROM agg_student_term_growth
            WHERE student_id='S1' AND semester_id='2024-2025-2'
        """).fetchone()
        self.assertAlmostEqual(2.5 * 2 / 6, term[0])
        self.assertEqual((2, 1), term[1:])
        outcomes = {
            row[0]: tuple(row[1:])
            for row in conn.execute("""
                SELECT course_id,fail_count,latest_is_pass
                FROM agg_student_course_outcome
                WHERE student_id='S1' ORDER BY course_id
            """)
        }
        self.assertEqual((1, 1), outcomes["C1"])
        self.assertEqual((1, 0), outcomes["C2"])
        meta = conn.execute("""
            SELECT source_grade_rows,source_student_count,
                   semester_min,semester_max,rule_version
            FROM agg_student_growth_meta WHERE singleton_id=1
        """).fetchone()
        self.assertEqual(
            (4, 2, "2024-2025-1", "2024-2025-2", "student-growth-v1"),
            meta,
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()

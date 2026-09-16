import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.etl import config
from backend.etl.extract_ts import SEMESTERS
from scripts import bootstrap_demo_data


class BasicReportDemoBootstrapTest(unittest.TestCase):
    def test_cet4_source_generation_preserves_existing_teaching_source(self):
        with TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            source_path = source_root / SEMESTERS[0]
            source_path = source_path.with_suffix(".db")
            with closing(sqlite3.connect(source_path)) as conn:
                conn.execute(
                    "CREATE TABLE students("
                    "student_id TEXT,college TEXT,major TEXT,grade_year TEXT,"
                    "class_name TEXT,status TEXT)"
                )
                conn.execute("CREATE TABLE scores(student_id TEXT, score REAL)")
                conn.execute(
                    "INSERT INTO students VALUES(?,?,?,?,?,?)",
                    ("REAL001", "真实学院", "真实专业", "2022", "真实班级", "在籍"),
                )
                conn.execute("INSERT INTO scores VALUES('REAL001', 88)")
                conn.commit()

            with patch.object(config, "TS_DIR", source_root):
                bootstrap_demo_data._create_cet4_sources(
                    bootstrap_demo_data._students()
                )

            with closing(sqlite3.connect(source_path)) as conn:
                self.assertEqual(
                    1,
                    conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0],
                )
                self.assertEqual(
                    "REAL001",
                    conn.execute("SELECT student_id FROM students").fetchone()[0],
                )

    def test_bootstrap_creates_anonymized_report_sources_and_refuses_overwrite(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "analytics.sqlite"
            v2_path = root / "analytics_v2.sqlite"
            source_root = root / "source"
            with (
                patch.object(config, "DB_PATH", db_path),
                patch.object(config, "V2_DB_PATH", v2_path),
                patch.object(config, "TS_DIR", source_root),
                patch.object(sys, "argv", ["bootstrap_demo_data.py"]),
            ):
                bootstrap_demo_data.main()
                self.assertTrue(db_path.is_file())
                self.assertTrue(v2_path.is_file())
                self.assertEqual(len(SEMESTERS), len(list(source_root.glob("*.db"))))

                with closing(sqlite3.connect(v2_path)) as conn:
                    self.assertEqual(63, conn.execute("SELECT COUNT(*) FROM dim_student").fetchone()[0])
                    self.assertGreater(conn.execute("SELECT COUNT(*) FROM grade_attempt").fetchone()[0], 0)
                    self.assertEqual(
                        0,
                        conn.execute("SELECT COUNT(*) FROM dim_student WHERE display_name NOT LIKE '演示%'").fetchone()[0],
                    )
                with closing(sqlite3.connect(db_path)) as conn:
                    self.assertEqual(12, conn.execute("SELECT COUNT(*) FROM sys_user").fetchone()[0])
                    self.assertGreater(conn.execute("SELECT COUNT(*) FROM fact_alert").fetchone()[0], 0)
                with closing(sqlite3.connect(source_root / "2025-2026-1.db")) as conn:
                    columns = {
                        row[1] for row in conn.execute("PRAGMA table_info(students)")
                    }
                    self.assertEqual(
                        {
                            "student_id", "college", "major", "grade_year",
                            "class_name", "status",
                        },
                        columns,
                    )
                    self.assertEqual(
                        63,
                        conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
                    )

                with self.assertRaises(SystemExit):
                    bootstrap_demo_data.main()


if __name__ == "__main__":
    unittest.main()

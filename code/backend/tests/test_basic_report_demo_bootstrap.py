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

                with self.assertRaises(SystemExit):
                    bootstrap_demo_data.main()


if __name__ == "__main__":
    unittest.main()

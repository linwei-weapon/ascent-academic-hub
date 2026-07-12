import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.etl.init_v2 import REQUIRED_TABLES, init_v2, validate_schema
from backend.etl.v2_sources import source_by_code, validate_selected_fields


class V2SchemaTest(unittest.TestCase):
    def test_schema_contains_required_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "analytics_v2.sqlite"
            conn = init_v2(path)
            report = validate_schema(conn)
            conn.close()
            self.assertEqual([], report["missing"])
            self.assertEqual(len(REQUIRED_TABLES), report["required_count"])
            self.assertEqual(1, report["foreign_keys"])

    def test_schema_is_idempotent(self):
        conn = sqlite3.connect(":memory:")
        from backend.etl import config
        sql = config.V2_SCHEMA_SQL.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.executescript(sql)
        self.assertEqual([], validate_schema(conn)["missing"])
        conn.close()

    def test_curriculum_plan_keeps_major_name_separate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            conn = init_v2(Path(temp_dir) / "v2.sqlite")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(curriculum_plan)")}
            conn.close()
            self.assertIn("major_code", columns)
            self.assertIn("major_name", columns)

    def test_field_whitelist_accepts_registered_fields(self):
        spec = source_by_code("student_current")
        validate_selected_fields(spec.code, ["学号", "姓名", "培养方案"])

    def test_field_whitelist_rejects_sensitive_fields(self):
        with self.assertRaises(ValueError):
            validate_selected_fields("student_current", ["学号", "身份证号"])

    def test_field_whitelist_rejects_unknown_fields(self):
        with self.assertRaises(ValueError):
            validate_selected_fields("course", ["课程代码", "未登记字段"])


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""教学数据总览 V2 指标契约测试。"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.routers.dashboard import (
    _pct_number,
    _pct_value,
    _select_management_focus,
    _v2_pass_stats,
)


class DashboardMetricContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "v2.db"
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
        CREATE TABLE agg_course_pass_stat(
          course_id TEXT,semester_id TEXT,course_name TEXT,course_group TEXT,
          first_attempts INTEGER,first_pass INTEGER,
          makeup_attempts INTEGER,makeup_pass INTEGER,
          retake_attempts INTEGER,retake_pass INTEGER);
        CREATE TABLE grade_attempt(
          attempt_id TEXT,student_id TEXT,course_id TEXT,semester_id TEXT,
          attempt_type TEXT,is_pass INTEGER,is_published INTEGER,is_void INTEGER);
        """)
        conn.executemany(
            "INSERT INTO agg_course_pass_stat VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                ("C1", "2024-2025-1", "课程1", "公共必修", 100, 80, 10, 5, 4, 2),
                ("C1", "2024-2025-2", "课程1", "公共必修", 50, 45, 4, 3, 2, 2),
                ("C2", "2024-2025-2", "课程2", "专业必修", 20, 10, 0, 0, 0, 0),
            ],
        )
        conn.executemany(
            "INSERT INTO grade_attempt VALUES(?,?,?,?,?,?,?,?)",
            [
                ("A1", "S1", "C1", "2024-2025-2", "regular", 1, 1, 0),
                ("A2", "S2", "C1", "2024-2025-2", "regular", 0, 1, 0),
                ("A3", "S2", "C1", "2024-2025-2", "makeup", 1, 1, 0),
                ("A4", "S3", "C2", "2024-2025-2", "retake", 0, 1, 0),
                # 无效记录不得进入聚合。
                ("A5", "S1", "C1", "2024-2025-2", "regular", 1, 0, 0),
                ("A6", "S1", "C1", "2024-2025-2", "regular", 1, 1, 1),
            ],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def open_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_unrestricted_stats_only_use_selected_semester(self):
        with patch(
            "backend.api.routers.dashboard.dbm.get_v2_conn",
            side_effect=self.open_conn,
        ):
            data = _v2_pass_stats("2024-2025-2")
        self.assertEqual(70, data["overall"]["fa"])
        self.assertEqual(55, data["overall"]["fp"])
        self.assertEqual(4, data["overall"]["ma"])
        self.assertEqual(3, data["overall"]["mp"])
        self.assertEqual(50, data["public_required"]["fa"])
        self.assertEqual(45, data["public_required"]["fp"])

    def test_restricted_stats_only_use_authorized_students(self):
        with patch(
            "backend.api.routers.dashboard.dbm.get_v2_conn",
            side_effect=self.open_conn,
        ):
            data = _v2_pass_stats("2024-2025-2", ["S1", "S2"])
        course = data["courses"]["C1"]
        self.assertEqual(2, course["fa"])
        self.assertEqual(1, course["fp"])
        self.assertEqual(1, course["ma"])
        self.assertEqual(1, course["mp"])
        self.assertNotIn("C2", data["courses"])
        self.assertEqual("公共必修", course["course_group"])

    def test_zero_denominator_is_missing_not_zero(self):
        self.assertEqual("—", _pct_value(0, 0))
        self.assertIsNone(_pct_number(0, 0))
        self.assertEqual("0.0%", _pct_value(0, 10))
        self.assertEqual(0.0, _pct_number(0, 10))

    def test_management_focus_keeps_each_category_top_one(self):
        candidates = [
            {
                "targetType": "college",
                "targetId": "COL-2",
                "title": "学院乙",
                "priorityScore": 8,
            },
            {
                "targetType": "course",
                "targetId": "COURSE-2",
                "title": "课程乙",
                "priorityScore": 88,
            },
            {
                "targetType": "college",
                "targetId": "COL-1",
                "title": "学院甲",
                "priorityScore": 12,
            },
            {
                "targetType": "course",
                "targetId": "COURSE-1",
                "title": "课程甲",
                "priorityScore": 66,
            },
        ]

        focus = _select_management_focus(candidates)

        self.assertEqual(
            [("college", "COL-1"), ("course", "COURSE-2")],
            [(item["targetType"], item["targetId"]) for item in focus],
        )
        self.assertTrue(all("priorityScore" not in item for item in focus))
        self.assertTrue(all("priorityScore" in item for item in candidates))


if __name__ == "__main__":
    unittest.main()

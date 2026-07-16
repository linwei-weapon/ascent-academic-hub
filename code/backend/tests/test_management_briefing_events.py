import sqlite3
import unittest

from backend.api.routers.ai import _build_management_events, _management_scope_context


def priority(theme: str, summary: str, level: str = "medium", rank: int = 1):
    return {
        "theme": theme,
        "summary": summary,
        "level": level,
        "rank": rank,
        "route": "/admin/example",
    }


class ManagementBriefingEventsTest(unittest.TestCase):
    def test_first_snapshot_creates_at_most_three_baseline_events(self):
        current = [priority(f"事项{i}", f"影响{i}", rank=i) for i in range(1, 5)]
        events = _build_management_events(current, None)
        self.assertEqual(3, len(events))
        self.assertTrue(all(item["changeType"] == "baseline" for item in events))

    def test_same_snapshot_creates_no_new_event(self):
        current = [priority("学生学业风险", "影响100人", "high")]
        self.assertEqual([], _build_management_events(current, current))

    def test_upgrade_and_resolved_are_traceable(self):
        previous = [priority("学生学业风险", "影响80人"), priority("课程团队保障", "影响5门")]
        current = [priority("学生学业风险", "影响120人", "high")]
        events = _build_management_events(current, previous)
        self.assertEqual("upgraded", events[0]["changeType"])
        self.assertTrue(any(item["changeType"] == "resolved" for item in events))
        self.assertIn("owner", events[0])
        self.assertIn("timing", events[0])

    def test_college_scope_maps_legacy_and_v2_without_school_fallback(self):
        legacy = sqlite3.connect(":memory:")
        legacy.row_factory = sqlite3.Row
        legacy.executescript("""
            CREATE TABLE sys_role(role_id TEXT, data_scope_type TEXT);
            CREATE TABLE sys_role_scope(role_id TEXT, scope_id TEXT);
            CREATE TABLE dim_college(college_id TEXT, name TEXT);
            INSERT INTO sys_role VALUES('college_dean','college');
            INSERT INTO sys_role_scope VALUES('college_dean','C01');
            INSERT INTO dim_college VALUES('C01','人工智能学院');
        """)
        v2 = sqlite3.connect(":memory:")
        v2.row_factory = sqlite3.Row
        v2.executescript("""
            CREATE TABLE access_scope_mapping(
                role_id TEXT, scope_type TEXT, source_scope_id TEXT,
                organization_id TEXT, major_code TEXT, class_code TEXT,
                mapping_status TEXT
            );
            INSERT INTO access_scope_mapping VALUES(
                'college_dean','college','C01','233',NULL,NULL,'mapped'
            );
        """)
        scope = _management_scope_context({"role_id": "college_dean"}, legacy, v2)
        self.assertEqual("college", scope["type"])
        self.assertEqual("人工智能学院", scope["label"])
        self.assertEqual("s.college_id = ?", scope["legacyStudentWhere"])
        self.assertEqual("s.organization_id IN (?)", scope["v2StudentWhere"])
        self.assertEqual("tl.organization_id IN (?)", scope["v2LessonWhere"])
        self.assertEqual(["233"], scope["v2LessonParams"])


if __name__ == "__main__":
    unittest.main()

"""明细下钻（数据要素 → 业务明细清单）单元测试。

覆盖：
- detail_specs 映射：可下钻数字返回行级清单，聚合/判定值显式不可下钻
- 行数硬上限 DETAIL_ROW_CAP 与截断标记
- 未知信号返回 None（对外 404，不泄露范围外信号存在性）
- 信号卡片携带 drillable_facts（前端点击入口的唯一依据）
"""
import unittest

from backend.skills.alert_priority import AlertPrioritySkill
from backend.skills.briefing import (DETAIL_ROW_CAP, _signal_card,
                                     build_signal_detail,
                                     drillable_facts_of)
from backend.skills.course_quality import CourseQualitySkill
from backend.skills.faculty_structure import FacultyStructureSkill
from backend.skills.graduation_gap import GraduationGapSkill
from backend.skills.protocol import Signal


def _briefing_with(card: dict) -> dict:
    return {
        "semester": "2025-2026-1",
        "generated_at": "2026-07-22T10:00:00",
        "priority_items": [],
        "watch_items": [],
        "positive_developments": [],
        "skill_sections": [{
            "skill_id": card["skill_id"],
            "skill_name": "测试Skill",
            "signals": [card],
        }],
    }


def _queue_row(rank: int, level: str = "警告") -> dict:
    return {
        "rank": rank, "student_id": f"S{rank:03d}",
        "student_name": f"学生{rank}", "college_id": "计算机学院",
        "level": level, "score": 50.0, "reasons": ["警告预警"],
        "reasons_text": "警告预警", "trigger_detail": "GPA低于2.0",
        "days_open": 20,
    }


QUEUE_CARD = {
    "signal_id": "alert-priority:queue",
    "skill_id": "alert-priority",
    "signal_type": "priority_queue",
    "headline": "本周优先介入队列3人",
    "facts": {"队列人数": "3人", "其中严重级": "1人", "全校活动预警": "100条"},
    "context": {"queue": [_queue_row(1, "严重"), _queue_row(2), _queue_row(3)]},
    "data_boundary": "测试边界",
    "evidence": {"verify_route": "/admin/alert"},
}

GAP_CARD = {
    "signal_id": "graduation-gap:course:C1",
    "skill_id": "graduation-gap",
    "signal_type": "course_gap",
    "headline": "硬课A：2人明确未通过",
    "facts": {"明确未通过": "2人", "待核验": "0人", "覆盖专业": "2个",
              "出路判定": "无路径"},
    "context": {
        "failed_students": [
            {"student_id": "S1", "student_name": "学生1", "major_name": "专业M1",
             "class_code": "C1", "course_name": "硬课A", "suggested_term": "7"},
            {"student_id": "S2", "student_name": "学生2", "major_name": "专业M2",
             "class_code": "C1", "course_name": "硬课A", "suggested_term": "7"},
        ],
        "failed_total": 2,
        "suspected_students": [],
        "suspected_total": 0,
    },
    "data_boundary": "",
    "evidence": {"verify_route": "/admin/curriculum?tab=graduation-readiness"},
}

QUALITY_OVERVIEW_CARD = {
    "signal_id": "course-quality:overview:2025-2026-2",
    "skill_id": "course-quality",
    "signal_type": "quality_overview",
    "headline": "本学期课程质量核查清单",
    "facts": {"持续偏高": "1门", "显著恶化": "1门", "高影响面": "0门",
              "全校基线": "10.0%"},
    "context": {"courses": [
        {"course_id": "PERSIST", "course_name": "持续课", "state": "persistent",
         "rate_pct": 30.0, "fails": 30, "total": 100},
        {"course_id": "SPIKE", "course_name": "恶化课", "state": "spike",
         "rate_pct": 25.0, "fails": 20, "total": 80},
    ]},
    "data_boundary": "",
    "evidence": {"verify_route": "/admin/operation/course-quality"},
}

FACULTY_OVERVIEW_CARD = {
    "signal_id": "faculty-structure:overview:2023-2024-1",
    "skill_id": "faculty-structure",
    "signal_type": "single_teacher_overview",
    "headline": "单人依赖课程快照",
    "facts": {"大规模单人课程": "1门", "中等规模单人课程": "1门",
              "快照学期": "2023-2024-1"},
    "context": {
        "high_courses": [{"course_id": "C1", "course_name": "大课A",
                          "enrolled": 500, "lesson_count": 5,
                          "organization_id": "石油工程学院"}],
        "mid_courses": [{"course_id": "C2", "course_name": "中课B",
                         "enrolled": 80, "lesson_count": 2,
                         "organization_id": "计算机学院"}],
    },
    "data_boundary": "",
    "evidence": {"verify_route": "/admin/operation/teacher-load"},
}


class DrillableFactsTest(unittest.TestCase):
    def test_queue_drillable_facts(self):
        facts = drillable_facts_of("alert-priority", "priority_queue")
        self.assertIn("队列人数", facts)
        self.assertIn("其中严重级", facts)
        self.assertNotIn("全校活动预警", facts)

    def test_stale_drillable_facts(self):
        self.assertEqual(drillable_facts_of("alert-priority", "stale_critical"),
                         ["滞留严重预警"])

    def test_gap_drillable_facts(self):
        facts = drillable_facts_of("graduation-gap", "course_gap")
        self.assertIn("明确未通过", facts)
        self.assertIn("待核验", facts)
        self.assertNotIn("覆盖专业", facts)
        self.assertNotIn("出路判定", facts)

    def test_unknown_skill_or_type(self):
        self.assertEqual(drillable_facts_of("no-such-skill", "x"), [])
        self.assertEqual(drillable_facts_of("alert-priority", "no-type"), [])

    def test_quality_overview_drillable_facts(self):
        facts = drillable_facts_of("course-quality", "quality_overview")
        self.assertIn("持续偏高", facts)
        self.assertIn("显著恶化", facts)
        self.assertIn("高影响面", facts)
        self.assertNotIn("全校基线", facts)

    def test_quality_course_drillable_facts(self):
        for stype in ("course_persistent", "course_spike", "course_high_impact"):
            facts = drillable_facts_of("course-quality", stype)
            self.assertEqual(facts, ["未通过人数"], stype)

    def test_improving_drillable_facts(self):
        self.assertEqual(drillable_facts_of("course-quality", "improving"),
                         ["改善课程"])

    def test_faculty_overview_drillable_facts(self):
        facts = drillable_facts_of("faculty-structure", "single_teacher_overview")
        self.assertIn("大规模单人课程", facts)
        self.assertIn("中等规模单人课程", facts)
        self.assertNotIn("快照学期", facts)

    def test_faculty_course_not_drillable(self):
        # 课程级信号全是聚合值（快照无行级名单），整类不可下钻
        self.assertEqual(
            drillable_facts_of("faculty-structure", "single_teacher_course"), [])
        self.assertEqual(
            drillable_facts_of("faculty-structure", "title_data_gap"), [])

    def test_signal_card_carries_drillable_facts(self):
        sig = Signal(
            signal_id="alert-priority:stale", skill_id="alert-priority",
            signal_type="stale_critical", severity="medium", headline="h",
            facts={"滞留严重预警": "2条"}, entity={}, action={},
            consequence="", confidence="high", evidence={},
        )
        card = _signal_card(sig, set())
        self.assertEqual(card["drillable_facts"], ["滞留严重预警"])


class BuildSignalDetailTest(unittest.TestCase):
    def test_queue_detail_rows(self):
        detail = build_signal_detail(_briefing_with(QUEUE_CARD),
                                     "alert-priority:queue", "队列人数")
        self.assertTrue(detail["drillable"])
        self.assertEqual(detail["total"], 3)
        self.assertEqual(len(detail["rows"]), 3)
        self.assertFalse(detail["truncated"])
        self.assertEqual(detail["rows"][0]["student_id"], "S001")
        labels = [c["label"] for c in detail["columns"]]
        self.assertIn("学号", labels)
        self.assertIn("综合评分", labels)
        self.assertEqual(detail["verify_route"], "/admin/alert")
        self.assertEqual(detail["fact_value"], "3人")

    def test_filter_critical_only(self):
        detail = build_signal_detail(_briefing_with(QUEUE_CARD),
                                     "alert-priority:queue", "其中严重级")
        self.assertTrue(detail["drillable"])
        self.assertEqual(len(detail["rows"]), 1)
        self.assertEqual(detail["rows"][0]["level"], "严重")

    def test_aggregate_fact_not_drillable(self):
        detail = build_signal_detail(_briefing_with(QUEUE_CARD),
                                     "alert-priority:queue", "全校活动预警")
        self.assertFalse(detail["drillable"])

    def test_unknown_fact_not_drillable(self):
        detail = build_signal_detail(_briefing_with(QUEUE_CARD),
                                     "alert-priority:queue", "不存在的数据")
        self.assertFalse(detail["drillable"])

    def test_unknown_signal_returns_none(self):
        self.assertIsNone(build_signal_detail(
            _briefing_with(QUEUE_CARD), "alert-priority:nope", "队列人数"))

    def test_row_cap_and_truncated(self):
        card = dict(QUEUE_CARD)
        card["context"] = {"queue": [_queue_row(i + 1)
                                     for i in range(DETAIL_ROW_CAP + 50)]}
        detail = build_signal_detail(_briefing_with(card),
                                     "alert-priority:queue", "队列人数")
        self.assertEqual(len(detail["rows"]), DETAIL_ROW_CAP)
        self.assertTrue(detail["truncated"])
        self.assertEqual(detail["total"], DETAIL_ROW_CAP + 50)

    def test_gap_course_detail(self):
        detail = build_signal_detail(_briefing_with(GAP_CARD),
                                     "graduation-gap:course:C1", "明确未通过")
        self.assertTrue(detail["drillable"])
        self.assertEqual(detail["total"], 2)
        self.assertEqual(detail["rows"][1]["major_name"], "专业M2")
        labels = [c["label"] for c in detail["columns"]]
        self.assertIn("建议修读学期", labels)

    def test_gap_judgement_fact_not_drillable(self):
        detail = build_signal_detail(_briefing_with(GAP_CARD),
                                     "graduation-gap:course:C1", "出路判定")
        self.assertFalse(detail["drillable"])

    def test_total_uses_total_key(self):
        card = dict(GAP_CARD)
        card["context"] = dict(GAP_CARD["context"])
        card["context"]["failed_total"] = 51   # 行被预截断时总数仍准确
        detail = build_signal_detail(_briefing_with(card),
                                     "graduation-gap:course:C1", "明确未通过")
        self.assertEqual(detail["total"], 51)
        self.assertTrue(detail["truncated"])

    def test_quality_overview_filter_by_state(self):
        detail = build_signal_detail(
            _briefing_with(QUALITY_OVERVIEW_CARD),
            "course-quality:overview:2025-2026-2", "持续偏高")
        self.assertTrue(detail["drillable"])
        self.assertEqual(len(detail["rows"]), 1)
        self.assertEqual(detail["rows"][0]["course_name"], "持续课")
        self.assertEqual(detail["fact_value"], "1门")

    def test_quality_overview_empty_state(self):
        detail = build_signal_detail(
            _briefing_with(QUALITY_OVERVIEW_CARD),
            "course-quality:overview:2025-2026-2", "高影响面")
        self.assertTrue(detail["drillable"])
        self.assertEqual(detail["rows"], [])
        self.assertEqual(detail["total"], 0)

    def test_quality_baseline_not_drillable(self):
        detail = build_signal_detail(
            _briefing_with(QUALITY_OVERVIEW_CARD),
            "course-quality:overview:2025-2026-2", "全校基线")
        self.assertFalse(detail["drillable"])

    def test_faculty_overview_detail(self):
        detail = build_signal_detail(
            _briefing_with(FACULTY_OVERVIEW_CARD),
            "faculty-structure:overview:2023-2024-1", "大规模单人课程")
        self.assertTrue(detail["drillable"])
        self.assertEqual(detail["total"], 1)
        self.assertEqual(detail["rows"][0]["enrolled"], 500)
        labels = [c["label"] for c in detail["columns"]]
        self.assertIn("开课单位", labels)

    def test_faculty_mid_courses_detail(self):
        detail = build_signal_detail(
            _briefing_with(FACULTY_OVERVIEW_CARD),
            "faculty-structure:overview:2023-2024-1", "中等规模单人课程")
        self.assertEqual(detail["rows"][0]["course_name"], "中课B")


class SkillDetailSpecsShapeTest(unittest.TestCase):
    """两个已落地 Skill 的 detail_specs 结构完整性。"""

    def _check(self, skill_cls):
        for stype, facts in skill_cls.detail_specs.items():
            self.assertTrue(stype)
            for label, spec in facts.items():
                self.assertTrue(label)
                self.assertTrue(spec.get("context_key"), f"{stype}/{label}")
                self.assertTrue(spec.get("columns"), f"{stype}/{label}")
                for col in spec["columns"]:
                    self.assertTrue(col.get("key") and col.get("label"))

    def test_alert_priority_specs(self):
        self._check(AlertPrioritySkill)

    def test_graduation_gap_specs(self):
        self._check(GraduationGapSkill)

    def test_course_quality_specs(self):
        self._check(CourseQualitySkill)

    def test_faculty_structure_specs(self):
        self._check(FacultyStructureSkill)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

from backend.ai_experts.registry import (
    EXPERT_PROTOCOL_VERSION,
    apply_school_override,
    get_expert,
    list_experts,
    validate_expert_definition,
    validate_school_override,
)
from backend.api.routers.ai_experts import _interpret_parameters


class AIExpertProtocolTest(unittest.TestCase):
    def test_three_first_experts_follow_complete_protocol(self):
        experts = list_experts("dean")
        self.assertEqual(3, len(experts))
        self.assertEqual("management-expert/1.0", EXPERT_PROTOCOL_VERSION)
        for expert in experts:
            self.assertEqual([], validate_expert_definition(expert), expert["expertId"])
            self.assertTrue(expert["metrics"])
            self.assertTrue(expert["outputs"])
            self.assertTrue(all(
                item["evidenceRoute"].startswith("/admin/")
                for item in expert["outputs"]
            ))

    def test_school_override_only_changes_whitelisted_values(self):
        expert = get_expert("graduation-readiness")
        override = {
            "thresholds": {"courseHighImpactStudents": 30},
            "parameterDefaults": {"addedClasses": 5},
            "recommendedQuestions": ["哪些课程需要优先保障？"],
        }
        self.assertEqual([], validate_school_override(expert, override))
        merged = apply_school_override(expert, override)
        self.assertEqual(30, merged["thresholds"]["courseHighImpactStudents"])
        self.assertEqual(5, merged["parameters"]["addedClasses"]["default"])
        self.assertEqual("school_override", merged["configurationSource"])
        self.assertEqual(
            expert["metrics"][0]["formula"],
            merged["metrics"][0]["formula"],
        )

    def test_school_override_cannot_replace_formula_source_or_route(self):
        expert = get_expert("high-impact-course-support")
        errors = validate_school_override(expert, {
            "metrics": [],
            "outputs": [{"evidenceRoute": "/admin/dashboard"}],
            "dataRequirements": [],
        })
        self.assertEqual(3, len(errors))
        self.assertTrue(all("不允许覆盖" in item for item in errors))

    def test_parameter_default_respects_type_and_range(self):
        expert = get_expert("course-team-continuity")
        self.assertTrue(validate_school_override(
            expert, {"parameterDefaults": {"availableTeachers": 99}}
        ))
        self.assertTrue(validate_school_override(
            expert, {"parameterDefaults": {"availableTeachers": "3"}}
        ))

    def test_role_catalog_is_filtered(self):
        self.assertEqual(3, len(list_experts("college_dean")))
        self.assertEqual([], list_experts("student"))

    def test_decision_workspace_uses_expert_catalog_instead_of_page_registry(self):
        root = Path(__file__).resolve().parents[2]
        page = (root / "frontend/src/views/admin/reports/DecisionSimulation.vue").read_text(
            encoding="utf-8"
        )
        client = (root / "frontend/src/utils/ai.ts").read_text(encoding="utf-8")
        self.assertIn("getAIExpertCatalog", page)
        self.assertIn("selectedExpertId", page)
        self.assertNotIn("const problemOptions: Array", page)
        self.assertIn("/admin/ai/experts", client)

    def test_natural_language_only_maps_registered_temporary_parameters(self):
        expert = get_expert("graduation-readiness")
        changes, matched = _interpret_parameters(
            expert, "如果新增5个班，每班40人，可协调4名教师，优先处理明确未通过"
        )
        self.assertEqual(5, changes["addedClasses"])
        self.assertEqual(40, changes["classCapacity"])
        self.assertEqual(4, changes["availableTeachers"])
        self.assertEqual("failed", changes["priorityFocus"])
        self.assertEqual(set(changes), set(matched))

    def test_natural_language_values_are_bounded_by_expert_protocol(self):
        expert = get_expert("course-team-continuity")
        changes, _ = _interpret_parameters(expert, "如果可协调99名教师，只看覆盖20人的课程")
        self.assertEqual(20, changes["availableTeachers"])
        self.assertEqual(50, changes["minimumStudents"])

    def test_natural_language_accepts_management_word_order(self):
        expert = get_expert("course-team-continuity")
        changes, _ = _interpret_parameters(expert, "把可协调教师改为5名")
        self.assertEqual(5, changes["availableTeachers"])


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

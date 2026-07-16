import unittest

from backend.api.routers.ai import _management_intervention


class AIManagementContractTest(unittest.TestCase):
    def test_high_risk_with_actionable_evidence_requires_action(self):
        payload = {
            "targetType": "student",
            "scenario": "student",
            "riskLevel": "critical",
            "riskTone": "danger",
            "riskLabel": "高风险",
            "confidence": "高",
            "summary": "该生存在复合型学业风险。",
            "evidence": [{"label": "未通过课程", "value": "3门", "detail": "其中必修2门"}],
            "reasons": ["连续两个学期存在明确课程问题"],
            "suggestions": [{"role": "二级学院", "action": "核查重修资源", "detail": "确认课程供给"}],
        }
        result = _management_intervention(payload)
        self.assertEqual("action_required", result["intervention"]["status"])
        self.assertEqual("核查重修资源", result["primaryAction"]["action"])
        self.assertFalse(result["comparison"]["available"])
        self.assertIn("不能判断", result["comparison"]["baseline"])

    def test_missing_evidence_is_verification_not_confirmed_risk(self):
        payload = {
            "targetType": "graduationCourse",
            "scenario": "graduation_course_supply",
            "riskLevel": "critical",
            "riskTone": "danger",
            "riskLabel": "高风险",
            "confidence": "中",
            "summary": "当前存在大量到期缺证据课程人次。",
            "evidence": [{"label": "到期缺证据", "value": "120人次", "detail": "需先核验认定与回写"}],
        }
        result = _management_intervention(payload)
        self.assertEqual("verification_required", result["intervention"]["status"])
        self.assertEqual("优先核验", result["intervention"]["label"])

    def test_low_risk_does_not_generate_intervention(self):
        payload = {
            "targetType": "student",
            "scenario": "student",
            "riskLevel": "low",
            "riskTone": "success",
            "riskLabel": "低风险",
            "summary": "当前未发现明显学业风险。",
            "evidence": [{"label": "当前有效预警", "value": "0条"}],
        }
        result = _management_intervention(payload)
        self.assertEqual("no_intervention", result["intervention"]["status"])


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.etl.v2_student_plan_loader import major_code, plan_id


class V2StudentPlanLoaderTest(unittest.TestCase):
    def test_plan_id_is_stable(self):
        name = "2022级人工智能专业培养方案"
        self.assertEqual(plan_id(name), plan_id(name))
        self.assertTrue(plan_id(name).startswith("PLAN-"))

    def test_major_code_restores_five_digit_format(self):
        self.assertEqual("02999", major_code(2999.0))
        self.assertEqual("12345", major_code("12345"))


if __name__ == "__main__":
    unittest.main()

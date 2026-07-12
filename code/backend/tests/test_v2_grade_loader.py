import unittest

from backend.etl.v2_grade_loader import attempt_id, parse_course_reference


class V2GradeLoaderTest(unittest.TestCase):
    def test_course_reference_parser(self):
        code, name, credits = parse_course_reference("大学体育Ⅱ（必修项目）(101099M002) 1分必修 通识必修")
        self.assertEqual("101099M002", code)
        self.assertEqual("大学体育Ⅱ（必修项目）", name)
        self.assertEqual(1.0, credits)

    def test_attempt_id_is_stable_per_source_row(self):
        self.assertEqual(attempt_id("batch", 2), attempt_id("batch", 2))
        self.assertNotEqual(attempt_id("batch", 2), attempt_id("batch", 3))


if __name__ == "__main__":
    unittest.main()

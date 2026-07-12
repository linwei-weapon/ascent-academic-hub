import unittest

from backend.etl.v2_legacy_grade_bridge import bridge_legacy_grades


class V2LegacyGradeBridgeTest(unittest.TestCase):
    def test_bridge_function_is_callable(self):
        self.assertTrue(callable(bridge_legacy_grades))


if __name__ == "__main__":
    unittest.main()

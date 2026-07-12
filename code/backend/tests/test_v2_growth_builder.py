import unittest

from backend.etl.v2_growth_builder import term_number


class V2GrowthBuilderTest(unittest.TestCase):
    def test_numeric_term(self):
        self.assertEqual(7, term_number("7"))
        self.assertEqual(3, term_number(3))

    def test_non_numeric_term_is_not_forced(self):
        self.assertIsNone(term_number("春,秋"))
        self.assertIsNone(term_number("3S"))


if __name__ == "__main__":
    unittest.main()

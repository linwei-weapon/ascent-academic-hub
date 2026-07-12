import unittest

from backend.etl.v2_master_loader import _code, _number, _text


class V2MasterLoaderTest(unittest.TestCase):
    def test_code_keeps_text_and_normalizes_excel_integer(self):
        self.assertEqual("200", _code(200.0))
        self.assertEqual("100101C001", _code("100101C001"))

    def test_number_accepts_hour_suffix(self):
        self.assertEqual(14.0, _number("14.0时"))
        self.assertIsNone(_number(None))

    def test_text_normalizes_blank(self):
        self.assertIsNone(_text("  "))
        self.assertEqual("启用", _text(" 启用 "))


if __name__ == "__main__":
    unittest.main()

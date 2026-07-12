import unittest
from backend.etl.v2_teaching_loader import day_part, parse_schedule

class V2TeachingLoaderTest(unittest.TestCase):
    def test_parse_schedule(self):
        rows = parse_schedule("7~18周 星期二 9~10节 校本部 三教111 李海燕")
        self.assertEqual(1, len(rows)); self.assertEqual(2, rows[0]["weekday"])
        self.assertEqual("三教111", rows[0]["room"]); self.assertEqual("evening", day_part(rows[0]["period_start"]))

if __name__ == "__main__": unittest.main()

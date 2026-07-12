import unittest

from backend.etl.v2_history_loader import event_id


class V2HistoryLoaderTest(unittest.TestCase):
    def test_event_id_prefers_source_flow_id(self):
        self.assertEqual("STATUS-本科202306280004", event_id("本科202306280004", "batch", 2, []))

    def test_event_id_is_stable_when_flow_missing(self):
        values = ["202001", "转专业", "2023-06-01"]
        self.assertEqual(event_id(None, "batch", 3, values), event_id(None, "batch", 3, values))
        self.assertNotEqual(event_id(None, "batch", 3, values), event_id(None, "batch", 4, values))


if __name__ == "__main__":
    unittest.main()

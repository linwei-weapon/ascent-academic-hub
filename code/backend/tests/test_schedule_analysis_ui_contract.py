import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ScheduleAnalysisUiContractTest(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_schedule_analysis_uses_confirmed_copy_and_visual_order(self):
        page = self.read("frontend/src/views/admin/operation/ScheduleAnalysis.vue")

        self.assertNotIn("基于真实课表复盘时段分布，为下一轮排课提供核查线索", page)
        self.assertNotIn("课程明细用于识别排课规模、晚间安排和星期集中度；不能单独判定排课不合理。", page)
        self.assertNotIn("data.definition.boundary", page)
        self.assertNotIn("data.semester || '加载中'", page)
        self.assertIn("重点课程组排课均衡分布情况", page)
        self.assertIn("｜课程排课情况", page)
        self.assertIn("yAxis:{type:'category',data:parts,inverse:true}", page)

    def test_schedule_fragment_tooltip_contains_confirmed_examples(self):
        page = self.read("frontend/src/views/admin/operation/ScheduleAnalysis.vue")
        card = self.read("frontend/src/components/KpiCard.vue")

        for copy in (
            "1. 排课片段：以星期为单位，一次连续节次为一个片段",
            "2. 排课片段举例：",
            "每周：周一 1~2节次，周三2~4节次，算2个片段",
            "每周：周一 1~4节次，算1个片段",
            "每周：周一 1~4节次，周二 1~4节次，算2个片段",
            "单周：周一 1~4节次，周二 1~4节次；双周：周二1~4节次，周四 1~2节次，算3个片段",
            "第18周：周一 2~3节次；算3个片段",
        ):
            self.assertIn(copy, page)
        self.assertIn("white-space: pre-line", card)


if __name__ == "__main__":
    unittest.main()

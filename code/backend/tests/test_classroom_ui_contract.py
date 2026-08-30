from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ClassroomUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "frontend/src/views/admin/operation/Classroom.vue").read_text(encoding="utf-8")
        cls.insight_drawer = (ROOT / "frontend/src/components/AIInsightDrawer.vue").read_text(encoding="utf-8")

    def test_classroom_page_uses_requested_labels_and_attention_rules(self):
        self.assertIn('title="教室资源研判"', self.page)
        self.assertIn("｜实际占用信息", self.page)
        self.assertIn(">查看资源研判<", self.page)
        self.assertIn(">详情<", self.page)
        self.assertIn("'1. 负载率 ≥45% 且记录数 ≥100：重点关注；'", self.page)
        self.assertIn("'2. 负载率 ≥30%：需关注；'", self.page)
        self.assertIn("'3. 教学楼为“待映射”：数据核验；'", self.page)
        self.assertIn("'4. 其余：常规。'", self.page)
        self.assertIn("label:'重点关注'", self.page)
        self.assertIn("label:'需关注'", self.page)

    def test_classroom_page_removes_requested_explanatory_copy(self):
        removed = (
            "从课程、考试、自习及其他活动的实际占用记录观察时序与楼宇负荷",
            "当前展示实际占用强度",
            "覆盖 ${fmt(s.observedDates)} 个日期",
            "不是学校可用教室总数",
            "定位集中占用时段",
            "当前图表已排除晚间",
            "按观测负荷固定分级",
            "判断资源压力主要来自常规教学",
            "这些记录已作为源数据核查线索保留",
            "观测负荷只用于定位占用集中",
            "当前仅需常规核查或数据映射",
        )
        for text in removed:
            self.assertNotIn(text, self.page)

    def test_classroom_insight_uses_scene_specific_display_options(self):
        for option in (
            "hide-intervention-tag",
            "hide-decision-meta",
            "hide-baseline",
            "hide-consequence",
            "hide-expected-result",
            "hide-no-comparison-tag",
            "hide-trace",
            "hide-evidence-help",
            "hide-evidence-source",
            "show-all-evidence",
        ):
            self.assertIn(option, self.page)

        drawer_contracts = (
            'v-if="!hideInterventionTag"',
            'v-if="!hideDecisionMeta"',
            'v-if="!hideBaseline"',
            'v-if="!hideConsequence"',
            'v-if="!hideExpectedResult"',
            'v-if="!hideNoComparisonTag && !view.comparison.available"',
            'v-if="!hideTrace"',
            'v-if="!hideEvidenceHelp"',
            'v-if="!hideEvidenceSource"',
            'showAllEvidence ? view.evidence : view.evidence.slice(0, 3)',
            "'single-column': hideExpectedResult",
            'v-if="hideTrace"',
            '事实来源：{{ trace.businessDataSources || listText(trace.dataSources) }}',
            '规则版本：{{ trace.ruleVersion || \'—\' }}',
            '适用边界：{{ trace.boundary || listText(view.limitations) }}',
        )
        for contract in drawer_contracts:
            self.assertIn(contract, self.insight_drawer)

    def test_heatmap_period_axis_is_ascending_from_top(self):
        self.assertIn("yAxis:{type:'category',inverse:true", self.page)

    def test_classroom_metric_tooltips_explain_deduplication_and_denominators(self):
        expected = (
            "1. 观测负荷 =【当前学期所有教室星期几第几节（星期一第一节）被占用的所有去重（有可能存在某个教室同一天同一节的重复占用记录）记录】 ÷ 【当前观测教室总数 × 该星期几（当期学期所有的星期一）出现的日期数】 × 100%",
            "2. 占用教室日数 = 当前学期所有教室星期几第几节（星期一第一节）被占用的所有去重（有可能存在某个教室同一天同一节的重复占用记录）记录",
            "占用教室日节次 = 当前学期该教学楼所有教室所有星期所有节次被占用的所有去重（有可能存在某个教室同一天同一节的重复占用记录）记录",
            "观测负荷 =【占用教室日节次】 ÷ 【当前学期该教学楼所有教室总数 × 观测日期数 × 纳入节次数】 × 100%",
        )
        for text in expected:
            self.assertIn(text, self.page)
        scope_notes = (
            '上述“所有教室”指当前筛选范围内已观测教室',
            '上述“所有节次”指当前纳入节次',
            '上述“所有教室总数”指当前学期该教学楼实际出现过占用的已观测教室数',
        )
        for text in scope_notes:
            self.assertIn(text, self.page)
        self.assertIn('#header-occupiedRoomSlots', self.page)
        self.assertIn('#header-observedLoadPct', self.page)


if __name__ == "__main__":
    unittest.main()

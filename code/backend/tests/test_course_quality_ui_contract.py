import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CourseQualityUiContractTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_course_result_page_uses_requested_labels_and_controls(self):
        page = self.read("frontend/src/views/admin/reports/CourseQuality.vue")
        operation = self.read("frontend/src/views/admin/operation/Index.vue")

        self.assertNotIn("课程结果使用独立多学期窗口", operation)
        self.assertNotIn("课程结果不等于教学归因", page)
        self.assertNotIn("趋势和开课资源仅在选择课程后加载", page)
        self.assertNotIn("指标口径与管理含义", page)
        self.assertIn(">查询</el-button>", page)
        self.assertIn(">重置</el-button>", page)
        self.assertIn("function reset()", page)
        self.assertIn("label: '首次通过率最大差值'", page)
        self.assertIn("function firstPassPct", page)
        self.assertIn("return v == null ? '-'", page)

    def test_kpi_tooltips_match_confirmed_wording(self):
        page = self.read("frontend/src/views/admin/reports/CourseQuality.vue")
        for wording in (
            "至少有一个学期达到30条有效成绩记录的去重课程数；有效记录是指已发布且未作废且 是否通过 非空的记录；",
            "首次修读（含缓考）通过人次数÷首次修读人次数，分母为0时 输出 '-' ",
            "同一门课程至少有2个学期及以上且每学期首次未通过率均高于15%",
            "同一门课程至少有2个学期及以上，最高与最低首次未通过率相差高于15个百分点",
            "筛选条件范围内重修成绩记录数量",
        ):
            self.assertIn(wording, page)
        for removed in (
            "至少一个学期满足样本量",
            "筛选范围内全部课程加权",
            "每个可比学期均≥15%",
            "最大差值≥15个百分点",
            "同一学生多次会重复计数",
        ):
            self.assertNotIn(removed, page)

    def test_both_semester_filters_use_descending_options(self):
        page = self.read("frontend/src/views/admin/reports/CourseQuality.vue")

        self.assertEqual(2, page.count('v-for="s in semesterOptions"'))
        self.assertIn("const semesterOptions = computed", page)
        self.assertIn("b.localeCompare(a", page)

    def test_course_detail_only_shows_semester_result_information(self):
        page = self.read("frontend/src/views/admin/reports/CourseQuality.vue")
        self.assertIn("｜学期结果信息", page)
        self.assertIn("学期变化", page)
        for removed in (
            "课程结果用于课程资源核查，不作教师个人评价",
            "该课程已接入开课资源",
            "offering_boundary",
            "detail.offerings",
        ):
            self.assertNotIn(removed, page)


if __name__ == "__main__":
    unittest.main()

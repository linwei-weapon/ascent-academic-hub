import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class GraduationReadinessUiContractTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_requested_copy_is_removed_or_renamed(self):
        page = self.read("frontend/src/views/admin/reports/GraduationReadiness.vue")

        for removed in (
            "本页是毕业准备核查工具，不是毕业或学位审核结论",
            "范围或口径指标",
            "专业表不受下方学生名单筛选影响",
            "以下条件只作用于本名单，不改变上方专业与课程统计",
            "当前显示全部授权范围",
            "应用名单条件",
            "清除全部条件",
            "查看指标口径、数据来源和适用边界",
            "明确问题",
            "数据候选",
            "明确未通过",
        ):
            self.assertNotIn(removed, page)

        for expected in (
            "高年级必修未通过",
            "全部年级必修未通过",
            "过期漏修学生",
            "label=\"必修未通过\"",
            "label=\"过期漏修\"",
            ">查询</el-button>",
            ">重置</el-button>",
        ):
            self.assertIn(expected, page)

    def test_global_filters_are_visible_and_reach_the_api(self):
        page = self.read("frontend/src/views/admin/reports/GraduationReadiness.vue")
        backend = self.read("backend/api/routers/v2.py")

        for placeholder in ("年级", "学院", "专业", "培养方案"):
            self.assertIn(f'placeholder="{placeholder}"', page)
        for parameter in ("grades", "organization_id", "major_code", "plan_id"):
            self.assertIn(f"q.set('{parameter}'", page)
        self.assertIn('"filterOptions": filter_options', backend)
        self.assertIn("grades: Optional[str] = None", backend)
        self.assertIn("organization_id: Optional[str] = None", backend)
        self.assertIn("if plan_id: cond.append(\"ps.plan_id=?\")", backend)

    def test_global_filter_options_load_independently_of_the_topic_response(self):
        page = self.read("frontend/src/views/admin/reports/GraduationReadiness.vue")

        self.assertIn("async function loadFilterOptions()", page)
        self.assertIn("http.get<any>('/v2/curriculum/options')", page)
        self.assertIn("options.overviewFilters", page)
        self.assertIn("Promise.all([loadFilterOptions(),loadOverview()])", page)
        self.assertIn("organizationId:plan.collegeId", page)
        self.assertIn("mergeFilterOptions(r.filterOptions,true)", page)
        self.assertIn("overwrite||!filterOptions[key].length", page)
        self.assertIn("查询条件加载失败，请重试", page)
        self.assertIn("if(!allFilterOptionsReady.value)filterOptionsError.value='查询条件加载失败，请重试'", page)
        self.assertNotIn("if(r.filterOptions)Object.assign(filterOptions,r.filterOptions)", page)

    def test_student_drill_actions_load_and_scroll_to_the_list(self):
        page = self.read("frontend/src/views/admin/reports/GraduationReadiness.vue")

        self.assertIn('ref="studentSection"', page)
        self.assertIn('@click.stop="useKpi(x)"', page)
        self.assertIn('@click="inspectMajor(row)"', page)
        self.assertIn("await loadStudents();scrollToStudents()", page)
        self.assertIn("studentSection.value?.scrollIntoView", page)
        self.assertIn("activeMajor.value='';activeMajorName.value='';draftStatus.value=x.filter", page)
        self.assertIn("draftStatus.value='';status.value='';activeMajor.value=row.major_code", page)

    def test_overview_tables_have_explicit_horizontal_scroll_regions(self):
        page = self.read("frontend/src/views/admin/reports/GraduationReadiness.vue")

        self.assertEqual(2, page.count('class="table-horizontal-scroll"'))
        self.assertIn('class="major-table-width"', page)
        self.assertIn('class="course-table-width"', page)
        self.assertIn(".table-horizontal-scroll{width:100%;max-width:100%;overflow-x:auto", page)
        self.assertIn(".grid>.sa-card{min-width:0}", page)
        self.assertIn(".major-table-width{min-width:1040px}", page)
        self.assertIn(".course-table-width{min-width:1280px}", page)

    def test_course_evidence_keeps_global_context_and_async_results_are_ordered(self):
        page = self.read("frontend/src/views/admin/reports/GraduationReadiness.vue")
        backend = self.read("backend/api/routers/v2.py")

        self.assertIn("const context=appendGlobalParams(new URLSearchParams(),false)", page)
        self.assertIn("/v2/curriculum/course-supply/", page)
        self.assertIn("/v2/curriculum/management-students?", page)
        self.assertIn("overviewRequestSeq=0,listRequestSeq=0", page)
        self.assertIn("const listRequestId=++listRequestSeq;listLoading.value=false", page)
        self.assertIn("applyData(r,true,listRequestId===listRequestSeq)", page)
        self.assertIn("includeOverview=false,includeStudents=true", page)
        self.assertIn("if(requestId===listRequestSeq)applyData(r)", page)
        self.assertIn("def curriculum_course_supply(course_id: str, organization_id: Optional[str] = None", backend)
        self.assertIn('affected_conditions.append("x.plan_id=?")', backend)
        self.assertIn("AND ps.rule_version=x.rule_version AND ps.binding_status='matched'", backend)
        self.assertIn('cond.append("ps.binding_status=\'matched\'")', backend)

    def test_student_evidence_and_insight_use_the_simplified_graduation_view(self):
        page = self.read("frontend/src/views/admin/reports/GraduationReadiness.vue")
        drawer = self.read("frontend/src/components/AIInsightDrawer.vue")

        self.assertNotIn('title="核查边界"', page)
        self.assertNotIn("studentEvidence.boundary", page)
        self.assertIn(">归纳核查重点</el-button>", page)
        self.assertNotIn("AI归纳核查重点", page)
        self.assertIn('title="毕业准备研判"', page)
        self.assertNotIn('title="毕业准备AI研判"', page)

        for prop in (
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
            self.assertIn(prop, page)

        self.assertIn("'single-column': hideExpectedResult", drawer)
        self.assertIn("showAllEvidence ? view.evidence : view.evidence.slice(0, 3)", drawer)
        self.assertNotIn("hide-trace-shortcut", page)
        for trace_field in ("分析范围：", "事实来源：", "规则版本：", "适用边界："):
            self.assertIn(trace_field, drawer)


if __name__ == "__main__":
    unittest.main()

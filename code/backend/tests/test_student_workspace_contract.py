from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class StudentWorkspaceContractTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_canonical_route_uses_role_aware_workspace(self):
        router = self.read("frontend/src/router/index.ts")
        workspace = self.read("frontend/src/views/admin/students/Workspace.vue")

        self.assertIn(
            "students/analysis', component: () => import('@/views/admin/students/Workspace.vue')",
            router,
        )
        self.assertIn("path: 'students/my', redirect:", router)
        self.assertIn("path: '/admin/students/analysis'", router)
        self.assertIn("<MyScope v-if=\"isRelationshipWorkspace\"", workspace)
        self.assertIn("permissionContext?.activeRole", workspace)
        for role_id in ("counselor", "class_adviser", "mentor"):
            self.assertIn(role_id, workspace)

    def test_legacy_path_is_not_an_independent_menu_key(self):
        menu = self.read("frontend/src/utils/menu.ts")
        migrate = self.read("scripts/migrate_menu.py")

        self.assertIn(
            "if (path === '/admin/students/my') return '/admin/students/analysis'",
            menu,
        )
        self.assertIn(
            '"/admin/students/my": ("/admin/students/analysis",)',
            migrate,
        )
        target_section = migrate.split("TARGET_MENUS = [", 1)[1].split(
            "PARENT_IDS =", 1,
        )[0]
        self.assertNotIn('("/admin/students/my",', target_section)

    def test_relationship_workspace_returns_to_canonical_entry(self):
        my_scope = self.read("frontend/src/views/admin/students/MyScope.vue")
        analysis = self.read("frontend/src/views/admin/students/Analysis.vue")
        drawer = self.read("frontend/src/components/StudentEvidenceDrawer.vue")

        self.assertIn("'我的学生学业关注'", my_scope)
        self.assertIn("'我的班级学业关注'", my_scope)
        self.assertIn("<StudentEvidenceDrawer", my_scope)
        self.assertIn("const returnTo = router.resolve", drawer)
        self.assertIn("path: route.path", drawer)
        self.assertNotIn("router.push('/admin/students/my')", analysis)

    def test_management_workspace_uses_explainable_growth_contract(self):
        analysis = self.read(
            "frontend/src/views/admin/students/Analysis.vue"
        )
        router = self.read("backend/api/routers/students.py")
        growth = self.read("backend/api/student_growth.py")

        self.assertIn("/growth/overview", router)
        self.assertIn("/growth/organizations", router)
        self.assertIn("/growth/list", router)
        self.assertIn("可比较学生", growth)
        self.assertIn("明确恶化", growth)
        self.assertIn("连续受挫", growth)
        self.assertIn("低年级首次受挫", growth)
        self.assertIn("重复未解决", growth)
        for removed_copy in (
            "识别真实变化、组织管理注意力",
            "调整条件后点击“应用范围”",
            "关注分组允许重叠。",
            "点击“查看名单”仅收窄当前授权范围",
            "规则版本 ${overview.rule?.version",
        ):
            self.assertNotIn(removed_copy, analysis)
        self.assertNotIn("BusinessPageContext", analysis)
        self.assertIn(":max-business-columns=\"8\"", analysis)
        self.assertNotIn("学位授予率", analysis)
        self.assertNotIn("毕业率", analysis)

    def test_growth_filters_cascade_and_comparable_board_drills_down(self):
        analysis = self.read(
            "frontend/src/views/admin/students/Analysis.vue"
        )

        self.assertNotIn('v-model="draft.grade"', analysis)
        self.assertNotIn('<div class="filter-title">分析范围</div>', analysis)
        self.assertNotIn('>应用范围</el-button>', analysis)
        self.assertIn('>查询</el-button>', analysis)
        self.assertIn(
            "draft.college ? majors.value.filter(item => "
            "item.college === draft.college) : []",
            analysis,
        )
        self.assertIn(
            "draft.major ? classes.value.filter(item => "
            "item.major === draft.major) : []",
            analysis,
        )
        self.assertIn(':disabled="!draft.college', analysis)
        self.assertIn(':disabled="!draft.major"', analysis)
        self.assertIn('class="comparison-board"', analysis)
        for copy in (
            "可比较学生情况看板",
            "参与比较学期",
            "可比较学生数",
            "在籍学生总数",
            "可比较学生占比",
            "两个参与学期均在籍的学生交集去重数",
            "两个参与学期在籍学生并集去重数",
            "两个参与学期均在籍的学生交集去重数 ÷ 两个参与学期在籍学生并集去重数 × 100%",
        ):
            self.assertIn(copy, analysis)
        self.assertNotIn("<span>学生总数</span>", analysis)
        self.assertNotIn("<span>可比较学生比例</span>", analysis)
        self.assertNotIn("<span>标题说明</span>", analysis)
        self.assertIn("comparisonBoardComparableCount", analysis)
        self.assertIn("comparisonBoardStudentCount", analysis)
        self.assertIn("comparisonBoardRate", analysis)
        self.assertIn("overview.rule?.version === 'student-growth-v2'", analysis)
        self.assertIn("if (!comparableMetricUsesRosterCohort.value) return metrics", analysis)
        self.assertIn('v-for="metric in metricCards"', analysis)
        self.assertIn("item.key !== 'comparable'", analysis)
        self.assertIn(':hint="metricHint(metric)"', analysis)
        for tooltip_copy in (
            "GPA明显上升且挂科未增加，或挂科减少且GPA未明显下降学生数",
            "明确改善学生数 ÷ 两个学期均有有效成绩证据的学生数 × 100%",
            "即认定为“明确改善”",
            "GPA明显下降且挂科未减少，或挂科增加且GPA未明显上升学生数",
            "明确恶化学生数 ÷ 两个学期均有有效成绩证据的学生数 × 100%",
            "即认定为“明确恶化”",
            "两个参与学期均在籍，且两个参与学期均至少有1门未通过课程的学生去重数",
            "连续受挫学生数 ÷ 两个学期均有有效成绩证据的学生 × 100%",
            "当前两个低年级群体在目标学期首次出现可观测未通过记录的学生去重数",
            "低年级首次受挫学生数 ÷ 两个参与学期至少一个学期在籍的学生去重总数 × 100%",
            "同一课程至少两次未通过且最新有效结果仍未通过的学生去重数",
            "重复未解决学生数 ÷ 两个参与学期在籍学生并集去重数 × 100%",
        ):
            self.assertIn(tooltip_copy, analysis)
        self.assertIn("1.指标说明：${detail.indicator}", analysis)
        self.assertIn("2.时间范围：${periodText.value}", analysis)
        self.assertIn("3.比例计算公式：${detail.formula}", analysis)
        self.assertIn("4.中文说明：${detail.description}", analysis)
        self.assertIn('"repeated_unresolved"', analysis)
        self.assertIn(
            "同一课程至少两次未通过且最新有效结果仍未通过",
            analysis,
        )
        self.assertIn(
            "selectGroup('comparable', '可比较学生')",
            analysis,
        )
        comparable_handler = analysis.split(
            "async function showComparableStudents()", 1
        )[1].split("async function selectGroup", 1)[0]
        for reset in (
            "selectedOrganizationId.value = ''",
            "selectedOrganizationName.value = ''",
            "keyword.value = ''",
        ):
            self.assertIn(reset, comparable_handler)

    def test_growth_organization_comparison_follows_query_level(self):
        analysis = self.read(
            "frontend/src/views/admin/students/Analysis.vue"
        )

        self.assertNotIn("管理关注分组", analysis)
        self.assertNotIn('class="sa-card group-panel"', analysis)
        self.assertIn(
            'class="sa-card organization-panel management-row"',
            analysis,
        )
        self.assertIn("{{ organizationTitle }}", analysis)
        self.assertIn("学院变化与关注比较", analysis)
        self.assertIn("各专业变化与关注比较", analysis)
        self.assertIn("各行政班变化与关注比较", analysis)
        self.assertIn("classOptionLabel(applied.classId)", analysis)
        self.assertIn("const organizationNameColumnLabel = computed", analysis)
        self.assertIn("organizationDisplayName(row)", analysis)
        self.assertIn("majors.value.find(item => item.value === organizationId)", analysis)
        self.assertIn("classes.value.find(item => item.value === organizationId)", analysis)
        self.assertIn("organizationResponseMatchesQuery(data)", analysis)
        self.assertIn("组织比较返回层级与当前查询条件不一致", analysis)
        self.assertIn("applied.classId ? [applied.classId]", analysis)
        self.assertIn(
            "!applied.classId && organizationId === 'UNASSIGNED'",
            analysis,
        )
        self.assertIn(
            "row.gradeEvidenceComparableCount ?? row.comparableCount",
            analysis,
        )
        self.assertIn("countText(denominator)", analysis)
        display_helper = analysis[
            analysis.index("function organizationDisplayName"):
            analysis.index("function valueText")
        ]
        self.assertNotIn("row.organizationName", display_helper)
        for label in ("学院名称", "专业名称", "行政班名称"):
            self.assertIn(label, analysis)
        organization_columns = analysis.split(
            "const organizationCols", 1
        )[1].split("const studentCols", 1)[0]
        self.assertNotIn("key: 'actions'", organization_columns)
        organization_panel = analysis.split(
            'class="sa-card organization-panel management-row"', 1
        )[1].split('class="sa-card list-panel"', 1)[0]
        self.assertNotIn("#col-actions", organization_panel)
        self.assertNotIn("selectOrganization", organization_panel)

    def test_growth_evidence_list_columns_match_copy_contract(self):
        analysis = self.read(
            "frontend/src/views/admin/students/Analysis.vue"
        )
        student_columns = analysis.split(
            "const studentCols", 1
        )[1].split("function onCollege", 1)[0]

        sid_index = student_columns.index("key: 'sid'")
        name_index = student_columns.index("key: 'name'")
        college_index = student_columns.index("key: 'college'")
        organization_index = student_columns.index("key: 'organization'")
        self.assertLess(sid_index, name_index)
        self.assertLess(name_index, college_index)
        self.assertLess(college_index, organization_index)
        self.assertIn("key: 'college', label: '院系'", student_columns)
        self.assertIn("key: 'unresolved', label: '当前未通过课程'", student_columns)
        self.assertIn("key: 'openAlerts', label: '当前有效预警'", student_columns)
        self.assertIn("{{ row.openAlerts }}条", analysis)
        self.assertNotIn("返回全部组织", analysis)
        self.assertNotIn("function clearOrganization", analysis)

    def test_student_evidence_drawer_is_shared_by_all_student_workspaces(self):
        drawer = self.read("frontend/src/components/StudentEvidenceDrawer.vue")
        for relative in (
            "frontend/src/views/admin/students/Analysis.vue",
            "frontend/src/views/admin/students/List.vue",
            "frontend/src/views/admin/students/MyScope.vue",
        ):
            page = self.read(relative)
            self.assertIn("<StudentEvidenceDrawer", page)
            self.assertIn(
                "import StudentEvidenceDrawer from "
                "'@/components/StudentEvidenceDrawer.vue'",
                page,
            )

        self.assertIn("为什么现在看", drawer)
        self.assertIn("当前未解决", drawer)
        self.assertIn("重复未解决", drawer)
        self.assertIn("历史已解决", drawer)
        self.assertIn("label: '挂科学期'", drawer)
        self.assertIn("label: '通过学期'", drawer)
        self.assertNotIn("label: '解决学期'", drawer)
        self.assertIn("failureView.value !== 'resolved'", drawer)
        alert_router = self.read("backend/api/routers/alert.py")
        self.assertIn('"resolvedSemester":', alert_router)
        self.assertIn("培养方案进度证据", drawer)
        self.assertIn("预警与核查记录", drawer)
        self.assertIn("`周期 ${props.context.period}`", drawer)
        self.assertNotIn("证据周期", drawer)
        self.assertNotIn("先核查事实，再形成管理判断", drawer)
        self.assertNotIn("规则 {{ context.ruleVersion }}", drawer)
        self.assertNotIn("数据来源与适用边界", drawer)
        self.assertNotIn("evidenceDescription", drawer)

    def test_student_profile_failure_history_shows_pass_semester(self):
        detail = self.read("frontend/src/views/admin/student/Detail.vue")
        failure_history = detail.split("历史未通过课程", 1)[1].split(
            "成绩明细", 1
        )[0]

        self.assertIn('label="挂科学期"', failure_history)
        self.assertIn('label="通过学期"', failure_history)
        self.assertIn("row.resolvedSemester || '—'", failure_history)
        self.assertLess(
            failure_history.index('label="挂科学期"'),
            failure_history.index('label="通过学期"'),
        )

    def test_student_profile_uses_business_growth_heading(self):
        detail = self.read("frontend/src/views/admin/student/Detail.vue")

        self.assertIn("学业成长指标", detail)
        self.assertNotIn(">V2 成长指标 ", detail)

    def test_student_profile_uses_compact_academic_review_copy(self):
        detail = self.read("frontend/src/views/admin/student/Detail.vue")

        self.assertIn(">学业研判</el-button>", detail)
        self.assertIn('title="学业研判"', detail)
        self.assertNotIn("AI学业研判", detail)
        self.assertNotIn("V2真实数据档案", detail)
        self.assertNotIn("生成方式：", detail)
        self.assertNotIn("deterministic-template-v1", detail)
        self.assertNotIn("当前未启用外部AI模型", detail)
        self.assertNotIn("正式课程、成绩和毕业审核以学校业务系统为准", detail)
        self.assertNotIn("v2-banner", detail)
        self.assertNotIn("advice-footer", detail)
        self.assertNotIn("数据来源：教务系统 · 本页仅做数据展示，预警处理请在教务系统中操作", detail)
        self.assertIn("growth.student.entry_grade", detail)
        self.assertIn("data.enrollOn = `${growth.student.entry_grade}年`", detail)

    def test_student_profile_academic_review_hides_auxiliary_copy_and_shows_all_evidence(self):
        detail = self.read("frontend/src/views/admin/student/Detail.vue")
        drawer = detail.split("<AIInsightDrawer", 1)[1].split("/>", 1)[0]

        for prop in (
            "hide-intervention-tag",
            "hide-decision-meta",
            "hide-judgment-boundary",
            "hide-consequence",
            "hide-expected-result",
            "hide-no-comparison-tag",
            "hide-trace",
            "hide-evidence-help",
            "hide-evidence-source",
            "show-all-evidence",
            "icon-only-trace-shortcut",
        ):
            self.assertIn(prop, drawer)
        self.assertNotIn("hide-baseline", drawer)
        self.assertNotIn("hide-trace-shortcut", drawer)

        shared_drawer = self.read("frontend/src/components/AIInsightDrawer.vue")
        self.assertIn(
            "!hideBaseline && (view.comparison.available || !hideJudgmentBoundary)",
            shared_drawer,
        )
        self.assertIn('v-if="iconOnlyTraceShortcut"', shared_drawer)
        self.assertIn('aria-label="查看研判依据"', shared_drawer)

    def test_growth_and_legacy_lists_restore_url_context(self):
        analysis = self.read("frontend/src/views/admin/students/Analysis.vue")
        legacy_list = self.read("frontend/src/views/admin/students/List.vue")
        drawer = self.read("frontend/src/components/StudentEvidenceDrawer.vue")

        for token in (
            "currentViewQuery()",
            "organization_id:",
            "page_size:",
            "scrollY",
            "returnQuery:",
        ):
            self.assertIn(token, analysis)
        for token in (
            "currentListQuery()",
            "keyword:",
            "page_size:",
            "scrollY",
            "returnQuery:",
        ):
            self.assertIn(token, legacy_list)
        self.assertIn("props.context?.returnQuery || route.query", drawer)
        self.assertIn("withScrollPosition(", drawer)

    def test_student_workspaces_have_local_retry_and_paginated_class_rows(self):
        analysis = self.read("frontend/src/views/admin/students/Analysis.vue")
        legacy_list = self.read("frontend/src/views/admin/students/List.vue")
        my_scope = self.read("frontend/src/views/admin/students/MyScope.vue")

        self.assertIn("重新加载名单", analysis)
        self.assertIn("重新加载组织比较", analysis)
        self.assertIn("loadOrganizations()", analysis)
        self.assertIn("listError.value =", analysis)
        self.assertIn("重新加载</el-button>", legacy_list)
        self.assertIn("重新加载</el-button>", my_scope)
        self.assertIn('storage-key="students:my-class-students"', my_scope)
        self.assertIn(':pagination="true"', my_scope)
        self.assertIn(':default-page-size="10"', my_scope)
        self.assertIn(":max-business-columns=\"4\"", my_scope)
        self.assertNotIn("<el-table :data=\"c.students\"", my_scope)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


class P3ModuleReorganizationTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_legacy_fact_topics_redirect_to_primary_modules(self):
        router = self.read("frontend/src/router/index.ts")
        expected = {
            "reports/early-setback": "/admin/alert?tab=early-risk",
            "reports/graduation-readiness": "/admin/curriculum?tab=graduation-readiness",
            "reports/course-quality": "/admin/operation/course-quality",
            "reports/faculty-resource-risk": "/admin/faculty",
            "reports/schedule-strategy": "/admin/operation/schedule-analysis",
        }
        for legacy, target in expected.items():
            self.assertIn(f"path: '{legacy}', redirect: '{target}'", router)
        self.assertNotIn("import('@/views/admin/reports/FacultyResourceRisk.vue')", router)
        self.assertNotIn("import('@/views/admin/reports/ScheduleStrategy.vue')", router)

    def test_primary_workspaces_absorb_topic_capabilities(self):
        alert = self.read("frontend/src/views/admin/alert/Workspace.vue")
        curriculum = self.read("frontend/src/views/admin/curriculum/index.vue")
        operation = self.read("frontend/src/views/admin/operation/Index.vue")
        self.assertIn('label="低年级风险观察"', alert)
        self.assertIn("<EarlySetback", alert)
        self.assertIn('label="毕业准备与课程保障"', curriculum)
        self.assertIn("<GraduationReadiness", curriculum)
        self.assertIn('label="课程结果"', operation)
        self.assertIn("<CourseQuality", operation)
        self.assertIn("provide('operationSemester', sharedSemester)", operation)
        self.assertIn("provide('operationDataContext', dataContext)", operation)
        self.assertNotIn("contentKey", operation)
        labels = [
            'label="开课供给"', 'label="排课结构"', 'label="教室占用"',
            'label="教师负荷"', 'label="调停课分析"', 'label="课程结果"',
        ]
        positions = [operation.index(label) for label in labels]
        self.assertEqual(sorted(positions), positions)

    def test_ai_evidence_routes_do_not_point_to_legacy_topics(self):
        ai = self.read("backend/api/routers/ai.py")
        for legacy in (
            "/admin/reports/graduation-readiness",
            "/admin/reports/course-quality",
            "/admin/reports/faculty-resource-risk",
        ):
            self.assertNotIn(legacy, ai)
        self.assertIn('"/admin/operation/course-quality"', ai)
        self.assertIn('"/admin/faculty"', ai)
        self.assertIn('{"tab": "graduation-readiness"}', ai)

    def test_business_pages_show_permission_context(self):
        component = self.read("frontend/src/components/BusinessPageContext.vue")
        self.assertIn("permissionContext?.detailScope", component)
        self.assertIn("activeRoleName", component)
        for page in (
            "frontend/src/views/admin/dashboard/index.vue",
            "frontend/src/views/admin/faculty/Index.vue",
            "frontend/src/views/admin/students/Analysis.vue",
        ):
            self.assertIn("BusinessPageContext", self.read(page), page)
        curriculum = self.read("frontend/src/views/admin/curriculum/index.vue")
        self.assertNotIn("BusinessPageContext", curriculum)
        alert = self.read("frontend/src/views/admin/alert/Workspace.vue")
        self.assertNotIn("BusinessPageContext", alert)
        self.assertIn("最新预警统计时间", alert)
        operation = self.read("frontend/src/views/admin/operation/Index.vue")
        self.assertNotIn("BusinessPageContext", operation)
        self.assertNotIn("当前数据覆盖", operation)

    def test_course_supply_uses_one_filter_snapshot_without_college_drill(self):
        page = self.read("frontend/src/views/admin/operation/Courses.vue")
        self.assertIn('placeholder="全部学院"', page)
        self.assertNotIn('placeholder="课程代码/名称"', page)
        self.assertIn("const params = buildCourseParams()", page)
        self.assertIn("data.dataQuality.excludedTeachers", page)
        self.assertIn('v-if="data.dataQuality.excludedTeachers"', page)
        self.assertNotIn('<el-collapse v-if="qualityIssues.length"', page)
        self.assertIn(':title="`查看 ${data.dataQuality.excludedTeachers} 条数据质量问题明细`"', page)
        self.assertIn("qualityIssues: [], dataQuality: {}", page)
        self.assertNotIn("/v2/courses/offerings", page)
        self.assertNotIn("showQualityAudit", page)
        self.assertNotIn('@row-click="goCollege"', page)
        self.assertNotIn("row-clickable", page)
        self.assertNotIn("历史趋势暂不展示", page)
        self.assertNotIn("V2 真实教学任务证据", page)

        self.assertIn("return { label:'重点关注', type:'danger' }", page)
        self.assertNotIn("完整清单按教学班数和选课人次排序", page)
        self.assertIn("return { label:'需关注', type:'warning' }", page)
        self.assertNotIn("label:'AI重点'", page)
        self.assertNotIn("label:'需核查'", page)
        self.assertIn('@click.stop="openOfferingReview(row)">详情</el-button>', page)
        self.assertNotIn('@click.stop="openOfferingReview(row)">查看</el-button>', page)
        self.assertIn("｜开课保障信息", page)
        self.assertNotIn("开课保障核查", page)
        self.assertNotIn("先核查运行证据", page)
        self.assertIn("查看开课保障研判", page)
        self.assertNotIn("查看 AI 开课保障研判", page)
        self.assertNotIn("当前未达到复合风险 AI 介入条件。", page)
        self.assertIn('v-if="offeringNeedsAi(selectedOffering)" class="review-actions"', page)
        self.assertIn(
            "按大班额、单一教师多班覆盖和单班集中供给排序，不是课程质量排名",
            page,
        )

    def test_curriculum_student_list_uses_review_queue_labels(self):
        curriculum = self.read("frontend/src/views/admin/curriculum/index.vue")
        self.assertIn("{key:'failedRequired',label:'必修未通过'", curriculum)
        self.assertIn("{key:'verificationRequired',label:'过期漏修'", curriculum)
        self.assertIn("studentEvidenceStatusLabel(row.evidenceStatus)", curriculum)
        self.assertIn("'明确需处理':'必修未通过'", curriculum)
        self.assertIn("'数据候选':'过期漏修'", curriculum)
        student_columns = curriculum[curriculum.index("const studentListColumns"):]
        ordered_columns = (
            "{key:'majorName',label:'专业'",
            "{key:'studentStatus',label:'学籍状态'",
            "{key:'evidenceStatus',label:'状态'",
            "{key:'statusReason',label:'状态原因'",
        )
        positions = [student_columns.index(column) for column in ordered_columns]
        self.assertEqual(sorted(positions), positions)
        self.assertIn('storage-key="curriculum:management-students" :max-business-columns="10"', curriculum)
        self.assertIn(':config-version="5" :page-size="studentDialog.pageSize"', curriculum)

        college_columns = curriculum[
            curriculum.index("const collegeColumns"):curriculum.index("const majorColumns")
        ]
        self.assertIn("{key:'actionRequired',label:'必修未通过'", college_columns)
        self.assertNotIn("{key:'actionRequired',label:'明确问题'", college_columns)
        self.assertIn("`${row.collegeName}｜必修未通过`", curriculum)

    def test_curriculum_plan_structure_module_is_hidden(self):
        curriculum = self.read("frontend/src/views/admin/curriculum/index.vue")
        router = self.read("frontend/src/router/index.ts")
        self.assertIn("const showPlanStructure = false", curriculum)
        self.assertIn(
            '<el-tab-pane v-if="showPlanStructure" label="方案结构与要求" name="plan">',
            curriculum,
        )
        self.assertIn("...(showPlanStructure ? ['plan'] : [])", curriculum)
        self.assertNotIn("当前分析方案", curriculum)
        self.assertNotIn("query:{ tab:'plan'", router)
        self.assertEqual(router.count("redirect: '/admin/curriculum'"), 2)

    def test_curriculum_progress_uses_review_queue_labels_and_reason(self):
        curriculum = self.read("frontend/src/views/admin/curriculum/index.vue")
        progress = self.read("frontend/src/views/admin/curriculum/Progress.vue")
        progress_tab = curriculum[curriculum.index('<el-tab-pane label="学生进度核查"'):]
        filter_order = tuple(
            progress_tab.index(f'placeholder="{label}"')
            for label in ("年级", "学院", "专业", "培养方案")
        )
        self.assertEqual(tuple(sorted(filter_order)), filter_order)
        self.assertLess(filter_order[-1], progress_tab.index('@click="queryProgress">查询</el-button>'))
        self.assertLess(filter_order[-1], progress_tab.index('@click="resetProgressFilters">重置</el-button>'))
        self.assertIn(':major-id="appliedProgressPlan"', progress_tab)
        self.assertIn("function queryProgress()", curriculum)
        self.assertIn("function resetProgressFilters()", curriculum)
        self.assertIn("new Set<number>(overviewFilterRows.value", curriculum)
        self.assertIn(".sort((a,b) => b-a).slice(0,5)", curriculum)
        self.assertIn("const progressPlans = ref<any[]>([])", curriculum)
        self.assertIn("Array.isArray(d.progressPlans)", curriculum)
        self.assertIn("Number(a.grade??Number.MAX_SAFE_INTEGER)-Number(b.grade??Number.MAX_SAFE_INTEGER)", curriculum)
        self.assertIn("grade.value=requested?.grade ?? grades.value[0] ?? ''", curriculum)
        self.assertIn("const first = requested || availablePlans.value[0]", curriculum)
        self.assertIn(':label="x.planName"', progress_tab)
        self.assertNotIn('`${x.planName} · ${x.coverageLabel}`', progress_tab)
        self.assertNotIn("按培养方案模块规则核查学生进度", progress)
        self.assertNotIn("definition.boundary", progress)
        self.assertIn('label="必修未通过学生"', progress)
        self.assertIn('label="过期漏修学生"', progress)
        self.assertIn("{key:'failedRequired',label:'必修未通过'", progress)
        self.assertIn("{key:'verificationRequired',label:'过期漏修'", progress)
        self.assertIn("{key:'status',label:'状态'", progress)
        self.assertIn("{key:'statusReason',label:'状态原因'", progress)
        self.assertIn('placeholder="全部状态"', progress)
        self.assertIn('@click="exportCsv">导出</el-button>', progress)
        self.assertNotIn("导出当前结果", progress)
        self.assertIn('<el-descriptions-item label="状态">', progress)
        self.assertNotIn('<el-descriptions-item label="证据状态">', progress)
        self.assertNotIn("本详情只核查培养方案执行证据", progress)
        self.assertIn('<el-option label="必修未通过" value="明确需处理"', progress)
        self.assertIn('<el-option label="过期漏修" value="数据候选"', progress)
        self.assertIn("{{statusLabel(row.status)}}", progress)
        self.assertIn("statusLabel(r.status)", progress)
        self.assertIn('#col-statusReason="{row}"', progress)
        self.assertIn("statusReasonLabel(row)", progress)
        self.assertIn("statusReasonLabel(r)", progress)
        self.assertIn("explicit_gap:'必修未通过',candidate:'过期漏修'", progress)
        self.assertIn("{key:'failedRequired',label:'必修未通过'", progress)
        self.assertIn("{key:'verificationRequired',label:'过期漏修'", progress)
        self.assertIn("`必修未通过课程（${failedCourses.length}）`", progress)
        self.assertIn("`过期漏修课程（${verificationCourses.length}）`", progress)
        self.assertNotIn("明确未解决课程", progress)
        self.assertNotIn("数据候选课程", progress)
        expected_tooltips = (
            "逐一核查该学生培养方案中的所有模块；优先比较已认可学分与最低学分，其次比较已完成门数与最低门数，最后核查模块内必修课程是否全部通过或认定",
            "该学生当前绑定培养方案中，所有课程及其最新结果状态的记录数，包括通过、替代或认定、未通过、尚无完成证据和证据未知",
        )
        for tooltip in expected_tooltips:
            self.assertIn(f'content="{tooltip}"', progress)
        self.assertEqual(2, progress.count('class="tab-help-icon"'))

    def test_curriculum_student_evidence_uses_due_study_result_labels(self):
        curriculum = self.read("frontend/src/views/admin/curriculum/index.vue")
        self.assertIn('class="description-label-with-help">必修未通过', curriculum)
        self.assertIn('aria-label="查看必修未通过计算说明"', curriculum)
        self.assertIn('<h4 class="evidence-title">必修未通过课程</h4>', curriculum)
        self.assertIn('empty-text="当前没有必修未通过课程"', curriculum)
        self.assertNotIn('class="description-label-with-help">明确未通过', curriculum)
        self.assertNotIn('>明确未通过必修课程 <small>', curriculum)
        self.assertNotIn('可直接进入重修与课程保障核查', curriculum)
        self.assertIn('class="description-label-with-help">到期缺修读结果', curriculum)
        self.assertIn('<h4 class="evidence-title">到期缺修读结果记录</h4>', curriculum)
        self.assertIn('empty-text="当前没有到期缺修读结果"', curriculum)
        self.assertNotIn('label="到期缺结果候选"', curriculum)
        self.assertNotIn('>到期缺结果记录候选 <small>', curriculum)
        self.assertNotIn('必须先核验选课、免修与认定数据', curriculum)

    def test_curriculum_overview_cards_disclose_display_limits(self):
        curriculum = self.read("frontend/src/views/admin/curriculum/index.vue")
        for title, note in (
            ("学院方案执行关注", "当前最多仅展示前 30 个学院"),
            ("专业执行关注", "当前最多仅展示前 50 个专业"),
            ("必修课程瓶颈", "当前最多仅展示前 20 门课程"),
        ):
            self.assertIn(
                f'<div class="sa-card-title">{title} <span class="extra">{note}</span></div>',
                curriculum,
            )

    def test_curriculum_student_evidence_summary_has_metric_tooltips(self):
        curriculum = self.read("frontend/src/views/admin/curriculum/index.vue")
        expected = (
            "该学生的必修课程中，教学任务里没有找到任何历史教学班记录的课程数",
            "该学生尚未达到要求的培养方案模块中，当前有效成绩仍为未通过的必修课程数",
            "该学生尚未达到要求的培养方案模块中，建议修读学期已过，但尚未形成明确修读结果的必修课程数",
        )
        for tooltip in expected:
            self.assertIn(f'content="{tooltip}"', curriculum)
        self.assertEqual(curriculum.count('class="description-label-with-help"'), 3)
        self.assertEqual(curriculum.count('class="description-help-icon"'), 3)

    def test_alert_monitor_followup_ui_contract(self):
        monitor = self.read("frontend/src/views/admin/alert/index.vue")
        self.assertIn("<b>查询条件</b>", monitor)
        self.assertNotIn("<b>当前快照</b>", monitor)
        self.assertIn("key: 'grade', label: '年级'", monitor)
        self.assertIn('config-version="3"', monitor)
        self.assertIn("latestGeneratedDate || meta.dataAsOf", monitor)
        self.assertIn("nameGap: 12", monitor)
        self.assertIn("position: 'insideEndTop'", monitor)
        self.assertIn("rotate: 0", monitor)
        self.assertEqual(2, monitor.count(':height="395"'))
        self.assertIn(".chart-card { height: 495px; }", monitor)
        self.assertIn("fourKpiPresetExpectedTotal", monitor)

    def test_early_setback_followup_ui_contract(self):
        page = self.read("frontend/src/views/admin/reports/EarlySetback.vue")
        self.assertNotIn("群体筛查不等于个人原因判断", page)
        self.assertNotIn("学生指标均按学号去重", page)
        self.assertNotIn("不同年级的后续观察时长不同", page)
        self.assertNotIn("用于识别基础课程支持方向", page)
        self.assertIn("<b>观察条件</b>", page)
        self.assertIn('placeholder="学院"', page)
        self.assertIn('placeholder="专业"', page)
        self.assertIn('placeholder="班级"', page)
        self.assertIn('placeholder="年级"', page)
        self.assertIn("focusTitle", page)
        self.assertIn("focusDescription", page)
        self.assertIn("applyKpiPreset", page)
        self.assertIn("studentListSection", page)
        self.assertLess(page.index('placeholder="年级"'), page.index('placeholder="班级"'))
        student_columns = page[page.index("const studentColumns"):]
        self.assertLess(
            student_columns.index("{ key: 'organization_name', label: '学院'"),
            student_columns.index("{ key: 'major_name', label: '专业'"),
        )
        self.assertLess(
            student_columns.index("{ key: 'class_code', label: '班级'"),
            student_columns.index("{ key: 'entry_grade', label: '年级'"),
        )
        drawer = self.read("frontend/src/views/admin/alert/EarlySetbackDrawer.vue")
        self.assertIn("no_setback: '大一未出现未通过'", drawer)
        self.assertNotIn("这是核查线索，不是个人原因判断", drawer)
        self.assertNotIn("历史预警用于理解风险变化", drawer)
        self.assertNotIn("本专题不自动建立帮扶任务", drawer)
        self.assertIn("student.value.semesterSummary", drawer)
        self.assertIn("point.semester", drawer)
        self.assertNotIn("`学期${index + 1}`", drawer)

    def test_college_comparison_separates_compare_and_drill(self):
        dashboard = self.read("frontend/src/views/admin/dashboard/index.vue")
        self.assertIn("/admin/meta/college-comparison", dashboard)
        self.assertIn("if (!row.canDrillDown) return", dashboard)
        self.assertIn("仅可比较", dashboard)

    def test_teacher_load_followup_ui_contract(self):
        page = self.read("frontend/src/views/admin/operation/TeacherLoad.vue")
        self.assertLess(page.index('placeholder="全部学院"'), page.index('placeholder="全部职称"'))
        self.assertNotIn("真实教学任务 ·", page)
        self.assertNotIn(":title=\"data.workloadPolicy.statement\"", page)
        self.assertIn(':title="`查看 ${qualityIssueCount} 条数据质量问题明细`"', page)
        self.assertIn('v-model="qualityPanels"', page)
        self.assertIn('>详情</el-button>', page)
        self.assertNotIn('>核查</el-button>', page)
        for label in ("学期", "教师", "问题说明", "处置建议"):
            self.assertIn(f'label="{label}"', page)
        self.assertNotIn(":description=\"data.dataQuality.policy\"", page)
        self.assertNotIn(":title=\"data.topTeacherPolicy.boundary\"", page)
        self.assertIn("teacherNeedsAi(row)?'重点关注':'需关注'", page)
        self.assertIn("$index<3?'优先关注'", page)
        self.assertNotIn('@row-click="goCollege"', page)
        self.assertNotIn("row-class-name=\"row-clickable\"", page)
        self.assertIn("｜教学负荷信息", page)
        self.assertNotIn("当前不在本轮前三名 AI 重点", page)
        self.assertIn(">查看负荷研判</el-button>", page)
        self.assertIn('title="教师负荷研判"', page)
        for prop in (
            "hide-intervention-tag", "hide-decision-meta", "hide-baseline",
            "hide-consequence", "hide-expected-result", "hide-no-comparison-tag",
            "hide-trace", "hide-trace-shortcut", "hide-evidence-help", "hide-evidence-source",
            "show-all-evidence",
        ):
            self.assertIn(prop, page)
        normalizer = self.read("frontend/src/utils/aiInsight.ts")
        self.assertIn("item.action !== primaryAction.action", normalizer)

    def test_operation_formal_tables_follow_public_table_contract(self):
        expected_storage_keys = {
            "frontend/src/views/admin/operation/Courses.vue": (
                "operation:courses-top10", "operation:courses-college", "operation:courses-all",
            ),
            "frontend/src/views/admin/operation/ScheduleAnalysis.vue": (
                "operation:schedule-focus",
            ),
            "frontend/src/views/admin/operation/Classroom.vue": (
                "operation:classroom-buildings",
            ),
            "frontend/src/views/admin/operation/TeacherLoad.vue": (
                "operation:teacher-load-title", "operation:teacher-load-review",
                "operation:teacher-load-college",
            ),
            "frontend/src/views/admin/operation/ScheduleChanges.vue": (
                "operation:schedule-changes-dept", "operation:schedule-changes-teachers",
            ),
            "frontend/src/views/admin/reports/CourseQuality.vue": (
                "reports:course-quality-public", "reports:course-quality",
            ),
        }
        for page, storage_keys in expected_storage_keys.items():
            source = self.read(page)
            self.assertIn("DataTable", source, page)
            for storage_key in storage_keys:
                self.assertIn(storage_key, source, page)

    def test_course_quality_uses_one_summary_request_and_drawer_detail(self):
        frontend = self.read("frontend/src/views/admin/reports/CourseQuality.vue")
        backend = self.read("backend/api/routers/v2.py")
        self.assertNotIn("loadPublic", frontend)
        self.assertIn("publicRequiredTop", frontend)
        self.assertIn("<el-drawer", frontend)
        self.assertIn('"publicRequiredTop": public_required[:10]', backend)
        self.assertIn("filtered_courses", backend)


if __name__ == "__main__":
    unittest.main()

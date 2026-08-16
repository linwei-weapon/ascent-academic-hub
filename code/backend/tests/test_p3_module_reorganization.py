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
            "frontend/src/views/admin/operation/Index.vue",
            "frontend/src/views/admin/curriculum/index.vue",
            "frontend/src/views/admin/faculty/Index.vue",
            "frontend/src/views/admin/students/Analysis.vue",
        ):
            self.assertIn("BusinessPageContext", self.read(page), page)
        alert = self.read("frontend/src/views/admin/alert/Workspace.vue")
        self.assertNotIn("BusinessPageContext", alert)
        self.assertIn("最新预警统计时间", alert)

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

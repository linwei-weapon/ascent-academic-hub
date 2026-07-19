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
        self.assertIn('label="毕业准备核查"', curriculum)
        self.assertIn("<GraduationReadiness", curriculum)
        self.assertIn('label="课程质量核查"', operation)
        self.assertIn("<CourseQuality", operation)
        self.assertIn("provide('operationSemester', sharedSemester)", operation)

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
            "frontend/src/views/admin/alert/Workspace.vue",
        ):
            self.assertIn("BusinessPageContext", self.read(page), page)

    def test_college_comparison_separates_compare_and_drill(self):
        dashboard = self.read("frontend/src/views/admin/dashboard/index.vue")
        self.assertIn("/admin/meta/college-comparison", dashboard)
        self.assertIn("if (!row.canDrillDown) return", dashboard)
        self.assertIn("仅可比较", dashboard)


if __name__ == "__main__":
    unittest.main()

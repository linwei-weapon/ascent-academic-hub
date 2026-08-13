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
        self.assertIn("不使用未披露的综合风险分", analysis)
        self.assertIn(":max-business-columns=\"8\"", analysis)
        self.assertNotIn("学位授予率", analysis)
        self.assertNotIn("毕业率", analysis)

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
        self.assertIn("数据来源与适用边界", drawer)

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

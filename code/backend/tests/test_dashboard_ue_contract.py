# -*- coding: utf-8 -*-
"""教学数据总览前端公共体验契约的静态门禁。"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "code" / "frontend" / "src"


class DashboardUeContractTest(unittest.TestCase):
    def test_data_table_supports_required_columns_limits_and_identity_scoping(self):
        source = (FRONTEND / "components" / "DataTable.vue").read_text(encoding="utf-8")
        for marker in (
            "required?: boolean",
            "region?: 'identity' | 'business' | 'action'",
            "maxBusinessColumns?: number",
            "configVersion?: string | number",
            "activeIdentityId",
            ":draggable=\"columnRegion(c) === 'business'\"",
            "为保证可读性，当前最多显示",
            "恢复默认",
        ):
            self.assertIn(marker, source)

    def test_dashboard_path_tables_use_public_component(self):
        targets = [
            FRONTEND / "views" / "admin" / "dashboard" / "index.vue",
            FRONTEND / "views" / "admin" / "dashboard" / "Detail.vue",
            FRONTEND / "views" / "admin" / "dashboard" / "MajorDetail.vue",
            FRONTEND / "views" / "admin" / "dashboard" / "CourseDetail.vue",
            FRONTEND / "views" / "admin" / "students" / "List.vue",
        ]
        for target in targets:
            source = target.read_text(encoding="utf-8")
            self.assertIn("<DataTable", source, target.name)
            self.assertNotIn("<el-table", source, target.name)
            self.assertIn("max-business-columns", source, target.name)
            self.assertIn("config-version", source, target.name)

    def test_dashboard_home_is_management_oriented_and_request_safe(self):
        backend = (
            ROOT / "code" / "backend" / "api" / "routers" / "dashboard.py"
        ).read_text(encoding="utf-8")
        frontend = (
            FRONTEND / "views" / "admin" / "dashboard" / "index.vue"
        ).read_text(encoding="utf-8")
        for marker in (
            '"managementSummary": management_summary',
            '"managementFocus": management_focus',
            '"previousSemester": previous_semester',
            '"selectionReason": "；".join(reasons)',
            "_DASHBOARD_CACHE_TTL_SECONDS",
            "scopeFingerprint",
        ):
            self.assertIn(marker, backend)
        for marker in (
            "本期管理判断",
            "优先核查事项",
            "学院偏离与变化",
            "本学期重点核查课程 TOP10",
            "dashboardRequestSeq",
            "正在按 {{ fSemester }} 更新，当前结果暂时保留",
        ):
            self.assertIn(marker, frontend)
        self.assertNotIn("应届毕业质量指标", frontend)

    def test_detail_pages_explain_priority_and_keep_long_lists_in_context(self):
        backend = (
            ROOT / "code" / "backend" / "api" / "routers" / "dashboard.py"
        ).read_text(encoding="utf-8")
        college = (
            FRONTEND / "views" / "admin" / "dashboard" / "Detail.vue"
        ).read_text(encoding="utf-8")
        major = (
            FRONTEND / "views" / "admin" / "dashboard" / "MajorDetail.vue"
        ).read_text(encoding="utf-8")
        course = (
            FRONTEND / "views" / "admin" / "dashboard" / "CourseDetail.vue"
        ).read_text(encoding="utf-8")
        for marker in (
            '"currentFailVsCollegePp"',
            '"priorityReason"',
            '"needsPriorityReview"',
            '"riskRank"',
            '"classSummary"',
            '"affectedStudents"',
            '"selectionReason"',
        ):
            self.assertIn(marker, backend)
        for marker in (
            "专业偏离与优先核查",
            "优先核查课程 TOP6",
            "pageLoading",
            "loadError",
        ):
            self.assertIn(marker, college)
        for marker in (
            "年级风险核查",
            "默认展开最需关注年级",
            "activeGrade",
            "priorityReason",
        ):
            self.assertIn(marker, major)
        self.assertNotIn("毕业去向分布", major)
        for marker in (
            "高风险行政班 TOP10",
            "查看全部 {{ data.classDetail.length }} 个行政班",
            "<el-drawer",
            "topClassRows",
            ':pagination="true"',
            "watch(() => route.fullPath",
        ):
            self.assertIn(marker, course)

    def test_drill_navigation_preserves_list_and_scroll_context(self):
        college = (
            FRONTEND / "views" / "admin" / "dashboard" / "Detail.vue"
        ).read_text(encoding="utf-8")
        student = (
            FRONTEND / "views" / "admin" / "student" / "Detail.vue"
        ).read_text(encoding="utf-8")
        router = (
            FRONTEND / "router" / "index.ts"
        ).read_text(encoding="utf-8")
        self.assertIn("returnTo:route.fullPath", college)
        self.assertLess(
            student.index("if (from === 'list')"),
            student.index("if (returnTo)"),
        )
        self.assertIn("savedPosition || { top: 0 }", router)
        student_list = (
            FRONTEND / "views" / "admin" / "students" / "List.vue"
        ).read_text(encoding="utf-8")
        self.assertIn("function currentListQuery()", student_list)
        self.assertIn("page: page.value > 1 ? String(page.value)", student_list)
        self.assertIn("await syncListState()", student_list)
        self.assertIn("window.scrollTo({ top: restoredScroll", student_list)


if __name__ == "__main__":
    unittest.main()

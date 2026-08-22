# -*- coding: utf-8 -*-
"""教学数据总览前端公共体验契约的静态门禁。"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "code" / "frontend" / "src"
BACKEND = ROOT / "code" / "backend"


class DashboardUeContractTest(unittest.TestCase):
    def test_alert_student_list_query_and_reset_keep_the_list_baseline(self):
        alert_page = (
            FRONTEND / "views" / "admin" / "alert" / "index.vue"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '@click="applyListFilters">\n            查询\n          </el-button>',
            alert_page,
        )
        self.assertIn('@click="resetListFilters">重置</el-button>', alert_page)
        self.assertNotIn(
            '@click="applyListFilters">\n            筛选名单\n          </el-button>',
            alert_page,
        )
        self.assertNotIn("清除名单筛选", alert_page)

        apply_block = alert_page.split(
            "function applyListFilters()", 1,
        )[1].split("function resetListFilters()", 1)[0]
        reset_block = alert_page.split(
            "function resetListFilters()", 1,
        )[1].split("function clearCardPreset()", 1)[0]
        self.assertNotIn("clearCardPreset()", apply_block)
        self.assertNotIn("clearCardPreset()", reset_block)
        self.assertIn(
            "Object.assign(listDraft, emptyListFilter())", reset_block,
        )
        self.assertIn(
            "Object.assign(listApplied, emptyListFilter())", reset_block,
        )

    def test_rule_discovery_requires_manifest_consent_and_shows_run_status(self):
        discovery = (
            FRONTEND / "views" / "admin" / "alert" / "Discovery.vue"
        ).read_text(encoding="utf-8")
        for marker in (
            "本次计算样本库表总数",
            "样本数据总量",
            "样本学生数",
            "样本库表数据清单",
            "数据脱敏说明",
            "免责说明协议",
            "拒绝",
            "执行",
            "/admin/settings/rules/discovery/preview",
            "/admin/settings/rules/discovery/status",
            "manifestFingerprint",
            "consentAccepted",
            ':disabled="!consentAccepted"',
            "setInterval",
            "新一轮分析运行中",
        ):
            self.assertIn(marker, discovery)
        self.assertNotIn("新一轮分析会将当前待审核建议标记", discovery)
        self.assertNotIn('class="model-boundary"', discovery)
        self.assertNotIn("<span>数据总量</span>", discovery)
        self.assertNotIn("<span>可分析学生</span>", discovery)
        self.assertNotIn("<h4>库表数据清单</h4>", discovery)

    def test_draft_rule_change_supports_trial_script_maintenance(self):
        settings = (
            FRONTEND / "views" / "admin" / "settings" / "index.vue"
        ).read_text(encoding="utf-8")
        for marker in (
            "试算脚本维护",
            "普通SQL",
            "存储过程",
            "scriptDialogVisible",
            "/trial-script",
            "保存",
            "取消",
        ):
            self.assertIn(marker, settings)

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
            "分别显示学院偏离与重点课程排序后的全局 TOP1",
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
            "本学院所有专业偏离与核查",
            "学院偏离与变化",
            "学院偏离与变化加载失败",
            "comparisonError",
            "优先核查课程 TOP6",
            "pageLoading",
            "loadError",
        ):
            self.assertIn(marker, college)
        readonly_start = college.index('data-testid="college-deviation-readonly"')
        readonly_end = college.index("<!-- 各年级修读结果", readonly_start)
        readonly_section = college[readonly_start:readonly_end]
        self.assertNotIn("@row-click", readonly_section)
        self.assertNotIn("goStudents", readonly_section)
        self.assertNotIn("key: 'drill'", readonly_section)
        self.assertIn('class="grade-result-column" :span="24" :lg="8"', college)
        self.assertIn('class="focus-course-column" :span="24" :lg="16"', college)
        for removed_copy in (
            "证据与口径说明",
            "与总览首页使用同一全校聚合口径；学院名称只读，不提供下钻",
            "学院名称只读；本表不提供学院详情或学生名单下钻。",
        ):
            self.assertNotIn(removed_copy, college)
        for marker in (
            "年级风险核查",
            "按入学年级倒序固定排列",
            "activeGrade",
            "priorityReason",
        ):
            self.assertIn(marker, major)
        self.assertNotIn("毕业去向分布", major)
        for marker in (
            "全部行政班",
            "有效成绩人次",
            ':pagination="true"',
            "watch(() => route.fullPath",
        ):
            self.assertIn(marker, course)
        self.assertNotIn("topClassRows", course)
        self.assertNotIn("classDrawer", course)

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

    def test_0726_history_and_new_drill_contracts_are_explicit(self):
        history = (
            FRONTEND / "components" / "MetricHistoryDialog.vue"
        ).read_text(encoding="utf-8")
        history_utils = (
            FRONTEND / "utils" / "dashboardHistory.ts"
        ).read_text(encoding="utf-8")
        for marker in (
            "历史指标查询条件",
            "起始学期",
            "结束学期",
            "“-”：表示学年学期对应内容无数据或无计算结果。",
            "历史指标加载失败",
            "当前范围暂无可绘制的历史数据",
            "正在按新条件更新，当前结果暂时保留",
            "restoreFocus",
            "semesterOptions",
            "option.label",
            "option.value",
        ):
            self.assertIn(marker, history)
        self.assertNotIn("semesterLabel", history_utils)
        self.assertNotIn("sortSemesterValuesDescending", history_utils)
        self.assertNotIn("sortHistoryPeriodsDescending", history_utils)
        self.assertNotIn("DASHBOARD_SEMESTERS", history_utils)
        self.assertNotIn("name: '人数/人次'", history)
        self.assertNotIn("name: unit || '%'", history)
        self.assertNotIn("'其余'", history)
        self.assertIn("numeratorLabel", history)
        self.assertIn("denominatorLabel", history)
        self.assertIn("data: rows.map((row: any) => row.denominator)", history)
        self.assertIn("barGap: '-100%'", history)
        self.assertIn("`${Number(value).toLocaleString('zh-CN')}${countUnit}`", history)
        self.assertIn("`${value}%`", history)
        self.assertIn("history-chart-legend", history)
        self.assertIn("legend-swatch outline", history)
        self.assertIn("legend-swatch bar", history)
        self.assertIn("legend-swatch line", history)
        self.assertIn("legend: { show: false }", history)
        self.assertIn("color: 'transparent'", history)
        self.assertIn("borderType: 'dashed'", history)
        self.assertNotIn("itemStyle: { color: '#e2e8f0' }", history)
        self.assertIn("value == null ? '-' :", history)
        self.assertNotIn("value == null ? '不可用' :", history)
        self.assertIn("changeText: row.change == null ? '-' :", history)
        self.assertNotIn("unit === '%' ? '个百分点' : ''", history)
        self.assertNotIn("key: 'status', label: '数据状态'", history)
        self.assertNotIn("#col-status", history)
        for page_name in ("index.vue", "Detail.vue", "MajorDetail.vue"):
            page = (
                FRONTEND / "views" / "admin" / "dashboard" / page_name
            ).read_text(encoding="utf-8")
            self.assertIn(':semester-options="semesters"', page)

        major_alerts = (
            FRONTEND / "components" / "MajorAlertStudentsDialog.vue"
        ).read_text(encoding="utf-8")
        for marker in (
            "姓名或学号", "行政班", "风险等级", "预警类型", "核查状态",
            "最高风险", "主要触发证据", "规则命中", "最近变化时间",
            "AlertStudentDrawer", "统计学期：{{ semester }}",
        ):
            self.assertIn(marker, major_alerts)
        self.assertIn("semester?: string", major_alerts)
        alert_student_drawer = (
            FRONTEND / "views" / "admin" / "alert" / "AlertStudentDrawer.vue"
        ).read_text(encoding="utf-8")
        self.assertIn('label="预警核查摘要" name="summary"', alert_student_drawer)
        self.assertNotIn('label="核查摘要" name="summary"', alert_student_drawer)
        self.assertIn("label: '所有未通过课程'", alert_student_drawer)
        self.assertIn("studySummary?.failed?.historicalCourses", alert_student_drawer)
        self.assertIn("student.value.failTrace || []", alert_student_drawer)
        self.assertIn("item.courseId || item.courseName", alert_student_drawer)
        self.assertNotIn("label: '当前未解决课程'", alert_student_drawer)
        self.assertIn('v-for="(alert, index) in criticalAlertHistory"', alert_student_drawer)
        self.assertIn('class="sa-card trajectory-group"', alert_student_drawer)
        self.assertIn(':show-header="index === 0"', alert_student_drawer)
        self.assertIn('grouped', alert_student_drawer)
        self.assertIn("student.value.alertHistory || []", alert_student_drawer)
        self.assertIn("alert.level === '严重'", alert_student_drawer)
        self.assertIn(':rule-id="alert.ruleId"', alert_student_drawer)
        self.assertNotIn('v-if="primarySignal"', alert_student_drawer)
        alert_router = (
            BACKEND / "api" / "routers" / "alert.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"ruleId": a["rule_id"]', alert_router)
        trajectory_card = (
            FRONTEND / "views" / "admin" / "alert" / "TrajectoryCard.vue"
        ).read_text(encoding="utf-8")
        self.assertIn("同类预警后续轨迹", trajectory_card)
        self.assertIn('v-if="showHeader"', trajectory_card)
        self.assertIn('grouped?: boolean', trajectory_card)
        self.assertIn("'traj-card--grouped': grouped", trajectory_card)
        self.assertNotIn("后续轨迹：可观察", trajectory_card)
        self.assertNotIn("发生在当前学期，尚无后续学期数据", trajectory_card)

        major_detail = (
            FRONTEND / "views" / "admin" / "dashboard" / "MajorDetail.vue"
        ).read_text(encoding="utf-8")
        self.assertIn(':semester="semLabel"', major_detail)

        grade_courses = (
            FRONTEND / "components" / "GradeCoursesDrawer.vue"
        ).read_text(encoding="utf-8")
        for marker in (
            "课程代码或名称", "课程代码", "课程名称",
            "未通过人次", "有效成绩人次", "未通过人次率",
        ):
            self.assertIn(marker, grade_courses)
        self.assertIn("{{ semester }}", grade_courses)

        course_detail = (
            FRONTEND / "views" / "admin" / "dashboard" / "CourseDetail.vue"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sortHistoryPeriodsDescending", course_detail)
        student_evidence = (
            FRONTEND / "components" / "StudentEvidenceDrawer.vue"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sortHistoryPeriodsDescending", student_evidence)
        self.assertIn("return rows.reverse()", student_evidence)

        router = (FRONTEND / "router" / "index.ts").read_text(encoding="utf-8")
        menu = (FRONTEND / "utils" / "menu.ts").read_text(encoding="utf-8")
        student_list = (
            FRONTEND / "views" / "admin" / "students" / "List.vue"
        ).read_text(encoding="utf-8")
        self.assertIn("course/:id/students", router)
        self.assertIn("path.startsWith('/admin/course/')", menu)
        self.assertIn("课程-学生学业画像", student_list)
        self.assertIn(":disabled=\"courseProfile\"", student_list)
        self.assertIn("label: '课程成绩'", student_list)
        self.assertIn("label: '课程成绩绩点(GP)'", student_list)
        self.assertNotIn("label: '本课程成绩'", student_list)
        self.assertNotIn("label: '本课程绩点'", student_list)
        self.assertNotIn("预警状态", student_list)
        self.assertNotIn("当前页识别出", student_list)
        self.assertNotIn("AI 重点学生", student_list)


if __name__ == "__main__":
    unittest.main()

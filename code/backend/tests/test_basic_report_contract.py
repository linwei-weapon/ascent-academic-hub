import unittest
import sqlite3
from inspect import signature
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import load_workbook

from backend.api.basic_reports.catalog import REPORTS
from backend.api.basic_reports.exporter import build_workbook
from backend.api.basic_reports.rule_registry import REPORT_RULES, RULES, RULE_VERSION
from backend.api.basic_reports.service import (
    _cet4_passed_ids_as_of,
    _failure_sets,
    _focus_rule_metadata,
    _pct,
    _rank_cet4_rows,
    _report_01,
    _report_02,
    _report_04a,
    _report_07,
    _rpt07_data_fingerprint,
    _report_title,
    _responsibility_grade,
    _student_cte,
    _title_scope_labels,
    build_report,
)
from scripts.migrate_basic_reports import _remove_stale_bindings
from backend.api.routers.basic_reports import (
    _normalize_class_code,
    _normalize_major_code,
    query_report,
)


class BasicReportContractTest(unittest.TestCase):
    def test_catalog_has_nine_unique_reports_and_rules(self):
        self.assertEqual(9, len(REPORTS))
        self.assertEqual(9, len({item.menu_path for item in REPORTS.values()}))
        self.assertEqual(set(REPORTS), set(REPORT_RULES))
        for report_id, rule_ids in REPORT_RULES.items():
            self.assertTrue(rule_ids, report_id)
            self.assertTrue(set(rule_ids) <= set(RULES), report_id)

    def test_rpt02_has_dedicated_student_rate_rule(self):
        self.assertEqual("basic-report-v1.5", RULE_VERSION)
        self.assertIn("BR-RETAINED-DEMOTED", REPORT_RULES["RPT-02"])
        self.assertIn("BR-MAJOR-MAKEUP-COMPARISON", REPORT_RULES["RPT-02"])
        self.assertNotIn("BR-MAKEUP-PASS", REPORT_RULES["RPT-02"])
        self.assertIn("BR-MAKEUP-PASS", REPORT_RULES["RPT-05"])

    def test_basic_report_migration_removes_only_stale_managed_bindings(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE sys_metric_page_binding(metric_id TEXT,page_path TEXT)")
        rpt02_page = REPORTS["RPT-02"].menu_path
        conn.executemany("INSERT INTO sys_metric_page_binding VALUES(?,?)", [
            ("BR-MAKEUP-PASS", rpt02_page),
            ("BR-MAJOR-MAKEUP-COMPARISON", rpt02_page),
            ("CUSTOM-RULE", rpt02_page),
            ("BR-MAKEUP-PASS", "/admin/other-page"),
        ])
        self.assertEqual(1, _remove_stale_bindings(conn))
        self.assertEqual(
            {
                ("BR-MAJOR-MAKEUP-COMPARISON", rpt02_page),
                ("CUSTOM-RULE", rpt02_page),
                ("BR-MAKEUP-PASS", "/admin/other-page"),
            },
            set(conn.execute("SELECT metric_id,page_path FROM sys_metric_page_binding")),
        )
        conn.close()

    def test_failure_sets_count_current_result_without_requiring_regular_attempt(self):
        pairs = [
            {"studentId": "S1", "courseId": "C1", "firstPass": 0, "currentPass": 1},
            {"studentId": "S1", "courseId": "C2", "firstPass": 0, "currentPass": 0},
            {"studentId": "S2", "courseId": "C3", "firstPass": None, "currentPass": 0},
        ]
        first, current, doors = _failure_sets(pairs)
        self.assertEqual({"S1"}, first)
        self.assertEqual({"S1", "S2"}, current)
        self.assertEqual({"S1": 1, "S2": 1}, dict(doors))
        self.assertIsNone(_pct(1, 0))
        self.assertEqual(0.333333, _pct(1, 3))

    def test_export_contains_result_explanation_and_rule_sheets(self):
        payload = {"reportId": "RPT-01", "title": "测试报表", "status": "available",
                   "rows": [{"categoryKey": "total", "category": "总人数（留降级：2）：10",
                             "gender": "男", "countDisplay": "6（1）", "rate": .6}],
                   "context": {"ruleVersion": "basic-report-v1.1"},
                   "rules": [{"ruleId": "BR-X", "formula": "x"}], "boundary": ["只读"]}
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        self.assertEqual(["报表结果", "报表说明", "口径规则"], workbook.sheetnames)
        self.assertEqual(["本科生", "性别", "人数", "比例"], [cell.value for cell in workbook["报表结果"][1]])
        self.assertEqual("0.00%", workbook["报表结果"]["D2"].number_format)
        self.assertEqual("6（1）", workbook["报表结果"]["C2"].value)

    def test_rpt01_displays_total_and_retained_demoted_counts(self):
        students = [
            {"student_id": "S1", "gender": "男"},
            {"student_id": "S2", "gender": "男"},
            {"student_id": "S3", "gender": "女"},
        ]
        pairs = [
            {"studentId": "S1", "courseId": "C1", "firstPass": 0, "currentPass": 0},
            {"studentId": "S2", "courseId": "C2", "firstPass": 1, "currentPass": 1},
            {"studentId": "S3", "courseId": "C3", "firstPass": 0, "currentPass": 1},
        ]
        retained = [
            {"student_id": "R1", "gender": "男"},
            {"student_id": "R2", "gender": "女"},
        ]
        pairs.extend([
            {"studentId": "R1", "courseId": "C4", "firstPass": 0, "currentPass": 0},
            {"studentId": "R2", "courseId": "C5", "firstPass": 0, "currentPass": 1},
        ])
        rows, summary = _report_01(students, pairs, retained)
        self.assertEqual("总人数（留降级：2）：3", rows[0]["category"])
        self.assertEqual("2（1）", rows[0]["countDisplay"])
        self.assertEqual("1（1）", rows[1]["countDisplay"])
        self.assertEqual("已挂人数（留降级：2）：2", rows[2]["category"])
        self.assertEqual("在挂人数（留降级：1）：1", rows[4]["category"])
        self.assertEqual(2, summary["retainedDemotedStudents"])
        self.assertEqual(1, summary["failedAfterRetainedDemotedStudents"])

    def test_rpt02_uses_major_population_denominators_and_retained_displays(self):
        students = [
            {"student_id": "S1", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
            {"student_id": "S2", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
            {"student_id": "S3", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
            {"student_id": "S4", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
        ]
        retained = [
            {"student_id": "R1", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
            {"student_id": "R2", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
        ]
        pairs = [
            {"studentId": "S1", "courseId": "C1", "firstPass": 0, "currentPass": 0},
            {"studentId": "S2", "courseId": "C2", "firstPass": 0, "currentPass": 1},
            {"studentId": "S4", "courseId": "C4", "firstPass": 1, "currentPass": 1},
            {"studentId": "R1", "courseId": "C5", "firstPass": 0, "currentPass": 0},
            {"studentId": "R2", "courseId": "C6", "firstPass": 0, "currentPass": 1},
        ]

        rows, summary = _report_02(students, pairs, retained)
        row = rows[0]
        self.assertEqual("4（2）", row["studentCountDisplay"])
        self.assertEqual("2（2）", row["failedBeforeDisplay"])
        self.assertEqual("1（1）", row["failedAfterDisplay"])
        self.assertEqual(0.5, row["failedBeforeRate"])
        self.assertEqual(0.25, row["failedAfterRate"])
        self.assertEqual(0.75, row["passRate"])
        self.assertEqual("总体情况(留降级)", rows[-1]["majorName"])
        self.assertEqual("4（2）", rows[-1]["studentCountDisplay"])
        self.assertEqual("2（2）", rows[-1]["failedBeforeDisplay"])
        self.assertEqual("1（1）", rows[-1]["failedAfterDisplay"])
        self.assertEqual(0.75, summary["passRate"])

    def test_rpt02_after_failures_are_limited_to_same_semester_failed_before_pairs(self):
        students = [
            {"student_id": "S1", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
            {"student_id": "S2", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
            {"student_id": "S3", "organization_id": "O1", "organization_name": "学院A",
             "major_code": "M1", "major_name": "专业A"},
        ]
        pairs = [
            # 同一所选学期内首次普通考试不及格，后续仍未通过：计入已挂和在挂。
            {"studentId": "S1", "courseId": "C1", "firstPass": 0, "currentPass": 0},
            # 原挂课程已通过；另一门只有重修未通过记录：只计入已挂，不计入在挂。
            {"studentId": "S2", "courseId": "C2", "firstPass": 0, "currentPass": 1},
            {"studentId": "S2", "courseId": "C3", "firstPass": None, "currentPass": 0},
            # 同一所选学期内只有重修未通过记录：不进入补考前后比较集合。
            {"studentId": "S3", "courseId": "C4", "firstPass": None, "currentPass": 0},
        ]

        rows, summary = _report_02(students, pairs)
        row = rows[0]
        self.assertEqual(2, row["failedBeforeStudents"])
        self.assertEqual(1, row["failedAfterStudents"])
        self.assertLessEqual(row["failedAfterStudents"], row["failedBeforeStudents"])
        self.assertEqual(2, summary["failedBeforeStudents"])
        self.assertEqual(1, summary["failedAfterStudents"])
    def test_retained_demoted_responsibility_grade_prefers_current_class(self):
        self.assertEqual(2022, _responsibility_grade("石工22-1留学生全英文班", "2021.0"))
        self.assertEqual(2021, _responsibility_grade(None, "2021.0"))
        self.assertIsNone(_responsibility_grade("未说明班级", None))

    def test_rpt06_cumulative_passes_are_distinct_as_of_selected_semester(self):
        semesters = [
            "2021-2022-2", "2022-2023-1", "2022-2023-2", "2023-2024-1",
            "2023-2024-2", "2024-2025-1", "2024-2025-2", "2025-2026-1",
        ]
        passed_by_semester = {
            "2024-2025-1": ["S1"],
            "2024-2025-2": ["S1", "S2", "S3"],  # S1重复通过，不重复计数
            "2025-2026-1": ["S4", "S5", "S6"],
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for semester in semesters:
                import sqlite3
                conn = sqlite3.connect(root / f"{semester}.db")
                conn.execute("""CREATE TABLE external_exams(
                    student_id TEXT,exam_type TEXT,is_passed INTEGER
                )""")
                conn.executemany(
                    "INSERT INTO external_exams VALUES(?,?,1)",
                    [(sid, "全国大学英语四级")
                     for sid in passed_by_semester.get(semester, [])],
                )
                conn.commit()
                conn.close()
            student_ids = {f"S{index}" for index in range(1, 8)}
            self.assertEqual(
                {"S1"},
                _cet4_passed_ids_as_of(student_ids, "2024-2025-1", root),
            )
            self.assertEqual(
                {"S1", "S2", "S3", "S4", "S5", "S6"},
                _cet4_passed_ids_as_of(student_ids, "2025-2026-1", root),
            )

    def test_rpt05_title_contains_selected_organization_and_major(self):
        report = REPORTS["RPT-05"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": "M01", "class_code": None},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 地质学 补考前后课程通过情况对比",
            title,
        )

    def test_rpt05_title_omits_optional_grade_when_not_selected(self):
        report = REPORTS["RPT-05"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", None, students,
            {"organization_id": "ORG", "major_code": "M01", "class_code": None},
        )
        self.assertEqual(
            "2025-2026-2 学期 地球科学学院 地质学 补考前后课程通过情况对比",
            title,
        )
        self.assertEqual(("semesterId",), report.required_filters)


    def test_rpt05_title_omits_unselected_scope_and_class_filter_is_disabled(self):
        report = REPORTS["RPT-05"]
        title = _report_title(
            report, "2025-2026-2", 2022, [],
            {"organization_id": None, "major_code": None, "class_code": None},
        )
        self.assertEqual("2025-2026-2 学期 2022 级 补考前后课程通过情况对比", title)
        self.assertIsNone(_normalize_class_code(report, "地质22-1班"))
        self.assertEqual("地质22-1班", _normalize_class_code(REPORTS["RPT-06"], "地质22-1班"))

    def test_rpt02_title_uses_grade_and_optional_organization(self):
        report = REPORTS["RPT-02"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": None, "class_code": None},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 各专业补考前后挂科率比较",
            title,
        )
        self.assertNotIn("本科", title)

    def test_rpt02_ignores_direct_major_and_class_filters(self):
        report = REPORTS["RPT-02"]
        self.assertIsNone(_normalize_major_code(report, "M01"))
        self.assertIsNone(_normalize_class_code(report, "地质22-1班"))
        self.assertEqual(
            "M01",
            _normalize_major_code(REPORTS["RPT-03"], "M01"),
        )
        self.assertEqual(
            "地质22-1班",
            _normalize_class_code(REPORTS["RPT-03"], "地质22-1班"),
        )

    def test_rpt04a_title_contains_selected_organization_and_major(self):
        report = REPORTS["RPT-04A"]
        students = [{"organization_name": "地球科学学院", "major_name": "资源勘查工程"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": "M01", "class_code": None},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 资源勘查工程 各班级挂科门数具体情况",
            title,
        )
        self.assertNotIn("本科", title)

    def test_rpt04a_title_omits_unselected_organization_and_major(self):
        report = REPORTS["RPT-04A"]
        title = _report_title(
            report, "2025-2026-2", 2022, [],
            {"organization_id": None, "major_code": None, "class_code": None},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 各班级挂科门数具体情况",
            title,
        )


    def test_rpt04a_direct_class_filter_is_ignored(self):
        report = REPORTS["RPT-04A"]
        students = [{"organization_name": "地球科学学院", "major_name": "资源勘查工程"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": "M01", "class_code": "资源22-1班"},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 资源勘查工程 各班级挂科门数具体情况",
            title,
        )
        self.assertIsNone(_normalize_class_code(report, "资源22-1班"))

    def test_rpt04b_title_contains_selected_organization_major_and_class(self):
        report = REPORTS["RPT-04B"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": "M01", "class_code": "地质22-1班"},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 地质学 地质22-1班 成绩分布",
            title,
        )

    def test_rpt04b_title_uses_all_classes_when_class_is_not_selected(self):
        report = REPORTS["RPT-04B"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": "M01", "class_code": None},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 地质学 各班级成绩分布",
            title,
        )

    def test_rpt04b_title_uses_authorized_scope_names_when_result_is_empty(self):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE dim_organization(organization_id TEXT PRIMARY KEY,name TEXT);
            CREATE TABLE dim_student(
                student_id TEXT,display_name TEXT,gender TEXT,entry_grade INTEGER,
                education_level TEXT,student_status TEXT,organization_id TEXT,
                major_code TEXT,major_name TEXT,class_code TEXT
            );
            INSERT INTO dim_organization VALUES('ORG','地球科学学院');
            INSERT INTO dim_student VALUES(
                'S1','测试学生','男',2021,'本科','在校','ORG','M01','地质学','地质21-1班'
            );
        """)
        filters = {
            "entry_grade": 2022, "organization_id": "ORG",
            "major_code": "M01", "class_code": None,
        }
        labels = _title_scope_labels(
            conn, {"authorized": True, "detailScope": {"type": "all"}}, filters,
        )
        title = _report_title(
            REPORTS["RPT-04B"], "2025-2026-2", 2022, [], {**filters, **labels},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 地质学 各班级成绩分布",
            title,
        )

    def test_rpt06_title_contains_selected_organization_major_and_class(self):
        report = REPORTS["RPT-06"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": "M01", "class_code": "地质22-1班"},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 地质学 地质22-1班 大学英语四级通过情况",
            title,
        )

    def test_rpt06_title_omits_unselected_scope_levels(self):
        report = REPORTS["RPT-06"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": None, "class_code": None},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 各班大学英语四级通过情况",
            title,
        )

    def test_rpt07_title_contains_selected_scope_levels(self):
        report = REPORTS["RPT-07"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": "M01", "class_code": "地质22-1班"},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 地质学 地质22-1班 重点关注学生名单",
            title,
        )

    def test_rpt07_title_omits_unselected_scope_levels(self):
        report = REPORTS["RPT-07"]
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        title = _report_title(
            report, "2025-2026-2", 2022, students,
            {"organization_id": "ORG", "major_code": None, "class_code": None},
        )
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 重点关注学生名单",
            title,
        )

    def test_rpt08_differs_from_rpt07_only_by_report_title(self):
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        filters = {"organization_id": "ORG", "major_code": "M01", "class_code": "地质22-1班"}
        rpt07_title = _report_title(REPORTS["RPT-07"], "2025-2026-2", 2022, students, filters)
        rpt08_title = _report_title(REPORTS["RPT-08"], "2025-2026-2", 2022, students, filters)
        self.assertEqual(
            "2025-2026-2 学期 2022 级 地球科学学院 地质学 地质22-1班 校级学业警示学生名单",
            rpt08_title,
        )
        self.assertEqual(rpt07_title.replace("重点关注学生名单", "校级学业警示学生名单"), rpt08_title)
        self.assertEqual(REPORT_RULES["RPT-07"], REPORT_RULES["RPT-08"])

    def test_rpt07_and_rpt08_require_semester_but_not_grade(self):
        self.assertEqual(("semesterId",), REPORTS["RPT-07"].required_filters)
        self.assertEqual(("semesterId",), REPORTS["RPT-08"].required_filters)

    def test_focus_roster_without_grade_queries_all_authorized_grades_and_omits_title_grade(self):
        with patch("backend.api.basic_reports.service.v2_student_scope", return_value=("", [])):
            cte, params = _student_cte(
                {}, None, entry_grade=None, organization_id="ORG",
                major_code=None, class_code=None,
            )
        self.assertNotIn("s.entry_grade=?", cte)
        self.assertEqual(["ORG"], params)
        students = [{"organization_name": "地球科学学院", "major_name": "地质学"}]
        filters = {"organization_id": "ORG", "major_code": None, "class_code": None}
        self.assertEqual(
            "2025-2026-2 学期 地球科学学院 重点关注学生名单",
            _report_title(REPORTS["RPT-07"], "2025-2026-2", None, students, filters),
        )
        self.assertEqual(
            "2025-2026-2 学期 地球科学学院 校级学业警示学生名单",
            _report_title(REPORTS["RPT-08"], "2025-2026-2", None, students, filters),
        )

    def test_rpt08_dispatches_to_same_roster_calculation_as_rpt07(self):
        report = REPORTS["RPT-08"]
        user = {"permission_context": {
            "menuPermissions": [report.menu_path], "actionPermissions": ["student.detail"],
            "activeRoleName": "测试角色", "detailScope": {"type": "all"},
            "scopeFingerprint": "test-scope",
        }}
        students = [{"student_id": "S1", "display_name": "测试学生",
                     "organization_name": "测试学院", "major_name": "测试专业",
                     "class_code": "测试班"}]
        expected_rows = [{"studentId": "S1", "unresolvedCourseCount": 2}]
        with patch("backend.api.basic_reports.service._students", return_value=students), \
             patch("backend.api.basic_reports.service._report_07",
                   return_value=(expected_rows, {"focusStudentCount": 1}, "available")) as roster, \
             patch("backend.api.basic_reports.service._focus_rule_metadata", return_value={"items": []}), \
             patch("backend.api.basic_reports.service._token", return_value="snapshot"), \
             patch("backend.api.basic_reports.service._source_mtime", return_value="cutoff"):
            payload = build_report(None, None, user, report,
                                   semester_id="2025-2026-2", entry_grade=2022)
        roster.assert_called_once_with(None, None, user, students, "2025-2026-2")
        self.assertEqual(expected_rows, payload["rows"])
        self.assertEqual("available", payload["status"])
        self.assertEqual("2025-2026-2 学期 2022 级 校级学业警示学生名单", payload["title"])

    def test_rpt07_export_explanation_uses_grade_label(self):
        payload = {
            "reportId": "RPT-07", "title": "重点关注学生名单", "status": "available",
            "rows": [], "context": {"entryGrade": None}, "rules": [], "boundary": [],
        }
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        self.assertEqual("年级", workbook["报表说明"]["A7"].value)
        self.assertEqual("全部授权年级", workbook["报表说明"]["B7"].value)

    def test_rpt07_export_records_actual_alert_rule_and_version(self):
        payload = {
            "reportId": "RPT-07", "title": "重点关注学生名单", "status": "available",
            "rows": [], "context": {}, "rules": [], "boundary": [],
            "focusRule": {
                "items": [{"ruleId": "R2W", "level": "警告", "enabled": True,
                           "description": "测试配置：最近3学期未解决课程=4门"}],
                "versions": ["R2-v9"], "dedupDescription": "按课程去重",
            },
        }
        sheet = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))["报表说明"]
        values = {row[0].value: row[1].value for row in sheet.iter_rows()}
        self.assertIn("最近3学期未解决课程=4门", values["重点关注规则"])
        self.assertEqual("R2-v9", values["预警规则版本"])

    def test_rpt08_export_matches_rpt07_structure_and_rule_explanation(self):
        payload = {
            "reportId": "RPT-08",
            "title": "2025-2026-2 学期 2022 级 校级学业警示学生名单",
            "status": "available",
            "rows": [{"sequence": 1, "name": "测试学生", "studentId": "202201001",
                      "majorClass": "地质学 地质22-1班", "mentor": "—", "failedCredits": 1.5,
                      "unresolvedCourseCount": 2, "courseEvidence": "课程证据"}],
            "context": {"semesterId": "2025-2026-2", "entryGrade": 2022},
            "rules": [], "boundary": [],
            "focusRule": {
                "items": [{"ruleId": "R2W", "level": "警告", "enabled": True,
                           "description": "近2学期不同且尚未通过的课程=2门"}],
                "versions": ["R2-v2.0"], "dedupDescription": "按课程去重",
            },
        }
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        result = workbook["报表结果"]
        self.assertEqual(payload["title"], result["A1"].value)
        self.assertIn("A1:H1", {str(item) for item in result.merged_cells.ranges})
        self.assertEqual("序号", result["A2"].value)
        explanation = {row[0].value: row[1].value for row in workbook["报表说明"].iter_rows()}
        self.assertEqual(2022, explanation["年级"])
        self.assertIn("R2W", explanation["重点关注规则"])
        self.assertEqual("R2-v2.0", explanation["预警规则版本"])

    def test_rpt07_export_has_query_title_above_headers(self):
        payload = {
            "reportId": "RPT-07",
            "title": "2025-2026-2 学期 2022 级 地球科学学院 重点关注学生名单",
            "status": "available",
            "rows": [{"sequence": 1, "name": "测试学生", "studentId": "202201001",
                      "majorClass": "地质学 地质22-1班", "mentor": "—", "failedCredits": 4,
                      "unresolvedCourseCount": 2, "courseEvidence": "课程证据"}],
            "context": {"semesterId": "2025-2026-2", "entryGrade": 2022},
            "rules": [], "boundary": [],
        }
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        sheet = workbook["报表结果"]
        self.assertEqual(payload["title"], sheet["A1"].value)
        self.assertIn("A1:H1", {str(item) for item in sheet.merged_cells.ranges})
        self.assertEqual(
            ["序号", "姓名", "学号", "专业班级", "导师", "挂科学分", "挂科门数", "具体情况"],
            [cell.value for cell in sheet[2]],
        )
        self.assertEqual("测试学生", sheet["B3"].value)
        self.assertEqual("A3", sheet.freeze_panes)
        self.assertEqual("A2:H3", sheet.auto_filter.ref)

    def test_rpt07_detail_uses_same_recent_two_semester_unresolved_rule_as_alert(self):
        import sqlite3
        legacy = sqlite3.connect(":memory:")
        v2 = sqlite3.connect(":memory:")
        self.addCleanup(legacy.close)
        self.addCleanup(v2.close)
        legacy.row_factory = sqlite3.Row
        v2.row_factory = sqlite3.Row
        legacy.execute("""CREATE TABLE fact_alert(
            student_id TEXT,rule_id TEXT,level TEXT,trigger_detail TEXT,rule_version TEXT,
            semester_id TEXT,is_active INTEGER
        )""")
        legacy.executescript("""
            CREATE TABLE fact_grade(
                grade_id INTEGER,student_id TEXT,course_id TEXT,semester_id TEXT,
                score REAL,is_pass INTEGER,credits REAL
            );
            CREATE TABLE dim_course(course_id TEXT,name TEXT,credits REAL);
        """)
        legacy.execute(
            "INSERT INTO fact_alert VALUES(?,?,?,?,?,?,?)",
            ("2022010732", "R2W", "警告", "近2学期尚未通过课程 2 门（按不同课程去重）",
             "R2-v2.0", "2025-2026-2", 1),
        )
        legacy.executemany(
            "INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?)",
            [
                (1, "2022010732", "C1", "2025-2026-1", 46.6, 0, 1.0),
                (2, "2022010732", "C2", "2025-2026-1", 55.6, 0, 0.5),
                (3, "2022010732", "C3", "2025-2026-1", 50.0, 0, 2.0),
                (4, "2022010732", "C3", "2025-2026-2", 70.0, 1, 2.0),
            ],
        )
        legacy.executemany(
            "INSERT INTO dim_course VALUES(?,?,?)",
            [("C1", "材料专业导论", 1.0), ("C2", "就业指导", 0.5), ("C3", "已解决课程", 2.0)],
        )
        v2.executescript("""
            CREATE TABLE staff_student_scope(
                student_id TEXT,staff_id TEXT,relation_type TEXT,status TEXT
            );
            CREATE TABLE dim_staff(staff_id TEXT,display_name TEXT);
        """)
        students = [{
            "student_id": "2022010732", "display_name": "张硕", "organization_name": "学院",
            "major_name": "能源创新班", "class_code": "碳中和能源创新22-1班",
        }]
        user = {"permission_context": {"actionPermissions": ["student.detail"]}}
        rows, _, status = _report_07(legacy, v2, user, students, "2025-2026-2")
        self.assertEqual("available", status)
        self.assertEqual(2, rows[0]["unresolvedCourseCount"])
        self.assertEqual(1.5, rows[0]["failedCredits"])
        self.assertIn("2025-2026-1", rows[0]["courseEvidence"])
        self.assertIn("材料专业导论（1学分） 46.6分", rows[0]["courseEvidence"])
        self.assertIn("就业指导（0.5学分） 55.6分", rows[0]["courseEvidence"])
        self.assertNotIn("已解决课程", rows[0]["courseEvidence"])

    def test_rpt07_rule_metadata_and_fingerprint_follow_actual_sources(self):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE sys_alert_rule(
                rule_id TEXT,name TEXT,level TEXT,params TEXT,enabled INTEGER
            );
            CREATE TABLE fact_alert(
                student_id TEXT,rule_id TEXT,level TEXT,trigger_detail TEXT,
                semester_id TEXT,is_active INTEGER,rule_version TEXT
            );
            CREATE TABLE fact_grade(
                grade_id INTEGER,student_id TEXT,course_id TEXT,semester_id TEXT,
                score REAL,is_pass INTEGER,credits REAL
            );
            CREATE TABLE dim_course(course_id TEXT,name TEXT,credits REAL);
            INSERT INTO sys_alert_rule VALUES
                ('R2W','测试关注规则','警告','{"text":"最近3学期未解决课程=4门"}',1),
                ('R2','测试严重规则','严重','{"text":"最近3学期未解决课程>=5门"}',1);
            INSERT INTO fact_alert VALUES
                ('S1','R2W','警告','测试命中','2025-2026-2',1,'R2-v9');
            INSERT INTO fact_grade VALUES
                (1,'S1','C1','2025-2026-1',55.6,0,0.5);
            INSERT INTO dim_course VALUES('C1','就业指导',0.5);
        """)
        metadata = _focus_rule_metadata(conn, "2025-2026-2")
        self.assertEqual("最近3学期未解决课程=4门", metadata["items"][0]["description"])
        self.assertEqual(["R2-v9"], metadata["versions"])
        before = _rpt07_data_fingerprint(conn, "2025-2026-2")
        conn.execute("UPDATE fact_grade SET score=56.6 WHERE grade_id=1")
        after_grade = _rpt07_data_fingerprint(conn, "2025-2026-2")
        self.assertNotEqual(before, after_grade)
        conn.execute("UPDATE sys_alert_rule SET params=? WHERE rule_id='R2W'", ('{"text":"新口径"}',))
        after_rule = _rpt07_data_fingerprint(conn, "2025-2026-2")
        self.assertNotEqual(after_grade, after_rule)

    def test_rpt06_pass_rate_dense_ranking_preserves_row_order(self):
        rows = [
            {"classCode": "丙班", "cet4PassRate": .8},
            {"classCode": "甲班", "cet4PassRate": .9},
            {"classCode": "丁班", "cet4PassRate": .7},
            {"classCode": "乙班", "cet4PassRate": .8},
        ]
        _rank_cet4_rows(rows)
        self.assertEqual(
            [("丙班", 2), ("甲班", 1), ("丁班", 3), ("乙班", 2)],
            [(row["classCode"], row["cet4PassRateRank"]) for row in rows],
        )

    def test_original_columns_required_filters_and_no_pagination_contract(self):
        report = REPORTS["RPT-04A"]
        self.assertEqual(("semesterId", "entryGrade"), report.required_filters)
        self.assertEqual(
            ["班级", "总人数", "1-2科", "3-5科", "5科以上"],
            [label for _, label in report.result_columns],
        )
        self.assertNotIn("page", signature(query_report).parameters)
        self.assertNotIn("page_size", signature(query_report).parameters)

    def test_empty_scope_does_not_create_fake_zero_summary_row(self):
        rows, summary = _report_04a([], [])
        self.assertEqual([], rows)
        self.assertEqual(0, summary["studentCount"])

    def test_rpt02_export_has_query_title_above_original_headers(self):
        payload = {
            "reportId": "RPT-02",
            "title": "2025-2026-2 学期 2022 级 地球科学学院 各专业补考前后挂科率比较",
            "status": "available",
            "rows": [{
                "majorName": "地质学", "studentCountDisplay": "29（2）",
                "failedBeforeDisplay": "7（1）", "failedBeforeRate": 7 / 29,
                "failedAfterDisplay": "3（1）", "failedAfterRate": 3 / 29,
                "passRate": 26 / 29,
            }],
            "context": {"semesterId": "2025-2026-2", "entryGrade": 2022,
                        "organizationId": "ORG", "majorCode": None, "classCode": None},
            "rules": [], "boundary": [],
        }
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        sheet = workbook["报表结果"]
        self.assertEqual(payload["title"], sheet["A1"].value)
        self.assertIn("A1:G1", {str(item) for item in sheet.merged_cells.ranges})
        self.assertEqual(
            ["专业名称", "专业人数", "已挂人数", "挂科率（补考前）",
             "在挂人数", "挂科率（补考后）", "通过率"],
            [cell.value for cell in sheet[2]],
        )
        self.assertEqual("地质学", sheet["A3"].value)
        self.assertEqual("29（2）", sheet["B3"].value)
        self.assertEqual("7（1）", sheet["C3"].value)
        self.assertEqual("3（1）", sheet["E3"].value)
        self.assertEqual(26 / 29, sheet["G3"].value)
        self.assertEqual("A3", sheet.freeze_panes)
        self.assertEqual("A2:G3", sheet.auto_filter.ref)
        self.assertEqual("年级", workbook["报表说明"]["A7"].value)
        self.assertEqual("全部授权范围", workbook["报表说明"]["B9"].value)
        self.assertEqual("全部授权范围", workbook["报表说明"]["B10"].value)

    def test_rpt04a_empty_export_has_query_title_above_original_headers(self):
        payload = {"reportId": "RPT-04A", "title": "2025-2026-2 学期 2022 级 地球科学学院 资源勘查工程 各班级挂科门数具体情况", "status": "available",
                   "rows": [], "context": {}, "rules": [], "boundary": []}
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        sheet = workbook["报表结果"]
        self.assertEqual(payload["title"], sheet["A1"].value)
        self.assertIn("A1:E1", {str(item) for item in sheet.merged_cells.ranges})
        self.assertEqual(
            ["班级", "总人数", "1-2科", "3-5科", "5科以上"],
            [cell.value for cell in sheet[2]],
        )
        self.assertEqual(2, sheet.max_row)
        self.assertEqual("A3", sheet.freeze_panes)
        self.assertEqual("年级", workbook["报表说明"]["A7"].value)

    def test_rpt06_export_has_query_title_above_headers(self):
        payload = {
            "reportId": "RPT-06",
            "title": "2025-2026-2 学期 2022 级 地球科学学院 各班大学英语四级通过情况",
            "status": "available",
            "rows": [{"classCode": "人工智能22-1班", "studentCount": 38,
                      "cet4PassedStudents": 33, "cet4PassRate": 33 / 38,
                      "cet4PassRateRank": 1}],
            "context": {"semesterId": "2025-2026-2", "entryGrade": 2022},
            "rules": [], "boundary": [],
        }
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        sheet = workbook["报表结果"]
        self.assertEqual(payload["title"], sheet["A1"].value)
        self.assertIn("A1:E1", {str(item) for item in sheet.merged_cells.ranges})
        self.assertEqual(["班级", "总人数", "四级通过人数", "四级通过率", "四级通过率排行"],
                         [cell.value for cell in sheet[2]])
        self.assertEqual("人工智能22-1班", sheet["A3"].value)
        self.assertEqual("①", sheet["E3"].value)
        self.assertEqual("A3", sheet.freeze_panes)
        self.assertEqual("A2:E3", sheet.auto_filter.ref)
        self.assertEqual("年级", workbook["报表说明"]["A7"].value)

    def test_rpt04b_export_has_query_title_above_headers(self):
        payload = {
            "reportId": "RPT-04B",
            "title": "2025-2026-2 学期 2022 级 地球科学学院 地质学 各班级成绩分布",
            "status": "available",
            "rows": [{"classCode": "地质22-1班", "rankedStudents": 26,
                      "top20Display": "5（19.23%）", "top20To50Display": "8（30.77%）",
                      "top50To80Display": "7（26.92%）", "bottom20Display": "6（23.08%）"}],
            "context": {"semesterId": "2025-2026-2", "entryGrade": 2022},
            "rules": [], "boundary": [],
        }
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        sheet = workbook["报表结果"]
        self.assertEqual(payload["title"], sheet["A1"].value)
        self.assertIn("A1:F1", {str(item) for item in sheet.merged_cells.ranges})
        self.assertEqual(
            ["班级", "总人数", "专业前20%", "专业前20-50%", "专业前50-80%", "专业后20%"],
            [cell.value for cell in sheet[2]],
        )
        self.assertEqual("地质22-1班", sheet["A3"].value)
        self.assertEqual("A3", sheet.freeze_panes)
        self.assertEqual("A2:F3", sheet.auto_filter.ref)
        self.assertEqual("年级", workbook["报表说明"]["A7"].value)

    def test_course_export_has_grouped_headers_and_merged_course_totals(self):
        rows = [
            {"courseKey": "C1", "course": "高等数学\n[6 学分]", "majorName": "专业A", "majorStudentCount": 30,
             "failedBeforeStudents": 5, "failedBeforeRate": .2, "failedBeforeCourseTotal": 8, "failedBeforeCourseRate": .16,
             "failedAfterStudents": 3, "failedAfterRate": .1, "failedAfterCourseTotal": 4, "failedAfterCourseRate": .08,
             "makeupPassedStudents": 2},
            {"courseKey": "C1", "course": "高等数学\n[6 学分]", "majorName": "专业B", "majorStudentCount": 20,
             "failedBeforeStudents": 3, "failedBeforeRate": .15, "failedBeforeCourseTotal": 8, "failedBeforeCourseRate": .16,
             "failedAfterStudents": 1, "failedAfterRate": .05, "failedAfterCourseTotal": 4, "failedAfterCourseRate": .08,
             "makeupPassedStudents": 2},
        ]
        payload = {"reportId": "RPT-05",
                   "title": "2025-2026-2 学期 地球科学学院 补考前后课程通过情况对比",
                   "status": "available", "rows": rows,
                   "context": {"semesterId": "2025-2026-2", "entryGrade": None},
                   "rules": [], "boundary": []}
        workbook = load_workbook(BytesIO(build_workbook(payload, {"username": "tester"})))
        sheet = workbook["报表结果"]
        self.assertEqual(payload["title"], sheet["A1"].value)
        self.assertIn("A1:L1", {str(item) for item in sheet.merged_cells.ranges})
        self.assertEqual("补考前数据", sheet["D2"].value)
        self.assertEqual("补考后数据", sheet["H2"].value)
        merged = {str(item) for item in sheet.merged_cells.ranges}
        self.assertTrue({"A2:A3", "B2:B3", "C2:C3", "L2:L3",
                         "A4:A5", "F4:F5", "G4:G5", "J4:J5", "K4:K5"} <= merged)
        self.assertEqual("全部年级", workbook["报表说明"]["B7"].value)

        self.assertEqual("A4", sheet.freeze_panes)
        self.assertEqual("年级", workbook["报表说明"]["A7"].value)

    def test_rpt08_no_longer_uses_unavailable_official_roster_placeholder(self):
        self.assertNotIn("BR-OFFICIAL-WARNING", RULES)
        self.assertEqual(["BR-STUDENT-SCOPE", "BR-FOCUS-R2"], REPORT_RULES["RPT-08"])


if __name__ == "__main__":
    unittest.main()

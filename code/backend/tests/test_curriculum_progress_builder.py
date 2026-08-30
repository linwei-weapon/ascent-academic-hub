from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.api.routers import v2
from backend.etl.init_v2 import init_v2
from backend.etl.v2_grade_loader import RULE_VERSION
from backend.etl.v2_growth_builder import (
    GROWTH_VERSION,
    build_growth,
    current_study_term,
)


class CurriculumProgressBuilderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "v2.sqlite"
        now = datetime.now()
        self.grade = now.year if now.month >= 9 else now.year - 1
        self.term = current_study_term(self.grade)
        conn = init_v2(self.db_path)
        conn.execute(
            "INSERT INTO curriculum_plan(plan_id,plan_name,grade,major_code,major_name) "
            "VALUES('P1','测试方案',?,'M1','测试专业')",
            (self.grade,),
        )
        conn.executemany(
            "INSERT INTO dim_course(course_id,name) VALUES(?,?)",
            [(f"C{i}", f"课程{i}") for i in range(1, 10)],
        )
        conn.executemany(
            "INSERT INTO curriculum_plan_course(plan_id,course_id,module,requirement_type,credits,suggested_term) "
            "VALUES('P1',?,?,?,?,?)",
            [
                ("C1", "模块A", "必修", 2, str(max(1, self.term - 1))),
                ("C2", "模块A", "必修", 2, str(max(1, self.term - 1))),
                ("C3", "二选一模块", "选修", 2, str(max(1, self.term - 1))),
                ("C4", "二选一模块", "选修", 2, str(max(1, self.term - 1))),
                ("C5", "逐门必修模块", "必修", 1, str(max(1, self.term - 1))),
                ("C6", "逐门必修模块", "必修", 1, str(self.term)),
                ("C7", "自由选修池", "选修", 1, str(max(1, self.term - 1))),
                ("C8", "错误继承学分模块", "必修", 2, str(max(1, self.term - 1))),
                ("C9", "未单列规则模块（二选一）", "选修", 2, str(max(1, self.term - 1))),
            ],
        )
        conn.executemany(
            "INSERT INTO curriculum_plan_module_requirement(plan_id,module_name,minimum_credits,minimum_courses,raw_hierarchy) "
            "VALUES('P1',?,?,?,?)",
            [
                ("模块A", 4, None, "模块A"),
                ("二选一模块", 0, None, "二选一模块"),
                ("错误继承学分模块", 44.5, None, "父级必修（二选一） / 错误继承学分模块"),
            ],
        )
        conn.executemany(
            "INSERT INTO dim_student(student_id,display_name,entry_grade,major_code,major_name,plan_id,student_status) "
            "VALUES(?,?,?,?,?,'P1','在校')",
            [
                ("S1", "匹配学生", self.grade, "M1", "测试专业"),
                ("S2", "错配学生", self.grade - 1, "M1", "测试专业"),
            ],
        )
        conn.executemany(
            "INSERT INTO student_plan_assignment(student_id,plan_id,valid_from,assignment_reason) "
            "VALUES(?,'P1','2025-09-01','测试')",
            [("S1",), ("S2",)],
        )
        conn.executemany(
            "INSERT INTO student_course_result(student_id,course_id,rule_version,effective_attempt_id,"
            "effective_score,is_pass,earned_credits,calculated_at) VALUES('S1',?,?,?,?,?,?,?)",
            [
                ("C1", RULE_VERSION, "A1", 80, 1, 2, "2026-01-01"),
                ("C2", RULE_VERSION, "A2", 50, 0, 0, "2026-01-01"),
                ("C5", RULE_VERSION, "A5", 85, 1, 1, "2026-01-01"),
            ],
        )
        conn.execute(
            "INSERT INTO student_course_substitution(substitution_id,student_id,original_course_id,"
            "substitute_course_id,recognized_credits,approval_status,workflow_status) "
            "VALUES('SUB1','S1','C3','CX',2,'通过','流程已结束')"
        )
        conn.commit()
        conn.close()
        self.report = build_growth(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        result = [dict(row) for row in conn.execute(sql, params)]
        conn.close()
        return result

    def test_current_term_is_not_overdue(self):
        row = self.rows(
            "SELECT is_overdue FROM student_plan_course_status "
            "WHERE student_id='S1' AND course_id='C6' AND rule_version=?",
            (GROWTH_VERSION,),
        )[0]
        self.assertEqual(0, row["is_overdue"])

    def test_module_rule_priority_and_choice_group(self):
        rows = {
            row["module_name"]: row for row in self.rows(
                "SELECT * FROM student_plan_module_status WHERE student_id='S1'"
            )
        }
        self.assertEqual("minimum_credits", rows["模块A"]["rule_type"])
        self.assertEqual("explicit_gap", rows["模块A"]["evidence_status"])
        self.assertEqual("minimum_courses", rows["二选一模块"]["rule_type"])
        self.assertEqual(1, rows["二选一模块"]["target_value"])
        self.assertEqual(1, rows["二选一模块"]["is_complete"])
        self.assertEqual("required_courses", rows["逐门必修模块"]["rule_type"])
        self.assertEqual("not_due", rows["逐门必修模块"]["evidence_status"])
        self.assertEqual("not_assessable", rows["自由选修池"]["rule_type"])
        self.assertEqual("required_courses", rows["错误继承学分模块"]["rule_type"])
        self.assertEqual(1, rows["错误继承学分模块"]["target_value"])
        self.assertEqual("minimum_courses", rows["未单列规则模块（二选一）"]["rule_type"])
        self.assertEqual(1, rows["未单列规则模块（二选一）"]["target_value"])

    def test_recognition_uses_plan_credits_once(self):
        row = self.rows(
            "SELECT completion_status,earned_credits FROM student_plan_course_status "
            "WHERE student_id='S1' AND course_id='C3'"
        )[0]
        self.assertEqual("recognized", row["completion_status"])
        self.assertEqual(2, row["earned_credits"])

    def test_grade_mismatch_is_excluded_from_course_status(self):
        self.assertEqual([], self.rows(
            "SELECT 1 FROM student_plan_course_status WHERE student_id='S2'"
        ))
        summary = self.rows(
            "SELECT binding_status,evidence_status FROM student_plan_progress_summary "
            "WHERE student_id='S2'"
        )[0]
        self.assertEqual("grade_mismatch", summary["binding_status"])
        self.assertEqual("binding_mismatch", summary["evidence_status"])
        self.assertEqual(1, self.report["binding_mismatches"])

    def test_three_curriculum_workspaces_share_the_same_summary(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        user = {"role_id": "dean", "username": "curriculum-contract-test"}
        v2._QUERY_CACHE.clear()
        v2._GRADUATION_TOPIC_CACHE.clear()
        with patch.object(v2.settings, "V2_DB_PATH", str(self.db_path)):
            overview = v2.curriculum_management_overview(conn=conn, user=user)["data"]
            progress = v2.curriculum_progress("P1", 100, 0, conn, user)["data"]
            readiness = v2.graduation_readiness_topic(
                plan_id="P1", limit=50, offset=0, conn=conn, user=user
            )["data"]
        conn.close()
        self.assertEqual(1, overview["summary"]["applicableStudents"])
        self.assertEqual(1, overview["summary"]["matchedStudents"])
        self.assertEqual(1, overview["summary"]["bindingReviewStudents"])
        self.assertEqual(1, overview["summary"]["actionRequiredStudents"])
        self.assertEqual(
            "模块尚未达到要求，存在明确未通过必修课程证据的去重学生数。",
            overview["definition"]["actionRequiredStudents"],
        )
        self.assertEqual(
            "模块尚未达到要求，存在已过建议学期但缺少结果记录的候选学生数。",
            overview["definition"]["verificationStudents"],
        )
        self.assertEqual(1, progress["summary"]["coveredStudents"])
        self.assertEqual(1, progress["summary"]["actionRequiredStudents"])
        self.assertEqual(
            "模块尚未达到要求，存在明确未通过必修课程证据的去重学生数。",
            progress["definition"]["actionRequired"],
        )
        self.assertEqual(
            "模块尚未达到要求，存在已过建议学期但缺少结果记录的候选学生数。",
            progress["definition"]["verificationRequired"],
        )
        self.assertEqual(
            "存在1门当前有效成绩仍为未通过的必修课程",
            progress["students"][0]["statusReason"],
        )
        self.assertEqual(1, readiness["summary"]["covered_students"])
        self.assertEqual(1, readiness["summary"]["action_required_students"])

    def test_management_student_list_has_true_pagination_total(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        result = v2.curriculum_management_students(
            status=None, limit=1, offset=0, conn=conn,
            user={"role_id": "dean", "username": "curriculum-list-test"},
        )["data"]
        conn.close()
        self.assertEqual(2, result["total"])
        self.assertEqual(1, len(result["items"]))

    def test_management_student_list_includes_student_status_and_status_reason(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        result = v2.curriculum_management_students(
            status=None, limit=20, offset=0, conn=conn,
            user={"role_id": "dean", "username": "curriculum-list-fields-test"},
        )["data"]
        conn.close()
        items = {row["studentId"]: row for row in result["items"]}
        self.assertEqual("在校", items["S1"]["studentStatus"])
        self.assertEqual("在校", items["S2"]["studentStatus"])
        self.assertEqual(
            "存在1门当前有效成绩仍为未通过的必修课程",
            items["S1"]["statusReason"],
        )
        self.assertEqual(
            "学生绑定的方案与学生入学年级不一致",
            items["S2"]["statusReason"],
        )

    def test_management_overview_filters_and_binding_rate_use_query_scope(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        user = {"role_id": "dean", "username": "curriculum-filter-test"}
        v2._QUERY_CACHE.clear()
        with patch.object(v2.settings, "V2_DB_PATH", str(self.db_path)):
            options = v2.curriculum_options(conn=conn, user=user)["data"]
            all_rows = v2.curriculum_management_overview(conn=conn, user=user)["data"]
            filtered = v2.curriculum_management_overview(
                grades=str(self.grade), conn=conn, user=user
            )["data"]
        conn.close()
        self.assertEqual({self.grade, self.grade - 1}, {
            row["grade"] for row in options["overviewFilters"]
        })
        self.assertEqual(["P1"], [row["planId"] for row in options["progressPlans"]])
        self.assertEqual(2, options["progressPlans"][0]["studentCount"])
        self.assertEqual(2, all_rows["colleges"][0]["totalStudents"])
        self.assertEqual(1, all_rows["colleges"][0]["matchedStudents"])
        self.assertEqual(50.0, all_rows["colleges"][0]["bindingRate"])
        self.assertEqual(1, filtered["summary"]["totalPlans"])
        self.assertEqual(1, filtered["summary"]["reviewablePlans"])
        self.assertEqual(1, filtered["summary"]["coveredStudents"])
        self.assertEqual(100.0, filtered["colleges"][0]["bindingRate"])

    def test_progress_plan_options_exclude_plans_only_bound_to_non_enrolled_students(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO curriculum_plan(plan_id,plan_name,grade,major_code,major_name) "
            "VALUES('P0','较早在校方案',?,'M0','较早专业')",
            (self.grade - 2,),
        )
        conn.execute(
            "INSERT INTO curriculum_plan(plan_id,plan_name,grade,major_code,major_name) "
            "VALUES('P2','已毕业方案',?,'M2','历史专业')",
            (self.grade - 3,),
        )
        conn.executemany(
            "INSERT INTO dim_student(student_id,display_name,entry_grade,major_code,major_name,plan_id,student_status) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("S0", "较早在校学生", self.grade - 2, "M0", "较早专业", "P0", "在校"),
                ("S5", "已毕业学生", self.grade - 3, "M2", "历史专业", "P2", "已毕业"),
            ],
        )
        conn.commit()
        user = {"role_id": "dean", "username": "curriculum-progress-options-test"}
        v2._QUERY_CACHE.clear()
        with patch.object(v2.settings, "V2_DB_PATH", str(self.db_path)):
            options = v2.curriculum_options(conn=conn, user=user)["data"]
        conn.close()
        self.assertEqual(["P0", "P1"], [row["planId"] for row in options["progressPlans"]])
        self.assertEqual(0, next(row for row in options["plans"] if row["planId"] == "P2")["studentCount"])
        self.assertNotIn(self.grade - 3, {row["grade"] for row in options["overviewFilters"]})

    def test_missing_binding_keys_enter_binding_review(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO dim_student(student_id,display_name,major_code,major_name,plan_id,student_status) "
            "VALUES('S3','缺少年级学生','M1','测试专业','P1','在校')"
        )
        conn.commit()
        user = {"role_id": "dean", "username": "curriculum-missing-key-test"}
        v2._QUERY_CACHE.clear()
        with patch.object(v2.settings, "V2_DB_PATH", str(self.db_path)):
            overview = v2.curriculum_management_overview(conn=conn, user=user)["data"]
            students = v2.curriculum_management_students(
                status="方案绑定待核验", limit=200, offset=0, conn=conn, user=user
            )["data"]
        conn.close()
        self.assertEqual(2, overview["summary"]["bindingReviewStudents"])
        self.assertEqual({"S2", "S3"}, {row["studentId"] for row in students["items"]})

    def test_same_major_name_uses_major_code_for_expected_plan(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO curriculum_plan(plan_id,plan_name,grade,major_code,major_name) "
            "VALUES('P2','同名专业方案',?,'M2','测试专业')",
            (self.grade,),
        )
        conn.execute(
            "INSERT INTO dim_student(student_id,display_name,entry_grade,major_code,major_name,plan_id,student_status) "
            "VALUES('S4','同名专业学生',?,'M2','测试专业','P2','在校')",
            (self.grade,),
        )
        conn.commit()
        user = {"role_id": "dean", "username": "curriculum-major-code-test"}
        v2._QUERY_CACHE.clear()
        with patch.object(v2.settings, "V2_DB_PATH", str(self.db_path)):
            overview = v2.curriculum_management_overview(
                grades=str(self.grade), conn=conn, user=user
            )["data"]
            students = v2.curriculum_management_students(
                grades=str(self.grade), major_name="测试专业", limit=200, offset=0,
                conn=conn, user=user,
            )["data"]
        conn.close()
        self.assertEqual(2, overview["summary"]["totalPlans"])
        expected = {row["studentId"]: row["expectedPlanId"] for row in students["items"]}
        self.assertEqual("P1", expected["S1"])
        self.assertEqual("P2", expected["S4"])

    def test_overview_counts_failed_and_candidate_evidence_independently(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "UPDATE student_plan_progress_summary SET evidence_status='explicit_gap',"
            "failed_required_courses=1,due_candidate_courses=2 WHERE student_id='S1'"
        )
        conn.commit()
        user = {"role_id": "dean", "username": "curriculum-overlap-test"}
        v2._QUERY_CACHE.clear()
        with patch.object(v2.settings, "V2_DB_PATH", str(self.db_path)):
            overview = v2.curriculum_management_overview(
                grades=str(self.grade), conn=conn, user=user
            )["data"]
            candidate_students = v2.curriculum_management_students(
                grades=str(self.grade), college_name="未映射学院", status="数据候选",
                limit=200, offset=0, conn=conn, user=user,
            )["data"]
            courses = v2.curriculum_management_courses(
                limit=20, grades=str(self.grade), college_name="未映射学院",
                conn=conn, user=user,
            )["data"]
        conn.close()
        self.assertEqual(1, overview["summary"]["actionRequiredStudents"])
        self.assertEqual(1, overview["summary"]["verificationStudents"])
        self.assertEqual({"S1"}, {row["studentId"] for row in candidate_students["items"]})
        self.assertEqual(
            "存在2门建议修读学期已过但尚未形成明确修读结果的必修课程",
            candidate_students["items"][0]["statusReason"],
        )
        self.assertTrue(courses["items"])


if __name__ == "__main__":
    unittest.main()

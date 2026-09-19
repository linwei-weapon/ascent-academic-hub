import sqlite3
import unittest
from datetime import date

from backend.api.routers.faculty import (
    _analysis_cache,
    _age_threshold_sides,
    _continuous_single_teacher_ids,
    _faculty_analysis,
    _matches_structure_review,
    _priority_classification,
    _real_teacher_value,
    _resolved_department,
    _under_35_flag,
    management_course,
    management_kpi_details,
    management_overview,
    management_teacher,
)


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_college(
            college_id TEXT PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE dim_teacher(
            teacher_id TEXT PRIMARY KEY,
            name TEXT,
            dept TEXT,
            title TEXT,
            source TEXT DEFAULT 'real'
        );
        CREATE TABLE dim_staff_employment_snapshot(
            semester_id TEXT NOT NULL,
            staff_id TEXT NOT NULL,
            college_id TEXT,
            dept TEXT,
            staff_category TEXT,
            employment_status TEXT NOT NULL,
            title TEXT,
            education TEXT,
            birth_date TEXT,
            age_band TEXT,
            is_under_35 INTEGER,
            source TEXT NOT NULL DEFAULT 'real',
            source_batch_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(semester_id,staff_id)
        );
        CREATE TABLE dim_course(
            course_id TEXT PRIMARY KEY,
            name TEXT,
            credits REAL,
            category TEXT,
            course_nature TEXT,
            is_required INTEGER,
            dept TEXT,
            source TEXT DEFAULT 'real'
        );
        CREATE TABLE fact_lesson(
            lesson_id TEXT,
            semester_id TEXT,
            course_id TEXT,
            teacher_id TEXT,
            teacher_ids TEXT,
            capacity INTEGER,
            enrolled INTEGER,
            total_hours REAL,
            class_names TEXT,
            PRIMARY KEY(lesson_id,semester_id)
        );
        CREATE TABLE data_quality_issue(
            issue_id TEXT PRIMARY KEY,
            domain TEXT,
            issue_type TEXT,
            semester_id TEXT,
            entity_type TEXT,
            entity_id TEXT,
            affected_rows INTEGER,
            severity TEXT,
            status TEXT,
            detail TEXT,
            recommendation TEXT,
            detected_at TEXT,
            source TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO dim_college(college_id,name) VALUES(?,?)",
        [("C1", "学院A"), ("C2", "学院B")],
    )
    conn.executemany(
        "INSERT INTO dim_teacher(teacher_id,name,dept,title) VALUES(?,?,?,?)",
        [
            ("T1", "教师1", "学院A", "讲师"),
            ("T2", "教师2", "学院A", "讲师"),
            ("TB", "外院教师", "学院B", "副教授"),
            ("TA", "异常教师", "学院A", "教授"),
        ],
    )
    conn.executemany(
        """INSERT INTO dim_staff_employment_snapshot(
            semester_id,staff_id,college_id,dept,staff_category,employment_status,
            title,education,birth_date,age_band,is_under_35,source,source_batch_id,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            ("2025-2026-2", "T1", "C1", "学院A", "专任教师", "在岗",
             "讲师", "硕士研究生", "2000-01-01", "35岁以下", 0, "real", "B1", "2026-02-01"),
            ("2025-2026-2", "T2", "C1", "学院A", "专任教师", "在岗",
             "讲师", None, "1980-01-01", "35-44岁", 0, "real", "B1", "2026-02-01"),
            ("2025-2026-2", "TB", "C2", "学院B", "专任教师", "在岗",
             "副教授", "博士研究生", "1975-01-01", "45-54岁", 0, "real", "B1", "2026-02-01"),
            ("2025-2026-2", "T3", "C2", "学院B", "行政人员", "在岗",
             None, None, "1985-01-01", "35-44岁", 0, "real", "B1", "2026-02-01"),
            ("2025-2026-2", "TA", "C1", "学院A", "专任教师", "在岗",
             "教授", "博士研究生", "1960-01-01", "55岁及以上", 0, "real", "B1", "2026-02-01"),
        ],
    )
    conn.executemany(
        """INSERT INTO dim_course(
            course_id,name,category,course_nature,is_required,dept
        ) VALUES(?,?,?,?,?,?)""",
        [
            ("C_NORMAL", "普通必修课", "专业课", "必修", 1, "学院A"),
            ("C_PRIORITY", "重点必修课", "专业课", "必修", 1, "学院A"),
            ("C_ANOM", "异常任务课程", "专业课", "必修", 1, "学院A"),
            ("C_CROSS", "跨单位承担课程", "专业课", "必修", 1, "学院A"),
            ("C_TEAM", "团队结构课程", "专业课", "必修", 1, "学院A"),
        ],
    )

    def add_lessons(course_id, semester, teacher_id, count, enrolled,
                    teacher_ids=""):
        for index in range(count):
            conn.execute(
                """INSERT INTO fact_lesson(
                    lesson_id,semester_id,course_id,teacher_id,teacher_ids,
                    capacity,enrolled,total_hours,class_names
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    f"{course_id}-{semester}-{teacher_id}-{index}", semester, course_id,
                    teacher_id, teacher_ids, enrolled + 5, enrolled, 32,
                    f"{course_id}-{index + 1}班",
                ),
            )

    add_lessons("C_NORMAL", "2025-2026-2", "T1", 1, 20)
    for semester in ("2024-2025-2", "2025-2026-1", "2025-2026-2"):
        # 最近3次中允许1次联合授课；同一教师至少2次唯一授课即可命中。
        teacher_ids = "T1;T2" if semester == "2024-2025-2" else ""
        add_lessons("C_PRIORITY", semester, "T1", 4, 30, teacher_ids)
    add_lessons("C_ANOM", "2025-2026-2", "TA", 4, 40)
    add_lessons("C_CROSS", "2025-2026-2", "TB", 4, 30)
    add_lessons("C_TEAM", "2025-2026-2", "T1", 2, 30, "T1;T2")
    add_lessons("C_TEAM", "2025-2026-2", "T2", 2, 30, "T1;T2")
    conn.execute(
        """INSERT INTO data_quality_issue(
            issue_id,domain,issue_type,semester_id,entity_type,entity_id,
            affected_rows,severity,status,detail,recommendation,detected_at,source
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "I1", "operation", "teacher_lesson_overflow", "2025-2026-2",
            "teacher", "TA", 4, "high", "open", "异常任务",
            "确认前继续排除", "2026-07-24", "derived",
        ),
    )
    conn.commit()
    return conn


def make_v2_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_organization(
            organization_id TEXT PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE dim_staff(
            staff_id TEXT PRIMARY KEY,
            display_name TEXT,
            organization_id TEXT,
            staff_type TEXT,
            title TEXT,
            status TEXT,
            source TEXT
        );
        INSERT INTO dim_organization VALUES ('OA','学院A');
        INSERT INTO dim_organization VALUES ('OB','学院B');
        INSERT INTO dim_staff VALUES
            ('S1','在职教师1','OA','正式工作人员',NULL,'在职','real'),
            ('S2','在职教师2','OA','自筹经费聘用人员',NULL,'在职','real'),
            ('S3','在职教师3','OB','正式工作人员',NULL,'在职','real'),
            ('S4','在职教师4','OB','正式工作人员',NULL,'在职','real'),
            ('S5','导师关系补录','学院A','mentor',NULL,'active','real'),
            ('S6','教学关系补录','学院A','lesson_teacher',NULL,'active','real_partial'),
            ('S7','离职教师','OA','正式工作人员',NULL,'不在职','real'),
            ('S8','在职状态导师占位','学院A','mentor',NULL,'在职','real');
    """)
    return conn


def college_user(college_id: str) -> dict:
    return {
        "role_id": "college_dean",
        "permission_context": {
            "authorized": True,
            "detailScope": {
                "type": "college",
                "sourceScopeIds": [college_id],
            },
        },
    }


def school_user() -> dict:
    return {
        "role_id": "dean",
        "permission_context": {
            "authorized": True,
            "detailScope": {"type": "all", "sourceScopeIds": []},
        },
    }


class FacultyAssuranceRuleTest(unittest.TestCase):
    def test_non_real_teacher_fields_do_not_enter_personnel_evidence(self):
        self.assertIsNone(
            _real_teacher_value({"source": "sim", "dept": "模拟学院"}, "dept")
        )
        self.assertEqual(
            "待映射部门",
            _resolved_department(None, "", _real_teacher_value(
                {"source": "demo", "dept": "演示学院"}, "dept",
            )),
        )

    def test_birth_date_precedes_under_35_snapshot_flag(self):
        self.assertEqual(
            1,
            _under_35_flag(
                {"birth_date": "2000-09-20", "is_under_35": 0},
                today=date(2035, 9, 19),
            ),
        )
        self.assertEqual(
            0,
            _under_35_flag(
                {"birth_date": "2000-09-19", "is_under_35": 1},
                today=date(2035, 9, 19),
            ),
        )

    def test_single_teacher_fact_does_not_alone_trigger_review(self):
        row = {
            "important_course": True,
            "lesson_count": 1,
            "enrolled": 20,
            "teacher_count": 1,
            "continuous_single": False,
            "high_concentration": False,
            "data_candidate": False,
            "title_completeness_rate": 100,
            "senior_title_teachers": 0,
        }
        review_type, reasons, _ = _priority_classification(row)
        self.assertEqual("general_observation", review_type)
        self.assertEqual([], reasons)

    def test_data_candidate_precedes_business_risk(self):
        row = {
            "important_course": True,
            "lesson_count": 10,
            "enrolled": 300,
            "teacher_count": 1,
            "continuous_single": True,
            "continuity_observations": 3,
            "high_concentration": True,
            "max_lesson_share": 100,
            "max_enrolled_share": 100,
            "data_candidate": True,
            "data_candidate_reasons": ["4条异常任务被排除"],
            "title_completeness_rate": 100,
            "senior_title_teachers": 1,
        }
        review_type, reasons, _ = _priority_classification(row)
        self.assertEqual("data_candidate", review_type)
        self.assertIn("4条异常任务被排除", reasons)

    def test_structure_rule_can_overlap_priority_classification(self):
        row = {
            "evaluable": True,
            "important_course": True,
            "lesson_count": 8,
            "enrolled": 240,
            "teacher_count": 2,
            "continuous_single": False,
            "high_concentration": True,
            "max_lesson_share": 90,
            "max_enrolled_share": 92,
            "data_candidate": False,
            "title_completeness_rate": 100,
            "senior_title_teachers": 0,
            "junior_title_only": True,
        }
        review_type, _, _ = _priority_classification(row)
        self.assertEqual("priority_review", review_type)
        self.assertTrue(_matches_structure_review(row))

    def test_structure_course_is_counted_once_when_multiple_rules_match(self):
        rows = [
            {
                "evaluable": True,
                "continuous_single": True,
                "age_structure_exception": True,
                "junior_title_only": True,
            },
            {
                "evaluable": True,
                "continuous_single": False,
                "age_structure_exception": True,
                "junior_title_only": False,
            },
            {
                "evaluable": True,
                "continuous_single": False,
                "age_structure_exception": False,
                "junior_title_only": False,
            },
        ]
        self.assertEqual(2, sum(_matches_structure_review(row) for row in rows))

    def test_each_structure_rule_can_independently_trigger_review(self):
        for flag in (
            "continuous_single", "age_structure_exception", "junior_title_only",
        ):
            row = {
                "evaluable": True,
                "continuous_single": False,
                "age_structure_exception": False,
                "junior_title_only": False,
            }
            row[flag] = True
            with self.subTest(flag=flag):
                self.assertTrue(_matches_structure_review(row))

    def test_two_actual_offerings_are_enough_for_continuous_single_rule(self):
        observed = [
            ("2025-2026-2", {"T1"}),
            ("2025-2026-1", {"T1"}),
        ]
        self.assertEqual(["T1"], _continuous_single_teacher_ids(observed))

    def test_age_threshold_uses_birth_date_and_treats_age_55_as_both_sides(self):
        today = date(2026, 9, 19)
        age_54 = _age_threshold_sides(None, "1972-09-20", today=today)
        age_55 = _age_threshold_sides(None, "1971-09-19", today=today)
        age_56 = _age_threshold_sides(None, "1970-09-19", today=today)

        self.assertEqual({"lte_55"}, age_54)
        self.assertEqual({"gte_55", "lte_55"}, age_55)
        self.assertEqual({"gte_55"}, age_56)
        self.assertTrue(all("lte_55" in sides for sides in (age_54, age_55)))
        self.assertTrue(all("gte_55" in sides for sides in (age_55, age_56)))
        self.assertFalse(
            all("lte_55" in sides for sides in (age_54, age_56))
            or all("gte_55" in sides for sides in (age_54, age_56))
        )


class FacultyAssuranceIntegrationTest(unittest.TestCase):
    def setUp(self):
        _analysis_cache.clear()
        self.conn = make_conn()
        self.v2_conn = make_v2_conn()

    def tearDown(self):
        self.conn.close()
        self.v2_conn.close()

    def test_anomaly_gate_continuity_and_course_responsibility(self):
        analysis = _faculty_analysis(self.conn, "2025-2026-2")
        courses = {row["course_id"]: row for row in analysis["courses"]}

        self.assertEqual("structure_review", courses["C_NORMAL"]["review_type"])
        self.assertTrue(courses["C_NORMAL"]["junior_title_only"])
        self.assertEqual("priority_review", courses["C_PRIORITY"]["review_type"])
        self.assertTrue(courses["C_PRIORITY"]["continuous_single"])
        self.assertEqual("data_candidate", courses["C_ANOM"]["review_type"])
        self.assertFalse(courses["C_ANOM"]["evaluable"])
        self.assertEqual(4, analysis["quality_gate"]["excluded_lesson_count"])
        # 责任学院按课程所属组织，而不是外院教师的人事归属。
        self.assertEqual("学院A", courses["C_CROSS"]["college_name"])

    def test_historical_analysis_does_not_use_future_offerings(self):
        analysis = _faculty_analysis(self.conn, "2025-2026-1")
        courses = {row["course_id"]: row for row in analysis["courses"]}

        self.assertEqual(2, courses["C_PRIORITY"]["continuity_observations"])
        self.assertFalse(courses["C_PRIORITY"]["continuous_single"])

    def test_continuity_evidence_does_not_expose_non_real_teacher_name(self):
        self.conn.execute(
            "UPDATE dim_teacher SET name='模拟姓名',source='sim' WHERE teacher_id='T1'"
        )
        analysis = _faculty_analysis(self.conn, "2025-2026-2")
        course = next(
            row for row in analysis["courses"] if row["course_id"] == "C_PRIORITY"
        )

        unique_evidence = next(
            row for row in course["continuity_evidence"]
            if row["semester_id"] == "2025-2026-2"
        )
        self.assertEqual(["T1"], unique_evidence["teacher_names"])

    def test_college_can_review_external_teacher_for_its_own_course(self):
        user = college_user("C1")
        detail = management_course(
            "C_CROSS", semester="2025-2026-2", user=user, conn=self.conn,
        )["data"]
        self.assertEqual("TB", detail["members"][0]["staff_id"])

        teacher = management_teacher(
            "TB", semester="2025-2026-2", course_id="C_CROSS",
            user=user, conn=self.conn,
        )["data"]
        self.assertEqual("外院教师", teacher["name"])
        self.assertNotIn("scoreTrend", teacher)
        self.assertNotIn("education", teacher)
        self.assertTrue(all("passRate" not in row for row in teacher["teachingHistory"]))
        self.assertEqual({"C_CROSS"}, {row["id"] for row in teacher["currentCourses"]})
        self.assertEqual({"C_CROSS"}, {row["courseId"] for row in teacher["teachingHistory"]})

    def test_other_college_cannot_open_course_team(self):
        with self.assertRaises(Exception) as caught:
            management_course(
                "C_CROSS", semester="2025-2026-2",
                user=college_user("C2"), conn=self.conn,
            )
        self.assertEqual(403, getattr(caught.exception, "status_code", None))

    def test_management_overview_exposes_five_drillable_kpis(self):
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
            v2_conn=self.v2_conn,
        )["data"]
        kpis = {item["key"]: item for item in payload["kpis"]}

        self.assertEqual(
            {
                "teaching_staff_coverage",
                "team_structure_exception",
                "continuous_single_teacher",
                "senior_title_teaching_rate",
                "young_teacher_teaching_rate",
            },
            set(kpis),
        )
        self.assertEqual("3 / 5 人", kpis["teaching_staff_coverage"]["value"])
        self.assertEqual(
            "1.授课教师总数：与当前学期 教学任务 里涉及的所有教师去重数\n"
            "2.教职工总数：当前学期 在职的教师数",
            kpis["teaching_staff_coverage"]["hint"],
        )
        self.assertEqual(4, kpis["team_structure_exception"]["numerator"])
        self.assertEqual("教师结构异常课程数", kpis["team_structure_exception"]["label"])
        self.assertEqual("", kpis["team_structure_exception"]["sub"])
        self.assertIn("职称仅包含助教或讲师", kpis["team_structure_exception"]["hint"])
        self.assertEqual(1, kpis["continuous_single_teacher"]["numerator"])
        self.assertEqual(
            "1. 同一教师在最近3次实际开课至少2次作为唯一授课教师（同一门课程），"
            "按教师工号去重（最近3次是实际开课记录，不是连续自然学期）",
            kpis["continuous_single_teacher"]["hint"],
        )
        self.assertEqual("33.3%", kpis["senior_title_teaching_rate"]["value"])
        self.assertEqual(
            "高职称教师授课占比=教授或副教授实际授课教师去重人数÷授课教师总数×100%",
            kpis["senior_title_teaching_rate"]["hint"],
        )
        self.assertEqual(3, kpis["senior_title_teaching_rate"]["denominator"])
        self.assertEqual("33.33%", kpis["young_teacher_teaching_rate"]["value"])
        self.assertEqual(
            "1/3人",
            kpis["young_teacher_teaching_rate"]["sub"],
        )
        self.assertEqual(1, kpis["young_teacher_teaching_rate"]["numerator"])
        self.assertEqual(
            "青年教师授课占比=35岁以下青年教师授课去重人数÷授课教师总数×100%",
            kpis["young_teacher_teaching_rate"]["hint"],
        )
        self.assertEqual(3, kpis["young_teacher_teaching_rate"]["denominator"])
        self.assertTrue(all(item["hint"] and item["drilldown"] for item in kpis.values()))

    def test_college_course_total_is_evaluable_plus_data_candidates(self):
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
            v2_conn=self.v2_conn,
        )["data"]
        college = next(item for item in payload["colleges"] if item["college_id"] == "C1")

        self.assertEqual(
            college["evaluable_courses"] + college["data_candidate_courses"],
            college["course_total"],
        )

    def test_kpi_details_reuse_course_and_teacher_evidence(self):
        teaching = management_kpi_details(
            "teaching_staff_coverage", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["T1", "TB", "T2"], [item["staff_id"] for item in teaching["items"]])
        self.assertEqual(["学院A", "学院B"], teaching["department_options"])
        self.assertEqual("硕士研究生", teaching["items"][0]["education"])
        self.assertEqual("专任教师", teaching["items"][0]["staff_category"])
        self.assertTrue(all(item["lesson_count"] > 0 for item in teaching["items"]))

        by_staff_id = management_kpi_details(
            "teaching_staff_coverage", semester="2025-2026-2", keyword="T2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["T2"], [item["staff_id"] for item in by_staff_id["items"]])

        by_name = management_kpi_details(
            "teaching_staff_coverage", semester="2025-2026-2", keyword="教师2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["T2"], [item["staff_id"] for item in by_name["items"]])

        by_course = management_kpi_details(
            "teaching_staff_coverage", semester="2025-2026-2", keyword="团队结构课程",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual({"T1", "T2"}, {item["staff_id"] for item in by_course["items"]})

        by_department = management_kpi_details(
            "teaching_staff_coverage", semester="2025-2026-2", department="学院A",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual({"T1", "T2"}, {item["staff_id"] for item in by_department["items"]})

    def test_teaching_staff_details_are_aggregated_only_within_authorized_course_scope(self):
        overview = management_overview(
            college="C1", semester="2025-2026-2", user=college_user("C1"),
            conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        coverage = next(
            item for item in overview["kpis"]
            if item["key"] == "teaching_staff_coverage"
        )
        self.assertEqual(3, coverage["numerator"])
        self.assertEqual(66.7, coverage["rate"])
        self.assertEqual("本科教学参与率 66.7%", coverage["sub"])
        young = next(
            item for item in overview["kpis"]
            if item["key"] == "young_teacher_teaching_rate"
        )
        self.assertEqual("33.33%", young["value"])
        self.assertEqual("1/3人", young["sub"])
        self.assertEqual(1, young["numerator"])
        self.assertEqual(3, young["denominator"])

        payload = management_kpi_details(
            "teaching_staff_coverage", college="C1", semester="2025-2026-2",
            user=college_user("C1"), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        items = {item["staff_id"]: item for item in payload["items"]}

        # 外院教师承担本院课程时仍属于当前授权课程范围，不能被人员归属过滤掉。
        self.assertEqual({"T1", "T2", "TB"}, set(items))
        self.assertEqual(1, items["TB"]["course_count"])
        self.assertEqual(4, items["TB"]["lesson_count"])
        self.assertEqual("跨单位承担课程", items["TB"]["course_names"])

        # 每名教师的课程、教学班和课程名称均只聚合当前授权学院内的教学任务。
        self.assertEqual(3, items["T1"]["course_count"])
        self.assertEqual(9, items["T1"]["lesson_count"])
        self.assertEqual(
            {"普通必修课", "重点必修课", "团队结构课程"},
            set(items["T1"]["course_names"].split("、")),
        )

        structure = management_kpi_details(
            "team_structure_exception", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(4, structure["total"])
        self.assertEqual(["学院A"], structure["college_options"])
        self.assertEqual(
            ["C_CROSS", "C_PRIORITY", "C_TEAM", "C_NORMAL"],
            [item["course_id"] for item in structure["items"]],
        )
        priority = next(item for item in structure["items"] if item["course_id"] == "C_PRIORITY")
        self.assertEqual(
            [
                "同一教师在最近3次实际开课至少2次作为唯一授课教师",
                "授课老师的年龄全部大于等于55岁，或者全部小于等于55岁",
                "授课教师中，职称仅包含助教或讲师",
            ],
            priority["reasons"],
        )
        self.assertEqual("；".join(priority["reasons"]), priority["reason"])
        self.assertNotIn("title_completeness_rate", priority)

        structure_by_id = management_kpi_details(
            "team_structure_exception", semester="2025-2026-2", keyword="C_TEAM",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["C_TEAM"], [item["course_id"] for item in structure_by_id["items"]])

        structure_by_name = management_kpi_details(
            "team_structure_exception", semester="2025-2026-2", keyword="跨单位",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["C_CROSS"], [item["course_id"] for item in structure_by_name["items"]])

        structure_by_college = management_kpi_details(
            "team_structure_exception", semester="2025-2026-2", opening_college="学院A",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(4, structure_by_college["total"])

        continuous = management_kpi_details(
            "continuous_single_teacher", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(1, continuous["summary"]["teacher_count"])
        self.assertEqual("T1", continuous["items"][0]["staff_id"])
        self.assertEqual("C_PRIORITY", continuous["items"][0]["course_id"])
        self.assertEqual("学院A", continuous["items"][0]["dept"])
        self.assertEqual("讲师", continuous["items"][0]["title"])
        self.assertEqual("硕士研究生", continuous["items"][0]["education"])
        self.assertEqual("专任教师", continuous["items"][0]["staff_category"])
        self.assertEqual(["学院A"], continuous["department_options"])

        continuous_by_id = management_kpi_details(
            "continuous_single_teacher", semester="2025-2026-2", keyword="T1",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["T1"], [item["staff_id"] for item in continuous_by_id["items"]])

        continuous_by_name = management_kpi_details(
            "continuous_single_teacher", semester="2025-2026-2", keyword="教师1",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["T1"], [item["staff_id"] for item in continuous_by_name["items"]])

        continuous_by_course = management_kpi_details(
            "continuous_single_teacher", semester="2025-2026-2", keyword="重点必修课",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["C_PRIORITY"], [item["course_id"] for item in continuous_by_course["items"]])

        continuous_by_department = management_kpi_details(
            "continuous_single_teacher", semester="2025-2026-2", department="学院A",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(1, continuous_by_department["total"])

        senior = management_kpi_details(
            "senior_title_teaching_rate", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual("TB", senior["items"][0]["staff_id"])
        self.assertEqual("副教授", senior["items"][0]["title"])
        self.assertEqual("博士研究生", senior["items"][0]["education"])
        self.assertGreater(senior["items"][0]["lesson_count"], 0)
        self.assertTrue(senior["breakdown"])
        self.assertEqual(["学院B"], senior["college_options"])

        senior_by_staff_id = management_kpi_details(
            "senior_title_teaching_rate", semester="2025-2026-2", keyword="TB",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["TB"], [item["staff_id"] for item in senior_by_staff_id["items"]])

        senior_by_name = management_kpi_details(
            "senior_title_teaching_rate", semester="2025-2026-2", keyword="外院",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["TB"], [item["staff_id"] for item in senior_by_name["items"]])

        senior_by_college = management_kpi_details(
            "senior_title_teaching_rate", semester="2025-2026-2", department="学院B",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["TB"], [item["staff_id"] for item in senior_by_college["items"]])

        young = management_kpi_details(
            "young_teacher_teaching_rate", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual("T1", young["items"][0]["staff_id"])
        self.assertEqual("35岁以下", young["items"][0]["age_band"])
        self.assertEqual("硕士研究生", young["items"][0]["education"])
        self.assertEqual("学院A", young["items"][0]["dept"])
        self.assertEqual(["学院A"], young["college_options"])
        self.assertEqual("学院A", young["breakdown"][0]["college_name"])
        self.assertEqual(1, young["breakdown"][0]["count"])
        self.assertEqual(3, young["breakdown"][0]["teacher_count"])
        self.assertEqual(33.3, young["breakdown"][0]["rate"])

        young_by_staff_id = management_kpi_details(
            "young_teacher_teaching_rate", semester="2025-2026-2", keyword="T1",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["T1"], [item["staff_id"] for item in young_by_staff_id["items"]])

        young_by_name = management_kpi_details(
            "young_teacher_teaching_rate", semester="2025-2026-2", keyword="教师1",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["T1"], [item["staff_id"] for item in young_by_name["items"]])

        young_by_college = management_kpi_details(
            "young_teacher_teaching_rate", semester="2025-2026-2", department="学院A",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertEqual(["T1"], [item["staff_id"] for item in young_by_college["items"]])

    def test_personnel_metrics_disclose_missing_real_snapshot(self):
        self.conn.execute("DROP TABLE dim_staff_employment_snapshot")
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
            v2_conn=self.v2_conn,
        )["data"]
        kpis = {item["key"]: item for item in payload["kpis"]}
        self.assertEqual("partial", kpis["teaching_staff_coverage"]["status"])
        self.assertEqual("3 / 4 人", kpis["teaching_staff_coverage"]["value"])
        self.assertEqual(4, kpis["teaching_staff_coverage"]["denominator"])
        self.assertEqual("", kpis["teaching_staff_coverage"]["sub"])
        self.assertEqual("unavailable", kpis["young_teacher_teaching_rate"]["status"])
        self.assertEqual("-", kpis["young_teacher_teaching_rate"]["value"])
        self.assertEqual(
            "-/3人",
            kpis["young_teacher_teaching_rate"]["sub"],
        )
        self.assertIsNone(kpis["young_teacher_teaching_rate"]["numerator"])
        self.assertEqual(3, kpis["young_teacher_teaching_rate"]["denominator"])

        details = management_kpi_details(
            "teaching_staff_coverage", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        self.assertGreater(details["items"][0]["lesson_count"], 0)

        self.v2_conn.execute("DELETE FROM dim_staff")
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
            v2_conn=self.v2_conn,
        )["data"]
        kpis = {item["key"]: item for item in payload["kpis"]}
        self.assertEqual("3 / — 人", kpis["teaching_staff_coverage"]["value"])
        self.assertIsNone(kpis["teaching_staff_coverage"]["denominator"])

    def test_young_teacher_rate_keeps_all_authorized_teachers_in_partial_denominator(self):
        self.conn.execute(
            """UPDATE dim_staff_employment_snapshot
               SET birth_date=NULL,age_band=NULL,is_under_35=NULL
               WHERE semester_id='2025-2026-2' AND staff_id='T2'"""
        )
        self.conn.execute(
            """DELETE FROM dim_staff_employment_snapshot
               WHERE semester_id='2025-2026-2' AND staff_id='TB'"""
        )

        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
            v2_conn=self.v2_conn,
        )["data"]
        young = next(
            item for item in payload["kpis"]
            if item["key"] == "young_teacher_teaching_rate"
        )
        self.assertEqual("partial", young["status"])
        self.assertEqual("33.33%", young["value"])
        self.assertEqual("1/3人", young["sub"])
        self.assertEqual(1, young["numerator"])
        self.assertEqual(3, young["denominator"])
        self.assertEqual(33.3, young["coverage"])

        details = management_kpi_details(
            "young_teacher_teaching_rate", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        college = next(
            row for row in details["breakdown"]
            if row["college_name"] == "学院A"
        )
        self.assertEqual(3, college["teacher_count"])
        self.assertEqual(1, college["known_count"])
        self.assertEqual(1, college["count"])
        self.assertEqual(33.3, college["rate"])
        self.assertEqual(33.3, college["coverage"])

    def test_young_teacher_drilldown_uses_real_attributes_and_sorts_college_rates(self):
        self.conn.execute(
            "UPDATE dim_teacher SET dept='模拟学院',title='模拟职称',source='sim' WHERE teacher_id='T1'"
        )
        self.conn.execute(
            """UPDATE dim_staff_employment_snapshot
               SET dept=NULL,title=NULL
               WHERE semester_id='2025-2026-2' AND staff_id='T1'"""
        )
        self.conn.execute(
            """UPDATE dim_staff_employment_snapshot
               SET birth_date='2000-01-01',age_band='35岁以下',is_under_35=1
               WHERE semester_id='2025-2026-2' AND staff_id='T2'"""
        )
        self.conn.execute(
            """INSERT INTO dim_course(
                   course_id,name,category,course_nature,is_required,dept
               ) VALUES('C_B','学院B青年课程','专业课','必修',1,'学院B')"""
        )
        self.conn.execute(
            """INSERT INTO fact_lesson(
                   lesson_id,semester_id,course_id,teacher_id,teacher_ids,
                   capacity,enrolled,total_hours,class_names
               ) VALUES('L_B','2025-2026-2','C_B','T2','',40,35,32,'学院B-1班')"""
        )
        _analysis_cache.clear()

        details = management_kpi_details(
            "young_teacher_teaching_rate", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        items = {item["staff_id"]: item for item in details["items"]}
        self.assertEqual("学院A", items["T1"]["dept"])
        self.assertIsNone(items["T1"]["title"])
        self.assertEqual("硕士研究生", items["T1"]["education"])
        self.assertEqual(["T1", "T2"], [item["staff_id"] for item in details["items"]])
        self.assertEqual(
            ["学院B", "学院A"],
            [row["college_name"] for row in details["breakdown"]],
        )
        self.assertEqual(100.0, details["breakdown"][0]["rate"])
        self.assertEqual(66.7, details["breakdown"][1]["rate"])

    def test_senior_teacher_list_uses_the_same_real_title_for_selection_and_display(self):
        self.conn.execute(
            "UPDATE dim_teacher SET title='讲师',source='sim' WHERE teacher_id='T1'"
        )
        self.conn.execute(
            "UPDATE dim_staff_employment_snapshot SET title='教授' WHERE staff_id='T1'"
        )
        self.conn.execute(
            "UPDATE dim_teacher SET title='教授',source='sim' WHERE teacher_id='TB'"
        )
        self.conn.execute(
            "UPDATE dim_staff_employment_snapshot SET title='讲师' WHERE staff_id='TB'"
        )
        self.conn.execute(
            "UPDATE dim_teacher SET title='教授',source='sim' WHERE teacher_id='T2'"
        )
        self.conn.execute(
            "UPDATE dim_staff_employment_snapshot SET title=NULL WHERE staff_id='T2'"
        )
        self.conn.execute(
            "UPDATE dim_course SET dept='学院B' WHERE course_id='C_CROSS'"
        )

        details = management_kpi_details(
            "senior_title_teaching_rate", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]

        self.assertEqual(["T1"], [item["staff_id"] for item in details["items"]])
        self.assertEqual("教授", details["items"][0]["title"])
        self.assertEqual(1, details["summary"]["senior_teacher_count"])
        self.assertEqual("学院A", details["breakdown"][0]["college_name"])
        self.assertEqual(1, details["breakdown"][0]["count"])
        self.assertEqual(2, details["breakdown"][0]["teacher_count"])
        self.assertEqual(50.0, details["breakdown"][0]["rate"])
        self.assertEqual(50.0, details["breakdown"][0]["coverage"])
        self.assertEqual(["学院A", "学院B"], [
            item["college_name"] for item in details["breakdown"]
        ])
        t2_gap = next(
            item for item in details["evidence_gaps"] if item["staff_id"] == "T2"
        )
        self.assertIsNone(t2_gap["title"])

    def test_staff_list_counts_tasks_without_lesson_id_and_uses_real_staff_fallback(self):
        self.conn.execute("DROP TABLE dim_staff_employment_snapshot")
        self.conn.execute(
            "UPDATE fact_lesson SET lesson_id=NULL "
            "WHERE course_id='C_NORMAL' AND semester_id='2025-2026-2'"
        )
        self.conn.execute("UPDATE dim_teacher SET dept='旧部门' WHERE teacher_id='T1'")
        self.v2_conn.execute(
            "INSERT INTO dim_staff VALUES(?,?,?,?,?,?,?)",
            ("T1", "教师1", "OA", "正式工作人员", "讲师", "在职", "real"),
        )

        details = management_kpi_details(
            "teaching_staff_coverage", semester="2025-2026-2",
            user=school_user(), conn=self.conn, v2_conn=self.v2_conn,
        )["data"]
        teacher = next(item for item in details["items"] if item["staff_id"] == "T1")

        self.assertGreater(teacher["lesson_count"], 0)
        self.assertEqual("学院A", teacher["dept"])
        self.assertEqual("正式工作人员", teacher["staff_category"])
        self.assertIsNone(teacher["education"])
        self.assertIn("学院A", details["department_options"])

    def test_personnel_snapshot_requires_trace_fields(self):
        self.conn.execute(
            "UPDATE dim_staff_employment_snapshot SET source_batch_id='' WHERE staff_id='T1'"
        )
        payload = management_overview(
            semester="2025-2026-2", user=school_user(), conn=self.conn,
            v2_conn=self.v2_conn,
        )["data"]
        kpis = {item["key"]: item for item in payload["kpis"]}
        self.assertEqual("partial", kpis["teaching_staff_coverage"]["status"])
        self.assertIn("缺少来源批次或更新时间", kpis["teaching_staff_coverage"]["sub"])

    def test_kpi_details_reject_other_college_scope(self):
        with self.assertRaises(Exception) as caught:
            management_kpi_details(
                "teaching_staff_coverage", college="C2", semester="2025-2026-2",
                user=college_user("C1"), conn=self.conn, v2_conn=self.v2_conn,
            )
        self.assertEqual(403, getattr(caught.exception, "status_code", None))


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""M1 课程通过率三分层测试：builder 聚合正确性、类别推导优先级、接口契约。

运行：cd code && python -X utf8 -m unittest backend.tests.test_course_pass_stat -v
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.envelope import ApiError
from backend.api.routers.v2 import (
    course_quality_detail,
    course_quality_topic,
    require_v2_all_reader,
)
from backend.etl.init_v2 import init_v2
from backend.etl.v2_course_pass_builder import (
    COURSE_GROUPS, classify_plan_row, derive_course_group, build_course_pass_stat,
)


class ClassifyTest(unittest.TestCase):
    """课程类别推导：培养方案模块规则与合并优先级。"""

    def test_plan_module_rules(self):
        self.assertEqual("公共必修", classify_plan_row("通识必修", "必修"))
        self.assertEqual("公共必修", classify_plan_row("公共基础课", "必修"))
        # 模块名不含“通识/公共/实践”关键词的必修课按规则落专业必修。
        self.assertEqual("专业必修", classify_plan_row("大学英语", "必修"))
        # 规则顺序即优先级：含“公共”且必修先于“实践”判定。
        self.assertEqual("公共必修", classify_plan_row("公共实践（必修）", "必修"))
        self.assertEqual("实践", classify_plan_row("专业实践（必修）", "必修"))
        self.assertEqual("专业必修", classify_plan_row("专业主干课", "必修"))
        self.assertEqual("选修", classify_plan_row("专业选修课", "选修"))
        self.assertIsNone(classify_plan_row("大学英语", None))
        self.assertIsNone(classify_plan_row(None, None))

    def test_merge_priority(self):
        # ① 培养方案优先，且同一课程多方案冲突时 公共必修 > 实践 > 专业必修 > 选修。
        self.assertEqual(("公共必修", "plan_module"),
                         derive_course_group(["选修", "公共必修"], "专业选修课"))
        self.assertEqual(("实践", "plan_module"),
                         derive_course_group(["专业必修", "实践"], None))
        self.assertEqual(("专业必修", "plan_module"),
                         derive_course_group(["选修", "专业必修"], None))
        # ② 无方案命中时回落 V1 category 映射。
        self.assertEqual(("公共必修", "v1_category"), derive_course_group([], "通识必修课"))
        self.assertEqual(("公共必修", "v1_category"), derive_course_group([], "体育课"))
        self.assertEqual(("专业必修", "v1_category"), derive_course_group([], "专业必修课"))
        self.assertEqual(("选修", "v1_category"), derive_course_group([], "专业选修课"))
        self.assertEqual(("实践", "v1_category"), derive_course_group([], "实践课"))
        # ③ 均无 → 其他。
        self.assertEqual(("其他", "default"), derive_course_group([], None))
        self.assertEqual(("其他", "default"), derive_course_group([], "理论课"))


_row_no = iter(range(1, 1000000))


def _insert_attempt(conn, attempt_id, course_id, semester, attempt_type, is_pass,
                    student="S1", published=1, void=0):
    conn.execute(
        "INSERT INTO grade_attempt(attempt_id,student_id,course_id,semester_id,"
        "attempt_type,is_pass,is_published,is_void,batch_id,source_row_no,source)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (attempt_id, student, course_id, semester, attempt_type, is_pass,
         published, void, "B1", next(_row_no), "real"))


class BuilderTest(unittest.TestCase):
    """小样本端到端：三率计算、分母0为NULL、有效记录过滤、类别落库。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v2_path = Path(self.tmp.name) / "v2.sqlite"
        conn = init_v2(self.v2_path)
        # C1：两层方案（一个公共必修一个选修）→ 公共必修；8首次(7过)+2补考(1过)+4重修(3过)
        conn.execute("INSERT INTO dim_course(course_id,name,category) VALUES('C1','公共课','理论课')")
        conn.execute("INSERT INTO curriculum_plan(plan_id,plan_name) VALUES('P1','方案一')")
        conn.execute("INSERT INTO curriculum_plan_course(plan_id,course_id,module,requirement_type)"
                     " VALUES('P1','C1','通识必修','必修')")
        conn.execute("INSERT INTO curriculum_plan_course(plan_id,course_id,module,requirement_type)"
                     " VALUES('P1','C1','扩展模块','选修')")
        for i in range(8):
            _insert_attempt(conn, f"C1-F{i}", "C1", "2024-2025-1", "regular", 1 if i < 7 else 0, student=f"S{i}")
        for i in range(2):
            _insert_attempt(conn, f"C1-M{i}", "C1", "2024-2025-1", "makeup", 1 if i < 1 else 0)
        for i in range(4):
            _insert_attempt(conn, f"C1-R{i}", "C1", "2024-2025-1", "retake", 1 if i < 3 else 0)
        # 无效记录不计入：未发布、已作废、is_pass 为空
        _insert_attempt(conn, "C1-X1", "C1", "2024-2025-1", "regular", 0, published=0)
        _insert_attempt(conn, "C1-X2", "C1", "2024-2025-1", "regular", 1, void=1)
        _insert_attempt(conn, "C1-X3", "C1", "2024-2025-1", "regular", None)
        # C2：无方案记录，靠 V1 category（实践课）→ 实践；只有首次记录，补考/重修分母为0
        conn.execute("INSERT INTO dim_course(course_id,name,category) VALUES('C2','实践课X','实践')")
        for i in range(4):
            _insert_attempt(conn, f"C2-F{i}", "C2", "2024-2025-1", "regular", 1 if i < 2 else 0)
        # C3：方案与 V1 都无 → 其他；deferred 计入首次链路
        conn.execute("INSERT INTO dim_course(course_id,name,category) VALUES('C3','其他课','理论课')")
        _insert_attempt(conn, "C3-F1", "C3", "2024-2025-1", "regular", 1)
        _insert_attempt(conn, "C3-D1", "C3", "2024-2025-1", "deferred", 0)
        conn.commit()
        conn.close()
        # V1 库：C2 实践课、C1 也有（但应被方案优先覆盖）
        self.v1_path = Path(self.tmp.name) / "v1.sqlite"
        v1 = sqlite3.connect(self.v1_path)
        v1.execute("CREATE TABLE dim_course(course_id TEXT PRIMARY KEY, category TEXT)")
        v1.executemany("INSERT INTO dim_course VALUES(?,?)",
                       [("C1", "专业选修课"), ("C2", "实践课")])
        v1.commit()
        v1.close()
        self.report = build_course_pass_stat(self.v2_path, self.v1_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _row(self, course_id):
        conn = sqlite3.connect(self.v2_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM agg_course_pass_stat WHERE course_id=?", (course_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def test_three_layer_rates(self):
        row = self._row("C1")
        self.assertEqual(8, row["first_attempts"])
        self.assertEqual(7, row["first_pass"])
        self.assertEqual(2, row["makeup_attempts"])
        self.assertEqual(1, row["makeup_pass"])
        self.assertEqual(4, row["retake_attempts"])
        self.assertEqual(3, row["retake_pass"])
        self.assertAlmostEqual(0.875, row["first_pass_rate"])
        self.assertAlmostEqual(0.5, row["makeup_pass_rate"])
        self.assertAlmostEqual(0.75, row["retake_pass_rate"])
        self.assertEqual("derived", row["source"])

    def test_zero_denominator_is_null(self):
        row = self._row("C2")
        self.assertEqual(0.5, row["first_pass_rate"])
        self.assertEqual(0, row["makeup_attempts"])
        self.assertIsNone(row["makeup_pass_rate"])
        self.assertIsNone(row["retake_pass_rate"])

    def test_deferred_counts_as_first(self):
        row = self._row("C3")
        self.assertEqual(2, row["first_attempts"])  # regular + deferred
        self.assertEqual(1, row["first_pass"])

    def test_group_derivation_end_to_end(self):
        self.assertEqual("公共必修", self._row("C1")["course_group"])  # 方案优先于V1“专业选修课”
        self.assertEqual("plan_module", self._row("C1")["group_basis"])
        self.assertEqual("实践", self._row("C2")["course_group"])
        self.assertEqual("v1_category", self._row("C2")["group_basis"])
        self.assertEqual("其他", self._row("C3")["course_group"])
        self.assertEqual("default", self._row("C3")["group_basis"])

    def test_idempotent_rebuild(self):
        again = build_course_pass_stat(self.v2_path, self.v1_path)
        self.assertEqual(self.report["rows"], again["rows"])
        conn = sqlite3.connect(self.v2_path)
        n = conn.execute("SELECT COUNT(*) FROM agg_course_pass_stat").fetchone()[0]
        conn.close()
        self.assertEqual(self.report["rows"], n)


def _api_conn():
    """接口测试用内存库：agg_course_pass_stat + dim_course + grade_attempt。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE agg_course_pass_stat(
        course_id TEXT, semester_id TEXT, course_name TEXT, course_group TEXT,
        group_basis TEXT, first_attempts INTEGER, first_pass INTEGER,
        makeup_attempts INTEGER, makeup_pass INTEGER,
        retake_attempts INTEGER, retake_pass INTEGER,
        first_pass_rate REAL, makeup_pass_rate REAL, retake_pass_rate REAL,
        rule_version TEXT, calculated_at TEXT, source TEXT,
        PRIMARY KEY(course_id, semester_id));
    CREATE TABLE dim_course(course_id TEXT PRIMARY KEY, name TEXT);
    CREATE TABLE grade_attempt(attempt_id TEXT, student_id TEXT, course_id TEXT,
        semester_id TEXT, attempt_type TEXT, is_pass INTEGER, score REAL,
        is_published INTEGER, is_void INTEGER);
    CREATE TABLE agg_course_offering(
        course_id TEXT, semester_id TEXT, lesson_count INTEGER,
        teacher_count INTEGER, enrolled INTEGER, total_hours REAL);
    INSERT INTO dim_course VALUES('PUB', '公共课A');
    INSERT INTO dim_course VALUES('ELE', '选修课B');
    INSERT INTO dim_course VALUES('NEW', '新学期课程');
    INSERT INTO dim_course VALUES('BOUND', '阈值边界课程');
    INSERT INTO dim_course VALUES('BOUNDVOL', '波动边界课程');
    INSERT INTO dim_course VALUES('LOWRETAKE', '低样本重修课程');
    """)
    # PUB：公共必修，两学期首次未通过率均>15 → persistent_high
    for sem, fa, fp in (("2024-2025-1", 40, 30), ("2024-2025-2", 40, 32)):
        conn.execute("INSERT INTO agg_course_pass_stat VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("PUB", sem, "公共课A", "公共必修", "plan_module", fa, fp, 5, 2, 6, 3,
                      round(fp / fa, 4), 0.4, 0.5, "pass-stat-v1", "now", "derived"))
        for i in range(fa):
            conn.execute("INSERT INTO grade_attempt VALUES(?,?,?,?,?,?,?,?,?)",
                         (f"PUB-{sem}-{i}", f"S{i}", "PUB", sem, "regular", 1, 80, 1, 0))
    conn.execute("INSERT INTO agg_course_pass_stat VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("NEW", "2025-2026-1", "新学期课程", "其他", "plan_module", 40, 34, 0, 0, 0, 0,
                  0.85, None, None, "pass-stat-v1", "now", "derived"))
    for i in range(40):
        conn.execute("INSERT INTO grade_attempt VALUES(?,?,?,?,?,?,?,?,?)",
                     (f"NEW-2025-2026-1-{i}", f"N{i}", "NEW", "2025-2026-1", "regular", 1, 80, 1, 0))
    for sem in ("2024-2025-1", "2024-2025-2"):
        conn.execute("INSERT INTO agg_course_pass_stat VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("BOUND", sem, "阈值边界课程", "其他", "plan_module", 40, 34, 0, 0, 0, 0,
                      0.85, None, None, "pass-stat-v1", "now", "derived"))
    for sem, fp in (("2024-2025-1", 36), ("2024-2025-2", 30)):
        conn.execute("INSERT INTO agg_course_pass_stat VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("BOUNDVOL", sem, "波动边界课程", "其他", "plan_module", 40, fp, 0, 0, 0, 0,
                      round(fp / 40, 4), None, None, "pass-stat-v1", "now", "derived"))
    conn.execute("INSERT INTO agg_course_pass_stat VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("LOWRETAKE", "2024-2025-1", "低样本重修课程", "其他", "plan_module", 0, 0, 0, 0, 5, 2,
                  None, None, 0.4, "pass-stat-v1", "now", "derived"))
    # ELE：选修，首次全部通过，无关注原因
    conn.execute("INSERT INTO agg_course_pass_stat VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("ELE", "2024-2025-1", "选修课B", "选修", "plan_module", 40, 40, 0, 0, 0, 0,
                  1.0, None, None, "pass-stat-v1", "now", "derived"))
    for i in range(40):
        conn.execute("INSERT INTO grade_attempt VALUES(?,?,?,?,?,?,?,?,?)",
                     (f"ELE-{i}", f"E{i}", "ELE", "2024-2025-1", "regular", 1, 80, 1, 0))
    conn.commit()
    return conn


class CourseQualityApiTest(unittest.TestCase):
    """接口契约：三分层字段、course_group 过滤、鉴权不变。"""

    def setUp(self):
        self.conn = _api_conn()

    def tearDown(self):
        self.conn.close()

    def _call(self, **kwargs):
        kwargs.setdefault("min_sample", 30)
        kwargs.setdefault("limit", 50)
        kwargs.setdefault("offset", 0)
        return course_quality_topic(conn=self.conn, user={"role_id": "dean"}, **kwargs)

    def test_three_layer_fields_present(self):
        data = self._call()["data"]
        course = next(c for c in data["courses"] if c["course_id"] == "PUB")
        self.assertEqual("公共必修", course["course_group"])
        self.assertAlmostEqual(77.5, course["first_pass_rate"])  # 62/80
        self.assertAlmostEqual(40.0, course["makeup_pass_rate"])  # 4/10
        self.assertAlmostEqual(50.0, course["retake_pass_rate"])  # 6/12
        # deprecated 兼容字段 = 首次未通过率
        self.assertAlmostEqual(22.5, course["fail_rate"])
        self.assertIn("persistent_high", course["attention_reasons"])
        self.assertEqual(1, data["summary"]["public_required_courses"])
        self.assertIn("first_pass_rate", data["definition"])
        self.assertIn("deprecated", data["definition"]["fail_rate"])
        self.assertEqual(
            "至少有一个学期达到30条有效成绩记录的去重课程数；有效记录是指已发布且未作废且 是否通过 非空的记录；",
            data["definition"]["sample"],
        )
        self.assertEqual(
            "首次修读（含缓考）通过人次数÷首次修读人次数，分母为0时 输出 '-' ",
            data["definition"]["first_pass_rate"],
        )
        self.assertEqual(
            "同一门课程至少有2个学期及以上且每学期首次未通过率均高于15%",
            data["definition"]["persistent_high"],
        )
        self.assertEqual(
            "同一门课程至少有2个学期及以上，最高与最低首次未通过率相差高于15个百分点",
            data["definition"]["volatile"],
        )
        self.assertEqual(
            "筛选条件范围内重修成绩记录数量",
            data["definition"]["retake_attempts"],
        )

    def test_course_group_filter(self):
        data = self._call(course_group="公共必修")["data"]
        ids = {c["course_id"] for c in data["courses"]}
        self.assertEqual({"PUB"}, ids)
        # 过滤后无命中时返回空而不是报错
        data2 = self._call(course_group="实践")["data"]
        self.assertEqual([], data2["courses"])
        self.assertEqual(0, data2["total"])

    def test_semester_options_are_descending_and_not_narrowed_by_filters(self):
        data = self._call(
            semester_from="2024-2025-2",
            semester_to="2024-2025-2",
            course_group="选修",
        )["data"]
        self.assertEqual(
            ["2025-2026-1", "2024-2025-2", "2024-2025-1"],
            data["semesters"],
        )

    def test_public_required_section_respects_course_group_filter(self):
        data = self._call(course_group="选修")["data"]
        self.assertEqual([], data["publicRequiredTop"])
        self.assertEqual(0, data["publicRequiredSummary"]["courses"])

    def test_attention_thresholds_are_strictly_greater_than_15(self):
        data = self._call()["data"]
        ids = {course["course_id"] for course in data["courses"]}
        self.assertNotIn("BOUND", ids)  # 每学期首次未通过率恰好15%
        self.assertNotIn("BOUNDVOL", ids)  # 最高与最低首次未通过率恰好相差15个百分点

    def test_retake_summary_includes_low_sample_terms_in_filter_range(self):
        data = self._call(
            semester_from="2024-2025-1",
            semester_to="2024-2025-2",
        )["data"]
        self.assertEqual(17, data["summary"]["retake_attempts"])

    def test_course_detail_semester_range_is_inclusive(self):
        data = course_quality_detail(
            "PUB",
            semester_from="2024-2025-1",
            semester_to="2024-2025-2",
            conn=self.conn,
            user={"role_id": "dean"},
        )["data"]
        self.assertEqual(
            ["2024-2025-1", "2024-2025-2"],
            [row["semester_id"] for row in data["trends"]],
        )

    def test_invalid_course_group_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            self._call(course_group="不存在类别")
        self.assertEqual(400, ctx.exception.status_code)

    def test_scoped_role_still_denied(self):
        # 鉴权逻辑不变：范围角色（学院/辅导员等）仍不能访问全校专题。
        for role in ("college_dean", "counselor", "mentor"):
            with self.assertRaises(ApiError):
                require_v2_all_reader({"role_id": role})
        with self.assertRaises(ApiError):
            require_v2_all_reader(
                {"role_id": "dean",
                 "permission_context": {"detailScope": {"type": "college"}}})
        self.assertEqual("dean", require_v2_all_reader({"role_id": "dean"})["role_id"])

    def test_missing_agg_table_returns_503(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
        CREATE TABLE dim_course(course_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE grade_attempt(attempt_id TEXT, student_id TEXT, course_id TEXT,
            semester_id TEXT, attempt_type TEXT, is_pass INTEGER,
            is_published INTEGER, is_void INTEGER);
        """)
        try:
            with self.assertRaises(ApiError) as ctx:
                course_quality_topic(conn=conn, user={"role_id": "dean"}, min_sample=30)
            self.assertEqual(503, ctx.exception.status_code)
        finally:
            conn.close()

    def test_group_values_closed_set(self):
        self.assertEqual(("公共必修", "专业必修", "选修", "实践", "其他"), COURSE_GROUPS)


if __name__ == "__main__":
    unittest.main()

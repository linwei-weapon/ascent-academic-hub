# -*- coding: utf-8 -*-
"""决策Skill单元测试：内存SQLite fixture，验证判定逻辑、分级、配置覆写与指纹稳定性。

运行：cd code && python -m unittest backend.tests.test_decision_skills -v
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skills import config_store
from backend.skills.alert_priority import AlertPrioritySkill
from backend.skills.course_quality import CourseQualitySkill
from backend.skills.faculty_structure import FacultyStructureSkill
from backend.skills.graduation_gap import GraduationGapSkill
from backend.skills.protocol import (SkillContext, Signal,
                                     briefing_fingerprint)

SEM = "2025-2026-2"
ADMIN = {"username": "admin", "role_id": "admin",
         "permission_context": {"authorized": True,
                                "detailScope": {"type": "all"},
                                "activeRole": "admin"}}


def mem_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def make_ctx(skill, legacy, v2, override=None, semester=SEM):
    config = dict(skill.default_config)
    if override:
        config.update(override)
    return SkillContext(user=ADMIN, legacy=legacy, v2=v2, config=config,
                        config_version="test", semester=semester)


def add_grades(conn, course_id, semester, total, fails, gpa_pass=3.0):
    for i in range(total):
        passed = i >= fails
        conn.execute(
            "INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?,?)",
            (f"{course_id}-{semester}-{i}", course_id, semester,
             80.0 if passed else 50.0, gpa_pass if passed else 0.0,
             1 if passed else 0, 1, 2.0))


# ---------------------------------------------------------------------------
class GraduationGapTest(unittest.TestCase):
    def setUp(self):
        self.legacy = mem_conn()
        self.v2 = v2 = mem_conn()
        v2.executescript("""
        CREATE TABLE dim_student(student_id TEXT PRIMARY KEY, entry_grade INTEGER,
            student_status TEXT, major_code TEXT, major_name TEXT,
            organization_id TEXT, class_code TEXT, display_name TEXT);
        CREATE TABLE dim_course(course_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE student_plan_course_status(student_id TEXT, course_id TEXT,
            rule_version TEXT, requirement_type TEXT, completion_status TEXT,
            is_overdue INTEGER, suggested_term TEXT, module TEXT);
        CREATE TABLE teaching_lesson(lesson_id TEXT, course_id TEXT,
            semester_id TEXT, enrolled INTEGER);
        CREATE TABLE student_course_substitution(substitution_id TEXT,
            student_id TEXT, original_course_id TEXT, approval_status TEXT);
        CREATE TABLE grade_attempt(student_id TEXT, course_id TEXT,
            is_void INTEGER, is_published INTEGER);
        """)
        students = [("S1", 2022, "M1"), ("S2", 2022, "M2"), ("S3", 2022, "M1"),
                    ("S4", 2022, "M1"), ("S5", 2022, "M1"), ("S6", 2022, "M1"),
                    ("S7", 2022, "M1"), ("S8", 2023, "M1")]
        for sid, grade, major in students:
            v2.execute("INSERT INTO dim_student VALUES(?,?,?,?,?,?,?,?)",
                       (sid, grade, "在校", major, f"专业{major}", "ORG1", "C1",
                        f"学生{sid}"))
        v2.executemany("INSERT INTO dim_course VALUES(?,?)",
                       [("C1", "硬课A"), ("C2", "疑似课B"), ("C3", "在途课C")])
        plan = []
        # C1：S1/S2 明确未通过（无教学班、无替代 → 无路径）
        plan += [("S1", "C1", "failed"), ("S2", "C1", "failed")]
        # C2：S3/S4 疑似（逾期+临近学期），S5 有替代通过→排除
        plan += [("S3", "C2", "not_completed"), ("S4", "C2", "not_completed"),
                 ("S5", "C2", "not_completed")]
        # C3：S6 有在途成绩→排除；S7 建议学期非临近→排除
        plan += [("S6", "C3", "not_completed"), ("S7", "C3", "not_completed")]
        # S8 非目标届，failed 也不应计入
        plan += [("S8", "C1", "failed")]
        terms = {"S3": "7", "S4": "7", "S5": "7", "S6": "7", "S7": "1"}
        for sid, cid, status in plan:
            overdue = 1 if status == "not_completed" else 0
            v2.execute(
                "INSERT INTO student_plan_course_status VALUES(?,?,?,?,?,?,?,?)",
                (sid, cid, "growth-v1", "必修", status, overdue,
                 terms.get(sid, "5"), "模块"))
        v2.execute("INSERT INTO student_course_substitution VALUES(?,?,?,?)",
                   ("SUB1", "S5", "C2", "通过"))
        v2.execute("INSERT INTO grade_attempt VALUES(?,?,?,?)",
                   ("S6", "C3", 0, 0))
        self.skill = GraduationGapSkill()

    def tearDown(self):
        self.legacy.close(); self.v2.close()

    def _run(self, override=None):
        return self.skill.run(make_ctx(self.skill, self.legacy, self.v2, override))

    def test_blocked_counts_and_exclusions(self):
        r = self._run()
        self.assertTrue(r.data_readiness["ready"])
        self.assertEqual(r.summary_stats["blocked_students"], 2)   # S1/S2，S8被届排除
        self.assertEqual(r.summary_stats["suspected_students"], 2)  # S3/S4，S5/S6/S7被排除
        gap = [s for s in r.signals if s.signal_id.endswith(":course:C1")]
        self.assertEqual(len(gap), 1)
        self.assertEqual(gap[0].severity, "high")       # 默认协调线20人 → 学院级
        self.assertIn("无路径", gap[0].headline)

    def test_school_level_with_override(self):
        r = self._run({"coordination_min_students": 2})
        gap = [s for s in r.signals if s.signal_id.endswith(":course:C1")][0]
        self.assertEqual(gap.severity, "critical")      # 达校级协调线
        self.assertIn("校级协调", gap.headline)

    def test_structural_vs_scattered(self):
        r = self._run()
        self.assertEqual(r.summary_stats["structural_courses"], 0)  # 默认线50
        self.assertEqual(r.summary_stats["scattered_suspected_students"], 2)
        r2 = self._run({"structural_gap_min_students": 2})
        self.assertEqual(r2.summary_stats["structural_courses"], 1)
        structural = [s for s in r2.signals if s.signal_type == "structural_gap"]
        self.assertEqual(len(structural), 1)
        self.assertIn("集中核验", structural[0].headline)

    def test_fingerprint_stable_and_sensitive(self):
        fp1 = briefing_fingerprint(self._run().signals)
        fp2 = briefing_fingerprint(self._run().signals)
        self.assertEqual(fp1, fp2)
        self.v2.execute(
            "INSERT INTO student_plan_course_status VALUES(?,?,?,?,?,?,?,?)",
            ("S3", "C1", "growth-v1", "必修", "failed", 0, "5", "模块"))
        fp3 = briefing_fingerprint(self._run().signals)
        self.assertNotEqual(fp1, fp3)

    def test_unavailable_when_tables_missing(self):
        empty = mem_conn()
        try:
            r = self.skill.run(make_ctx(self.skill, self.legacy, empty))
            self.assertFalse(r.data_readiness["ready"])
            self.assertEqual(r.signals, [])
        finally:
            empty.close()


# ---------------------------------------------------------------------------
class CourseQualityTest(unittest.TestCase):
    def setUp(self):
        self.legacy = lv = mem_conn()
        self.v2 = mem_conn()
        lv.executescript("""
        CREATE TABLE dim_student(student_id TEXT PRIMARY KEY, college_id TEXT,
            name TEXT);
        CREATE TABLE dim_course(course_id TEXT PRIMARY KEY, name TEXT, is_required INTEGER);
        CREATE TABLE fact_grade(student_id TEXT, course_id TEXT, semester_id TEXT,
            score REAL, gpa REAL, is_pass INTEGER, is_required INTEGER, credits REAL);
        """)
        courses = [("BASE1", "基础课1"), ("BASE2", "基础课2"), ("BASE3", "基础课3"),
                   ("BASE4", "基础课4"), ("PERSIST", "持续课"), ("SPIKE", "恶化课"),
                   ("IMPROV", "改善课")]
        for cid, name in courses:
            lv.execute("INSERT INTO dim_course VALUES(?,?,?)", (cid, name, 1))
        hist = {"BASE1": 1, "BASE2": 1, "BASE3": 1, "BASE4": 1,
                "PERSIST": 3, "SPIKE": 0, "IMPROV": 3}
        prev = {"BASE1": 1, "BASE2": 1, "BASE3": 1, "BASE4": 1,
                "PERSIST": 3, "SPIKE": 0, "IMPROV": 2}
        cur = {"BASE1": 1, "BASE2": 1, "BASE3": 1, "BASE4": 1,
               "PERSIST": 3, "SPIKE": 3, "IMPROV": 0}
        # 三学期，每学期10人；IMPROV 第三学期 0 挂科但需 f1<f2：用 1 挂科
        cur["IMPROV"] = 0
        for cid, _ in courses:
            add_grades(lv, cid, "2024-2025-1", 10, hist[cid])
            add_grades(lv, cid, "2024-2025-2", 10, prev[cid])
            add_grades(lv, cid, SEM, 10, cur[cid])
        # IMPROV 当前学期 1 挂科保证 f1<f2<f3 不成立则换 0.5 不可——用 0/10 与 prev 2/10
        self.skill = CourseQualitySkill()

    def tearDown(self):
        self.legacy.close(); self.v2.close()

    def _run(self, override=None):
        cfg = {"min_sample": 5}
        if override:
            cfg.update(override)
        return self.skill.run(make_ctx(self.skill, self.legacy, self.v2, cfg))

    def test_states_classification(self):
        r = self._run()
        stats = r.summary_stats
        # 当前学期率：BASE=0.1 ×4, PERSIST=0.3, SPIKE=0.3, IMPROV=0
        # 基线中位数=0.1 → 持续线=max(0.2,0.10)=0.2
        self.assertEqual(stats["baseline_fail_rate"], 10.0)
        self.assertEqual(stats["persistent_courses"], 1)   # PERSIST 两学期0.3>0.2
        self.assertEqual(stats["spike_courses"], 1)        # SPIKE 0→0.3，Δ30pp
        types = {s.signal_type for s in r.signals}
        self.assertIn("course_persistent", types)
        self.assertIn("course_spike", types)
        self.assertIn("quality_overview", types)

    def test_persistent_severity_and_action(self):
        r = self._run()
        p = [s for s in r.signals if s.signal_type == "course_persistent"][0]
        self.assertEqual(p.severity, "high")
        self.assertIn("复盘", p.action["what"])
        self.assertEqual(p.entity["id"], "PERSIST")

    def test_improving_positive_signal(self):
        # IMPROV: 0.3 → 0.2 → 0.0，连续下降且 f3=0.3>baseline
        r = self._run()
        imp = [s for s in r.signals if s.signal_type == "improving"]
        self.assertEqual(len(imp), 1)
        self.assertEqual(imp[0].severity, "low")
        self.assertIn("改善课", imp[0].headline)

    def test_normal_courses_excluded(self):
        r = self._run()
        ids = {s.entity.get("id") for s in r.signals}
        for base in ("BASE1", "BASE2", "BASE3", "BASE4"):
            self.assertNotIn(base, ids)

    def test_failed_students_context(self):
        """课程级信号携带本学期挂科学生行（明细下钻数据源）。"""
        r = self._run()
        p = [s for s in r.signals if s.signal_type == "course_persistent"][0]
        self.assertEqual(p.context["failed_total"], 3)
        self.assertEqual(len(p.context["failed_students"]), 3)
        self.assertIn("score", p.context["failed_students"][0])
        # 总览信号携带全量课程清单（门数类数字的明细下钻数据源）
        ov = [s for s in r.signals if s.signal_type == "quality_overview"][0]
        states = {c["state"] for c in ov.context["courses"]}
        self.assertIn("persistent", states)
        self.assertIn("spike", states)


# ---------------------------------------------------------------------------
class AlertPriorityTest(unittest.TestCase):
    def setUp(self):
        self.legacy = lv = mem_conn()
        self.v2 = mem_conn()
        lv.executescript("""
        CREATE TABLE dim_student(student_id TEXT PRIMARY KEY, name TEXT, college_id TEXT);
        CREATE TABLE fact_alert(alert_id INTEGER PRIMARY KEY, student_id TEXT,
            level TEXT, type TEXT, trigger_detail TEXT, created_at TEXT, is_active INTEGER);
        CREATE TABLE alert_event(alert_id INTEGER, workflow_status TEXT,
            first_detected_at TEXT);
        CREATE TABLE fact_grade(student_id TEXT, course_id TEXT, semester_id TEXT,
            score REAL, gpa REAL, is_pass INTEGER, is_required INTEGER, credits REAL);
        """)
        for sid, college in (("SA", "C01"), ("SB", "C01"), ("SC", "C02")):
            lv.execute("INSERT INTO dim_student VALUES(?,?,?)",
                       (sid, f"学生{sid}", college))
        now = datetime.now()
        old = (now - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
        recent = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        lv.execute("INSERT INTO fact_alert VALUES(1,'SA','严重','学业','链A',?,1)", (old,))
        lv.execute("INSERT INTO fact_alert VALUES(2,'SB','严重','学业','链B',?,1)", (old,))
        lv.execute("INSERT INTO fact_alert VALUES(3,'SC','提醒','学业','链C',?,1)", (recent,))
        lv.execute("INSERT INTO alert_event VALUES(1,'new',?)", (old,))
        lv.execute("INSERT INTO alert_event VALUES(2,'contacted',?)", (old,))
        lv.execute("INSERT INTO alert_event VALUES(3,'new',?)", (recent,))
        # SA：本学期3门必修未通过；GPA 3.0 → 1.0（下降2.0）
        for i in range(3):
            lv.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?,?)",
                       ("SA", f"F{i}", SEM, 40.0, 0.0, 0, 1, 2.0))
        lv.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?,?)",
                   ("SA", "P1", SEM, 90.0, 4.0, 1, 1, 2.0))
        lv.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?,?)",
                   ("SA", "P2", "2024-2025-2", 90.0, 3.0, 1, 1, 2.0))
        self.skill = AlertPrioritySkill()

    def tearDown(self):
        self.legacy.close(); self.v2.close()

    def _run(self, override=None):
        return self.skill.run(make_ctx(self.skill, self.legacy, self.v2, override))

    def test_composite_scoring_order(self):
        r = self._run()
        queue_sig = [s for s in r.signals if s.signal_type == "priority_queue"][0]
        queue = queue_sig.context["queue"]
        # SA = 40(严重) + 24(3门必修×8封顶24) + 15(GPA降≥0.5) + 10(滞留) = 89
        self.assertEqual(queue[0]["student_id"], "SA")
        self.assertEqual(queue[0]["score"], 89)
        self.assertEqual(queue[1]["student_id"], "SB")  # 40
        self.assertEqual(queue[2]["student_id"], "SC")  # 10
        self.assertEqual(len(queue[0]["reasons"]), 4)

    def test_stale_signal_only_unclaimed_critical(self):
        r = self._run()
        stale = [s for s in r.signals if s.signal_type == "stale_critical"]
        self.assertEqual(len(stale), 1)
        self.assertIn("1条严重级预警滞留", stale[0].headline)  # 仅SA；SB已认领、SC非严重

    def test_top_n_cut(self):
        r = self._run({"top_n": 2})
        queue_sig = [s for s in r.signals if s.signal_type == "priority_queue"][0]
        self.assertEqual(len(queue_sig.context["queue"]), 2)
        self.assertEqual(r.summary_stats["queue_size"], 2)


# ---------------------------------------------------------------------------
class FacultyStructureTest(unittest.TestCase):
    def setUp(self):
        self.legacy = mem_conn()
        self.v2 = v2 = mem_conn()
        v2.executescript("""
        CREATE TABLE agg_course_offering(semester_id TEXT, course_id TEXT,
            lesson_count INTEGER, teacher_count INTEGER, enrolled INTEGER,
            PRIMARY KEY(semester_id, course_id));
        CREATE TABLE agg_course_team(semester_id TEXT, course_id TEXT,
            teacher_count INTEGER, professor_count INTEGER,
            associate_professor_count INTEGER, lecturer_count INTEGER,
            unknown_title_count INTEGER, PRIMARY KEY(semester_id, course_id));
        CREATE TABLE dim_course(course_id TEXT PRIMARY KEY, name TEXT,
            organization_id TEXT);
        CREATE TABLE dim_staff(staff_id TEXT PRIMARY KEY, title TEXT);
        """)
        snap = "2023-2024-1"
        offerings = [("H", 4, 1, 400), ("M", 2, 1, 100),
                     ("S", 1, 1, 10), ("N", 5, 3, 500)]
        for cid, lessons, tc, enrolled in offerings:
            v2.execute("INSERT INTO agg_course_offering VALUES(?,?,?,?,?)",
                       (snap, cid, lessons, tc, enrolled))
        teams = [("H", 1, 0, 0, 0, 1), ("M", 1, 0, 0, 0, 1),
                 ("S", 1, 0, 0, 0, 1), ("N", 3, 1, 1, 1, 0)]
        for cid, tc, prof, assoc, lect, unk in teams:
            v2.execute("INSERT INTO agg_course_team VALUES(?,?,?,?,?,?,?)",
                       (snap, cid, tc, prof, assoc, lect, unk))
        for cid, org in (("H", "O1"), ("M", "O1"), ("S", "O2"), ("N", "O2")):
            v2.execute("INSERT INTO dim_course VALUES(?,?,?)", (cid, f"课{cid}", org))
        self.skill = FacultyStructureSkill()

    def tearDown(self):
        self.legacy.close(); self.v2.close()

    def _run(self, override=None):
        return self.skill.run(make_ctx(self.skill, self.legacy, self.v2, override))

    def test_matrix_split_and_snapshot(self):
        r = self._run()
        stats = r.summary_stats
        self.assertEqual(stats["snapshot_semester"], "2023-2024-1")
        self.assertEqual(stats["single_teacher_high"], 1)   # H
        self.assertEqual(stats["single_teacher_mid"], 1)    # M；S被排除、N非单教师
        course_signals = [s for s in r.signals
                          if s.signal_type == "single_teacher_course"]
        self.assertEqual(len(course_signals), 1)
        self.assertEqual(course_signals[0].entity["id"], "H")
        self.assertIn("快照", course_signals[0].evidence["freshness"])

    def test_title_gap_triggered(self):
        r = self._run()
        # unknown 3/6 = 0.5 ≥ 0.30
        gap = [s for s in r.signals if s.signal_type == "title_data_gap"]
        self.assertEqual(len(gap), 1)
        self.assertEqual(gap[0].severity, "low")

    def test_age_dimension_declared_excluded(self):
        r = self._run()
        text = " ".join(e["what"] for e in r.exclusions)
        self.assertIn("年龄", text)

    def test_boundary_no_individual_evaluation(self):
        self.assertIn("不对教师个体", self.skill.data_boundary)


# ---------------------------------------------------------------------------
class ConfigStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = mem_conn()
        self.skill = GraduationGapSkill()

    def tearDown(self):
        self.conn.close()

    def test_default_when_no_override(self):
        config, version = config_store.resolve_config(self.conn, self.skill)
        self.assertEqual(version, "product_default")
        self.assertEqual(config["coordination_min_students"], 20)

    def test_draft_publish_merge(self):
        draft = config_store.create_draft(
            self.conn, self.skill, {"coordination_min_students": 30},
            "校级协调线调整", "admin")
        config_store.publish(self.conn, self.skill.skill_id,
                             draft["configId"], "admin")
        config, version = config_store.resolve_config(self.conn, self.skill)
        self.assertEqual(version, "1.0-school")
        self.assertEqual(config["coordination_min_students"], 30)
        self.assertEqual(config["target_grade"], 2022)  # 未覆写项保持默认

    def test_invalid_override_rejected(self):
        with self.assertRaises(ValueError):
            config_store.create_draft(
                self.conn, self.skill, {"coordination_min_students": 1},
                "低于下限", "admin")
        with self.assertRaises(ValueError):
            config_store.create_draft(
                self.conn, self.skill, {"unknown_key": 1}, "未声明配置", "admin")

    def test_publish_only_draft_and_rollback(self):
        d1 = config_store.create_draft(
            self.conn, self.skill, {"coordination_min_students": 25}, "v1", "admin")
        config_store.publish(self.conn, self.skill.skill_id, d1["configId"], "admin")
        with self.assertRaises(ValueError):
            config_store.publish(self.conn, self.skill.skill_id,
                                 d1["configId"], "admin")  # 重复发布
        d2 = config_store.create_draft(
            self.conn, self.skill, {"coordination_min_students": 40}, "v2", "admin")
        config_store.publish(self.conn, self.skill.skill_id, d2["configId"], "admin")
        config, _ = config_store.resolve_config(self.conn, self.skill)
        self.assertEqual(config["coordination_min_students"], 40)
        config_store.rollback(self.conn, self.skill.skill_id,
                              d1["configId"], "admin", "回滚")
        config, version = config_store.resolve_config(self.conn, self.skill)
        self.assertEqual(config["coordination_min_students"], 25)
        self.assertEqual(version, "3.0-school")


# ---------------------------------------------------------------------------
class ProtocolTest(unittest.TestCase):
    def test_fingerprint_ignores_timestamps(self):
        def sig(run_at_note):
            return Signal(
                signal_id="s:1", skill_id="s", signal_type="t", severity="high",
                headline="h", facts={"n": "1人"}, entity={}, action={},
                consequence="c", confidence="high",
                evidence={"freshness": run_at_note})
        fp1 = briefing_fingerprint([sig("截至今天")])
        fp2 = briefing_fingerprint([sig("截至明天")])
        self.assertEqual(fp1, fp2)
        fp3 = briefing_fingerprint([Signal(
            signal_id="s:1", skill_id="s", signal_type="t", severity="high",
            headline="h", facts={"n": "2人"}, entity={}, action={},
            consequence="c", confidence="high", evidence={})])
        self.assertNotEqual(fp1, fp3)

    def test_validate_override_bounds(self):
        skill = GraduationGapSkill()
        self.assertEqual(skill.validate_override({"target_grade": 2023}), [])
        errors = skill.validate_override({"target_grade": 1999})
        self.assertTrue(any("下限" in e for e in errors))
        errors = skill.validate_override({"near_grad_terms": "7"})
        self.assertTrue(errors)  # list 类型不接受字符串


if __name__ == "__main__":
    unittest.main()

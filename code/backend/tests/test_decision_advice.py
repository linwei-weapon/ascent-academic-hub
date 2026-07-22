# -*- coding: utf-8 -*-
"""R4 专家问策单元测试：越界识别、证据编号、会话存储、领域材料裁剪。

运行：cd code && python -m unittest backend.tests.test_decision_advice -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skills import advice, store
from backend.skills.briefing import build_briefing
from backend.skills.merger import merge_signals
from backend.tests.test_decision_briefing import make_result, make_signal
from backend.tests.test_decision_skills import mem_conn


def _briefing():
    results = [
        make_result("graduation-gap", [
            make_signal("g:1", "graduation-gap", "critical",
                        {"type": "course", "id": "C1", "name": "体质测试"}),
            make_signal("g:2", "graduation-gap", "high"),
        ]),
        make_result("course-quality", [
            make_signal("q:1", "course-quality", "medium"),
        ]),
    ]
    merged = merge_signals(results, {"graduation-gap": "main",
                                     "course-quality": "main"})
    return build_briefing(merged, results, [], "2025-2026-2", "fp")


class OutOfDomainTest(unittest.TestCase):
    def test_redirect_to_other_expert(self):
        # 毕业专家被问课程通过率问题 → 指向课程质量专家
        target = advice.detect_out_of_domain("哪些课程通过率异常？", "graduation-gap")
        self.assertEqual(target, "course-quality")

    def test_own_domain_not_redirected(self):
        self.assertIsNone(
            advice.detect_out_of_domain("本届有多少学生存在毕业缺口？", "graduation-gap"))

    def test_generic_question_not_redirected(self):
        self.assertIsNone(
            advice.detect_out_of_domain("今天最该关注什么？", "graduation-gap"))

    def test_refusal_payload(self):
        p = advice.refusal_payload("哪些课程通过率异常？", "graduation-gap", "course-quality")
        self.assertEqual(p["intent"], "out_of_domain")
        self.assertEqual(p["redirect"]["skill_id"], "course-quality")
        self.assertTrue(p["suggested_questions"])


class AskFlowTest(unittest.TestCase):
    def test_scoped_material_and_refs(self):
        b = _briefing()
        result = advice.ask("毕业缺口有多少？", "graduation-gap", "", [], b, {})
        self.assertNotEqual(result["intent"], "out_of_domain")
        refs = result["evidence_refs"]
        self.assertTrue(refs)
        # [n] 从 1 开始连续编号，且只引用本专家信号
        self.assertEqual([r["n"] for r in refs], list(range(1, len(refs) + 1)))
        for r in refs:
            self.assertTrue(r["signal_id"].startswith("g:"))
        self.assertTrue(result["suggested_questions"])
        self.assertLessEqual(len(result["suggested_questions"]), 3)
        self.assertIn("毕业", result["boundary"])

    def test_no_cross_domain_citation(self):
        """问毕业专家时，证据引用不得出现课程质量专家的信号。"""
        b = _briefing()
        result = advice.ask("有多少问题？", "graduation-gap", "", [], b, {})
        for r in result["evidence_refs"]:
            self.assertFalse(r["signal_id"].startswith("q:"))

    def test_out_of_domain_flow(self):
        b = _briefing()
        result = advice.ask("哪些课程通过率异常？", "graduation-gap", "", [], b, {})
        self.assertEqual(result["intent"], "out_of_domain")
        self.assertEqual(result["redirect"]["skill_id"], "course-quality")

    def test_expert_list(self):
        b = _briefing()
        items = advice.expert_list(b)
        self.assertEqual(len(items), 4)
        grad = [i for i in items if i["skill_id"] == "graduation-gap"][0]
        self.assertEqual(grad["signal_count"], 2)
        self.assertIsNotNone(grad["top_signal"])
        self.assertGreaterEqual(len(grad["example_questions"]), 6)


class AdviceStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = mem_conn()
        store.ensure_advice_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_session_isolation_by_user(self):
        sid = store.create_session(self.conn, "dean", "graduation-gap", "标题")
        self.assertIsNotNone(store.get_session(self.conn, sid, "dean"))
        self.assertIsNone(store.get_session(self.conn, sid, "college_dean"))

    def test_list_and_replay(self):
        sid = store.create_session(self.conn, "dean", "course-quality", "问题一",
                                   context_signal_id="q:1")
        store.append_message(self.conn, sid, "user", "哪些课程通过率异常？")
        store.append_message(self.conn, sid, "assistant", "查到 1 条相关信号",
                             {"evidence_refs": [{"n": 1, "signal_id": "q:1"}]})
        sessions = store.list_sessions(self.conn, "dean", "course-quality")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["context_signal_id"], "q:1")
        msgs = store.list_messages(self.conn, sid)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[1]["payload"]["evidence_refs"][0]["signal_id"], "q:1")

    def test_list_filter_by_skill(self):
        store.create_session(self.conn, "dean", "graduation-gap", "A")
        store.create_session(self.conn, "dean", "course-quality", "B")
        self.assertEqual(len(store.list_sessions(self.conn, "dean")), 2)
        self.assertEqual(len(store.list_sessions(self.conn, "dean", "graduation-gap")), 1)


if __name__ == "__main__":
    unittest.main()

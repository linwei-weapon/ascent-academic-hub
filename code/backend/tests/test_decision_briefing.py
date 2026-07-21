# -*- coding: utf-8 -*-
"""阶段2单元测试：信号合并、快照diff、模板简报装配、快照存储与建议追踪。

运行：cd code && python -m unittest backend.tests.test_decision_briefing -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.skills.briefing import _embed_tracking, build_briefing
from backend.skills.merger import (diff_signals, find_hotspots, merge_signals,
                                   scope_key, signal_digest)
from backend.skills.protocol import Signal, SkillResult
from backend.skills import store
from backend.tests.test_decision_skills import mem_conn

ADMIN = {"username": "admin", "role_id": "admin",
         "permission_context": {"authorized": True,
                                "detailScope": {"type": "all"},
                                "activeRole": "admin"}}


def make_signal(signal_id, skill_id="skill-a", severity="high",
                entity=None, headline=None, signal_type="t"):
    return Signal(
        signal_id=signal_id, skill_id=skill_id, signal_type=signal_type,
        severity=severity, headline=headline or f"标题{signal_id}",
        facts={"n": "1人"}, entity=entity or {"type": "course", "id": "X", "name": "课X"},
        action={"owner": "教务处", "what": "处置", "when": "本周", "rationale": "理由"},
        consequence="代价", confidence="high",
        evidence={"table": "t", "condition": "c", "verify_route": "/r",
                  "freshness": "实时"})


def make_result(skill_id, signals, tier_stats=None):
    return SkillResult(
        skill_id=skill_id, skill_name=f"名{skill_id}",
        management_question=f"问题{skill_id}", signals=signals,
        summary_stats=tier_stats or {}, exclusions=[], data_readiness={"ready": True},
        config_version="test", data_boundary="边界")


# ---------------------------------------------------------------------------
class MergerTest(unittest.TestCase):
    def test_severity_order_and_top_n(self):
        results = [
            make_result("a", [make_signal("a:1", "a", "low"),
                              make_signal("a:2", "a", "critical")]),
            make_result("b", [make_signal("b:1", "b", "medium")]),
        ]
        merged = merge_signals(results, {"a": "main", "b": "main"}, top_n=2)
        ids = [s.signal_id for s in merged["priority_items"]]
        self.assertEqual(ids, ["a:2", "b:1"])  # critical > medium，low 被截断

    def test_hotspot_detection_and_related(self):
        entity = {"type": "course", "id": "C1", "name": "军事理论"}
        results = [
            make_result("a", [make_signal("a:1", "a", "high", entity)]),
            make_result("b", [make_signal("b:1", "b", "medium", entity)]),
            make_result("c", [make_signal("c:1", "c", "high",
                                          {"type": "course", "id": "C2", "name": "其他"})]),
        ]
        merged = merge_signals(results, {"a": "main", "b": "topic", "c": "main"})
        self.assertEqual(merged["hotspots"], {"a:1": ["b:1"], "b:1": ["a:1"]})
        sig_a = [s for s in merged["all_signals"] if s.signal_id == "a:1"][0]
        self.assertEqual(sig_a.related, ["b:1"])
        # 热点在同级严重度内优先：a:1(high,热点) 应排在 c:1(high,非热点) 前
        ids = [s.signal_id for s in merged["priority_items"]]
        self.assertLess(ids.index("a:1"), ids.index("c:1"))

    def test_diff_states(self):
        current = [
            make_signal("s:new", severity="low"),
            make_signal("s:keep", severity="high"),
            make_signal("s:up", severity="critical"),
        ]
        previous = [
            {"signal_id": "s:keep", "severity": "high", "headline": "h"},
            {"signal_id": "s:up", "severity": "high", "headline": "h"},
            {"signal_id": "s:gone", "severity": "medium", "headline": "已消除"},
        ]
        current, resolved = diff_signals(current, previous)
        state = {s.signal_id: s.change for s in current}
        self.assertEqual(state["s:new"], "new")
        self.assertEqual(state["s:keep"], "ongoing")
        self.assertEqual(state["s:up"], "upgraded")
        self.assertEqual(resolved[0]["signal_id"], "s:gone")

    def test_scope_key_stable_by_scope(self):
        k1 = scope_key(ADMIN)
        k2 = scope_key(ADMIN)
        self.assertEqual(k1, k2)
        other = {"permission_context": {
            "activeRole": "dean", "detailScope": {"type": "college",
                                                  "sourceScopeIds": ["C01"]}}}
        self.assertNotEqual(k1, scope_key(other))


# ---------------------------------------------------------------------------
class BriefingBuildTest(unittest.TestCase):
    def _merged(self):
        results = [
            make_result("graduation-gap", [
                make_signal("g:1", "graduation-gap", "critical",
                            {"type": "course", "id": "C1", "name": "体质测试"}),
                make_signal("g:2", "graduation-gap", "high"),
            ], {"blocked_students": 3}),
            make_result("course-quality", [
                make_signal("q:1", "course-quality", "low", signal_type="improving"),
            ]),
        ]
        merged = merge_signals(results, {"graduation-gap": "main",
                                         "course-quality": "main"})
        return merged, results

    def test_structure_and_topline(self):
        merged, results = self._merged()
        b = build_briefing(merged, results, [], [], "2025-2026-2", "fp")
        self.assertEqual(b["urgency"], "critical")
        self.assertIn("1项紧急", b["topline"])
        self.assertIn("体质测试", b["topline"])
        self.assertEqual(len(b["skill_sections"]), 2)
        self.assertEqual(len(b["positive_developments"]), 1)
        self.assertEqual(b["stats"]["graduation-gap"]["blocked_students"], 3)
        self.assertEqual(b["generation_method"], "rule_template")
        self.assertEqual(b["snapshot_fingerprint"], "fp")

    def test_followup_states(self):
        merged, results = self._merged()
        tracking = [
            {"signal_id": "g:1", "skill_id": "graduation-gap", "headline": "h",
             "entity": {}, "action": {}, "status": "done", "assignee": None,
             "note": None, "updated_at": "t"},
            {"signal_id": "g:gone", "skill_id": "graduation-gap", "headline": "h2",
             "entity": {}, "action": {}, "status": "open", "assignee": None,
             "note": None, "updated_at": "t"},
        ]
        b = build_briefing(merged, results, [], tracking, "2025-2026-2", "fp")
        follow = {f["signal_id"]: f for f in b["previous_followup"]}
        self.assertEqual(follow["g:1"]["state"], "recheck")      # 完成但信号仍在
        self.assertEqual(follow["g:gone"]["state"], "signal_gone")
        # recheck 排在最前
        self.assertEqual(b["previous_followup"][0]["state"], "recheck")
        # 卡片回填追踪状态
        top = b["priority_items"][0]
        self.assertEqual(top["tracking"]["status"], "done")

    def test_embed_tracking_refreshes_cached_briefing(self):
        merged, results = self._merged()
        b = build_briefing(merged, results, [], [], "2025-2026-2", "fp")
        self.assertIsNone(b["priority_items"][0]["tracking"])
        tracking = [
            {"signal_id": "g:1", "skill_id": "graduation-gap", "headline": "h",
             "entity": {}, "action": {}, "status": "in_progress",
             "assignee": "张三", "note": "跟进中", "updated_at": "t2"},
        ]
        _embed_tracking(b, tracking)
        top = b["priority_items"][0]
        self.assertEqual(top["tracking"]["status"], "in_progress")
        self.assertEqual(top["tracking"]["assignee"], "张三")
        follow = {f["signal_id"]: f for f in b["previous_followup"]}
        self.assertEqual(follow["g:1"]["state"], "active")


# ---------------------------------------------------------------------------
class StoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = mem_conn()

    def tearDown(self):
        self.conn.close()

    def test_snapshot_roundtrip(self):
        digests = [signal_digest(make_signal("s:1"))]
        store.save_snapshot(self.conn, "scope1", "2025-2026-2", "fp1",
                            "rule_template", {"topline": "t"}, digests, "admin")
        snap = store.latest_snapshot(self.conn, "scope1")
        self.assertEqual(snap["fingerprint"], "fp1")
        self.assertEqual(snap["briefing"]["topline"], "t")
        self.assertEqual(snap["signals"][0]["signal_id"], "s:1")
        self.assertIsNone(store.latest_snapshot(self.conn, "other-scope"))

    def test_tracking_upsert_idempotent(self):
        signal = {"signal_id": "s:1", "skill_id": "a", "headline": "h",
                  "entity": {"id": "E"}, "action": {"what": "w"}}
        r1 = store.upsert_tracking(self.conn, signal, "open", "admin", "scope1")
        r2 = store.upsert_tracking(self.conn, signal, "in_progress", "admin",
                                   "scope1", assignee="张三", note="跟进中")
        self.assertEqual(r1["trackingId"], r2["trackingId"])
        self.assertFalse(r1["updated"])
        self.assertTrue(r2["updated"])
        rows = store.list_tracking(self.conn, "scope1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "in_progress")
        self.assertEqual(rows[0]["assignee"], "张三")
        with self.assertRaises(ValueError):
            store.upsert_tracking(self.conn, signal, "bogus", "admin", "scope1")


if __name__ == "__main__":
    unittest.main()

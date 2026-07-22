# -*- coding: utf-8 -*-
"""阶段6黄金评估：信号命中率≥95%、Top1一致率≥90%、对话数字错误率=0。

对真实演示库运行（库缺失时跳过）。用例见 golden/decision_golden.v1.json。
评估口径：
- 信号命中：期望信号ID存在，且严重度/类型/关键数字与固化值一致
- Top1一致：简报优先处置首位 = 固化信号，且来自 main 层 Skill；跨专题热点成对出现
- 数字安全：规则模式对话答案中的全部数字字面量，必须可追溯到
  引用信号载荷/问题本身/简报topline（剥离列表序号后统计）

运行：cd code && python -m pytest backend/tests/test_decision_golden.py -q
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.etl import config as etl_config
from backend.skills import chat, config_store
from backend.skills.briefing import build_briefing
from backend.skills.merger import merge_signals
from backend.skills.narrative import extract_numbers
from backend.skills.protocol import SkillContext
from backend.skills.registry import list_skills

GOLDEN_PATH = Path(__file__).parent / "golden" / "decision_golden.v1.json"
SEMESTER = "2025-2026-2"
DB_OK = (Path(etl_config.DB_PATH).exists()
         and Path(etl_config.V2_DB_PATH).exists())

ADMIN = {"username": "admin", "role_id": "admin",
         "permission_context": {"authorized": True,
                                "detailScope": {"type": "all"},
                                "activeRole": "admin"}}
DISABLED_LLM = {"enabled": False, "chat_enabled": True}


def _run_all_skills(legacy, v2, rw):
    results, tier_map = [], {}
    for skill in list_skills():
        config, version = config_store.resolve_config(rw, skill)
        ctx = SkillContext(user=ADMIN, legacy=legacy, v2=v2, config=config,
                           config_version=version, semester=SEMESTER)
        results.append(skill.run(ctx))
        tier_map[skill.skill_id] = skill.briefing_tier
    return results, tier_map


@unittest.skipUnless(DB_OK, "演示库不存在，跳过黄金评估")
class GoldenEvalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        cls.legacy = sqlite3.connect(
            f"file:{etl_config.DB_PATH}?mode=ro", uri=True)
        cls.legacy.row_factory = sqlite3.Row
        cls.v2 = sqlite3.connect(
            f"file:{etl_config.V2_DB_PATH}?mode=ro", uri=True)
        cls.v2.row_factory = sqlite3.Row
        cls.rw = sqlite3.connect(str(etl_config.DB_PATH))
        cls.rw.row_factory = sqlite3.Row
        cls.results, cls.tier_map = _run_all_skills(cls.legacy, cls.v2, cls.rw)
        cls.merged = merge_signals(cls.results, cls.tier_map)
        cls.briefing = build_briefing(
            cls.merged, cls.results, [], SEMESTER, "golden-eval")

    @classmethod
    def tearDownClass(cls):
        cls.legacy.close()
        cls.v2.close()
        cls.rw.close()

    # -- 信号命中率 ≥95% --
    def test_signal_hit_rate(self):
        by_skill = {r.skill_id: r for r in self.results}
        cases = self.cases["signal_cases"]
        misses = []
        for case in cases:
            result = by_skill[case["skill_id"]]
            expect = case["expect"]
            found = [s for s in result.signals
                     if s.signal_id == expect["signal_id"]]
            ok = bool(found)
            if ok and expect.get("severity"):
                ok = found[0].severity == expect["severity"]
            if ok and expect.get("signal_type"):
                ok = found[0].signal_type == expect["signal_type"]
            if ok:
                facts_json = json.dumps(found[0].facts, ensure_ascii=False)
                ok = all(sub in facts_json
                         for sub in expect.get("facts_contain", []))
            if not ok:
                misses.append(case["id"])
        rate = (len(cases) - len(misses)) / len(cases)
        self.assertGreaterEqual(
            rate, 0.95,
            f"信号命中率 {rate:.1%} < 95%，未命中: {misses}")

    # -- 同数据必同ID（确定性回归） --
    def test_signal_ids_deterministic(self):
        again, _ = _run_all_skills(self.legacy, self.v2, self.rw)
        first = {r.skill_id: sorted(s.signal_id for s in r.signals)
                 for r in self.results}
        second = {r.skill_id: sorted(s.signal_id for s in r.signals)
                  for r in again}
        self.assertEqual(first, second)

    # -- Top1 一致率 ≥90% --
    def test_top1_consistency(self):
        top = self.merged["priority_items"][0]
        cases = self.cases["top1_cases"]
        misses = []
        for case in cases:
            ok = True
            if case.get("expect_signal_id"):
                ok = top.signal_id == case["expect_signal_id"]
            if ok and case.get("expect_severity"):
                ok = top.severity == case["expect_severity"]
            if ok and case.get("expect_main_tier"):
                ok = self.tier_map.get(top.skill_id) == "main"
            if ok and case.get("expect_hotspot_pair"):
                a, b = case["expect_hotspot_pair"]
                ok = b in self.merged["hotspots"].get(a, [])
            if not ok:
                misses.append(case["id"])
        rate = (len(cases) - len(misses)) / len(cases)
        self.assertGreaterEqual(
            rate, 0.90,
            f"Top1一致率 {rate:.1%} < 90%，不一致: {misses}")

    # -- 对话：意图正确 + 内容包含 + 数字错误率=0 --
    def _answer(self, question):
        routed = chat.route(question, "", self.briefing)
        result = chat.answer(question, [], routed, self.briefing, DISABLED_LLM)
        return routed, result

    def test_chat_intents_and_content(self):
        failures = []
        for case in self.cases["chat_cases"]:
            routed, result = self._answer(case["question"])
            if routed["intent"] != case["expect_intent"]:
                failures.append(f"{case['id']}: 意图 "
                                f"{routed['intent']} != {case['expect_intent']}")
                continue
            for sub in case.get("must_contain", []):
                if sub not in result["text"]:
                    failures.append(f"{case['id']}: 答案缺少「{sub}」")
            if case.get("expect_layers"):
                layers = [b["layer"] for b in result["blocks"]]
                if layers != case["expect_layers"]:
                    failures.append(f"{case['id']}: 分层 {layers}")
            facts_block = next((b for b in result["blocks"]
                                if b["layer"] == "facts"), None)
            for sub in case.get("facts_contain", []):
                if not facts_block or sub not in facts_block.get("text", ""):
                    failures.append(f"{case['id']}: 事实层缺少「{sub}」")
        self.assertEqual(failures, [])

    def test_chat_number_safety(self):
        """数字错误率=0：答案数字必须可追溯到引用信号/问题/简报topline。"""
        base_allowed = extract_numbers(
            (self.briefing.get("topline") or "")
            + (self.briefing.get("urgency_rationale") or ""))
        bad_cases = []
        total_numbers = 0
        for case in self.cases["chat_cases"]:
            routed, result = self._answer(case["question"])
            allowed = set(base_allowed)
            allowed |= extract_numbers(
                json.dumps(routed["cited"], ensure_ascii=False))
            allowed |= extract_numbers(case["question"])
            allowed.add(str(len(routed["cited"])))
            text = result["text"] + "".join(
                (b.get("text") or "") + (b.get("verify") or "")
                + "".join(b.get("items") or [])
                for b in result["blocks"])
            # 剥离列表序号（"1. " "2、"）——序号是排版不是数据
            cleaned = re.sub(r"(?m)^\s*\d+[.、]\s*", "", text)
            out = extract_numbers(cleaned)
            total_numbers += len(out)
            bad = out - allowed
            if bad:
                bad_cases.append(f"{case['id']}: 不可追溯数字 {sorted(bad)}")
        self.assertEqual(
            bad_cases, [],
            f"数字错误率应为0（共{total_numbers}个数字字面量）: {bad_cases}")


if __name__ == "__main__":
    unittest.main()

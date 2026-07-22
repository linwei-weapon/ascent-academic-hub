# -*- coding: utf-8 -*-
"""阶段4单元测试：LLM配置、叙事增强数字校验回退、意图路由五类、归因三明治、SSE端点。

运行：cd code && python -m unittest backend.tests.test_decision_llm -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

from backend.skills import chat, llm_client, llm_config, narrative
from backend.skills.llm_client import LLMError
from backend.tests.test_decision_skills import mem_conn

ADMIN = {"username": "admin", "role_id": "admin",
         "permission_context": {"authorized": True,
                                "detailScope": {"type": "all"},
                                "activeRole": "admin"}}

READY_CFG = {"enabled": True, "provider": "openai_compatible",
             "base_url": "http://llm.local/v1", "api_key": "k", "model": "m",
             "timeout_seconds": 5, "max_retries": 1,
             "narrative_enabled": True, "chat_enabled": True}
DISABLED_CFG = dict(llm_config.DEFAULTS)


def make_card(signal_id="g:1", skill_id="graduation-gap", severity="critical",
              name="体质测试", headline=None, facts=None, questions=None):
    return {
        "signal_id": signal_id, "skill_id": skill_id, "signal_type": "blocked",
        "severity": severity,
        "headline": headline or f"{name}存在毕业缺口，144名学生受阻",
        "facts": facts if facts is not None else {"受阻学生": "144人", "涉及课程": "3门"},
        "entity": {"type": "course", "id": "C1", "name": name},
        "action": {"owner": "教务处", "what": "组织补修", "when": "本周",
                   "rationale": "临近审核"},
        "consequence": "144名学生无法按期毕业",
        "confidence": "high",
        "evidence": {"table": "t", "condition": "c", "verify_route": "/r",
                     "freshness": "实时"},
        "context": {"big_list": list(range(100))}, "related": [],
        "data_boundary": "口径", "change": "new",
        "suggested_questions": questions if questions is not None else ["为什么受阻？"],
    }


def make_briefing(cards=None):
    cards = cards if cards is not None else [make_card()]
    return {
        "topline": "今日1项需处置事项（1项紧急），首要：体质测试——教务处，本周。",
        "urgency": "critical",
        "urgency_rationale": "存在1项紧急事项与0项重点事项，需要今日内明确责任人与时限。",
        "priority_items": cards,
        "skill_sections": [], "watch_items": [], "positive_developments": [],
        "generation_method": "rule_template",
    }


def _sys_config_table(conn):
    llm_config.ensure_tables(conn)
    conn.commit()


# ---------------------------------------------------------------------------
class LlmConfigTest(unittest.TestCase):
    def setUp(self):
        self.conn = mem_conn()
        _sys_config_table(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_defaults_disabled(self):
        cfg = llm_config.load_config(self.conn)
        self.assertFalse(cfg["enabled"])
        self.assertFalse(llm_config.llm_ready(cfg))

    def test_save_load_roundtrip_and_illegal_keys(self):
        saved = llm_config.save_config(self.conn, {
            "enabled": True, "base_url": "http://x/v1", "api_key": "k",
            "model": "qwen", "provider": "hacked", "unknown": 1}, "admin")
        self.assertEqual(saved["provider"], "openai_compatible")  # 不可编辑
        self.assertNotIn("unknown", saved)
        loaded = llm_config.load_config(self.conn)
        self.assertTrue(llm_config.llm_ready(loaded))
        self.assertEqual(loaded["model"], "qwen")

    def test_ready_requires_full_quadruple(self):
        for patch in ({"enabled": True},
                      {"enabled": True, "base_url": "http://x"},
                      {"enabled": True, "base_url": "http://x", "api_key": "k"}):
            cfg = dict(llm_config.DEFAULTS) | patch
            self.assertFalse(llm_config.llm_ready(cfg), patch)


# ---------------------------------------------------------------------------
class NumberExtractTest(unittest.TestCase):
    def test_arabic_decimal_percent_thousands(self):
        nums = narrative.extract_numbers("未通过率12.5%，涉及1,852名学生、3门课程")
        self.assertIn("12.5", nums)
        self.assertIn("1852", nums)
        self.assertIn("3", nums)

    def test_chinese_numeral_with_measure_word(self):
        nums = narrative.extract_numbers("三门课程、十名学生、两项事项")
        self.assertTrue({"3", "10", "2"} <= nums)

    def test_plain_chinese_numeral_ignored(self):
        # 非量词场景的中文数字不提取（避免误伤「一方面」等表述）
        nums = narrative.extract_numbers("一方面需要关注")
        self.assertNotIn("1", nums)


# ---------------------------------------------------------------------------
class NarrativeTest(unittest.TestCase):
    def test_disabled_config_keeps_template(self):
        b = make_briefing()
        out = narrative.enhance_briefing(b, DISABLED_CFG)
        self.assertEqual(out["generation_method"], "rule_template")
        self.assertEqual(out["llm_status"], "disabled")
        self.assertEqual(out["topline"], b["topline"])

    def test_empty_priority_skips_llm(self):
        b = make_briefing(cards=[])
        b["priority_items"] = []
        out = narrative.enhance_briefing(b, READY_CFG)
        self.assertEqual(out["llm_status"], "disabled")

    def test_valid_narrative_replaces_topline(self):
        b = make_briefing()
        llm_json = json.dumps({
            "topline": "本期1项紧急事项需今日处置：体质测试144名学生毕业受阻。",
            "urgency_rationale": "1项紧急事项要求今日明确责任人与时限。",
            "item_narratives": {"g:1": "144名学生受阻于体质测试，教务处本周组织补修，"
                                       "否则无法按期毕业。"},
        }, ensure_ascii=False)
        with mock.patch.object(narrative, "chat_completion", return_value=llm_json):
            out = narrative.enhance_briefing(b, READY_CFG)
        self.assertEqual(out["generation_method"], "llm_enhanced")
        self.assertEqual(out["llm_status"], "ok")
        self.assertIn("144", out["topline"])
        self.assertIn("narrative", out["priority_items"][0])

    def test_fabricated_number_rejected_and_fallback(self):
        b = make_briefing()
        original_topline = b["topline"]
        llm_json = json.dumps({
            "topline": "约300名学生面临毕业风险，需立即处理。",  # 300为编造数字
            "urgency_rationale": "涉及300人需关注。",           # 同为编造
        }, ensure_ascii=False)
        with mock.patch.object(narrative, "chat_completion", return_value=llm_json):
            out = narrative.enhance_briefing(b, READY_CFG)
        self.assertEqual(out["generation_method"], "rule_template")
        self.assertEqual(out["llm_status"], "failed:number_validation")
        self.assertEqual(out["topline"], original_topline)

    def test_bad_item_narrative_dropped_but_topline_kept(self):
        b = make_briefing()
        llm_json = json.dumps({
            "topline": "本期1项紧急事项需今日处置。",
            "item_narratives": {"g:1": "涉及999名学生"},  # 编造
        }, ensure_ascii=False)
        with mock.patch.object(narrative, "chat_completion", return_value=llm_json):
            out = narrative.enhance_briefing(b, READY_CFG)
        self.assertEqual(out["generation_method"], "llm_enhanced")
        self.assertNotIn("narrative", out["priority_items"][0])

    def test_llm_error_falls_back_honestly(self):
        b = make_briefing()
        with mock.patch.object(narrative, "chat_completion",
                               side_effect=LLMError("timeout", "t")):
            out = narrative.enhance_briefing(b, READY_CFG)
        self.assertEqual(out["generation_method"], "rule_template")
        self.assertEqual(out["llm_status"], "failed:timeout")

    def test_invalid_json_falls_back(self):
        b = make_briefing()
        with mock.patch.object(narrative, "chat_completion",
                               return_value="这不是JSON"):
            out = narrative.enhance_briefing(b, READY_CFG)
        self.assertEqual(out["llm_status"], "failed:invalid_json")
        self.assertEqual(out["generation_method"], "rule_template")


# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(payload or {}, ensure_ascii=False)

    def json(self):
        return self._payload


class _FakeClient:
    """按脚本行为响应的httpx.Client替身。behavior为列表，逐项消费。"""
    behavior: list = []
    calls: int = 0

    def __init__(self, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None, headers=None):
        type(self).calls += 1
        action = type(self).behavior.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


class LlmClientTest(unittest.TestCase):
    def setUp(self):
        _FakeClient.calls = 0
        _FakeClient.behavior = []

    def _patch(self, behavior):
        _FakeClient.behavior = list(behavior)
        return mock.patch.object(llm_client.httpx, "Client", _FakeClient)

    def test_not_configured(self):
        with self.assertRaises(LLMError) as ctx:
            llm_client.chat_completion(DISABLED_CFG, [])
        self.assertEqual(ctx.exception.kind, "not_configured")

    def test_success(self):
        payload = {"choices": [{"message": {"content": " 你好 "}}]}
        with self._patch([_FakeResponse(200, payload)]):
            text = llm_client.chat_completion(READY_CFG, [{"role": "user", "content": "hi"}])
        self.assertEqual(text, "你好")
        self.assertEqual(_FakeClient.calls, 1)

    def test_timeout_retried_once(self):
        payload = {"choices": [{"message": {"content": "ok"}}]}
        with self._patch([httpx.TimeoutException("t"), _FakeResponse(200, payload)]):
            text = llm_client.chat_completion(READY_CFG, [])
        self.assertEqual(text, "ok")
        self.assertEqual(_FakeClient.calls, 2)  # 重试≤1次

    def test_400_not_retried(self):
        with self._patch([_FakeResponse(400, {"error": "bad"})]):
            with self.assertRaises(LLMError) as ctx:
                llm_client.chat_completion(READY_CFG, [])
        self.assertEqual(ctx.exception.kind, "http")
        self.assertEqual(_FakeClient.calls, 1)

    def test_503_retried_then_fails(self):
        with self._patch([_FakeResponse(503), _FakeResponse(503)]):
            with self.assertRaises(LLMError) as ctx:
                llm_client.chat_completion(READY_CFG, [])
        self.assertEqual(ctx.exception.kind, "http")
        self.assertEqual(_FakeClient.calls, 2)

    def test_invalid_response_shape(self):
        with self._patch([_FakeResponse(200, {"unexpected": True})]):
            with self.assertRaises(LLMError) as ctx:
                llm_client.chat_completion(READY_CFG, [])
        self.assertEqual(ctx.exception.kind, "invalid_response")


# ---------------------------------------------------------------------------
class IntentRouteTest(unittest.TestCase):
    def test_five_intents(self):
        self.assertEqual(chat.classify_intent("为什么毕业缺口这么大？"), chat.INTENT_ATTRIBUTE)
        self.assertEqual(chat.classify_intent("如果新增5个班会怎样？"), chat.INTENT_SIMULATE)
        self.assertEqual(chat.classify_intent("两门课哪个更严重？"), chat.INTENT_COMPARE)
        self.assertEqual(chat.classify_intent("受阻学生有多少？"), chat.INTENT_VERIFY)
        self.assertEqual(chat.classify_intent("怎么看现在的整体情况？"), chat.INTENT_OPEN)

    def test_attribute_beats_verify(self):
        # 「为什么…多少」应归为归因而非查证
        self.assertEqual(chat.classify_intent("为什么受阻学生有144人？"),
                         chat.INTENT_ATTRIBUTE)

    def test_match_signals_by_entity_and_keyword(self):
        cards = [make_card("g:1", name="体质测试"),
                 make_card("a:1", skill_id="alert-priority", name="队列",
                           headline="本周预警队列2名学生", facts={"队列": "2人"})]
        hit = chat.match_signals("体质测试的情况如何？", cards)
        self.assertEqual(hit[0]["signal_id"], "g:1")
        hit2 = chat.match_signals("本周预警先给谁？", cards)
        self.assertEqual(hit2[0]["signal_id"], "a:1")

    def test_route_trims_context(self):
        briefing = make_briefing()
        routed = chat.route("体质测试", "", briefing)
        self.assertNotIn("context", routed["cited"][0])
        self.assertEqual(routed["cited"][0]["signal_id"], "g:1")


# ---------------------------------------------------------------------------
class AnswerTest(unittest.TestCase):
    def _routed(self, message, briefing=None, signal_id=""):
        return chat.route(message, signal_id, briefing or make_briefing())

    def test_verify_answers_from_data_without_llm(self):
        result = chat.answer("受阻学生有多少？最好查一下体质测试", [],
                             self._routed("体质测试受阻学生有多少？"),
                             make_briefing(), DISABLED_CFG)
        self.assertEqual(result["llm_status"], "not_used")
        self.assertIn("144", result["text"])

    def test_verify_without_match_states_boundary(self):
        result = chat.answer("食堂满意度有多少？", [],
                             self._routed("食堂满意度有多少？"),
                             make_briefing(), DISABLED_CFG)
        self.assertEqual(result["llm_status"], "not_used")
        self.assertIn("没有与该问题直接相关", result["text"])

    def test_simulate_states_capability_boundary(self):
        result = chat.answer("如果新增5个班会怎样？", [],
                             self._routed("如果新增5个班会怎样？"),
                             make_briefing(), READY_CFG)
        self.assertEqual(result["intent"], chat.INTENT_SIMULATE)
        self.assertIn("后续阶段", result["text"])
        self.assertEqual(result["llm_status"], "not_used")

    def test_attribute_sandwich_without_llm(self):
        result = chat.answer("体质测试为什么受阻？", [],
                             self._routed("体质测试为什么受阻？"),
                             make_briefing(), DISABLED_CFG)
        layers = [b["layer"] for b in result["blocks"]]
        self.assertEqual(layers, ["facts", "hypothesis", "action"])
        self.assertIn("144", result["blocks"][0]["text"])
        self.assertEqual(result["llm_status"], "disabled")

    def test_attribute_sandwich_with_llm(self):
        llm_json = json.dumps({
            "facts_text": "体质测试144名学生受阻，属紧急事项。",
            "hypotheses": [
                {"text": "可能是补修安排未覆盖该批学生", "verify": "查看近3学期补修开班记录"},
                {"text": "涉及学生达999人", "verify": "坏假设应被丢弃"},  # 999编造
            ],
            "action_text": "教务处本周组织补修。",
        }, ensure_ascii=False)
        with mock.patch.object(chat, "chat_completion", return_value=llm_json):
            result = chat.answer("体质测试为什么受阻？", [],
                                 self._routed("体质测试为什么受阻？"),
                                 make_briefing(), READY_CFG)
        self.assertEqual(result["llm_status"], "ok")
        hypothesis = [b for b in result["blocks"] if b["layer"] == "hypothesis"]
        self.assertEqual(len(hypothesis), 1)
        self.assertIn("补修开班记录", hypothesis[0]["verify"])

    def test_attribute_all_hypotheses_rejected_marks_failure(self):
        llm_json = json.dumps({
            "facts_text": "体质测试144名学生受阻。",
            "hypotheses": [{"text": "涉及999人", "verify": "x"}],
            "action_text": "教务处本周组织补修。",
        }, ensure_ascii=False)
        with mock.patch.object(chat, "chat_completion", return_value=llm_json):
            result = chat.answer("体质测试为什么受阻？", [],
                                 self._routed("体质测试为什么受阻？"),
                                 make_briefing(), READY_CFG)
        self.assertEqual(result["llm_status"], "failed:number_validation")
        hypothesis = [b for b in result["blocks"] if b["layer"] == "hypothesis"]
        self.assertIn("未通过系统校验", hypothesis[0]["text"])

    def test_compare_fallback_lists_facts(self):
        briefing = make_briefing(cards=[
            make_card("g:1", name="体质测试"),
            make_card("g:2", name="军事理论",
                      headline="军事理论存在毕业缺口，30名学生受阻",
                      facts={"受阻学生": "30人"}),
        ])
        result = chat.answer("体质测试和军事理论哪个更严重？", [],
                             self._routed("体质测试和军事理论哪个更严重？", briefing),
                             briefing, DISABLED_CFG)
        self.assertEqual(result["intent"], chat.INTENT_COMPARE)
        self.assertIn("144", result["text"])
        self.assertIn("30", result["text"])
        self.assertEqual(result["llm_status"], "disabled")

    def test_open_fallback_uses_topline(self):
        result = chat.answer("怎么看现在的整体情况？", [],
                             self._routed("怎么看现在的整体情况？"),
                             make_briefing(), DISABLED_CFG)
        self.assertIn("当前简报总判断", result["text"])
        self.assertEqual(result["llm_status"], "disabled")

    def test_history_numbers_allowed(self):
        # 对话历史中出现过的数字属于允许集
        llm_json = json.dumps({
            "facts_text": "体质测试144名学生受阻，较你刚才提到的130人有所增加。",
            "hypotheses": [],
            "action_text": "教务处本周组织补修。",
        }, ensure_ascii=False)
        history = [{"role": "user", "content": "上周是不是130人？"},
                   {"role": "assistant", "content": "是的，上周快照为130人。"}]
        with mock.patch.object(chat, "chat_completion", return_value=llm_json):
            result = chat.answer("为什么变多了？", history,
                                 self._routed("体质测试为什么变多了？"),
                                 make_briefing(), READY_CFG)
        self.assertIn("130", result["blocks"][0]["text"])


# ---------------------------------------------------------------------------
class ChatEndpointTest(unittest.TestCase):
    """端点级：直接调用路由函数并消费SSE流（含LLM故障注入）。"""

    def _collect(self, resp) -> dict:
        async def _run():
            chunks = []
            async for chunk in resp.body_iterator:
                chunks.append(chunk if isinstance(chunk, str) else chunk.decode())
            return "".join(chunks)
        raw = asyncio.run(_run())
        events = {}
        for block in raw.split("\n\n"):
            event, data = "", ""
            for line in block.split("\n"):
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: "):
                    data = line[6:]
            if event and data:
                events.setdefault(event, []).append(json.loads(data))
        return events

    def _call(self, message, cfg, briefing=None, chat_mock=None):
        from backend.api.routers import ai_decision
        briefing = briefing or make_briefing()
        cm = chat_mock or mock.patch.object(
            chat, "chat_completion", side_effect=LLMError("timeout", "t"))
        # SSE生成器在消费时才执行，补丁必须覆盖到流消费结束
        with mock.patch.object(ai_decision, "generate_briefing", return_value=briefing), \
             mock.patch.object(ai_decision.llm_config, "load_config", return_value=cfg), \
             cm:
            resp = ai_decision.chat(ai_decision.ChatIn(message=message),
                                    ADMIN, None, None, None)
            return self._collect(resp)

    def test_verify_intent_streams_without_llm(self):
        events = self._call("体质测试受阻学生有多少？", DISABLED_CFG)
        self.assertEqual(events["meta"][0]["intent"], "verify")
        text = "".join(d["text"] for d in events["delta"])
        self.assertIn("144", text)
        self.assertEqual(events["done"][0]["llm_status"], "not_used")
        self.assertTrue(events["done"][0]["followups"])

    def test_attribute_intent_llm_failure_falls_back(self):
        # LLM故障注入：三明治仍给出事实层与行动层，状态诚实标注
        events = self._call("体质测试为什么受阻？", READY_CFG)
        done = events["done"][0]
        self.assertEqual(done["llm_status"], "failed:timeout")
        layers = [b["layer"] for b in done["blocks"]]
        self.assertEqual(layers, ["facts", "hypothesis", "action"])
        self.assertIn("144", done["blocks"][0]["text"])

    def test_unauthorized_rejected(self):
        from backend.api.routers import ai_decision
        from backend.api.envelope import ApiError
        bad_user = {"username": "x", "permission_context": {"authorized": False}}
        with self.assertRaises((ApiError, Exception)):
            ai_decision.chat(ai_decision.ChatIn(message="test"), bad_user,
                             None, None, None)


if __name__ == "__main__":
    unittest.main()

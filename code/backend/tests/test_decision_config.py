# -*- coding: utf-8 -*-
"""阶段5单元测试：学校配置中心——Skill阈值三态流转、校验硬边界、LLM配置端点。

运行：cd code && python -m unittest backend.tests.test_decision_config -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.envelope import ApiError
from backend.api.routers import ai_decision
from backend.skills import config_store, llm_client, llm_config
from backend.skills.llm_client import LLMError
from backend.skills.registry import get_skill
from backend.tests.test_decision_skills import mem_conn

SYS_ADMIN = {"username": "admin", "role_id": "dean",
             "permission_context": {"authorized": True,
                                    "actionPermissions": ["system.manage"],
                                    "detailScope": {"type": "all"},
                                    "activeRole": "dean"}}
NOT_ADMIN = {"username": "viewer", "role_id": "dept_research",
             "permission_context": {"authorized": True,
                                    "actionPermissions": [],
                                    "detailScope": {"type": "all"},
                                    "activeRole": "dept_research"}}


def _unwrap(result):
    """ok() 封套 → data（兼容直接返回dict的两种写法）。"""
    if hasattr(result, "body"):
        import json
        return json.loads(result.body)["data"]
    return result.get("data", result) if isinstance(result, dict) else result


class SkillConfigFlowTest(unittest.TestCase):
    """端点级：直接调用路由函数，验证草稿→发布→回滚与校验硬边界。"""

    def setUp(self):
        self.rw = mem_conn()

    def tearDown(self):
        self.rw.close()

    def test_list_skills_with_bounds_and_empty_versions(self):
        data = _unwrap(ai_decision.skill_config_list(SYS_ADMIN, self.rw))
        self.assertEqual(len(data["items"]), 4)
        gap = [i for i in data["items"] if i["skill_id"] == "graduation-gap"][0]
        self.assertIn("target_grade", gap["config_bounds"])
        self.assertEqual(gap["config_version"], "product_default")
        self.assertEqual(gap["versions"], [])

    def test_draft_publish_flow_changes_active_config(self):
        draft = _unwrap(ai_decision.skill_config_draft(
            "course-quality",
            ai_decision.SkillConfigDraftIn(
                override={"min_sample": 30}, changeReason="样本量适配小规模学院"),
            SYS_ADMIN, self.rw))
        self.assertEqual(draft["status"], "draft")
        # 草稿未发布前不生效
        _, version = config_store.active_override(self.rw, "course-quality")
        self.assertEqual(version, "product_default")

        _unwrap(ai_decision.skill_config_publish(
            "course-quality", ai_decision.ConfigActionIn(configId=draft["configId"]),
            SYS_ADMIN, self.rw))
        override, version = config_store.active_override(self.rw, "course-quality")
        self.assertEqual(override, {"min_sample": 30})
        self.assertNotEqual(version, "product_default")

    def test_draft_out_of_bounds_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            ai_decision.skill_config_draft(
                "course-quality",
                ai_decision.SkillConfigDraftIn(
                    override={"min_sample": 5}, changeReason="低于下限应拒绝"),
                SYS_ADMIN, self.rw)
        self.assertEqual(ctx.exception.status_code if hasattr(ctx.exception, "status_code") else 400, 400)
        self.assertIn("低于下限", str(ctx.exception))

    def test_draft_non_whitelisted_key_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            ai_decision.skill_config_draft(
                "course-quality",
                ai_decision.SkillConfigDraftIn(
                    override={"formula": "hacked"}, changeReason="非白名单键"),
                SYS_ADMIN, self.rw)
        self.assertIn("不允许", str(ctx.exception))

    def test_republish_draft_rejected(self):
        draft = _unwrap(ai_decision.skill_config_draft(
            "alert-priority",
            ai_decision.SkillConfigDraftIn(
                override={"top_n": 12}, changeReason="扩大队列"),
            SYS_ADMIN, self.rw))
        _unwrap(ai_decision.skill_config_publish(
            "alert-priority", ai_decision.ConfigActionIn(configId=draft["configId"]),
            SYS_ADMIN, self.rw))
        with self.assertRaises(ApiError):
            ai_decision.skill_config_publish(
                "alert-priority", ai_decision.ConfigActionIn(configId=draft["configId"]),
                SYS_ADMIN, self.rw)

    def test_rollback_keeps_audit_chain(self):
        d1 = _unwrap(ai_decision.skill_config_draft(
            "alert-priority",
            ai_decision.SkillConfigDraftIn(override={"top_n": 10}, changeReason="版本一"),
            SYS_ADMIN, self.rw))
        _unwrap(ai_decision.skill_config_publish(
            "alert-priority", ai_decision.ConfigActionIn(configId=d1["configId"]),
            SYS_ADMIN, self.rw))
        d2 = _unwrap(ai_decision.skill_config_draft(
            "alert-priority",
            ai_decision.SkillConfigDraftIn(override={"top_n": 20}, changeReason="版本二"),
            SYS_ADMIN, self.rw))
        _unwrap(ai_decision.skill_config_publish(
            "alert-priority", ai_decision.ConfigActionIn(configId=d2["configId"]),
            SYS_ADMIN, self.rw))
        override, _ = config_store.active_override(self.rw, "alert-priority")
        self.assertEqual(override["top_n"], 20)

        rb = _unwrap(ai_decision.skill_config_rollback(
            "alert-priority",
            ai_decision.ConfigActionIn(configId=d1["configId"], changeReason="回退到版本一"),
            SYS_ADMIN, self.rw))
        self.assertEqual(rb["status"], "published")
        override, _ = config_store.active_override(self.rw, "alert-priority")
        self.assertEqual(override["top_n"], 10)
        versions = config_store.list_versions(self.rw, "alert-priority")
        self.assertEqual(len(versions), 3)  # v1(退役) + v2(退役) + 回滚新版(生效)

    def test_unknown_skill_404(self):
        with self.assertRaises(ApiError):
            ai_decision.skill_config_draft(
                "no-such-skill",
                ai_decision.SkillConfigDraftIn(override={}, changeReason="任意原因"),
                SYS_ADMIN, self.rw)


class LlmConfigEndpointTest(unittest.TestCase):
    def setUp(self):
        self.rw = mem_conn()

    def tearDown(self):
        self.rw.close()

    def test_get_masks_api_key(self):
        llm_config.save_config(self.rw, {
            "enabled": True, "base_url": "http://x/v1",
            "api_key": "sk-1234567890abcd", "model": "qwen"}, "admin")
        data = _unwrap(ai_decision.llm_config_get(SYS_ADMIN, self.rw))
        self.assertNotIn("sk-1234567890abcd", str(data))
        self.assertTrue(data["has_api_key"])
        self.assertEqual(data["api_key_tail"], "abcd")
        self.assertTrue(data["ready"])

    def test_put_keeps_key_when_not_provided(self):
        llm_config.save_config(self.rw, {"api_key": "sk-keep-me-9999"}, "admin")
        _unwrap(ai_decision.llm_config_put(
            ai_decision.LlmConfigIn(enabled=True, base_url="http://x/v1",
                                    api_key=None, model="m1"),
            SYS_ADMIN, self.rw))
        cfg = llm_config.load_config(self.rw)
        self.assertEqual(cfg["api_key"], "sk-keep-me-9999")
        self.assertTrue(cfg["enabled"])

    def test_put_clears_key_with_empty_string(self):
        llm_config.save_config(self.rw, {"api_key": "sk-to-clear"}, "admin")
        _unwrap(ai_decision.llm_config_put(
            ai_decision.LlmConfigIn(api_key=""), SYS_ADMIN, self.rw))
        self.assertEqual(llm_config.load_config(self.rw)["api_key"], "")

    def test_put_ignores_non_editable_fields(self):
        _unwrap(ai_decision.llm_config_put(
            ai_decision.LlmConfigIn(enabled=False), SYS_ADMIN, self.rw))
        cfg = llm_config.load_config(self.rw)
        self.assertEqual(cfg["provider"], "openai_compatible")  # 不可经端点修改

    def test_connection_test_success_and_failure(self):
        llm_config.save_config(self.rw, {
            "enabled": False,  # 测试不要求 enabled
            "base_url": "http://x/v1", "api_key": "k", "model": "m"}, "admin")
        with mock.patch.object(llm_client, "chat_completion", return_value="ok"):
            data = _unwrap(ai_decision.llm_config_test(SYS_ADMIN, self.rw))
        self.assertTrue(data["success"])

        with mock.patch.object(llm_client, "chat_completion",
                               side_effect=LLMError("timeout", "t")):
            data = _unwrap(ai_decision.llm_config_test(SYS_ADMIN, self.rw))
        self.assertFalse(data["success"])
        self.assertEqual(data["kind"], "timeout")

    def test_connection_test_requires_triple(self):
        with self.assertRaises(LLMError) as ctx:
            llm_client.test_connection(dict(llm_config.DEFAULTS))
        self.assertEqual(ctx.exception.kind, "not_configured")


class AdminGuardTest(unittest.TestCase):
    def test_non_admin_rejected_by_require_admin(self):
        from backend.api.deps import require_admin
        require_admin(SYS_ADMIN)  # 不抛异常
        with self.assertRaises(ApiError) as ctx:
            require_admin(NOT_ADMIN)
        self.assertEqual(getattr(ctx.exception, "status_code", 403), 403)


if __name__ == "__main__":
    unittest.main()

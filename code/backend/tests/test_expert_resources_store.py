"""Resource lifecycle tests use an isolated control store and explicit executors."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.expert_resources import store


ACTOR = {"username": "manager", "identity_id": "identity-a", "name": "管理员",
         "permission_context": {"authorized": True, "activeIdentityId": "identity-a", "scopeFingerprint": "school-v1"}}


def success(kind, content, inputs, actor, dependencies):
    return {"status": "passed", "summary": "实际执行器测试替身", "missingEvidence": [],
            "result": {"status": "limited", "summary": content["name"], "scope": {"college": "A"},
                       "data": [{"count": 10}], "sources": [{"table": "test_fixture"}],
                       "limitations": ["单元测试数据"], "missingEvidence": []},
            "trace": [{"step": "fixture", "status": "passed"}]}


class ResourceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = patch.dict(os.environ, {"EXPERT_RESOURCES_DB_PATH": str(Path(self.tmp.name) / "resources.sqlite")})
        self.config.start()
        self.runtime_version = patch("backend.expert_resources.runtime.fingerprint", return_value="sha256:test-adapter")
        self.runtime_version.start()
        self.seed = Path(self.tmp.name) / "seed.json"
        catalog = json.loads((store.CODE / "expert-resources/catalog.json").read_text(encoding="utf-8"))
        self.tool = next(t for mcp in catalog["mcps"] for t in mcp["tools"] if t["name"] == "read_program_structure")
        self.seed.write_text(json.dumps({
            "mcps": [{"id": "db", "content": {"name": "测试数据库", "tools": [self.tool]}}],
            "skills": [{"id": "analyse", "content": {"name": "统计分析", "execution": {"handler": "read_program_structure"},
                        "toolBindings": [{"serverId": "db", "toolName": "read_program_structure"}]}}],
            "experts": [{"id": "program", "content": {"name": "专业专家", "skillIds": ["analyse"]}}],
        }), encoding="utf-8")
        store.initialize(self.seed)

    def tearDown(self):
        self.runtime_version.stop()
        self.config.stop()
        self.tmp.cleanup()

    def publish(self, kind, resource_id):
        row = store.get_resource(kind, resource_id, ACTOR)
        revision = row["draft"]["revision"]
        row = store.test_resource(kind, resource_id, revision, {}, ACTOR, success)
        self.assertEqual(row["draft"]["test"]["status"], "passed")
        if kind != "mcps":
            store.review_resource(kind, resource_id, revision, row["draft"]["test"]["runId"], True,
                                  "已核对范围、口径及适用边界", ACTOR)
        return store.publish_resource(kind, resource_id, revision, ACTOR)

    def publish_all(self):
        for kind, resource_id in (("mcps", "db"), ("skills", "analyse"), ("experts", "program")):
            self.publish(kind, resource_id)

    def test_disabled_expert_catalog_reports_unavailable_and_preserves_version(self):
        self.publish_all()
        disabled = store.set_enabled('experts', 'program', False, ACTOR)
        self.assertFalse(disabled['readiness']['canRun'])
        self.assertIn('专家已停用', disabled['readiness']['runReasons'])
        self.assertIsNotNone(disabled['published'])
        restored = store.set_enabled('experts', 'program', True, ACTOR)
        self.assertTrue(restored['readiness']['canRun'])

    def test_structured_rule_edit_preserves_legacy_text_metadata_and_published_rules(self):
        self.publish('mcps', 'db')
        skill = store.get_resource('skills', 'analyse', ACTOR)
        content = deepcopy(skill['draft']['content'])
        content['rules'] = ['保留原有口径说明', {
            'group': 'metric', 'title': '数量口径', 'text': '按登记范围计算记录数',
            'sourceRef': {'name': '确认书', 'locator': '指标1'},
        }]
        saved = store.save_resource('skills', 'analyse', skill['draft']['revision'], content, ACTOR)
        published = self.publish('skills', 'analyse')
        edited = deepcopy(saved['draft']['content'])
        edited['rules'][1]['text'] = '补充字段含义；实际算法保持登记方法'
        updated = store.save_resource('skills', 'analyse', saved['draft']['revision'], edited, ACTOR)
        self.assertEqual(updated['draft']['content']['rules'][0], content['rules'][0])
        self.assertEqual(updated['draft']['content']['rules'][1]['sourceRef'], content['rules'][1]['sourceRef'])
        self.assertEqual(updated['published']['content']['rules'], published['published']['content']['rules'])
        self.assertEqual(updated['draft']['content']['execution'], content['execution'])
        self.assertNotEqual(updated['draft']['version'], updated['published']['version'])

    def assert_error(self, status, fn, *args):
        with self.assertRaises(ApiError) as caught:
            fn(*args)
        self.assertEqual(caught.exception.status_code, status)

    def test_initialize_is_idempotent_and_preserves_local_draft(self):
        definition = store.get_resource("experts", "program")["draft"]["content"]
        definition["name"] = "经修改的专业专家"
        store.save_resource("experts", "program", 1, definition, ACTOR)
        store.initialize(self.seed)
        result = store.get_resource("experts", "program", ACTOR)
        self.assertEqual(result["name"], "经修改的专业专家")
        self.assertEqual(result["draft"]["revision"], 2)
        self.assertIsNone(result["published"])

    def test_optimistic_revision_conflict_and_edit_invalidates_test(self):
        result = store.test_resource("mcps", "db", 1, {}, ACTOR, success)
        content = result["draft"]["content"]
        content["summary"] = "new content"
        result = store.save_resource("mcps", "db", 1, content, ACTOR)
        self.assertNotIn("test", result["draft"])
        self.assert_error(409, store.save_resource, "mcps", "db", 1, content, ACTOR)
        self.assert_error(409, store.publish_resource, "mcps", "db", 2, ACTOR)

    def test_failed_execution_cannot_be_accepted_or_published(self):
        self.publish("mcps", "db")
        def failed(*_):
            return {"status": "failed", "summary": "数据库不可达", "result": None, "trace": [], "missingEvidence": []}
        resource = store.test_resource("skills", "analyse", 1, {}, ACTOR, failed)
        run_id = resource["draft"]["test"]["runId"]
        self.assert_error(409, store.review_resource, "skills", "analyse", 1, run_id, True, "wrong", ACTOR)
        self.assert_error(409, store.publish_resource, "skills", "analyse", 1, ACTOR)
        self.assertFalse(store.review_resource("skills", "analyse", 1, run_id, False, "退回修正", ACTOR)["draft"]["review"]["accepted"])

    def test_unpublished_dependency_blocks_execution(self):
        called = []
        def executor(*args):
            called.append(args)
            return success(*args)
        result = store.test_resource("skills", "analyse", 1, {}, ACTOR, executor)
        self.assertEqual(result["draft"]["test"]["status"], "blocked")
        self.assertEqual(called, [])
        self.assert_error(409, store.publish_resource, "skills", "analyse", 1, ACTOR)

    def test_dependency_version_drift_invalidates_test_and_review(self):
        self.publish("mcps", "db")
        row = store.test_resource("skills", "analyse", 1, {}, ACTOR, success)
        store.review_resource("skills", "analyse", 1, row["draft"]["test"]["runId"], True, "已复核", ACTOR)
        db = store.get_resource("mcps", "db", ACTOR)
        db["draft"]["content"]["summary"] = "changed endpoint definition"
        db = store.save_resource("mcps", "db", 1, db["draft"]["content"], ACTOR)
        self.assertEqual(db["draft"]["version"], "1.1.0")
        self.publish("mcps", "db")
        row = store.get_resource("skills", "analyse", ACTOR)
        self.assertFalse(row["draft"]["test"]["valid"])
        self.assertFalse(row["readiness"]["canPublish"])
        self.assert_error(409, store.publish_resource, "skills", "analyse", 1, ACTOR)

    def test_business_review_required_even_when_technical_execution_passed(self):
        self.publish("mcps", "db")
        row = store.test_resource("skills", "analyse", 1, {}, ACTOR, success)
        self.assertEqual(row["draft"]["test"]["result"]["status"], "limited")
        self.assertFalse(row["readiness"]["canPublish"])
        row = store.review_resource("skills", "analyse", 1, row["draft"]["test"]["runId"], True, "接受已标注边界", ACTOR)
        self.assertTrue(row["readiness"]["canPublish"])

    def test_missing_business_material_cannot_publish_even_with_executor_pass(self):
        self.publish("mcps", "db")
        content = store.get_resource("skills", "analyse", ACTOR)["draft"]["content"]
        content["missingEvidence"] = ["本年度推免规则"]
        row = store.save_resource("skills", "analyse", 1, content, ACTOR)
        row = store.test_resource("skills", "analyse", 2, {}, ACTOR, success)
        store.review_resource("skills", "analyse", 2, row["draft"]["test"]["runId"], True, "不能覆盖缺失规则", ACTOR)
        self.assert_error(409, store.publish_resource, "skills", "analyse", 2, ACTOR)

    def test_owner_identity_and_scope_isolate_test_results(self):
        store.test_resource("mcps", "db", 1, {"sensitive": "fixture"}, ACTOR, success)
        for field, value in (("username", "other"), ("identity", "other"), ("scope", "college-a-v1")):
            actor = deepcopy(ACTOR)
            if field == "username":
                actor["username"] = value
            elif field == "identity":
                actor["identity_id"] = actor["permission_context"]["activeIdentityId"] = value
            else:
                actor["permission_context"]["scopeFingerprint"] = value
            row = store.catalog(actor)["mcps"][0]
            self.assertTrue(row["draft"]["test"]["redacted"])
            self.assertNotIn("result", row["draft"]["test"])
            self.assertNotIn("trace", row["draft"]["test"])
            self.assertNotIn("input", row["draft"]["test"])
            self.assertFalse(row["readiness"]["canPublish"])

    def test_research_remains_pinned_while_new_research_uses_new_version(self):
        self.publish_all()
        first = store.create_research("program", {}, "第一次研究", ACTOR, success)
        old_expert_version = first["expertVersion"]
        old_skill_version = first["dependencies"]["skills"][0]["version"]
        content = store.get_resource("skills", "analyse", ACTOR)["draft"]["content"]
        content["name"] = "统计分析新版"
        store.save_resource("skills", "analyse", 1, content, ACTOR)
        self.publish("skills", "analyse")
        content = store.get_resource("experts", "program", ACTOR)["draft"]["content"]
        content["summary"] = "new skill release"
        store.save_resource("experts", "program", 1, content, ACTOR)
        self.publish("experts", "program")
        later = store.create_research("program", {}, "新研究", ACTOR, success)
        self.assertNotEqual(later["expertVersion"], old_expert_version)
        self.assertNotEqual(later["dependencies"]["skills"][0]["version"], old_skill_version)
        captured = []
        def record(kind, content, inputs, actor, deps):
            captured.append(deps["skills"][0]["version"])
            return success(kind, content, inputs, actor, deps)
        continued = store.add_turn(first["id"], {}, "继续原研究", ACTOR, record)
        self.assertEqual(captured, [old_skill_version])
        self.assertEqual(continued["expertVersion"], old_expert_version)
        self.assertEqual(len(continued["turns"]), 2)

    def test_disable_blocks_old_research_calls_but_preserves_authorized_history(self):
        self.publish_all()
        result = store.create_research("program", {}, "已有研究", ACTOR, success)
        store.set_enabled("mcps", "db", False, ACTOR)
        self.assert_error(409, store.add_turn, result["id"], {}, "继续", ACTOR, success)
        self.assert_error(409, store.create_research, "program", {}, "新研究", ACTOR, success)
        self.assertEqual(len(store.get_research(result["id"], ACTOR)["turns"]), 1)

    def test_new_turn_replaces_scope_so_cleared_filters_do_not_reappear(self):
        self.publish_all()
        result = store.create_research('program', {'college_id': 'A', 'plan_id': 'old'}, '初始范围', ACTOR, success)
        captured = []
        def capture(kind, content, inputs, actor, deps):
            captured.append(inputs)
            return success(kind, content, inputs, actor, deps)
        updated = store.add_turn(result['id'], {'semester_id':'new'}, '重新选择范围', ACTOR, capture)
        self.assertNotIn('college_id', captured[0])
        self.assertNotIn('plan_id', captured[0])
        self.assertEqual(updated['input'], {'semester_id': 'new'})

    def test_research_read_requires_same_owner_identity_and_current_scope(self):
        self.publish_all()
        result = store.create_research("program", {}, "范围隔离", ACTOR, success)
        actor = deepcopy(ACTOR)
        actor["permission_context"]["scopeFingerprint"] = "changed-scope"
        self.assert_error(404, store.get_research, result["id"], actor)
        self.assertEqual(store.list_research(actor), {"items": [], 'total': 0, 'offset': 0, 'limit': 50})
        actor = deepcopy(ACTOR)
        actor["username"] = "other"
        self.assert_error(404, store.get_research, result["id"], actor)
        actor = deepcopy(ACTOR)
        actor["permission_context"].pop("scopeFingerprint")
        self.assert_error(403, store.list_research, actor)

    def test_runtime_cannot_claim_success_with_invalid_status(self):
        result = store.test_resource("mcps", "db", 1, {}, ACTOR, lambda *_: {"status": "fake_success"})
        self.assertEqual(result["draft"]["test"]["status"], "failed")
        self.assertFalse(result["readiness"]["canPublish"])

    def test_save_during_execution_prevents_recording_stale_success(self):
        def mutate(kind, content, inputs, actor, deps):
            store.save_resource(kind, "db", 1, {**content, "summary": "concurrent edit"}, actor)
            return success(kind, content, inputs, actor, deps)
        self.assert_error(409, store.test_resource, "mcps", "db", 1, {}, ACTOR, mutate)
        self.assertNotIn("test", store.get_resource("mcps", "db", ACTOR)["draft"])

    def test_dependency_changes_during_execution_preserve_invalid_result(self):
        self.publish("mcps", "db")
        def mutate(kind, content, inputs, actor, deps):
            definition = store.get_resource("mcps", "db", actor)["draft"]["content"]
            store.save_resource("mcps", "db", 1, {**definition, "summary": "changed during execution"}, actor)
            self.publish("mcps", "db")
            return success(kind, content, inputs, actor, deps)
        result = store.test_resource("skills", "analyse", 1, {}, ACTOR, mutate)
        self.assertEqual(result["draft"]["test"]["status"], "passed")
        self.assertFalse(result["draft"]["test"]["valid"])
        self.assertFalse(result["readiness"]["canPublish"])

    def test_invalid_resource_identity_handler_tool_and_schema_are_rejected(self):
        definition = store.get_resource("skills", "analyse", ACTOR)["draft"]["content"]
        cases = [
            {**definition, "id": "another-skill"},
            {**definition, "execution": {"handler": "arbitrary_python"}},
            {**definition, "inputSchema": {"type": "invented"}},
            {**definition, "outputSchema": {"$ref": "http://localhost/private"}},
            {**definition, "toolBindings": [{"serverId": "db", "toolName": "compare_programs"}]},
        ]
        for content in cases:
            self.assert_error(422, store.save_resource, "skills", "analyse", 1, content, ACTOR)
        mcp = store.get_resource("mcps", "db", ACTOR)["draft"]["content"]
        mcp["tools"] = [{"name": "arbitrary_sql"}]
        self.assert_error(422, store.save_resource, "mcps", "db", 1, mcp, ACTOR)
        mcp["tools"] = [self.tool]
        mcp["endpoint"] = "https://unconfigured-server.example/mcp"
        self.assert_error(422, store.save_resource, "mcps", "db", 1, mcp, ACTOR)
        mcp.pop("endpoint")
        mcp["tools"][0] = {**self.tool, "inputSchema": {"type": "object"}}
        self.assert_error(422, store.save_resource, "mcps", "db", 1, mcp, ACTOR)

    def test_expert_test_declares_the_selected_method_coverage(self):
        self.publish_all()
        result = store.test_resource("experts", "program", 1, {"skill_id": "analyse"}, ACTOR, success)
        self.assertEqual(result["draft"]["test"]["coverage"]["testedSkillIds"], ["analyse"])

    def test_request_models_bound_nested_content_size(self):
        from backend.expert_resources.models import TestInput
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            TestInput(revision=1, input={"question": "x" * 24001})

    def test_runtime_error_on_retest_clears_previous_acceptance(self):
        self.publish("mcps", "db")
        row = store.test_resource("skills", "analyse", 1, {}, ACTOR, success)
        store.review_resource("skills", "analyse", 1, row["draft"]["test"]["runId"], True, "首次复核", ACTOR)
        def raises(*_):
            raise ApiError("数据连接失败", status_code=503)
        row = store.test_resource("skills", "analyse", 1, {}, ACTOR, raises)
        self.assertEqual(row["draft"]["test"]["status"], "failed")
        self.assertNotIn("review", row["draft"])
        self.assertFalse(row["readiness"]["canPublish"])

    def test_permission_error_during_retest_revokes_previous_acceptance(self):
        store.test_resource("mcps", "db", 1, {}, ACTOR, success)
        def forbidden(*_):
            raise ApiError("权限已失效", status_code=403)
        self.assert_error(403, store.test_resource, "mcps", "db", 1, {}, ACTOR, forbidden)
        self.assertFalse(store.get_resource("mcps", "db", ACTOR)["readiness"]["canPublish"])

    def test_older_slow_test_cannot_replace_a_newer_test_result(self):
        def second_test(kind, content, inputs, actor, deps):
            store.test_resource("mcps", "db", 1, {"request": "newer"}, ACTOR, success)
            return success(kind, content, inputs, actor, deps)
        self.assert_error(409, store.test_resource, "mcps", "db", 1, {"request": "older"}, ACTOR, second_test)
        result = store.get_resource("mcps", "db", ACTOR)
        self.assertEqual(result["draft"]["test"]["input"], {"request": "newer"})

    def test_leadership_api_reads_catalog_without_admin_test_data_or_mutation_rights(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from backend.expert_resources.auth import current_actor
        from backend.expert_resources.router import router
        self.publish_all()
        research = store.create_research("program", {}, "管理员私有研究", ACTOR, success)
        app = FastAPI()
        app.include_router(router)
        @app.exception_handler(ApiError)
        async def handler(_request, exc):
            return JSONResponse({"code": exc.code, "msg": exc.msg, "data": None}, status_code=exc.status_code)
        leader = deepcopy(ACTOR)
        leader["username"] = "leader"
        leader["permission_context"].update({"activeRole": "dean", "detailScope": {"type": "all"},
            "actionPermissions": ["ai.analyze", "expert_team.use"],
            "menuPermissions": ["/admin/reports/expert-team"]})
        app.dependency_overrides[current_actor] = lambda: leader
        with TestClient(app) as client:
            response = client.get("/api/admin/expert-resources/catalog")
            self.assertEqual(response.status_code, 200)
            data = response.json()["data"]
            self.assertFalse(data["canManage"])
            self.assertTrue(data["skills"][0]["draft"]["test"]["redacted"])
            self.assertNotIn("result", data["skills"][0]["draft"]["test"])
            self.assertNotIn("note", data["skills"][0]["draft"]["review"])
            denied = client.post("/api/admin/expert-resources/resources/experts/program/enabled", json={"enabled": False})
            self.assertEqual(denied.status_code, 403)
            for method, url, body in (
                ("POST", "/resources/experts", {"name": "禁止新增"}),
                ("POST", "/resources/experts/program/copy", {"revision": 1, "name": "禁止复制"}),
                ("DELETE", "/resources/experts/program?revision=1", None),
                ("POST", "/resources/experts/program/restore", {"revision": 1}),
                ("GET", "/resources/experts/program/references", None),
                ("GET", "/archived", None),
            ):
                response = client.request(method, "/api/admin/expert-resources" + url, json=body)
                self.assertEqual(response.status_code, 403, url)
            self.assertEqual(client.get(f"/api/admin/expert-resources/research/{research['id']}").status_code, 404)

    def test_changed_runtime_invalidates_tests_and_prevents_old_algorithm_claims(self):
        self.publish_all()
        research = store.create_research("program", {}, "发布算法研究", ACTOR, success)
        current = store.get_resource("skills", "analyse", ACTOR)
        recorded = current["draft"]["test"]["runtimeFingerprint"]
        self.assertTrue(recorded)
        with patch("backend.expert_resources.runtime.fingerprint", return_value="sha256:new-deployment"):
            current = store.get_resource("skills", "analyse", ACTOR)
            self.assertFalse(current["draft"]["test"]["valid"])
            self.assert_error(409, store.create_research, "program", {}, "部署后新研究", ACTOR, success)
            self.assert_error(409, store.add_turn, research["id"], {}, "部署后继续", ACTOR, success)
            self.assertEqual(len(store.get_research(research["id"], ACTOR)["turns"]), 1)
            content = current["draft"]["content"]
            store.save_resource("skills", "analyse", 1, content, ACTOR)
            self.publish("skills", "analyse")
            expert = store.get_resource("experts", "program", ACTOR)
            store.save_resource("experts", "program", 1, expert["draft"]["content"], ACTOR)
            self.publish("experts", "program")
            new = store.create_research("program", {}, "使用新版本", ACTOR, success)
            self.assertEqual(new["dependencies"]["runtimeFingerprint"], "sha256:new-deployment")
            # An old research remains pinned and must not silently upgrade its processor.
            self.assert_error(409, store.add_turn, research["id"], {}, "旧研究仍受保护", ACTOR, success)


    def test_create_and_copy_clean_drafts(self):
        row = store.create_resource("skills", "新方法", ACTOR, "new-method", category="分类", summary="说明")
        self.assertEqual(row["draft"]["content"]["execution"]["handler"], "unavailable")
        self.assertFalse(row["readiness"]["canPublish"])
        self.assertEqual(row["category"], "分类")
        self.assert_error(422, store.create_resource, "mcps", "未知服务", ACTOR)
        copied = store.create_resource("mcps", "模板", ACTOR, "new-db", "db")
        self.assertEqual(copied["draft"]["content"]["tools"], [self.tool])
        self.assert_error(409, store.create_resource, "skills", "重复", ACTOR, "new-method")
        self.assert_error(422, store.create_resource, "skills", "路径", ACTOR, "../unsafe")
        self.publish_all()
        row = store.copy_resource("skills", "analyse", 1, "复制", ACTOR, "analyse-copy")
        self.assertEqual(row["draft"]["revision"], 1)
        self.assertNotIn("test", row["draft"])
        self.assertNotIn("review", row["draft"])
        self.assertIsNone(row["published"])
        self.assertEqual(row["draft"]["content"]["id"], "analyse-copy")
        self.assert_error(409, store.copy_resource, "skills", "analyse", 99, "冲突", ACTOR)

    def test_references_block_current_published_deletion(self):
        self.publish_all()
        refs = store.references("skills", "analyse")
        self.assertEqual({i["relation"] for i in refs["items"]}, {"draft", "published"})
        self.assert_error(409, store.delete_resource, "skills", "analyse", 1, ACTOR)
        content = deepcopy(store.get_resource("experts", "program")["draft"]["content"])
        content["skillIds"] = []
        store.save_resource("experts", "program", 1, content, ACTOR)
        self.assertEqual([i["relation"] for i in store.references("skills", "analyse")["items"]], ["published"])
        self.assert_error(409, store.delete_resource, "skills", "analyse", 1, ACTOR)
        store.delete_resource("experts", "program", 2, ACTOR)
        self.assertTrue(store.references("skills", "analyse")["canDelete"])

    def test_delete_restore_preserves_seed_tombstone_and_revision(self):
        row = store.delete_resource("experts", "program", 1, ACTOR)
        self.assertTrue(row["deletedAt"])
        self.assertFalse(row["enabled"])
        self.assertEqual(store.catalog(ACTOR)["experts"], [])
        self.assert_error(404, store.get_resource, "experts", "program", ACTOR)
        store.initialize(self.seed)
        self.assertEqual(store.catalog(ACTOR)["experts"], [])
        self.assertEqual(len(store.archived("experts", ACTOR)["items"]), 1)
        self.assert_error(409, store.restore_resource, "experts", "program", 1, ACTOR)
        restored = store.restore_resource("experts", "program", 2, ACTOR)
        self.assertIsNone(restored["deletedAt"])
        self.assertFalse(restored["enabled"])
        self.assertEqual(restored["draft"]["revision"], 3)
        self.assert_error(409, store.restore_resource, "experts", "program", 3, ACTOR)

    def test_deleted_expert_research_retained_execution_rejected(self):
        self.publish_all()
        research = store.create_research("program", {}, "原研究", ACTOR, success)
        row = store.delete_resource("experts", "program", 1, ACTOR)
        self.assertEqual(store.get_research(research["id"], ACTOR)["turns"][0]["question"], "原研究")
        self.assertIsNotNone(row["published"])
        self.assertGreaterEqual(row["references"]["historyCount"], 2)
        self.assert_error(404, store.add_turn, research["id"], {}, "继续", ACTOR, success)
        self.assert_error(404, store.create_research, "program", {}, "重新", ACTOR, success)
        self.assert_error(404, store.test_resource, "experts", "program", 2, {}, ACTOR, success)
        store.restore_resource("experts", "program", 2, ACTOR)
        self.assert_error(409, store.add_turn, research["id"], {}, "继续", ACTOR, success)
        store.set_enabled("experts", "program", True, ACTOR)
        self.assertEqual(len(store.add_turn(research["id"], {}, "继续", ACTOR, success)["turns"]), 2)

    def test_crud_identity_required(self):
        self.assert_error(403, store.create_resource, "experts", "未授权", {})
        self.assert_error(403, store.copy_resource, "experts", "program", 1, "未授权", {})
        self.assert_error(403, store.delete_resource, "experts", "program", 1, {})
        self.assert_error(403, store.restore_resource, "experts", "program", 1, {})

if __name__ == "__main__":
    unittest.main()

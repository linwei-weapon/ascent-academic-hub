"""Module isolation, protected registration and rollback use only an isolated SQLite transport."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.metric_verification import mapping_store, registry
from backend.metric_verification.config import ASSETS
from backend.metric_verification.mapping_contract import validate_package
from backend.metric_verification.options import parameter_columns
try:
    from .test_metric_mapping_store import Connection, ACTOR
    from .test_metric_mapping_contract import package_fixture
except ImportError:
    from test_metric_mapping_store import Connection, ACTOR
    from test_metric_mapping_contract import package_fixture


class ModuleStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = Connection()
        self.db.conn.executescript("""
        CREATE TABLE sys_metric_definition(id INTEGER PRIMARY KEY,metric_code TEXT UNIQUE,metric_name TEXT,metric_type TEXT,
          data_source TEXT,sql_template TEXT,cache_ttl INTEGER,enabled INTEGER,created_at TEXT,updated_at TEXT,
          definition_status TEXT,implementation_status TEXT,technical_kpi_id TEXT,boundary TEXT,management_value TEXT,
          grain TEXT,update_cycle TEXT,version TEXT,source_kind TEXT,definition_source TEXT,page_refs TEXT);
        CREATE TABLE sys_metric_page_binding(id INTEGER PRIMARY KEY,metric_code TEXT,page_path TEXT,position TEXT,
          sort_order INTEGER,enabled INTEGER,created_at TEXT,UNIQUE(metric_code,page_path));
        """)
        self.patcher = patch.object(mapping_store, "connection", self.db.open)
        self.patcher.start()
        self.package = json.loads((ASSETS / "mappings/ai-briefing/package.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.patcher.stop()
        self.db.conn.close()

    def save_ai(self):
        with mapping_store.module_scope("ai-briefing"):
            return mapping_store.save_package(self.package, ACTOR)

    def test_required_mode_bootstrap_read_does_not_relax_business_head(self):
        with mapping_store.module_scope("ai-briefing"), patch.dict(os.environ, {"MV_MAPPING_MODE": "required"}), patch.object(mapping_store, "database_config", return_value=SimpleNamespace(configured=True)), patch.object(mapping_store, "table_ready", return_value=True):
            with self.assertRaises(ApiError) as denied:
                mapping_store.get_head()
            self.assertEqual(503, denied.exception.status_code)
            self.assertIsNone(mapping_store.get_head(allow_empty=True)["revisionId"])
            with self.assertRaises(ApiError):
                mapping_store.get_head()
            self.assertEqual(0, self.db.conn.execute("SELECT COUNT(*) FROM sys_metric_mapping_head").fetchone()[0])

    def activate_ai(self):
        saved = self.save_ai()
        with mapping_store.module_scope("ai-briefing"):
            return mapping_store.activate_revision(saved["revisionId"], None, ACTOR)

    def test_module_and_project_scope_cannot_be_selected_by_package(self):
        for key, value in [("moduleId", "ai-briefing"), ("projectId", "other-school"), ("environmentId", "prod")]:
            package = package_fixture()
            package[key] = value
            with self.assertRaises(ApiError) as error:
                mapping_store.save_package(package, ACTOR)
            self.assertEqual(403, error.exception.status_code)
        with self.assertRaises(ApiError):
            with mapping_store.module_scope("anything"):
                self.fail("arbitrary module admitted")

    def test_two_modules_keep_independent_heads_and_revision_visibility(self):
        original = mapping_store.save_package(package_fixture(), ACTOR)
        mapping_store.activate_revision(original["revisionId"], None, ACTOR)
        ai = self.activate_ai()
        heads = self.db.conn.execute("SELECT module_id,revision_id FROM sys_metric_mapping_head ORDER BY module_id").fetchall()
        self.assertEqual({"teaching-overview": original["revisionId"], "ai-briefing": ai["revisionId"]}, {r[0]: r[1] for r in heads})
        self.assertEqual(original["revisionId"], mapping_store.list_revisions()[0]["revisionId"])
        self.assertEqual(ai["revisionId"], mapping_store.list_revisions(module_id="ai-briefing")[0]["revisionId"])
        with self.assertRaises(ApiError) as error:
            mapping_store.get_revision(ai["revisionId"])
        self.assertEqual(404, error.exception.status_code)
        self.assertEqual("ai-briefing", mapping_store.get_revision(ai["revisionId"], module_id="ai-briefing")["package"]["moduleId"])

    def test_registration_requires_actual_matching_definition_and_binding(self):
        draft = self.save_ai()
        status = mapping_store.registration_status(draft["revisionId"], module_id="ai-briefing")
        self.assertFalse(status["registered"])
        self.activate_ai()
        status = mapping_store.registration_status(draft["revisionId"], module_id="ai-briefing")
        self.assertTrue(status["registered"])
        self.assertEqual(6, len(status["metrics"]))
        self.db.conn.execute("UPDATE sys_metric_definition SET sql_template='SELECT 0' WHERE metric_code='AI-C-04'")
        self.db.conn.commit()
        status = mapping_store.registration_status(draft["revisionId"], module_id="ai-briefing")
        self.assertFalse(status["registered"])
        self.assertFalse(next(r for r in status["metrics"] if r["metricCode"] == "AI-C-04")["registered"])

    def test_collision_cannot_overwrite_other_definition_and_rolls_back_all(self):
        self.db.conn.execute("INSERT INTO sys_metric_definition(metric_code,metric_name,definition_source) VALUES('AI-C-03','Existing','another-interface')")
        self.db.conn.commit()
        saved = self.save_ai()
        with mapping_store.module_scope("ai-briefing"), self.assertRaises(ApiError):
            mapping_store.activate_revision(saved["revisionId"], None, ACTOR)
        self.assertEqual(1, self.db.conn.execute("SELECT COUNT(*) FROM sys_metric_definition").fetchone()[0])
        self.assertEqual(0, self.db.conn.execute("SELECT COUNT(*) FROM sys_metric_page_binding").fetchone()[0])
        self.assertIsNone(self.db.conn.execute("SELECT revision_id FROM sys_metric_mapping_head WHERE module_id='ai-briefing'").fetchone()[0])

    def test_failing_binding_write_rolls_back_definitions_and_head(self):
        self.db.conn.execute("CREATE TRIGGER fail_binding BEFORE INSERT ON sys_metric_page_binding BEGIN SELECT RAISE(ABORT,'test-write-failure'); END")
        self.db.conn.commit()
        saved = self.save_ai()
        with mapping_store.module_scope("ai-briefing"), self.assertRaises(Exception):
            mapping_store.activate_revision(saved["revisionId"], None, ACTOR)
        self.assertEqual(0, self.db.conn.execute("SELECT COUNT(*) FROM sys_metric_definition").fetchone()[0])
        self.assertIsNone(self.db.conn.execute("SELECT revision_id FROM sys_metric_mapping_head WHERE module_id='ai-briefing'").fetchone()[0])

    def test_ai_consumer_bindings_do_not_import_106_navigation(self):
        bindings = mapping_store.legacy_bindings(self.package)
        self.assertEqual("ai-briefing", bindings["module"]["id"])
        self.assertEqual(set(mapping_store.MODULES) - {"teaching-overview"}, {bindings["module"]["id"]})
        self.assertEqual(6, len(bindings["entries"]))
        self.assertTrue(all(e["metricId"].startswith("AI-C-") for e in bindings["entries"]))
        self.assertTrue(all(r["pagePaths"] == [mapping_store.AI_BRIEFING_PAGE] for r in bindings["requirements"].values()))

    def test_package_queries_declared_and_no_student_identifiers(self):
        report = validate_package(self.package)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(54, len(report["queryChecks"]))
        self.assertTrue(all(q["executionApproval"] == "documented" for q in report["queryChecks"].values()))
        for query in self.package["queries"]:
            self.assertNotIn("student_id", query["sql"].lower())
        self.assertNotIn("open_org_id", str(self.package))
        for query in self.package["queries"]:
            if query["kind"] == "count" and query["layer"] != "application":
                self.assertIn("source_records", query["sql"])
                self.assertIn("state_groups", query["sql"])

    def test_cast_parameter_choices_only_use_declared_physical_columns(self):
        query = next(q for q in self.package["queries"] if q["id"] == "AI-C-01-fact-count")
        checks = validate_package(self.package)["queryChecks"][query["id"]]
        result = parameter_columns({**query, "requiredColumns": checks["requiredColumns"]})
        self.assertEqual(("act_grade_attempt", "semester_id"), result["semester_id"])
        self.assertEqual(("act_course", "organization_id"), result["organization_id"])
        self.assertEqual(("act_grade_attempt", "course_id"), result["course_id"])


class ModuleContextTests(unittest.TestCase):
    def test_async_contexts_are_isolated_and_restored(self):
        async def selected(module_id):
            with mapping_store.module_scope(module_id):
                await asyncio.sleep(0.001)
                return mapping_store.scope()[1]
        async def run():
            return await asyncio.gather(selected("ai-briefing"), selected("teaching-overview"))
        self.assertEqual(["ai-briefing", "teaching-overview"], asyncio.run(run()))
        self.assertEqual("teaching-overview", mapping_store.scope()[1])

    def test_thread_contexts_and_legacy_environment_are_not_process_global_selection(self):
        def selected(module_id):
            with mapping_store.module_scope(module_id):
                return mapping_store.scope()[1]
        with patch.dict(os.environ, {"MV_MAPPING_MODULE": "ai-briefing"}), ThreadPoolExecutor(2) as pool:
            self.assertEqual(["ai-briefing", "teaching-overview"], list(pool.map(selected, ["ai-briefing", "teaching-overview"])))
            self.assertEqual("teaching-overview", mapping_store.scope()[1])

    def test_ai_without_revision_cannot_fallback_to_106_files(self):
        with mapping_store.module_scope("ai-briefing"), patch.object(registry, "_active_revision", return_value=None), patch.object(registry, "read_json", side_effect=AssertionError("106 file read")):
            self.assertEqual([], registry.catalog()["metrics"])
            self.assertEqual([], registry.queries_document()["metrics"])

    def test_pinned_revision_cache_key_includes_current_module(self):
        def head():
            return {"revisionId": mapping_store.scope()[1]}
        def revision(revision_id):
            return {"revisionId": revision_id, "package": {"moduleId": revision_id}}
        with patch.object(mapping_store, "get_head", side_effect=head), patch.object(mapping_store, "get_revision", side_effect=revision):
            with registry.revision_scope():
                self.assertEqual("teaching-overview", registry.current_revision_id())
                with mapping_store.module_scope("ai-briefing"):
                    self.assertEqual("ai-briefing", registry.current_revision_id())
                self.assertEqual("teaching-overview", registry.current_revision_id())

    def test_http_middleware_scopes_concurrent_requests_and_rejects_unknown_module(self):
        import httpx
        from fastapi import FastAPI
        from backend.metric_verification.app import mapping_snapshot, PREFIX
        app = FastAPI()
        app.middleware("http")(mapping_snapshot)
        @app.get(PREFIX + "/mapping/test-module-context")
        async def selected_context():
            await asyncio.sleep(0.001)
            return {"moduleId": mapping_store.scope()[1]}
        async def request_both():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                paths = [PREFIX + "/mapping/test-module-context?moduleId=" + module for module in ["ai-briefing", "teaching-overview", "unregistered"]]
                return await asyncio.gather(*(client.get(path) for path in paths))
        responses = asyncio.run(request_both())
        self.assertEqual(["ai-briefing", "teaching-overview"], [response.json()["moduleId"] for response in responses[:2]])
        self.assertEqual(422, responses[2].status_code)
        self.assertEqual("teaching-overview", mapping_store.scope()[1])


if __name__ == "__main__":
    unittest.main()

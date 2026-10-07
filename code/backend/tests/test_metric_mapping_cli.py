"""Workflow invariants, isolated from databases and existing user credentials."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code"))
spec = importlib.util.spec_from_file_location("metric_mapping_cli", ROOT / "code/scripts/metric_mapping.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
from backend.metric_verification.mapping_legacy import build_initial_package


class FakeService:
    def __init__(self, corrupt=False):
        self.calls = []
        self.package = None
        self.corrupt = corrupt

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        if path == "/mapping/packages":
            self.package = deepcopy(body)
            return {"revisionId": "revision-test"}
        if path == "/mapping/revisions/revision-test":
            package = deepcopy(self.package)
            if self.corrupt: package["moduleName"] = "changed"
            return {"package": package}
        if path == "/mapping/activate": return {"revisionId": "revision-test", "state": "active"}
        if path.endswith("/answers"): return {"answerId": "answer-test"}
        raise AssertionError(path)


class MappingCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = build_initial_package()

    def test_initial_migration_is_business_only_and_not_verified(self):
        p = self.package
        result = cli.offline_validate(p)
        self.assertTrue(result["valid"], result["errors"])
        self.assertNotIn("requirements", p)
        self.assertNotIn("pages", p)
        self.assertNotIn("scenes", p)
        self.assertTrue(all(m["definition"]["evidenceRefs"] for m in p["metrics"]))
        self.assertEqual(result["checks"]["runtimeSql"], "not_run")
        self.assertTrue(all(m["verificationPlan"]["closureStatus"] == "not_verified" for m in p["metrics"]))
        self.assertTrue(all(q["purpose"] != "application_actual" for q in p["queries"]))

    def test_prepare_follows_business_dependencies(self):
        input_data = deepcopy(self.package["inputManifest"])
        input_data["scope"]["metricIds"] = ["O-10"]
        result = cli.prepare_work(input_data, package=self.package)
        self.assertTrue({"O-02", "O-08"}.issubset(result["dependencyMetricIds"]))
        self.assertIn("MV106-COLLEGE-EXCESS-IMPACT", result["affectedMetricIds"])
        self.assertNotIn("MV106-TEACHER-COUNT", result["affectedMetricIds"])

    def test_partial_work_preserves_other_metrics(self):
        patch_package = deepcopy(self.package)
        patch_package["baseRevisionId"] = "r1"
        patch_package["inputManifest"]["baseRevisionId"] = "r1"
        patch_package["metrics"] = [deepcopy(next(m for m in self.package["metrics"] if m["id"] == "O-10"))]
        merged = cli.assemble_package(patch_package, self.package, partial=True)
        self.assertEqual(len(merged["metrics"]), len(self.package["metrics"]))
        self.assertEqual(next(m for m in merged["metrics"] if m["id"] == "MV106-TEACHER-COUNT"),
                         next(m for m in self.package["metrics"] if m["id"] == "MV106-TEACHER-COUNT"))

    def test_no_silent_delete(self):
        changed = deepcopy(self.package)
        changed["baseRevisionId"] = "r1"; changed["inputManifest"]["baseRevisionId"] = "r1"
        changed["metrics"] = [m for m in changed["metrics"] if m["id"] != "MV106-TEACHER-COUNT"]
        self.assertFalse(cli.offline_validate(changed, self.package)["valid"])

    def test_shared_rule_change_invalidates_dependents_only(self):
        changed = deepcopy(self.package)
        changed["sharedRules"][0]["definition"]["validityRules"] = ["changed for isolated test"]
        before = cli.semantic_signatures(self.package); after = cli.semantic_signatures(changed)
        self.assertNotEqual(before["O-10"], after["O-10"])
        self.assertNotEqual(before["MV106-COLLEGE-EXCESS-IMPACT"], after["MV106-COLLEGE-EXCESS-IMPACT"])
        self.assertEqual(before["MV106-TEACHER-COUNT"], after["MV106-TEACHER-COUNT"])

    def test_no_credentials_no_request_and_no_secret_in_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(cli.WorkflowError) as caught:
                cli.ServiceClient({"baseUrl": "http://127.0.0.1:8010"})
        self.assertIn("未发送请求", str(caught.exception))

    def test_analyze_only_cannot_publish(self):
        client = FakeService()
        with self.assertRaises(cli.WorkflowError): cli.publish_package(self.package, client, "save_draft")
        self.assertEqual(client.calls, [])

    def test_readback_before_activation(self):
        package = deepcopy(self.package); package["inputManifest"]["delivery"]["mode"] = "activate"
        client = FakeService(corrupt=True)
        with self.assertRaises(cli.WorkflowError): cli.publish_package(package, client, "activate")
        self.assertNotIn(("POST", "/mapping/activate"), client.calls)

    def test_answers_do_not_activate_unapplied_rules(self):
        package = deepcopy(self.package); package["inputManifest"]["delivery"]["mode"] = "activate"
        question = package["questions"][0]
        package["pendingAnswers"] = [{"submissionId": "submission-test", "questionId": question["id"],
            "questionContextHash": question["contextHash"], "rawAnswer": "test answer", "customAnswer": "test answer"}]
        client = FakeService()
        receipt = cli.publish_package(package, client, "activate")
        self.assertEqual(receipt["storageStatus"], "draft")
        self.assertEqual(receipt["answerSync"][0]["answerId"], "answer-test")
        self.assertNotIn(("POST", "/mapping/activate"), client.calls)

    def test_live_requires_the_registered_snapshot(self):
        client = FakeService()
        client.package = deepcopy(self.package)
        client.corrupt = True
        with self.assertRaises(cli.WorkflowError):
            cli.live_validate(self.package, client, "revision-test", evidence_id="execution-test")
        self.assertEqual(client.calls, [("GET", "/mapping/revisions/revision-test")])

    def test_live_receipt_never_exports_raw_inputs(self):
        package = self.package
        class EvidenceService:
            def request(self, method, path, body=None):
                if path.startswith("/mapping/revisions/"): return {"package": package}
                return {"mappingRevisionId": "revision-test", "datasets": [{"queryId": "input", "rows": [{"student_id": "sensitive-test"}],
                    "matchedRecordCount": 1, "returnedRecordCount": 1, "complete": True}], "integrity": {"contentHash": "a" * 64, "readbackVerified": True},
                    "resultDisclosure": "withheld", "validation": {"status": "pending", "differences": []}}
        receipt = cli.live_validate(package, EvidenceService(), "revision-test", evidence_id="execution-test")
        self.assertNotIn("sensitive-test", str(receipt))
        self.assertEqual(receipt["independentCalculation"], "pending")

    def test_module_mismatch_is_rejected_before_service_use(self):
        with self.assertRaises(cli.WorkflowError):
            cli.package_module(self.package, "ai-briefing")
        with self.assertRaises(cli.WorkflowError):
            cli.check_module("another-module")
        input_data = deepcopy(self.package["inputManifest"])
        input_data["module"]["id"] = "ai-briefing"
        with self.assertRaises(cli.WorkflowError):
            cli.prepare_work(input_data, package=self.package)


if __name__ == "__main__": unittest.main()

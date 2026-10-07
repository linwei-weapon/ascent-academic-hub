"""Trusted evidence import and save validation, isolated from all real databases."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.api.envelope import ApiError
from backend.metric_verification import app as service, auth, evidence_import as imp, registry, store
from backend.tests.test_metric_verification import actor, Connection, fake_connection, registered_query
from backend.tests.test_metric_verification_comparison import observation, record_body


SCENE = {"id": "home-fail", "metricId": "O-10", "requirementId": "REQ", "name": "当前挂科学生率", "comparisonKind": "scalar"}


class EvidenceImportTests(unittest.TestCase):
    def setUp(self):
        self.query = registered_query(id="Q", kind="calculate")
        self.snapshot = {"status": "success", "queryKind": "calculate", "scenarioId": SCENE["id"],
                         "scenarioChecksum": "S", "requirementChecksum": "R", "returnedRows": 1, "truncated": False,
                         "metrics": {"candidate_metric_value": "20.780950000", "numerator": 2033, "denominator": 9783}}
        self.stored = {"metric_id": "O-10", "query_id": "Q", "query_version": "1.0.0", "query_checksum": "fixture-checksum",
                       "layer_name": "fact", "executed_at": "2026-09-29T15:21:56+00:00",
                       "parameters_json": json.dumps({"semester_id": "301", "organization_id": None, "grade_batch_id": "B1"})}
        patch.object(registry, "scenario", return_value=SCENE).start()
        patch.object(registry, "scenario_checksum", return_value="S").start()
        patch.object(registry, "requirement_checksum", return_value="R").start()
        patch.object(registry, "find_query", side_effect=lambda _: self.query).start()
        patch.object(registry, "catalog", return_value={"metrics": [{"id": "O-10", "unit": "%"}]}).start()
        self.addCleanup(patch.stopall)

    def draft(self, missing=False):
        row = {**self.stored, "result_json": json.dumps(self.snapshot)}
        self.conn = Connection({"rows": [] if missing else [row]})
        with patch.object(imp, "connection", return_value=fake_connection(self.conn)):
            return imp.expected_draft("REQ", "home-fail", "E1", actor())

    def test_real_aggregate_and_components_import_without_filling_actual(self):
        draft = self.draft()
        self.assertEqual([r["expected"] for r in draft["rows"]], ["20.780950000", "2033", "9783"])
        self.assertEqual([r["unit"] for r in draft["rows"]], ["%", "人", "人"])
        self.assertTrue(all(r["actual"] == "" for r in draft["rows"]))
        self.assertEqual(draft["expectedObservedAt"], self.stored["executed_at"])
        self.assertIn("B1", draft["dataVersion"])
        self.assertNotIn("asOf", draft)  # Retrieval time is not the business cutoff.

    def test_owner_and_identity_are_bound_in_lookup(self):
        self.draft()
        sql, params = self.conn.executions[0]
        self.assertIn("identity_id=%s", sql)
        self.assertEqual(params, ("E1", "REQ", "fixture-user", "fixture-identity"))
        with self.assertRaises(ApiError) as failure:
            self.draft(missing=True)
        self.assertEqual(failure.exception.status_code, 403)

    def test_other_scenario_and_dependency_metric_cannot_be_main_result(self):
        self.snapshot["scenarioId"] = "another"
        with self.assertRaises(ApiError): self.draft()
        self.snapshot["scenarioId"] = SCENE["id"]
        self.stored["metric_id"] = "O-02"
        with self.assertRaises(ApiError): self.draft()

    def test_definition_or_query_changes_reject_old_values(self):
        for key in ("scenarioChecksum", "requirementChecksum"):
            with self.subTest(key=key):
                previous = self.snapshot[key]
                self.snapshot[key] = "old"
                with self.assertRaises(ApiError): self.draft()
                self.snapshot[key] = previous
        self.stored["query_checksum"] = "old"
        with self.assertRaises(ApiError): self.draft()

    def test_application_reference_count_detail_or_unapproved_query_are_not_expected_metric(self):
        for changes in ({"layer": "application", "mappingMode": "reference_from_fact"}, {"kind": "count"},
                        {"kind": "detail"}, {"executionApproval": "blocked"}):
            with self.subTest(changes=changes):
                self.query = {**registered_query(id="Q", kind="calculate"), **changes}
                with self.assertRaises(ApiError): self.draft()

    def test_failed_truncated_and_multirow_results_cannot_be_scalar_import(self):
        initial = deepcopy(self.snapshot)
        for changes in ({"status": "error"}, {"truncated": True}, {"returnedRows": 2}, {"returnedRows": 0}):
            self.snapshot = {**initial, **changes}
            with self.subTest(changes=changes), self.assertRaises(ApiError): self.draft()

    def test_null_remains_missing_and_zero_remains_zero(self):
        self.snapshot["metrics"] = {"candidate_metric_value": None, "numerator": 0, "denominator": 0}
        self.assertEqual([r["expected"] for r in self.draft()["rows"]], ["", "0", "0"])

    def test_incomplete_ratio_is_not_silently_imported(self):
        del self.snapshot["metrics"]["denominator"]
        with self.assertRaises(ApiError): self.draft()

    def test_save_revalidates_value_unit_source_scope_and_all_components(self):
        draft = self.draft()
        with patch.object(imp, "expected_draft", return_value=draft):
            self.assertEqual(imp.validate_binding(draft, "REQ", "home-fail", actor()), "E1")
            for key in ("scope", "period", "dataVersion", "expectedSource", "expectedObservedAt", "startLayer"):
                with self.subTest(key=key), self.assertRaises(ApiError):
                    imp.validate_binding({**draft, key: "modified"}, "REQ", "home-fail", actor())
            for key in ("label", "unit", "expected", "expectedKey"):
                modified = deepcopy(draft); modified["rows"][0][key] = "modified"
                with self.subTest(key=key), self.assertRaises(ApiError):
                    imp.validate_binding(modified, "REQ", "home-fail", actor())
            for rows in (draft["rows"][:1], draft["rows"] + draft["rows"][:1]):
                with self.assertRaises(ApiError): imp.validate_binding({**draft, "rows": rows}, "REQ", "home-fail", actor())

    def test_actual_values_and_additional_manual_rows_remain_editable(self):
        draft = self.draft(); changed = deepcopy(draft)
        changed["rows"][0]["actual"] = "20.78"
        changed["rows"].append({"label": "人工说明", "unit": "项", "actual": "A", "expected": "B"})
        with patch.object(imp, "expected_draft", return_value=draft):
            self.assertEqual(imp.validate_binding(changed, "REQ", "home-fail", actor()), "E1")

    def test_record_attaches_imported_execution_even_if_client_omits_checkbox(self):
        draft = self.draft()
        row = {**self.stored, "result_json": json.dumps(self.snapshot)}
        conn = Connection({"rows": [row]})
        with patch.object(imp, "expected_draft", return_value=draft), patch.object(store, "connection", return_value=fake_connection(conn)):
            saved = store.record_save(record_body(judgment="条件不足", comparison={**observation(), **draft}), actor())
        self.assertEqual(saved["evidenceIds"], ["E1"])
        self.assertTrue(saved["current"])

    def test_import_endpoint_requires_execution_permission(self):
        service.app.dependency_overrides[auth.current_actor] = lambda: actor(scope="college")
        try:
            with TestClient(service.app) as client, patch.object(service, "expected_draft") as read:
                response = client.post(service.PREFIX + "/comparisons/from-execution", json={"requirementId": "REQ", "scenarioId": "home-fail", "executionId": "E1"})
                self.assertEqual(response.status_code, 403); read.assert_not_called()
        finally:
            service.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()

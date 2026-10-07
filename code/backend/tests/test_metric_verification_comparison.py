"""Scenario, manual observation and historical-evidence regression tests; no DB."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.api.envelope import ApiError
from backend.metric_verification import app as service, comparison, registry, store, auth
from backend.tests.test_metric_verification import actor, Connection, Cursor, fake_connection, registered_query


SCENE = {"id": "home-fail", "metricId": "O-10", "requirementId": "REQ", "status": "explicit"}


def observation(**changes):
    result = {
        "scope": "学院A", "period": "2025-2026-2", "asOf": "2026-09-29T10:00:00+08:00",
        "dataVersion": "源快照S1→事实B2→应用V3（人工核对批次对应）",
        "coverage": "display", "startLayer": "manual", "actualSource": "教学数据总览/学院A",
        "actualObservedAt": "2026-09-29T10:00:00+08:00", "expectedSource": "已核对的SQL结果记录",
        "expectedObservedAt": "2026-09-29T09:59:00+08:00", "comparisonRule": "精确一致",
        "rows": [{"label": "挂科学生率", "unit": "%", "actual": "4.20", "expected": "4.2", "difference": "999"}],
    }
    return {**result, **changes}


def record_body(**changes):
    return {"requirementId": "REQ", "metricId": "O-10", "scenarioId": "home-fail",
            "judgment": "符合", "comment": "同范围页面显示一致", "evidenceIds": [],
            "comparison": observation(), **changes}


class DifferenceTests(unittest.TestCase):
    def test_decimal_difference_replaces_client_result_without_float_rounding(self):
        value = observation(rows=[{"label": "GPA", "actual": "9007199254740993.3", "expected": "9007199254740993.1", "unit": "", "difference": "0"}])
        self.assertEqual(comparison.prepare(value, "有差异")["rows"][0]["difference"], "0.2")
        self.assertEqual(value["rows"][0]["difference"], "0")

    def test_missing_value_is_not_zero_or_conformance(self):
        value = observation(rows=[{"label": "人数", "actual": "", "expected": "0", "unit": "人"}])
        self.assertIsNone(comparison.prepare(value, "条件不足")["rows"][0]["difference"])
        with self.assertRaises(ApiError):
            comparison.prepare(value, "符合")

    def test_exact_rule_checks_all_components_not_only_the_equal_rate(self):
        value = observation(rows=[{"label": "比例", "actual": "50", "expected": "50"},
                                  {"label": "分母", "actual": "20", "expected": "40"}])
        with self.assertRaises(ApiError):
            comparison.prepare(value, "符合")

    def test_ranking_order_is_not_reduced_to_total_count(self):
        value = observation(rows=[{"label": "成员及顺序", "actual": "课程A\n课程B", "expected": "课程B\n课程A"}])
        self.assertIn("内容不同", comparison.prepare(value, "有差异")["rows"][0]["difference"])
        with self.assertRaises(ApiError):
            comparison.prepare(value, "符合")

    def test_full_chain_needs_source_and_snapshot_evidence(self):
        for changes in ({"coverage": "full_chain"}, {"coverage": "full_chain", "startLayer": "source", "dataVersion": ""}):
            with self.subTest(changes=changes), self.assertRaises(ApiError):
                comparison.prepare(observation(**changes), "符合")

    def test_conformance_requires_unit_at_server_boundary(self):
        with self.assertRaises(ApiError):
            comparison.prepare(observation(rows=[{"label": "人数", "actual": "10", "expected": "10", "unit": ""}]), "符合")


class ScenarioStorageTests(unittest.TestCase):
    def setUp(self):
        self.scene = patch.object(registry, "scenario", return_value=SCENE).start()
        patch.object(registry, "scenario_checksum", return_value="scene-current").start()
        patch.object(registry, "requirement_checksum", return_value="req-current").start()
        self.addCleanup(patch.stopall)

    def test_manual_real_comparison_saved_and_loaded_without_schema_migration(self):
        conn = Connection({})
        with patch.object(store, "connection", return_value=fake_connection(conn)):
            saved = store.record_save(record_body(), actor())
        self.assertTrue(saved["current"])
        self.assertEqual(saved["comparison"]["rows"][0]["difference"], "0.00")
        payload = json.loads(conn.executions[0][1][5])
        self.assertEqual(payload["scenarioId"], SCENE["id"])
        rows = [{"record_id": saved["id"], "requirement_id": "REQ", "metric_id": "O-10", "judgment": "符合",
                 "comment_text": saved["comment"], "evidence_json": json.dumps(payload),
                 "created_at": saved["createdAt"], "created_by": "fixture-user"}]
        loaded = store.records_from_rows(rows)["items"][0]
        self.assertEqual(loaded["comparison"], saved["comparison"])
        with patch.object(registry, "scenario_checksum", return_value="changed"):
            self.assertFalse(store.records_from_rows(rows)["items"][0]["current"])

    def test_legacy_array_stays_readable_but_is_not_current_comparison(self):
        row = {"record_id": "OLD", "requirement_id": "REQ", "metric_id": "O-10", "judgment": "符合",
               "comment_text": "旧意见", "evidence_json": '["E1"]', "created_at": "old", "created_by": "fixture-user"}
        item = store.records_from_rows([row])["items"][0]
        self.assertEqual(item["evidenceIds"], ["E1"])
        self.assertFalse(item["current"])
        self.assertIsNone(item["comparison"])

    def test_other_scenario_or_legacy_execution_cannot_be_attached(self):
        for scenario_id in (None, "other-scene"):
            evidence = {"metric_id": "O-10", "result_json": json.dumps({"status": "success", "scenarioId": scenario_id})}
            conn = Connection({"rows": [evidence]})
            with patch.object(store, "connection", return_value=fake_connection(conn)), self.assertRaises(ApiError) as error:
                store.record_save(record_body(evidenceIds=["E"]), actor())
            self.assertEqual(error.exception.status_code, 422)
            self.assertEqual(len(conn.executions), 1)

    def test_pending_calculation_cannot_be_declared_verified(self):
        self.scene.return_value = {**SCENE, "status": "pending"}
        with patch.object(store, "connection") as connect, self.assertRaises(ApiError):
            store.record_save(record_body(comparison=observation(coverage="fact_application")), actor())
        connect.assert_not_called()

    def test_same_scene_different_period_evidence_does_not_pass(self):
        base = {"metric_id": "O-10", "query_id": "Q", "query_version": "1.0.0", "query_checksum": "fixture-checksum",
                "result_json": json.dumps({"status": "success", "scenarioId": SCENE["id"],
                                           "scenarioChecksum": "scene-current", "requirementChecksum": "req-current"})}
        conn = Connection()
        cursor = Cursor(conn, {})
        cursor.fetchone = Mock(side_effect=[{**base, "parameters_json": json.dumps({"semester_id": period})} for period in ("T1", "T2")])
        with patch.object(conn, "cursor", return_value=cursor), patch.object(store, "connection", return_value=fake_connection(conn)), patch.object(registry, "find_query", return_value=registered_query()), self.assertRaises(ApiError) as error:
            store.record_save(record_body(evidenceIds=["E1", "E2"]), actor())
        self.assertIn("范围不同", error.exception.msg)

    def test_recent_records_are_limited_to_user_and_identity(self):
        conn = Connection({"rows": []})
        with patch.object(store, "connection", return_value=fake_connection(conn)):
            self.assertEqual(store.record_recent(actor()), {"items": []})
        sql, values = conn.executions[0]
        self.assertIn("created_by=%s AND identity_id=%s", sql)
        self.assertEqual(values, ("fixture-user", "fixture-identity"))


class ScenarioApiTests(unittest.TestCase):
    def setUp(self):
        self.current = actor()
        service.app.dependency_overrides[auth.current_actor] = lambda: self.current
        self.addCleanup(service.app.dependency_overrides.clear)
        self.client = TestClient(service.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def test_preview_is_real_calculation_and_never_saves(self):
        with patch.object(store, "record_save") as save:
            response = self.client.post(service.PREFIX + "/comparisons/preview", json=observation())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["rows"][0]["difference"], "0.00")
        save.assert_not_called()

    def test_manual_comparison_is_allowed_without_an_internal_query(self):
        with patch.object(registry, "requirement", return_value={"metricIds": ["O-10"]}), patch.object(registry, "scenario", return_value=SCENE), patch.object(store, "record_save", side_effect=lambda body, _: body):
            response = self.client.post(service.PREFIX + "/records", json=record_body())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["comparison"]["rows"][0]["difference"], "0.00")

    def test_definition_reader_can_preview_and_read_only_own_manual_records(self):
        self.current = actor(actions=["definition.read"], scope="college")
        response = self.client.post(service.PREFIX + "/comparisons/preview", json=observation())
        self.assertEqual(response.status_code, 200)
        with patch.object(store, "record_recent", return_value={"items": []}) as recent:
            response = self.client.get(service.PREFIX + "/records/recent")
        self.assertEqual(response.status_code, 200)
        recent.assert_called_once_with(self.current)


if __name__ == "__main__":
    unittest.main()

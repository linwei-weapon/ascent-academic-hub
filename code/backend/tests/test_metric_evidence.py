"""Evidence boundaries: consistent inputs, no early reveal, immutable owned proof."""
from contextlib import contextmanager
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, MagicMock, patch

from backend.api.envelope import ApiError
from backend.metric_verification import evidence, registry
from backend.metric_verification.config import DatabaseConfig


OWNER = {"username": "test-owner", "identity_id": "test-identity"}
CONFIG = DatabaseConfig("mysql", "fixture", 3306, "fixture", "fixture", "fixture")


def query(identifier, kind):
    return {"id": identifier, "metricId": "M", "layer": "fact", "dialect": "mysql", "kind": kind,
            "sql": "SELECT :student_id AS student_id", "checksum": "registered", "executionApproval": "documented",
            "parameters": [{"name": "student_id", "required": True, "type": "string"}],
            "requiredColumns": {"ACT_SAMPLE": ["student_id"]},
            "resultContract": {"columns": [{"key": "value", "dataType": "decimal"}],
                               "completeness": {"totalCountQueryId": "count"}}}


@contextmanager
def fake_connection(conn, *args, **kwargs):
    yield conn


def saved_evidence():
    value = {"id": "E", "executionId": "E", "caseId": "C", "mappingRevisionId": "R", "metricId": "M",
             "capture": {"consistency": "verified"}, "scope": {"coverage": "bounded_sample"},
             "datasets": [{"rows": [{"student_id": "sample", "grade": "1.10"}]}],
             "testedResult": {"rows": [{"value": "1.10"}], "columns": [{"key": "value", "dataType": "decimal"}],
                              "complete": True, "truncated": False}}
    value["integrity"] = {"contentHash": evidence.content_hash(value), "readbackVerified": True}
    return value


class CaptureTests(unittest.TestCase):
    def capture(self, count=1, truncated=False):
        queries = {name: query(name, kind) for name, kind in (("calc", "calculate"), ("raw", "detail"), ("count", "count"))}
        package = {"environmentId": "test", "metrics": [{"id":"M", "definition":{"precision":{"comparison":None}}}], "validationCases": [{"id": "C", "metricId": "M",
                    "execution": {"queryId": "calc"}, "samplePlan": {"inputDatasets": [{"queryId": "raw", "countQueryId": "count"}]}}]}
        conn = Mock()
        def read(actual_conn, q, params, engine, limit, **kwargs):
            self.assertIs(actual_conn, conn)
            self.assertTrue(kwargs["precise"])
            if q["kind"] == "count":
                return {"recordCount": count, "truncated": False, "returnedRows": 1, "columns": ["matched_records"], "rows": [{"matched_records": count}]}
            rows = [{"student_id": "sample"}] if q["kind"] == "detail" else [{"value": "1.10"}]
            return {"rows": rows, "columns": list(rows[0]), "returnedRows": len(rows), "truncated": truncated}
        with patch.object(registry, "current_package", return_value=package), patch.object(registry, "current_revision_id", return_value="R"), patch.object(registry, "find_query", side_effect=lambda name: queries[name]), patch.object(evidence, "database_config", return_value=CONFIG), patch.object(evidence, "connection", side_effect=lambda *a, **kw: fake_connection(conn)) as connect, patch.object(evidence, "assert_snapshot_tables"), patch.object(evidence, "execute_read", side_effect=read) as reads:
            result = evidence.capture_case(queries["calc"], {"student_id": "sample"}, "C", {"id": "E"})
        connect.assert_called_once_with("fact", consistent=True)
        self.assertEqual([call.args[1]["id"] for call in reads.call_args_list], ["count", "raw", "calc"])
        return result

    def test_one_read_transaction_keeps_exact_input_and_output(self):
        result = self.capture()
        self.assertEqual(result["testedResult"]["rows"], [{"value": "1.10"}])
        self.assertEqual(result["integrity"]["contentHash"], evidence.content_hash(result))
        self.assertEqual(result["scope"]["coverage"], "bounded_sample")

    def test_large_or_truncated_input_never_becomes_valid_evidence(self):
        for arguments in ({"count": 51}, {"truncated": True}, {"count": 2}):
            with self.subTest(arguments=arguments), self.assertRaises(ApiError):
                self.capture(**arguments)

    def test_view_or_nontransactional_table_does_not_claim_consistency(self):
        conn = MagicMock(); cur = conn.cursor.return_value.__enter__.return_value
        for engine, kind in (("MyISAM", "BASE TABLE"), (None, "VIEW")):
            cur.fetchall.return_value = [{"TABLE_NAME": "ACT_SAMPLE", "ENGINE": engine, "TABLE_TYPE": kind}]
            with self.subTest(engine=engine), self.assertRaises(ApiError):
                evidence.assert_snapshot_tables(conn, [query("calc", "calculate")], "mysql")


class RetentionTests(unittest.TestCase):
    def test_frozen_tolerance_only_applies_to_matching_result_unit(self):
        sample = saved_evidence()
        sample['comparisonPolicy'] = {'mode':'absolute', 'tolerance':'0.000001', 'unit':'%'}
        sample['testedResult']['columns'][0].update(unit='%',semanticRole='metric_value')
        expected = {'rows':[{'value':'1.1000005'}], 'resultKnownBeforeCalculation':False}
        self.assertEqual(evidence.compare_expected(sample, expected)['status'], 'match')
        for update in ({'semanticRole':'denominator'}, {'unit':'人'}, {'dataType':'integer'}):
            changed=deepcopy(sample); changed['testedResult']['columns'][0].update(update)
            self.assertEqual(evidence.compare_expected(changed, expected)['status'], 'different')
        sample['resultRowKey']=['value']
        self.assertEqual(evidence.compare_expected(sample, expected)['status'], 'different')

    def test_original_result_is_not_visible_before_expectation(self):
        original = saved_evidence()
        result = evidence.public_evidence(original)
        self.assertIsNone(result["testedResult"])
        self.assertEqual(result["resultDisclosure"], "withheld")
        self.assertEqual(result["validation"]["status"], "pending")
        self.assertEqual(original["testedResult"]["rows"], [{"value": "1.10"}])

    def test_exact_decimal_and_prior_result_knowledge_are_respected(self):
        original = saved_evidence()
        self.assertEqual(evidence.compare_expected(original, {"rows": [{"value": "1.100"}]})["status"], "match")
        self.assertEqual(evidence.compare_expected(original, {"rows": [{"value": "1.10000000001"}]})["status"], "different")
        self.assertEqual(evidence.compare_expected(original, {"rows": [{"value": "1.10"}], "resultKnownBeforeCalculation": True})["status"], "inconclusive")

    def test_owned_read_requires_saved_content_and_matching_hash(self):
        original = saved_evidence()
        conn = MagicMock(); cur = conn.cursor.return_value.__enter__.return_value
        with patch.object(evidence, "connection", side_effect=lambda *a, **kw: fake_connection(conn)):
            cur.fetchone.return_value = None
            with self.assertRaises(ApiError): evidence.get_evidence("E", OWNER)
            self.assertEqual(cur.execute.call_args.args[1], ("E", "test-owner", "test-identity"))
            changed = deepcopy(original); changed["datasets"][0]["rows"][0]["grade"] = "9"
            cur.fetchone.return_value = {"evidence_json": json.dumps(changed)}
            with self.assertRaises(ApiError): evidence.get_evidence("E", OWNER)

    def test_expectation_is_write_once_and_result_reveals_only_after_save(self):
        original = saved_evidence()
        row = {"evidence_json": json.dumps(original), "independent_expectation_json": None,
               "result_json": json.dumps({"resultDisclosure": "withheld", "metrics": {}})}
        conn = MagicMock(); cur = conn.cursor.return_value.__enter__.return_value
        body = {"method": "independent", "basisRef": "requirement", "derivation": "from stored input",
                "rows": [{"value": "1.10"}], "inputContentHash": original["integrity"]["contentHash"],
                "resultKnownBeforeCalculation": False}
        with patch.object(evidence, "connection", side_effect=lambda *a, **kw: fake_connection(conn)), patch.object(evidence, "_owned_row", return_value=(row, original)):
            result = evidence.save_expectation("E", body, OWNER)
            self.assertEqual(result["resultDisclosure"], "revealed")
            self.assertEqual(result["validation"]["status"], "match")
            saved = json.loads(cur.execute.call_args.args[1][0])
            self.assertEqual(saved["determinedByRef"], OWNER["username"])
            row["independent_expectation_json"] = json.dumps(saved)
            cur.reset_mock()
            evidence.save_expectation("E", body, OWNER)
            cur.execute.assert_not_called()
            with self.assertRaises(ApiError):
                evidence.save_expectation("E", {**body, "rows": [{"value": "2"}]}, OWNER)


if __name__ == "__main__":
    unittest.main()

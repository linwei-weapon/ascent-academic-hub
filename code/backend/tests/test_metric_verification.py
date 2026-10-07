"""Security and result-contract tests for the metric verification prototype.

These tests use explicit fake identities, connections and result sets. They do
not connect to the test environment, inspect credentials or mutate a database.
Run from code/: backend/.venv/Scripts/python.exe -m unittest
backend.tests.test_metric_verification -v
"""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import io
import hashlib
import json
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient

from backend.api.envelope import ApiError
from backend.metric_verification import auth, database, options, registry, store
from backend.metric_verification import app as service
from backend.metric_verification.config import DatabaseConfig


CONFIG = DatabaseConfig("mysql", "fixture.invalid", 3306, "fixture", "fixture", "fixture")


def actor(*, actions=None, scope="all", authorized=True, identity="fixture-identity"):
    return {
        "username": "fixture-user", "name": "测试用户", "identity_id": identity, "menus": [],
        "permission_context": {
            "authorized": authorized, "activeIdentityId": identity,
            "actionPermissions": ["system.manage"] if actions is None else actions,
            "detailScope": {"type": scope}, "scopeFingerprint": "fixture-scope",
        },
    }


def payload(**kwargs):
    value = actor(**kwargs)
    return {"username": value["username"], "name": value["name"],
            "activeIdentityId": value["identity_id"], "permissionContext": value["permission_context"], "menus": []}


def registered_query(**overrides):
    query = {
        "id": "O-10-fact-count-mysql", "metricId": "O-10", "layer": "fact", "kind": "count",
        "version": "1.0.0", "checksum": "fixture-checksum", "dialect": "mysql",
        "executionApproval": "documented", "requiresServerScope": True,
        "sql": "SELECT COUNT(*) AS matched_records FROM ACT_STUDENT s WHERE s.organization_id = :organization_id",
        "parameters": [{"name": "organization_id", "label": "学院", "type": "string", "required": True}],
        "requiredTables": ["ACT_STUDENT"], "requiredColumns": {"ACT_STUDENT": ["student_id", "organization_id"]},
    }
    query.update(overrides)
    return query


class Cursor:
    def __init__(self, owner, result):
        self.owner, self.result = owner, result
        self.description = [(name,) for name in result.get("columns", [])]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, parameters=None):
        self.owner.executions.append((sql, parameters))

    def fetchall(self):
        return self.result.get("rows", [])

    def fetchmany(self, count):
        return self.result.get("rows", [])[:count]

    def fetchone(self):
        rows = self.result.get("rows", [])
        return rows[0] if rows else None


class Connection:
    def __init__(self, *results):
        self.results = list(results)
        self.executions = []

    def cursor(self):
        if not self.results:
            raise AssertionError("Unexpected database operation")
        return Cursor(self, self.results.pop(0))


@contextmanager
def fake_connection(conn):
    yield conn


def mysql_metadata(table="act_student", fields=("student_id", "organization_id")):
    return {"rows": [{"TABLE_NAME": table, "COLUMN_NAME": field} for field in fields]}


class PermissionTests(unittest.TestCase):
    def test_execution_requires_all_three_authorization_conditions(self):
        self.assertTrue(auth.can_execute(actor()))
        for current in [actor(authorized=False), actor(actions=["definition.read"]),
                        actor(actions=["definition.manage"]), actor(scope="college"),
                        actor(scope="class"), actor(scope="staff_relation"), {"role_id": "admin"}, {}]:
            with self.subTest(current=current):
                self.assertFalse(auth.can_execute(current))
                with self.assertRaises(ApiError) as failure:
                    auth.require_execution(current)
                self.assertEqual(failure.exception.status_code, 403)

    def test_definition_read_can_inspect_but_cannot_execute(self):
        current = auth.normalize_actor(payload(actions=["definition.read"], scope="college"))
        self.assertFalse(auth.can_execute(current))
        menu = auth.menu_for_actor(current)
        self.assertTrue(menu["authorized"])
        self.assertFalse(menu["canExecute"])
        self.assertFalse(menu["mappingManage"])
        self.assertEqual(menu["menu"]["title"], "指标核验")

    def test_access_permission_is_independent_of_active_mapping(self):
        self.addCleanup(service.app.dependency_overrides.clear)
        client = TestClient(service.app, raise_server_exceptions=False)
        with patch.object(registry, "revision_scope", side_effect=AssertionError("must not read active mapping")):
            for actions, expected in [(["definition.read"], False), (["definition.manage"], True), (["system.manage"], True)]:
                service.app.dependency_overrides[auth.current_actor] = lambda selected=actions: actor(actions=selected)
                response = client.get(service.PREFIX + "/access?moduleId=ai-briefing", headers={"Authorization": "Bearer fixture"})
                self.assertEqual(200, response.status_code)
                self.assertEqual(expected, response.json()["data"]["mappingManage"])

    def test_bootstrap_head_read_is_only_relaxed_for_actual_management(self):
        self.addCleanup(service.app.dependency_overrides.clear)
        client = TestClient(service.app, raise_server_exceptions=False)
        def initial_head(*, allow_empty=False):
            if not allow_empty:
                raise ApiError("当前作用域没有生效映射版本", status_code=503)
            return {"revisionId": None, "moduleId": "ai-briefing"}
        with patch.object(service.mapping_store, "get_head", side_effect=initial_head):
            service.app.dependency_overrides[auth.current_actor] = lambda: actor(actions=["definition.read"])
            self.assertEqual(503, client.get(service.PREFIX + "/mapping/head?moduleId=ai-briefing").status_code)
            service.app.dependency_overrides[auth.current_actor] = lambda: actor(actions=["definition.manage"])
            response = client.get(service.PREFIX + "/mapping/head?moduleId=ai-briefing")
            self.assertEqual(200, response.status_code)
            self.assertIsNone(response.json()["data"]["revisionId"])

    def test_missing_context_action_or_active_identity_fails_closed(self):
        mismatched = payload()
        mismatched["permissionContext"]["activeIdentityId"] = "another-identity"
        for value in [{"username": "admin"}, payload(actions=[]), payload(authorized=False), payload(identity=None), mismatched]:
            with self.subTest(value=value):
                with self.assertRaises(ApiError):
                    auth.normalize_actor(value)

    def test_bearer_required_before_contacting_auth_server(self):
        with patch.object(auth, "urlopen") as transport:
            with self.assertRaises(ApiError) as failure:
                auth.current_actor(authorization="", identity="fixture-identity")
            self.assertEqual(failure.exception.status_code, 401)
            transport.assert_not_called()

    def test_current_identity_is_forwarded_and_mismatch_denied(self):
        response = io.BytesIO(json.dumps({"code": 0, "data": payload()}).encode())
        with patch.object(auth, "authentication_origin", return_value="https://auth.fixture.invalid"), patch.object(auth, "urlopen", return_value=response) as transport:
            current = auth.current_actor("Bearer fixture-token", "fixture-identity")
        self.assertEqual(current["identity_id"], "fixture-identity")
        request = transport.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer fixture-token")
        self.assertEqual(request.get_header("X-active-identity"), "fixture-identity")
        response = io.BytesIO(json.dumps({"code": 0, "data": payload()}).encode())
        with patch.object(auth, "authentication_origin", return_value="https://auth.fixture.invalid"), patch.object(auth, "urlopen", return_value=response):
            with self.assertRaises(ApiError) as failure:
                auth.current_actor("Bearer fixture-token", "different-identity")
        self.assertEqual(failure.exception.status_code, 403)

    def test_auth_service_unavailable_does_not_allow_local_fallback(self):
        with patch.object(auth, "authentication_origin", return_value="https://auth.fixture.invalid"), patch.object(auth, "urlopen", side_effect=URLError("fixture-network-error")):
            with self.assertRaises(ApiError) as failure:
                auth.current_actor("Bearer fixture-token", "fixture-identity")
        self.assertEqual(failure.exception.status_code, 503)


class TransientAuthenticationTests(unittest.TestCase):
    def test_one_transient_failure_revalidates_remote_identity(self):
        response = io.BytesIO(json.dumps({"code": 0, "data": payload()}).encode())
        with patch.object(auth, "authentication_origin", return_value="https://auth.fixture.invalid"), patch.object(auth, "urlopen", side_effect=[URLError("temporary"), response]) as transport:
            self.assertEqual(auth.current_actor("Bearer fixture-token", "fixture-identity")["identity_id"], "fixture-identity")
        self.assertEqual(transport.call_count, 2)

    def test_auth_rejection_is_never_retried(self):
        for status in (401, 403):
            with patch.object(auth, "authentication_origin", return_value="https://auth.fixture.invalid"), patch.object(auth, "urlopen", side_effect=HTTPError("https://auth.fixture.invalid", status, "denied", {}, None)) as transport:
                with self.assertRaises(ApiError) as failure:
                    auth.current_actor("Bearer fixture-token", "fixture-identity")
                self.assertEqual(failure.exception.status_code, status)
                self.assertEqual(transport.call_count, 1)

    def test_retry_exhaustion_still_fails_closed(self):
        with patch.object(auth, "authentication_origin", return_value="https://auth.fixture.invalid"), patch.object(auth, "urlopen", side_effect=TimeoutError()) as transport:
            with self.assertRaises(ApiError) as failure:
                auth.current_actor("Bearer fixture-token", "fixture-identity")
        self.assertEqual(failure.exception.status_code, 503)
        self.assertEqual(transport.call_count, 2)


class BindingTests(unittest.TestCase):
    def test_required_unknown_and_undeclared_placeholders_rejected(self):
        cases = [(registered_query(), {}), (registered_query(), {"organization_id": ""}),
                 (registered_query(), {"organization_id": "A", "arbitrary_sql": "SELECT 1"}),
                 (registered_query(sql="SELECT :different FROM ACT_STUDENT"), {"organization_id": "A"})]
        for query, values in cases:
            with self.subTest(values=values, sql=query["sql"]):
                with self.assertRaises(ApiError) as failure:
                    database.bind_parameters(query, values)
                self.assertEqual(failure.exception.status_code, 422)

    def test_optional_blank_becomes_null_without_implying_authorization(self):
        query = registered_query(parameters=[{"name": "organization_id", "type": "string", "required": False}])
        self.assertEqual(database.bind_parameters(query, {"organization_id": ""}), {"organization_id": None})
        self.assertFalse(auth.can_execute(actor(scope="college")))

    def test_injection_text_is_a_bound_value_not_query_text(self):
        attack = "A' OR 1=1 --"
        query = registered_query()
        params = database.bind_parameters(query, {"organization_id": attack})
        conn = Connection(mysql_metadata(), {"columns": ["matched_records"], "rows": [{"matched_records": 0}]})
        database.execute_read(conn, query, params, "mysql", 10)
        sql, passed = conn.executions[-1]
        self.assertNotIn(attack, sql)
        self.assertIn("%(organization_id)s", sql)
        self.assertEqual(passed["organization_id"], attack)

    def test_integer_number_and_length_boundaries(self):
        query = registered_query(sql="SELECT :v FROM ACT_STUDENT", parameters=[{"name": "v", "type": "integer", "required": True}])
        for value in [True, 1.2, "1 OR 1=1", [], {}]:
            with self.subTest(value=value):
                with self.assertRaises(ApiError):
                    database.bind_parameters(query, {"v": value})
        self.assertEqual(database.bind_parameters(query, {"v": "-12"}), {"v": -12})
        query["parameters"][0]["type"] = "number"
        for value in ["nan", "Infinity", "-Infinity", {}, []]:
            with self.subTest(value=value):
                with self.assertRaises(ApiError):
                    database.bind_parameters(query, {"v": value})
        query["parameters"][0]["type"] = "string"
        with self.assertRaises(ApiError):
            database.bind_parameters(query, {"v": "x" * 201})


class ReadOnlySqlTests(unittest.TestCase):
    def test_registered_select_and_cte_are_allowed(self):
        for sql in ["SELECT COUNT(*) FROM ACT_STUDENT", "WITH x AS (SELECT student_id FROM ACT_STUDENT) SELECT COUNT(*) FROM x"]:
            self.assertEqual(database.validate_sql(sql), sql)

    def test_writes_multistatement_locks_file_and_delay_operations_rejected(self):
        for sql in ["UPDATE ACT_STUDENT SET name='x'", "SELECT 1; DELETE FROM ACT_STUDENT",
                    "WITH x AS (DELETE FROM ACT_STUDENT) SELECT 1", "SELECT * FROM ACT_STUDENT FOR UPDATE",
                    "SELECT * FROM ACT_STUDENT LOCK IN SHARE MODE", "SELECT 1 INTO OUTFILE '/tmp/x'",
                    "SELECT LOAD_FILE('/tmp/x')", "SELECT SLEEP(10)", "SELECT BENCHMARK(1000000,1)"]:
            with self.subTest(sql=sql):
                with self.assertRaises(ApiError):
                    database.validate_sql(sql)

    def test_comments_are_removed_before_execution(self):
        clean = database.validate_sql("SELECT 1 /* comment */ -- another comment\n")
        self.assertNotIn("comment", clean)

    def test_mysql_read_connection_sets_read_only_and_always_rolls_back(self):
        conn = Connection({})
        conn.rollback, conn.close, conn.commit = Mock(), Mock(), Mock()
        driver = SimpleNamespace(connect=Mock(return_value=conn), cursors=SimpleNamespace(DictCursor=object()))
        with patch.dict("sys.modules", {"pymysql": driver}), patch.object(database, "database_config", return_value=CONFIG), patch.object(database, "query_timeout", return_value=5):
            with database.connection("fact") as opened:
                self.assertIs(opened, conn)
        self.assertEqual([sql for sql, _ in conn.executions], ["SET SESSION MAX_EXECUTION_TIME = %s", "START TRANSACTION READ ONLY"])
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_source_write_is_denied_before_driver_connection(self):
        driver = SimpleNamespace(connect=Mock(), cursors=SimpleNamespace(DictCursor=object()))
        with patch.dict("sys.modules", {"pymysql": driver}), patch.object(database, "database_config", return_value=CONFIG):
            with self.assertRaises(ApiError) as failure:
                with database.connection("source", write=True):
                    self.fail("Source write must not yield a connection")
        self.assertEqual(failure.exception.status_code, 403)
        driver.connect.assert_not_called()


class SchemaAndResultsTests(unittest.TestCase):
    def test_mysql_table_case_is_mapped_without_weakening_column_requirements(self):
        conn = Connection(mysql_metadata("act_student"))
        self.assertEqual(database.schema_mapping(conn, registered_query(), "mysql"), {"ACT_STUDENT": "act_student"})
        self.assertIn("TABLE_SCHEMA=DATABASE()", conn.executions[0][0])

    def test_missing_table_column_ambiguous_case_and_missing_metadata_rejected(self):
        cases = [({}, registered_query()), (mysql_metadata(fields=("student_id",)), registered_query()),
                 ({"rows": mysql_metadata()["rows"] + mysql_metadata("ACT_STUDENT")["rows"]}, registered_query()),
                 (mysql_metadata(), registered_query(requiredColumns={}))]
        for metadata, query in cases:
            with self.subTest(metadata=metadata):
                with self.assertRaises(ApiError):
                    database.schema_mapping(Connection(metadata), query, "mysql")

    def test_count_returns_matched_records_not_one_aggregate_row(self):
        conn = Connection(mysql_metadata(), {"columns": ["matched_records"], "rows": [{"matched_records": Decimal("427")}]})
        result = database.execute_read(conn, registered_query(), {"organization_id": "A"}, "mysql", 50)
        self.assertEqual(result["recordCount"], 427)
        self.assertEqual(result["returnedRows"], 1)
        self.assertFalse(result["truncated"])
        self.assertIn("FROM `act_student`", conn.executions[-1][0])

    def test_oracle_uppercase_alias_preserves_real_record_count(self):
        conn = Connection({"rows": [("ACT_STUDENT", "STUDENT_ID"), ("ACT_STUDENT", "ORGANIZATION_ID")]},
                          {"columns": ["MATCHED_RECORDS"], "rows": [(427,)]})
        result = database.execute_read(conn, registered_query(dialect="oracle"), {"organization_id": "A"}, "oracle", 50)
        self.assertEqual(result["recordCount"], 427)
        self.assertEqual(result["returnedRows"], 1)
        self.assertIn(":organization_id", conn.executions[-1][0])

    def test_detail_limit_is_separate_from_complete_record_count(self):
        rows = [{"student_id": f"S{n}"} for n in range(4)]
        conn = Connection(mysql_metadata(), {"columns": ["student_id"], "rows": rows})
        result = database.execute_read(conn, registered_query(kind="detail", sql="SELECT s.student_id FROM ACT_STUDENT s WHERE s.organization_id=:organization_id ORDER BY s.student_id LIMIT 100"), {"organization_id": "A"}, "mysql", 3)
        self.assertEqual(result["returnedRows"], 3)
        self.assertIsNone(result["recordCount"])
        self.assertTrue(result["truncated"])

    def test_sql_limit_reached_is_disclosed_even_when_api_limit_is_equal(self):
        rows = [{"student_id": f"S{n}"} for n in range(100)]
        conn = Connection(mysql_metadata(), {"columns": ["student_id"], "rows": rows})
        result = database.execute_read(conn, registered_query(kind="detail", sql="SELECT s.student_id FROM ACT_STUDENT s LIMIT 100"), {}, "mysql", 100)
        self.assertEqual(result["returnedRows"], 100)
        self.assertTrue(result["truncated"])
        self.assertIsNone(result["recordCount"])

    def test_schema_failure_happens_before_business_select(self):
        conn = Connection({"rows": []})
        with self.assertRaises(ApiError):
            database.execute_read(conn, registered_query(), {"organization_id": "A"}, "mysql", 10)
        self.assertEqual(len(conn.executions), 1)


class RegistryTests(unittest.TestCase):
    def test_actual_registry_links_all_requirement_metric_ids(self):
        catalog = registry.catalog()
        sql_catalog = registry.queries_document()
        metric_ids = {metric["id"] for metric in catalog["metrics"]}
        self.assertEqual(metric_ids, {m["metricId"] for m in sql_catalog["metrics"]})
        for req in catalog["requirements"]:
            self.assertTrue(set(req["metricIds"]) <= metric_ids, req["id"])

    def test_registered_sql_file_loads_and_checksum_matches(self):
        query = registry.find_query("O-10-fact-count-mysql")
        self.assertEqual(query["metricId"], "O-10")
        self.assertEqual(query["layer"], "fact")
        self.assertEqual(len(query["checksum"]), 64)
        self.assertIn("matched_records", query["sql"])

    def test_every_registered_query_passes_runtime_file_and_read_only_validation(self):
        seen = set()
        document = registry.queries_document()
        for metric in document["metrics"]:
            for layer in metric["layers"]:
                for original in layer["queries"]:
                    with self.subTest(query_id=original["id"]):
                        self.assertNotIn(original["id"], seen)
                        seen.add(original["id"])
                        loaded = registry.load_sql(original)
                        self.assertEqual(loaded["sql"].strip(), original["sql"].strip())
                        self.assertEqual(len(loaded["checksum"]), 64)
                        self.assertIn(loaded["executionApproval"], {"documented", "blocked"})
        self.assertGreater(len(seen), 0)

    def test_sql_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(registry, "ASSETS", Path(directory)):
                with self.assertRaises(ApiError):
                    registry.load_sql({"sqlFile": "../../outside.sql", "sql": "SELECT 1"})

    def test_sql_file_and_inline_registration_cannot_diverge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sql").mkdir()
            (root / "sql" / "fixture.sql").write_text("SELECT 1", encoding="utf-8")
            with patch.object(registry, "ASSETS", root):
                with self.assertRaises(ApiError) as failure:
                    registry.load_sql({"sqlFile": "sql/fixture.sql", "sql": "SELECT 2"})
            self.assertEqual(failure.exception.status_code, 409)

    def test_no_calculation_becomes_executable_merely_from_a_configured_database(self):
        manifest = {"metrics": [{"metricId": "O-10", "layers": [{"id": "fact", "queries": [
            registered_query(), registered_query(id="blocked", kind="calculate", executionApproval="blocked", blockedReason="缺少规则依据")]}]}]}
        with patch.object(registry, "database_config", return_value=CONFIG), patch.object(registry, "queries_document", return_value=manifest):
            metric = registry.metric_queries("O-10", allow_execute=True)
        for layer in metric["layers"]:
            for query in layer["queries"]:
                if query["kind"] == "calculate":
                    self.assertFalse(query["executable"])
                    self.assertTrue(query["blockedReason"])
                else:
                    self.assertTrue(query["executable"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.current = actor()
        service.app.dependency_overrides[auth.current_actor] = lambda: self.current
        self.client = TestClient(service.app, raise_server_exceptions=False)
        self.addCleanup(service.app.dependency_overrides.clear)
        self.addCleanup(self.client.close)
        self.prefix = service.PREFIX

    def post_execute(self, **body):
        data = {"requirementId": "REQ", "parameters": {"organization_id": "A"}, "sqlVersion": "1.0.0"}
        data.update(body)
        return self.client.post(self.prefix + "/queries/O-10-fact-count-mysql/execute", json=data)

    def test_definition_reader_cannot_execute_sql_but_can_keep_owned_manual_records(self):
        self.current = actor(actions=["definition.read"], scope="college")
        with patch.object(service, "connection") as connect, patch.object(registry, "requirement", return_value={"id": "REQ", "metricIds": ["O-10"]}), patch.object(store, "record_list", return_value={"items": []}) as read_records, patch.object(store, "record_save", side_effect=lambda body, owner: {**body, "owner": owner["username"]}) as save_record:
            responses = [self.post_execute(), self.client.get(self.prefix + "/schema/fact"),
                         self.client.get(self.prefix + "/requirements/REQ/records"),
                         self.client.post(self.prefix + "/records", json={"requirementId": "REQ", "judgment": "条件不足", "comment": "test"}),
                         self.client.get(self.prefix + "/queries/Q/options?requirementId=REQ"),
                         self.client.get(self.prefix + "/requirements/REQ/executions")]
        self.assertEqual([r.status_code for r in responses], [403, 403, 200, 200, 403, 403])
        self.assertEqual(read_records.call_args.args[1], self.current)
        self.assertEqual(save_record.call_args.args[1], self.current)
        connect.assert_not_called()

    def test_query_must_belong_to_selected_requirement(self):
        with patch.object(registry, "requirement", return_value={"id": "REQ", "metricIds": ["O-01"]}), patch.object(registry, "find_query", return_value=registered_query()), patch.object(service, "connection") as connect:
            response = self.post_execute()
        self.assertEqual(response.status_code, 403)
        connect.assert_not_called()

    def test_version_dialect_blocked_and_unknown_approval_prevent_execution(self):
        for query, expected in [(registered_query(version="2.0.0"), 409),
                                (registered_query(dialect="oracle"), 409),
                                (registered_query(kind="calculate", executionApproval="blocked", blockedReason="规则待确认"), 409),
                                (registered_query(executionApproval="unknown"), 409)]:
            with self.subTest(query=query):
                with patch.object(registry, "requirement", return_value={"id": "REQ", "metricIds": ["O-10"]}), patch.object(registry, "find_query", return_value=query), patch.object(service, "database_config", return_value=CONFIG), patch.object(service, "connection") as connect, patch.object(store, "execution_save"):
                    response = self.post_execute()
                self.assertEqual(response.status_code, expected)
                connect.assert_not_called()

    def test_real_query_result_is_returned_with_separate_persistence_state(self):
        query_result = {"columns": ["matched_records"], "rows": [{"matched_records": 427}], "metrics": {"matched_records": 427}, "recordCount": 427, "returnedRows": 1, "truncated": False}
        with patch.object(registry, "requirement", return_value={"id": "REQ", "metricIds": ["O-10"]}), patch.object(registry, "find_query", return_value=registered_query()), patch.object(service, "database_config", return_value=CONFIG), patch.object(service, "connection", return_value=fake_connection(object())), patch.object(service, "execute_read", return_value=query_result), patch.object(store, "execution_save", side_effect=RuntimeError("fixture-db-down")):
            response = self.post_execute()
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["recordCount"], 427)
        self.assertEqual(data["returnedRows"], 1)
        self.assertFalse(data["evidenceSaved"])

    def test_query_driver_exception_is_not_exposed_or_changed_to_zero(self):
        with patch.object(registry, "requirement", return_value={"id": "REQ", "metricIds": ["O-10"]}), patch.object(registry, "find_query", return_value=registered_query()), patch.object(service, "database_config", return_value=CONFIG), patch.object(service, "connection", return_value=fake_connection(object())), patch.object(service, "execute_read", side_effect=RuntimeError("fixture-secret-password")), patch.object(store, "execution_save"):
            response = self.post_execute()
        data = response.json()["data"]
        self.assertEqual(data["status"], "error")
        self.assertIsNone(data["recordCount"])
        self.assertNotIn("fixture-secret-password", response.text)

    def test_metric_conformance_requires_real_saved_evidence(self):
        with patch.object(registry, "requirement", return_value={"id": "REQ", "metricIds": ["O-10"]}), patch.object(store, "record_save") as save:
            response = self.client.post(self.prefix + "/records", json={"requirementId": "REQ", "metricId": "O-10", "judgment": "符合", "comment": "观察一致", "evidenceIds": []})
        self.assertEqual(response.status_code, 422)
        save.assert_not_called()

    def test_options_reject_query_outside_selected_requirement(self):
        with patch.object(registry, "requirement", return_value={"id": "REQ", "metricIds": ["O-01"]}), patch.object(registry, "find_query", return_value=registered_query()), patch.object(service, "parameter_options") as read:
            response = self.client.get(self.prefix + "/queries/Q/options?requirementId=REQ")
        self.assertEqual(response.status_code, 403)
        read.assert_not_called()


class ParameterOptionsTests(unittest.TestCase):
    def test_only_registered_dimension_columns_are_enumerated_never_students(self):
        query = registered_query(
            sql="SELECT s.student_id FROM ACT_STUDENT s WHERE s.student_id=:student_id AND s.batch_id=:student_batch_id AND s.password=:organization_id",
            parameters=[{"name": name} for name in ("student_id", "student_batch_id", "organization_id")],
            requiredColumns={"ACT_STUDENT": ["student_id", "batch_id"]})
        self.assertEqual(options.parameter_columns(query), {"student_batch_id": ("ACT_STUDENT", "batch_id")})

    def test_choices_are_bounded_without_exposing_rows_or_credentials(self):
        conn = Connection({"rows": [{"option_value": f"B{i}"} for i in range(101)]})
        with patch.object(options, "database_config", return_value=CONFIG), patch.object(options, "connection", return_value=fake_connection(conn)), patch.object(options, "schema_mapping", return_value={"ACT_STUDENT": "act_student"}):
            response = options.parameter_options(registered_query())
        entry = response["parameters"]["organization_id"]
        self.assertEqual(len(entry["items"]), 100)
        self.assertTrue(entry["truncated"])
        self.assertIn("LIMIT 101", conn.executions[0][0])
        self.assertNotIn("password", json.dumps(response))


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        # These cases cover the legacy requirement+metric checksum contract.
        # A locally activated mapping revision must not change their fixture mode.
        legacy_catalog = deepcopy(registry.catalog())
        legacy_catalog.pop('mappingRevisionId', None)
        patcher = patch.object(registry, 'catalog', return_value=legacy_catalog)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_execution_keeps_definition_from_query_start_if_definition_changes_during_query(self):
        conn = Connection({})
        result = {"id": "E", "metricId": "O-10", "queryId": "Q", "sqlVersion": "1", "layer": "fact",
                  "parameters": {}, "executedAt": "2026-09-29T10:00:00Z", "durationMs": 10,
                  "requirementChecksum": "at-query-start", "rows": []}
        with patch.object(store, "connection", return_value=fake_connection(conn)), patch.object(registry, "requirement_checksum", return_value="changed-during-query") as current:
            store.execution_save(result, actor(), "REQ", "SQL")
        snapshot = json.loads(conn.executions[0][1][10])
        self.assertEqual(snapshot["requirementChecksum"], "at-query-start")
        current.assert_not_called()

    def saved_evidence(self, requirement=None):
        requirement = requirement or {"id": "REQ", "metricIds": ["O-10"], "description": "fixture requirement"}
        metric_definitions = [m for m in registry.catalog()["metrics"] if m["id"] in requirement["metricIds"]]
        snapshot = {"requirement": requirement, "metrics": metric_definitions}
        checksum = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {"metric_id": "O-10", "query_id": "O-10-fact-count-mysql", "query_version": "1.0.0", "query_checksum": "fixture-checksum",
                "result_json": json.dumps({"status": "success", "requirementChecksum": checksum})}, requirement

    def evidence_body(self):
        return {"requirementId": "REQ", "metricId": "O-10", "judgment": "符合", "comment": "test", "evidenceIds": ["E1"]}

    def test_evidence_query_is_scoped_to_requirement_actor_and_active_identity(self):
        conn = Connection({"rows": []})
        with patch.object(store, "connection", return_value=fake_connection(conn)):
            with self.assertRaises(ApiError) as failure:
                store.record_save({"requirementId": "REQ", "metricId": "O-10", "judgment": "符合", "comment": "test", "evidenceIds": ["E1"]}, actor())
        self.assertEqual(failure.exception.status_code, 403)
        sql, values = conn.executions[0]
        self.assertIn("requirement_id=%s AND actor=%s AND identity_id=%s", sql)
        self.assertEqual(values, ("E1", "REQ", "fixture-user", "fixture-identity"))

    def test_failed_execution_cannot_support_conformance(self):
        conn = Connection({"rows": [{"metric_id": "O-10", "result_json": json.dumps({"status": "error"})}]})
        with patch.object(store, "connection", return_value=fake_connection(conn)):
            with self.assertRaises(ApiError) as failure:
                store.record_save({"requirementId": "REQ", "metricId": "O-10", "judgment": "符合", "comment": "test", "evidenceIds": ["E1"]}, actor())
        self.assertEqual(failure.exception.status_code, 422)
        self.assertEqual(len(conn.executions), 1)

    def test_other_metric_evidence_cannot_be_attached(self):
        conn = Connection({"rows": [{"metric_id": "O-01", "result_json": json.dumps({"status": "success"})}]})
        with patch.object(store, "connection", return_value=fake_connection(conn)):
            with self.assertRaises(ApiError) as failure:
                store.record_save({"requirementId": "REQ", "metricId": "O-10", "judgment": "符合", "comment": "test", "evidenceIds": ["E1"]}, actor())
        self.assertEqual(failure.exception.status_code, 403)

    def test_changed_sql_version_text_or_requirement_invalidates_conformance(self):
        for changed in ["query_version", "query_checksum", "requirement"]:
            with self.subTest(changed=changed):
                saved, requirement = self.saved_evidence()
                if changed == "requirement":
                    requirement["description"] = "a changed definition"
                else:
                    saved[changed] = "previous"
                conn = Connection({"rows": [saved]})
                with patch.object(store, "connection", return_value=fake_connection(conn)), patch.object(registry, "find_query", return_value=registered_query()), patch.object(registry, "requirement", return_value=requirement):
                    with self.assertRaises(ApiError) as failure:
                        store.record_save(self.evidence_body(), actor())
                self.assertEqual(failure.exception.status_code, 409)
                self.assertEqual(len(conn.executions), 1)

    def test_withdrawn_query_approval_invalidates_old_successful_evidence(self):
        saved, requirement = self.saved_evidence()
        conn = Connection({"rows": [saved]})
        with patch.object(store, "connection", return_value=fake_connection(conn)), patch.object(registry, "find_query", return_value=registered_query(executionApproval="blocked")), patch.object(registry, "requirement", return_value=requirement):
            with self.assertRaises(ApiError) as failure:
                store.record_save(self.evidence_body(), actor())
        self.assertEqual(failure.exception.status_code, 409)
        self.assertEqual(len(conn.executions), 1)

    def test_unchanged_successful_evidence_can_be_saved(self):
        saved, requirement = self.saved_evidence()
        conn = Connection({"rows": [saved]})
        with patch.object(store, "connection", return_value=fake_connection(conn)), patch.object(registry, "find_query", return_value=registered_query()), patch.object(registry, "requirement", return_value=requirement):
            result = store.record_save(self.evidence_body(), actor())
        self.assertEqual(result["judgment"], "符合")
        self.assertEqual(len(conn.executions), 2)
        self.assertIn("INSERT INTO sys_metric_verification_record", conn.executions[-1][0])

    def test_metric_formula_change_invalidates_evidence_even_when_requirement_is_unchanged(self):
        saved, requirement = self.saved_evidence()
        changed_catalog = deepcopy(registry.catalog())
        next(m for m in changed_catalog["metrics"] if m["id"] == "O-10")["formula"] = "changed numerator / changed denominator"
        conn = Connection({"rows": [saved]})
        with patch.object(store, "connection", return_value=fake_connection(conn)), patch.object(registry, "find_query", return_value=registered_query()), patch.object(registry, "requirement", return_value=requirement), patch.object(registry, "catalog", return_value=changed_catalog):
            with self.assertRaises(ApiError) as failure:
                store.record_save(self.evidence_body(), actor())
        self.assertEqual(failure.exception.status_code, 409)
        self.assertEqual(len(conn.executions), 1)

    def test_whole_requirement_cannot_pass_with_only_one_of_its_metrics(self):
        requirement = {"id": "REQ", "metricIds": ["O-10", "O-01"], "description": "multi metric"}
        saved, requirement = self.saved_evidence(requirement)
        conn = Connection({"rows": [saved]})
        body = self.evidence_body()
        body.pop("metricId")
        with patch.object(store, "connection", return_value=fake_connection(conn)), patch.object(registry, "find_query", return_value=registered_query()), patch.object(registry, "requirement", return_value=requirement):
            with self.assertRaises(ApiError) as error:
                store.record_save(body, actor())
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(len(conn.executions), 1)

    def test_history_is_scoped_and_keeps_old_referenced_evidence_without_detail_rows(self):
        row = {"execution_id": "OLD", "requirement_id": "REQ", "metric_id": "O-10", "query_id": "Q",
               "query_version": "old", "query_checksum": "old", "layer_name": "fact", "parameters_json": "{}",
               "result_json": json.dumps({"status": "success", "recordCount": 19, "requirementChecksum": "old", "rows": [{"student_id": "sensitive"}]}),
               "executed_at": "2026-09-29T10:00:00Z", "duration_ms": 50}
        conn = Connection()
        cursor = Cursor(conn, {})
        cursor.fetchall = Mock(side_effect=[[], [row]])
        with patch.object(conn, "cursor", return_value=cursor), patch.object(store, "record_list", return_value={"items": [{"evidenceIds": ["OLD"]}]}), patch.object(store, "connection", return_value=fake_connection(conn)), patch.object(registry, "requirement_checksum", return_value="new"), patch.object(registry, "requirement", return_value={"metricIds": ["O-10"]}), patch.object(registry, "find_query", return_value=registered_query()):
            response = store.execution_list("REQ", actor())
        self.assertEqual(response["items"][0]["recordCount"], 19)
        self.assertFalse(response["items"][0]["current"])
        self.assertNotIn("sensitive", json.dumps(response))
        for sql, values in conn.executions:
            self.assertIn("requirement_id=%s AND actor=%s AND identity_id=%s", sql)
            self.assertEqual(values[:3], ("REQ", "fixture-user", "fixture-identity"))


if __name__ == "__main__":
    unittest.main()

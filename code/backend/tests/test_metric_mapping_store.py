"""Persistence tests use an isolated SQLite transport for SQL transaction behavior, never 114."""
from contextlib import contextmanager
from copy import deepcopy
import sqlite3
import unittest
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.metric_verification import mapping_store, registry
from backend.metric_verification.mapping_contract import question_context
try:
    from .test_metric_mapping_contract import package_fixture
except ImportError:
    from test_metric_mapping_contract import package_fixture

ACTOR = {"username": "test-recorder", "identity_id": "test-role"}


class Cursor:
    def __init__(self, conn):
        self.cursor = conn.cursor()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.cursor.close()
    def execute(self, sql, args=()):
        self.cursor.execute(sql.replace("%s", "?").replace(" FOR UPDATE", "").replace("INSERT IGNORE", "INSERT OR IGNORE"), args)
    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None
    def fetchall(self):
        return [dict(r) for r in self.cursor.fetchall()]


class Connection:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE sys_metric_mapping_revision(revision_id TEXT PRIMARY KEY,project_id TEXT,module_id TEXT,environment_id TEXT,package_id TEXT,analysis_id TEXT,base_revision_id TEXT,schema_version TEXT,package_hash TEXT,package_json TEXT,validation_json TEXT,bindings_json TEXT,created_by TEXT,created_at TEXT,UNIQUE(project_id,module_id,environment_id,package_id));
        CREATE TABLE sys_metric_mapping_head(project_id TEXT,module_id TEXT,environment_id TEXT,revision_id TEXT,lock_version INTEGER,updated_by TEXT,updated_at TEXT,PRIMARY KEY(project_id,module_id,environment_id));
        CREATE TABLE sys_metric_mapping_question(project_id TEXT,module_id TEXT,environment_id TEXT,question_id TEXT,semantic_key TEXT,context_hash TEXT,question_json TEXT,answers_json TEXT,status TEXT,applied_revision_id TEXT,lock_version INTEGER,updated_at TEXT,PRIMARY KEY(project_id,module_id,environment_id,question_id));
        """)
    def cursor(self):
        return Cursor(self.conn)
    @contextmanager
    def open(self, layer, *, write=False):
        try:
            yield self
            if write:
                self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise


class MappingStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = Connection()
        self.patcher = patch.object(mapping_store, "connection", self.db.open)
        self.patcher.start()
    def tearDown(self):
        self.patcher.stop()
        self.db.conn.close()

    def save(self, package=None):
        return mapping_store.save_package(package or package_fixture(), ACTOR)

    def test_idempotent_package_and_different_content_conflict(self):
        first = self.save()
        again = self.save()
        self.assertEqual(first["revisionId"], again["revisionId"])
        self.assertTrue(again["idempotent"])
        package = package_fixture()
        package["moduleName"] = "Changed"
        with self.assertRaises(ApiError) as ctx:
            self.save(package)
        self.assertEqual(409, ctx.exception.status_code)

    def test_idempotent_retry_rechecks_after_waiting_for_head_lock(self):
        first = self.save()
        original = mapping_store._one
        calls = 0
        def stale_first_read(cursor):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None  # Simulate a snapshot taken before the competing publisher committed.
            return original(cursor)
        with patch.object(mapping_store, "_one", side_effect=stale_first_read):
            again = self.save()
        self.assertEqual(first["revisionId"], again["revisionId"])
        self.assertTrue(again["idempotent"])

    def test_active_question_list_does_not_mix_draft_contexts(self):
        first = self.save()
        mapping_store.activate_revision(first["revisionId"], None, ACTOR)
        changed = package_fixture()
        changed.update(packageId="changed-question-draft", baseRevisionId=first["revisionId"])
        changed["inputManifest"]["baseRevisionId"] = first["revisionId"]
        original_question = deepcopy(changed["questions"][0])
        changed["questions"][0]["problem"] = "新的草稿歧义"
        new_question = deepcopy(changed["questions"][0])
        new_question.update(id="Q-DRAFT-ONLY", semanticKey="draft-only")
        changed["questions"].append(new_question)
        self.save(changed)
        current_questions = mapping_store.list_questions(revision_id=first["revisionId"])
        self.assertNotIn("Q-DRAFT-ONLY", {q["id"] for q in current_questions})
        old_question = next(q for q in current_questions if q["id"] == original_question["id"])
        self.assertEqual(question_context(original_question), old_question["contextHash"])
        self.assertFalse(old_question["contextCurrent"])
        self.assertEqual("superseded", old_question["status"])
        self.assertTrue(old_question["problem"].startswith(original_question["problem"]))

    def test_cas_and_stale_base(self):
        first = self.save()
        activated = mapping_store.activate_revision(first["revisionId"], None, ACTOR)
        self.assertEqual("active", activated["state"])
        self.assertTrue(mapping_store.get_revision(first["revisionId"])["current"])

        stale = package_fixture()
        stale["packageId"] = "new-stale"
        with self.assertRaises(ApiError):
            self.save(stale)
        updated = package_fixture()
        updated["packageId"] = "new-current"
        updated["baseRevisionId"] = first["revisionId"]
        updated["inputManifest"]["baseRevisionId"] = first["revisionId"]
        second = self.save(updated)
        with self.assertRaises(ApiError):
            mapping_store.activate_revision(second["revisionId"], None, ACTOR)
        self.assertTrue(mapping_store.get_revision(first["revisionId"])["current"])

    def test_activation_rechecks_current_contract_without_switching_on_failure(self):
        saved = self.save()
        with patch.object(mapping_store, "validate_package", return_value={"valid": False, "errors": [{"message": "new contract"}]}):
            with self.assertRaises(ApiError):
                mapping_store.activate_revision(saved["revisionId"], None, ACTOR)
        self.assertFalse(mapping_store.get_revision(saved["revisionId"])["current"])

    def test_answer_retries_and_adoption(self):
        draft = self.save()
        question = package_fixture()["questions"][0]
        body = {"submissionId": "answer-1", "questionContextHash": question_context(question), "rawAnswer": "确认说明",
                "customAnswer": "确认说明", "scope": ["O-10"], "opinionSourceRef": "current_actor"}
        answer = mapping_store.answer_question(question["id"], body, ACTOR)
        again = mapping_store.answer_question(question["id"], body, ACTOR)
        self.assertEqual(answer["answerId"], again["answerId"])
        self.assertEqual(ACTOR["username"], answer["recordedBy"])
        answered = next(q for q in mapping_store.list_questions() if q["id"] == question["id"])
        self.assertEqual("answered", answered["status"])
        changed = {**body, "rawAnswer": "另一个答案"}
        with self.assertRaises(ApiError):
            mapping_store.answer_question(question["id"], changed, ACTOR)
        package = package_fixture()
        package["packageId"] = "with-answer"
        package["decisions"] = [{"questionId": question["id"], "answerId": answer["answerId"]}]
        final = self.save(package)
        mapping_store.activate_revision(final["revisionId"], None, ACTOR)
        adopted = next(q for q in mapping_store.list_questions() if q["id"] == question["id"])
        self.assertEqual("resolved", adopted["status"])

    def test_new_answer_blocks_stale_decision_activation(self):
        self.save()
        question = package_fixture()["questions"][0]
        body = {"submissionId": "first", "contextHash": question_context(question), "rawAnswer": "第一答复",
                "scope": "O-10", "opinionSourceRef": "current_actor"}
        first = mapping_store.answer_question(question["id"], body, ACTOR)
        package = package_fixture()
        package["packageId"] = "adopting-first"
        package["decisions"] = [{"questionId": question["id"], "answerId": first["answerId"]}]
        draft = self.save(package)
        mapping_store.answer_question(question["id"], {**body, "submissionId": "second", "rawAnswer": "修改答复"}, ACTOR)
        with self.assertRaises(ApiError):
            mapping_store.activate_revision(draft["revisionId"], None, ACTOR)

    def test_source_reference_and_scope_not_fabricated(self):
        self.save()
        question = package_fixture()["questions"][0]
        body = {"submissionId": "first", "contextHash": question_context(question), "rawAnswer": "答复",
                "scope": "O-10", "opinionSourceRef": "nonexistent-source"}
        with self.assertRaises(ApiError):
            mapping_store.answer_question(question["id"], body, ACTOR)
        with self.assertRaises(ApiError):
            mapping_store.answer_question(question["id"], {**body, "scope": "unrelated", "opinionSourceRef": "current_actor"}, ACTOR)

    def test_revision_integrity_checked(self):
        saved = self.save()
        self.db.conn.execute("UPDATE sys_metric_mapping_revision SET package_hash='tampered'")
        with self.assertRaises(ApiError):
            mapping_store.get_revision(saved["revisionId"])

    def test_defer_cannot_unlock_calculation(self):
        self.save()
        question = package_fixture()["questions"][0]
        body = {"submissionId": "deferred", "contextHash": question_context(question), "rawAnswer": "暂不确定",
                "choiceId": "defer", "scope": "O-10", "opinionSourceRef": "current_actor"}
        answer = mapping_store.answer_question(question["id"], body, ACTOR)
        package = package_fixture()
        package["packageId"] = "wrongly-resolved"
        package["decisions"] = [{"questionId": question["id"], "answerId": answer["answerId"]}]
        with self.assertRaises(ApiError):
            self.save(package)

    def test_missing_context_and_invalid_scope_rejected(self):
        self.save()
        question = package_fixture()["questions"][0]
        body = {"submissionId": "answer", "rawAnswer": "答复", "scope": "O-10", "opinionSourceRef": "current_actor"}
        with self.assertRaises(ApiError) as ctx:
            mapping_store.answer_question(question["id"], body, ACTOR)
        self.assertEqual(422, ctx.exception.status_code)
        with self.assertRaises(ApiError) as ctx:
            mapping_store.answer_question(question["id"], {**body, "contextHash": question_context(question), "scope": 12}, ACTOR)
        self.assertEqual(422, ctx.exception.status_code)

    def test_database_failure_does_not_fall_back_to_json(self):
        from backend.metric_verification.config import DatabaseConfig
        configured = DatabaseConfig("mysql", "host", 3306, "db", "user", "not-used")
        with patch.dict("os.environ", {"MV_MAPPING_MODE": "auto"}), patch.object(mapping_store, "database_config", return_value=configured), patch.object(mapping_store, "table_ready", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                mapping_store.get_head()

    def test_pinned_request_and_stale_revision(self):
        saved = self.save()
        with patch.object(mapping_store, "get_head", return_value={"revisionId": saved["revisionId"]}):
            with registry.revision_scope(saved["revisionId"]):
                self.assertEqual(saved["revisionId"], registry.current_revision_id())
                self.assertEqual("O-10", registry.current_package()["metrics"][0]["id"])
                self.assertEqual(saved["revisionId"], registry.catalog()["mappingRevisionId"])
                query = registry.find_query("QRY-O10-FACT-EXPECTED")
                self.assertEqual("blocked", query["executionApproval"])
            with self.assertRaises(ApiError):
                with registry.revision_scope("stale"):
                    pass


if __name__ == "__main__":
    unittest.main()

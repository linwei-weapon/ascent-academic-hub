"""Durability, privacy, cancellation and result preservation on isolated stores."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.api.envelope import ApiError
from backend.expert_resources import execution, store, rules, model_adapter
from backend.tests.test_expert_resources_store import success

ACTOR = {'username': 'fixture-manager', 'identity_id': 'fixture-identity',
         'permission_context': {'authorized': True, 'activeIdentityId': 'fixture-identity',
            'scopeFingerprint': 'fixture-scope', 'actionPermissions': ['system.manage'], 'detailScope': {'type': 'all'}}}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'EXPERT_RESOURCES_DB_PATH': str(Path(self.tmp.name) / 'local.sqlite')})
        self.env.start()
        self.seed = Path(self.tmp.name) / 'seed.json'
        catalog = json.loads((store.CODE / 'expert-resources/catalog.json').read_text(encoding='utf-8'))
        mcp = {'id': 'education-data', 'name': '夹具工具', 'tools': [t for t in catalog['mcps'][0]['tools'] if t['name'] == 'read_program_structure']}
        skill = {'id': 'program-structure', 'name': '夹具方案结构', 'execution': {'handler': 'read_program_structure'},
                 'toolBindings': [{'serverId': 'education-data', 'toolName': 'read_program_structure'}]}
        expert = {'id': 'program', 'name': '夹具专家', 'skillIds': ['program-structure']}
        self.seed.write_text(json.dumps({'mcps': [mcp], 'skills': [skill], 'experts': [expert]}), encoding='utf-8')
        store.initialize(self.seed)
        rules.initialize()
        execution.initialize()
        for kind, resource_id in (('mcps', 'education-data'), ('skills', 'program-structure'), ('experts', 'program')):
            row = store.test_resource(kind, resource_id, 1, {}, ACTOR, success)
            if kind != 'mcps':
                store.review_resource(kind, resource_id, 1, row['draft']['test']['runId'], True, '明确开发夹具', ACTOR)
            store.publish_resource(kind, resource_id, 1, ACTOR)

    def tearDown(self):
        with execution._credentials_lock:
            execution._credentials.clear()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, **changes):
        return {'clientRequestId': str(uuid4()), 'expertId': 'program', 'mode': 'selected_task',
                'expectedTurn': 0, 'question': '核对真实数据', 'input': {'taskId': 'P-STRUCTURE', 'plan_id': 'fixture-plan'}, **changes}

    def submit(self, **changes):
        return execution.submit(self.request(**changes), ACTOR, start=False)

    def outcome(self):
        return {'status': 'passed', 'summary': '保存完成', 'trace': [], 'missingEvidence': [],
                'result': {'status': 'limited', 'schemaVersion': '2.0', 'taskId': 'P-STRUCTURE', 'resultKind': 'facts',
                 'facts': [], 'scope': {'plan_id': 'fixture-plan'}, 'evidence': [
                   {'evidenceId': 'saved-1', 'retentionComplete': True, 'sourceRowCount': 2,
                    'records': [{'course_id': 'A'}, {'course_id': 'B'}]}], 'issues': []}}

    def test_idempotency_and_different_payload_conflict(self):
        req = self.request()
        first = execution.submit(req, ACTOR, start=False)
        self.assertEqual(first['executionId'], execution.submit(req, ACTOR, start=False)['executionId'])
        with self.assertRaises(ApiError):
            execution.submit({**req, 'question': '更改内容'}, ACTOR, start=False)
        self.assertEqual(len(store.get_research(first['researchId'], ACTOR)['turns']), 1)

    def test_authorization_failure_before_lease_does_not_leave_queued(self):
        view = self.submit()
        execution._supervise(view['executionId'])
        self.assertEqual(execution.get(view['executionId'], ACTOR)['state'], 'failed')

    def test_identity_and_scope_isolation(self):
        view = self.submit()
        other = deepcopy(ACTOR)
        other['permission_context']['scopeFingerprint'] = 'changed'
        with self.assertRaises(ApiError):
            execution.get(view['executionId'], other)
        with self.assertRaises(ApiError):
            store.get_research(view['researchId'], other)

    def test_one_active_request_per_research_and_optimistic_turn(self):
        first = self.submit()
        with self.assertRaises(ApiError):
            self.submit(researchId=first['researchId'], expectedTurn=1)
        execution.cancel(first['executionId'], ACTOR)
        with self.assertRaises(ApiError):
            self.submit(researchId=first['researchId'], expectedTurn=0)
        next_turn = self.submit(researchId=first['researchId'], expectedTurn=1)
        self.assertEqual(next_turn['state'], 'queued')

    def test_cancelled_execution_cannot_save_late_result(self):
        view = self.submit()
        execution.cancel(view['executionId'], ACTOR)
        self.assertFalse(execution._terminal(view['executionId'], 'completed', '迟到', outcome=self.outcome()))
        self.assertIsNone(execution.get(view['executionId'], ACTOR)['resultId'])

    def test_saved_evidence_uses_retained_rows_and_is_terminal_once(self):
        view = self.submit()
        execution._terminal(view['executionId'], 'partial', '保存完成', outcome=self.outcome())
        public = execution.get_result(view['executionId'], ACTOR)
        self.assertNotIn('records', public['result']['evidence'][0])
        self.assertEqual(public['result']['resultId'], view['executionId'])
        self.assertEqual(execution.evidence(view['executionId'], 'saved-1', ACTOR, 1, 1)['rows'], [{'course_id': 'B'}])
        self.assertFalse(execution._terminal(view['executionId'], 'completed', '重写', outcome=self.outcome()))
        self.assertEqual(execution.get(view['executionId'], ACTOR)['state'], 'partial')
        detail = store.get_research(view['researchId'], ACTOR)
        self.assertNotIn('records', detail['turns'][0]['result']['evidence'][0])
        with store._db() as db:
            self.assertNotIn('outcome', [r[1] for r in db.execute('PRAGMA table_info(er_execution)')])

    def test_result_size_failure_is_atomic(self):
        view = self.submit()
        with patch.object(execution, 'MAX_BYTES', 50), self.assertRaises(ApiError):
            execution._terminal(view['executionId'], 'completed', '过大', outcome=self.outcome())
        self.assertEqual(execution.get(view['executionId'], ACTOR)['state'], 'queued')
        with store._db() as db:
            saved = db.execute('SELECT outcome FROM er_turn WHERE id=?', (view['turnId'],)).fetchone()[0]
            self.assertEqual(json.loads(saved)['kind'], 'pending')

    def test_deadline_and_restart_fail_explicitly(self):
        view = self.submit()
        with store._db(write=True) as db:
            db.execute('UPDATE er_execution SET deadline=? WHERE id=?',
                       ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), view['executionId']))
        execution._terminal(view['executionId'], 'completed', '迟到', outcome=self.outcome())
        self.assertEqual(execution.get(view['executionId'], ACTOR)['failureCode'], 'deadline_exceeded')
        another = self.submit()
        self.assertEqual(execution.recover_interrupted(), 1)
        self.assertEqual(execution.get(another['executionId'], ACTOR)['failureCode'], 'interrupted_auth_lost')

    def test_auth_revalidation_detects_changed_scope_and_token_is_never_saved(self):
        view = self.submit()
        execution._credentials[view['executionId']] = ('Bearer fixture-only', 'fixture-identity', store._identity(ACTOR), time.monotonic()+10)
        changed = deepcopy(ACTOR)
        changed['permission_context']['scopeFingerprint'] = 'changed'
        with patch.object(execution, 'remote_identity_payload', return_value={}), patch.object(execution, 'normalize_actor', return_value=changed):
            with self.assertRaises(ApiError):
                execution._authenticate(view['executionId'])
        with store._db() as db:
            for table in ('er_execution', 'er_turn', 'er_research'):
                self.assertNotIn('Bearer fixture-only', str([tuple(r) for r in db.execute('SELECT * FROM ' + table)]))

    def test_missing_evidence_creates_independent_issue_events(self):
        view = self.submit()
        outcome = {'status': 'blocked', 'summary': '缺依据', 'result': None, 'missingEvidence': ['有效成绩依据'], 'trace': []}
        execution._terminal(view['executionId'], 'blocked', '缺依据', outcome=outcome)
        issue = rules.list_issues(view['researchId'], ACTOR)['items'][0]
        self.assertEqual(issue['originalTurnId'], view['turnId'])
        self.assertEqual(issue['revision'], 1)
        rules.append_issue_event(view['researchId'], issue['issueId'],
            {'type': 'submitted', 'revision': 1, 'sourceRef': {'name': '待核文件'}}, ACTOR)
        self.assertEqual(len(store.get_research(view['researchId'], ACTOR)['turns']), 1)
        self.assertEqual(rules.list_issues(view['researchId'], ACTOR)['items'][0]['resolutionState'], 'open')

    def test_course_issues_keep_original_object_and_do_not_collide_across_turns(self):
        first = self.submit()
        outcome = self.outcome()
        outcome['result']['facts'] = [{'factId': 'ratio', 'objectRef': {'course_id': 'A'}}]
        outcome['result']['evidence'][0]['records'][0]['course_name'] = '夹具课程'
        outcome['result']['issues'] = [{'issueId': 'row-1', 'originalTurnId': None,
            'requiredEvidence': '分母未知', 'affectedFacts': ['ratio']}]
        execution._terminal(first['executionId'], 'partial', '部分结果', outcome=outcome)
        second = self.submit(researchId=first['researchId'], expectedTurn=1)
        execution._terminal(second['executionId'], 'partial', '部分结果', outcome=outcome)
        issues = rules.list_issues(first['researchId'], ACTOR)['items']
        self.assertEqual(len(issues), 2)
        self.assertEqual({issue['originalTurnId'] for issue in issues}, {first['turnId'], second['turnId']})
        self.assertTrue(all(issue['title'] == '课程夹具课程：分母未知' for issue in issues))
        self.assertTrue(all(issue['resolutionState'] == 'open' for issue in issues))

    def test_recheck_tracks_the_saved_subject_and_closes_only_cleared_evidence(self):
        first = self.submit()
        original = self.outcome()
        original['result']['facts'] = [{'factId': 'ratio-old', 'name': '比例', 'unit': '%', 'value': 80,
            'objectRef': {'course_id': 'A', 'aggregateRow': 1}}]
        original['result']['issues'] = [{'issueId': 'unknown-source', 'affectedFacts': ['ratio-old'],
            'requiredEvidence': '比例只覆盖已识别范围'}]
        execution._terminal(first['executionId'], 'partial', '原问题', outcome=original)
        recheck = self.submit(researchId=first['researchId'], expectedTurn=1, originalTurnId=first['turnId'])
        still_unknown = self.outcome()
        still_unknown['result']['facts'] = [{'factId': 'ratio-new', 'name': '比例', 'unit': '%', 'value': 80,
            'objectRef': {'course_id': 'A', 'aggregateRow': 5}}]
        still_unknown['result']['issues'] = [{'issueId': 'new-warning', 'affectedFacts': ['ratio-new'],
            'requiredEvidence': '比例只覆盖已识别范围'}]
        execution._terminal(recheck['executionId'], 'partial', '仍缺来源', outcome=still_unknown)
        issues = rules.list_issues(first['researchId'], ACTOR)['items']
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['resolutionState'], 'open')
        ready = self.submit(researchId=first['researchId'], expectedTurn=2, originalTurnId=first['turnId'])
        cleared = deepcopy(still_unknown)
        cleared['result']['issues'] = []
        execution._terminal(ready['executionId'], 'partial', '原依据已核清', outcome=cleared)
        issue = rules.list_issues(first['researchId'], ACTOR)['items'][0]
        self.assertEqual(issue['resolutionState'], 'resolved')
        self.assertEqual(issue['lastRecheck']['resultRef']['resultId'], ready['executionId'])
        self.assertEqual(issue['originalTurnId'], first['turnId'])

    def test_recheck_rejects_other_research_and_does_not_close_changed_scope(self):
        first = self.submit()
        original = self.outcome()
        original['result']['facts'] = [{'factId': 'unknown', 'name': '比例', 'value': None}]
        original['result']['issues'] = [{'issueId': 'missing', 'affectedFacts': ['unknown'], 'requiredEvidence': '依据缺失'}]
        execution._terminal(first['executionId'], 'partial', '原问题', outcome=original)
        with self.assertRaises(ApiError):
            self.submit(originalTurnId=first['turnId'])
        changed = self.submit(researchId=first['researchId'], expectedTurn=1, originalTurnId=first['turnId'],
            input={'taskId': 'P-STRUCTURE', 'plan_id': 'another-plan'})
        cleared = self.outcome()
        cleared['result']['facts'] = [{'factId': 'unknown', 'name': '比例', 'value': 100}]
        execution._terminal(changed['executionId'], 'partial', '其他范围', outcome=cleared)
        self.assertEqual(rules.list_issues(first['researchId'], ACTOR)['items'][0]['resolutionState'], 'open')


class ModelTests(unittest.TestCase):
    def test_no_config_means_no_model(self):
        with patch.dict(os.environ, {'EXPERT_LLM_ENABLED': 'false'}):
            self.assertFalse(model_adapter.available_models()['available'])
            self.assertEqual(model_adapter.available_models()['items'], [])

    def test_explanation_cannot_invent_facts_or_change_numbers(self):
        expert = {'id': 'program', 'version': '1', 'content': {'skillIds': []}}
        outcome = {'result': {'facts': [{'factId': 'one', 'value': 12}], 'conditions': []}}
        with patch.object(model_adapter, '_json_call', return_value={'factIds': ['invented'], 'conditionIds': []}):
            model_adapter.explain(expert, {'skills': []}, {}, outcome)
        self.assertEqual(outcome['result']['facts'][0]['value'], 12)
        self.assertEqual(outcome['result']['explanation']['mode'], 'deterministic_fallback')


if __name__ == '__main__':
    unittest.main()

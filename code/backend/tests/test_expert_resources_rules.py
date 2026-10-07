from copy import deepcopy
import json
import unittest

from backend.api.envelope import ApiError
from backend.expert_resources import rules, store
from backend.tests import test_expert_resources_store as fixtures


PAYLOAD = {'ruleId': 'graduation-fixture', 'version': '1.0.0', 'domain': 'graduation',
           'applicability': {'years': [2026], 'organizations': ['A'], 'programs': ['p']},
           'conditions': [{'conditionId': 'c1', 'category': 'graduation', 'type': 'course_completion', 'courseId': 'c1'}],
           'sources': [{'sourceRef': 'fixture:hand-confirmed', 'location': '条款1'}]}


def actor(actions):
    value = deepcopy(fixtures.ACTOR)
    value['permission_context']['actionPermissions'] = actions
    value['permission_context']['detailScope'] = {'type': 'all'}
    return value


class RulesTests(unittest.TestCase):
    setUp = fixtures.ResourceStoreTests.setUp
    tearDown = fixtures.ResourceStoreTests.tearDown

    def create(self):
        rules.initialize()
        return rules.create_rule(PAYLOAD, actor(['system.manage']))

    def record(self, rule_id, run_id):
        manager = actor(['system.manage'])
        owner, identity, fingerprint = store._identity(manager)
        row = rules.get_rule(rule_id, '1.0.0')
        with store._db(write=True) as conn:
            conn.execute('INSERT INTO er_run VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (run_id, 'rules', rule_id, 1, owner, identity, fingerprint,
                          json.dumps({'ruleRef': {'ruleId': rule_id, 'version': '1.0.0', 'revision': 1, 'payloadHash': row['payloadHash']}}),
                          json.dumps({'processorFingerprint': rules.processor_fingerprint()}), json.dumps({'status': 'passed'}), '2026'))
        return rules.record_test(rule_id, '1.0.0', 1, manager,
                                 {'testRunId': run_id, 'processorFingerprint': rules.processor_fingerprint(), 'caseRefs': ['VR-G01']})

    def publish(self):
        self.create()
        manager = actor(['system.manage'])
        rules.confirm_rule(PAYLOAD['ruleId'], '1.0.0', 1, actor(['policy.confirm']), {'note': '夹具明确确认'}, True)
        self.record(PAYLOAD['ruleId'], 'fixture:run')
        return rules.publish_rule(PAYLOAD['ruleId'], '1.0.0', 1, manager)

    def test_lifecycle_immutable_and_withdrawn(self):
        row = self.publish()
        self.assertEqual(row['state'], 'published')
        with self.assertRaises(ApiError):
            rules.update_rule(PAYLOAD['ruleId'], '1.0.0', 1, PAYLOAD, actor(['system.manage']))
        row = rules.withdraw_rule(PAYLOAD['ruleId'], '1.0.0', 1, actor(['system.manage']), '原依据撤回')
        self.assertEqual(row['payload'], PAYLOAD)
        self.assertEqual(row['state'], 'withdrawn')
        with self.assertRaises(ApiError):
            rules.select_rule('graduation', {'year': 2026, 'organization': 'A', 'program': 'p'})

    def test_management_does_not_confirm_and_external_requires_permission(self):
        self.create()
        with self.assertRaises(ApiError) as error:
            rules.confirm_rule(PAYLOAD['ruleId'], '1.0.0', 1, actor(['system.manage']), {'note': '管理批准'})
        self.assertEqual(error.exception.status_code, 403)
        record = {'mode': 'external', 'note': '导入实际批准记录', 'businessConfirmer': '学校负责人',
                  'sourceRef': 'fixture:approval', 'confirmedAt': '2026-01-01'}
        row = rules.confirm_rule(PAYLOAD['ruleId'], '1.0.0', 1, actor(['policy.confirm.import']), record)
        self.assertEqual(row['confirmation']['businessConfirmer'], '学校负责人')
        self.assertEqual(row['confirmation']['importedBy'], fixtures.ACTOR['username'])

    def test_confirmation_permission_does_not_expand_organization_scope(self):
        self.create()
        confirmer = actor(['policy.confirm'])
        confirmer['permission_context']['detailScope'] = {'type': 'college', 'collegeIds': ['B']}
        with self.assertRaises(ApiError) as error:
            rules.confirm_rule(PAYLOAD['ruleId'], '1.0.0', 1, confirmer, {'note': '跨学院确认'})
        self.assertEqual(error.exception.status_code, 403)

    def test_edit_clears_confirmation_test_and_revision_guard(self):
        self.create()
        rules.confirm_rule(PAYLOAD['ruleId'], '1.0.0', 1, actor(['policy.confirm']), {'note': '确认'})
        payload = deepcopy(PAYLOAD)
        payload['conditions'][0]['courseId'] = 'changed'
        row = rules.update_rule(PAYLOAD['ruleId'], '1.0.0', 1, payload, actor(['system.manage']))
        self.assertEqual(row['state'], 'draft')
        self.assertIsNone(row['confirmation'])
        self.assertIsNone(row['test'])
        self.assertEqual(row['revision'], 2)
        self.assertTrue(any(item.get('confirmation') for item in row['history']))
        with self.assertRaises(ApiError):
            rules.confirm_rule(PAYLOAD['ruleId'], '1.0.0', 1, actor(['policy.confirm']), {'note': '旧revision'})

    def test_unique_applicability_no_latest_fallback(self):
        self.publish()
        context = {'year': 2026, 'organization': 'A', 'program': 'p'}
        self.assertEqual(rules.select_rule('graduation', context)['version'], '1.0.0')
        with self.assertRaises(ApiError):
            rules.select_rule('graduation', {**context, 'year': 2025})
        payload = deepcopy(PAYLOAD)
        payload['ruleId'] = 'other'
        rules.create_rule(payload, actor(['system.manage']))
        rules.confirm_rule('other', '1.0.0', 1, actor(['policy.confirm']), {'note': '其他同适用规则'})
        self.record('other', 'fixture:run2')
        rules.publish_rule('other', '1.0.0', 1, actor(['system.manage']))
        with self.assertRaises(ApiError):
            rules.select_rule('graduation', context)

    def test_client_passed_flag_cannot_replace_actual_candidate_run(self):
        self.create()
        with self.assertRaises(ApiError):
            rules.record_test(PAYLOAD['ruleId'], '1.0.0', 1, actor(['system.manage']),
                              {'testRunId': 'invented', 'processorFingerprint': 'fiction', 'caseRefs': ['VR-G01'], 'passed': True})

    def test_issue_events_do_not_add_turns_and_upload_does_not_resolve(self):
        rules.initialize()
        value = fixtures.ACTOR
        owner, identity, fingerprint = store._identity(value)
        with store._db(write=True) as conn:
            conn.execute('INSERT INTO er_research (id,owner,identity_id,scope_fingerprint,title,expert_id,expert_version,dependencies,input,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         ('research-fixture', owner, identity, fingerprint, '原问题', 'program', '1.0.0', '{}', '{}', '2026', '2026'))
            conn.execute('INSERT INTO er_turn VALUES (?,?,?,?,?,?,?)', ('turn-fixture', 'research-fixture', 1, '缺少依据', '{}', '{}', '2026'))
        issue = rules.append_issue_event('research-fixture', 'issue', {'type': 'opened', 'originalTurnId': 'turn-fixture'}, value)
        issue = rules.append_issue_event('research-fixture', 'issue', {'type': 'submitted', 'sourceRef': {'name': 'wrong-year', 'locator': '夹具'}}, value)
        self.assertEqual(issue['resolutionState'], 'open')
        rules.append_issue_event('research-fixture', 'issue', {'type': 'rejected', 'reason': '年度错误'}, value)
        rules.append_issue_event('research-fixture', 'issue', {'type': 'confirmed', 'sourceRef': 'correct-year'}, value)
        with self.assertRaises(ApiError):
            rules.append_issue_event('research-fixture', 'issue', {'type': 'rechecked', 'resolved': True}, value)
        issue = rules.append_issue_event('research-fixture', 'issue', {'type': 'rechecked', 'originalTurnId': 'turn-fixture',
                                         'resultRef': {'resultId': 'result-fixture'}, 'resolved': True, 'requiredEvidenceComplete': True},
                                         value, trusted_recheck=True)
        self.assertEqual(issue['resolutionState'], 'resolved')
        with store._db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM er_turn').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT updated_at FROM er_research WHERE id=?', ('research-fixture',)).fetchone()[0], '2026')
        unauthorized = deepcopy(value)
        unauthorized['identity_id'] = 'other'
        unauthorized['permission_context']['activeIdentityId'] = 'other'
        with self.assertRaises(ApiError):
            rules.list_issues('research-fixture', unauthorized)

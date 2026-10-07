from contextlib import nullcontext
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.expert_resources import policy_adapter as adapter
from backend.tests.test_expert_resources_matching import RULE
from backend.tests.test_expert_resources_store import ACTOR


def actor(scope=None):
    value = deepcopy(ACTOR)
    value['permission_context']['actionPermissions'] = ['system.manage']
    value['permission_context']['detailScope'] = scope or {'type': 'all'}
    return value


INPUT = {'plan_id': 'p', 'populationRef': 'plan:p', 'year': 2026, 'ruleRef': {'ruleId': 'fixture', 'version': '1.0.0'}}
PLAN = {'organization_id': 'A', 'grade': '2022'}
BASIS = {'effectiveResultSource': 'act_student_course_result', 'attemptSource': 'act_grade_attempt',
         'gradeRuleVersion': 'grade-effective-v1', 'creditsSource': 'act_student_course_result.earned_credits',
         'selectionConfirmed': True, 'creditsConfirmed': True}


def row(course, **kwargs):
    return {'id': 'r:' + course, 'student_id': 'PRIVATE_S1', 'course_id': course, 'effective_attempt_id': 'attempt:' + course,
            'rule_version': 'grade-effective-v1', 'result_pass': 1, 'earned_credits': '2', 'result_basis': 'published-pass-highest-score',
            'calculated_at': '2026', 'attempt_published': 1, 'attempt_void': 0, 'attempt_pass': 1, 'attempt_credits': '2', **kwargs}


class PolicyAdapterTests(unittest.TestCase):
    def context(self, rows=None, rule=None, students=None):
        full_rule = {'state': 'published', 'confirmation': {'accepted': True}, 'payload': {**deepcopy(RULE), 'learningBasis': BASIS}}
        self.addCleanup(patch.stopall)
        patch.object(adapter, 'connection', return_value=nullcontext(object())).start()
        patch.object(adapter.runtime, 'authorized_plan', return_value=PLAN).start()
        patch.object(adapter.rules, 'select_rule', return_value=rule or full_rule).start()
        patch.object(adapter, '_metadata').start()
        patch.object(adapter, '_rows', side_effect=[students if students is not None else [{'student_id': 'PRIVATE_S1', 'assignment_plan_id': 'p', 'assignment_primary': 1, 'assignment_source': 'real'}], rows if rows is not None else [row('c1'), row('c2')]]).start()

    def test_client_business_fields_and_cross_college_rejected_before_db(self):
        with patch.object(adapter, 'connection') as db:
            with self.assertRaises(ApiError):
                adapter.execute('G-CHECK', {**INPUT, 'achievements': [row('c1')]}, actor())
            with self.assertRaises(ApiError):
                adapter.execute('G-CHECK', {**INPUT, 'college_id': 'B'}, actor({'type': 'college', 'collegeIds': ['A']}))
            db.assert_not_called()

    def test_published_basis_positive_and_missing_unknown_not_failed(self):
        self.context()
        output = adapter.execute('G-CHECK', INPUT, actor())
        self.assertEqual(output['status'], 'passed')
        conditions = output['result']['objects'][0]['conditions']
        self.assertEqual([c['state'] for c in conditions], ['satisfied', 'unknown'])
        self.assertIsNone(conditions[1]['gap'])
        self.assertIsNone(output['result']['wholeEligibility'])
        self.assertFalse(output['result']['learningEvidence']['coverage']['sourceComplete'])
        self.assertNotIn('PRIVATE_S1', json.dumps(output))

    def test_tool_facts_not_school_confirmation(self):
        self.context()
        output = adapter.read_learning_results({'plan_id': 'p', 'populationRef': 'plan:p'}, actor())
        achievement = output['objects'][0]['achievements'][0]
        self.assertTrue(achievement['attemptChecksPassed'])
        self.assertFalse(achievement['validityConfirmed'])
        self.assertFalse(achievement['creditsConfirmed'])
        self.assertNotIn('PRIVATE_S1', json.dumps(output))

    def test_unknown_pass_invalid_attempt_and_credit_conflict(self):
        self.context(rows=[row('c1', attempt_published=0), row('c2', result_pass=None), row('c3', earned_credits='96')])
        result = adapter.execute('G-CHECK', INPUT, actor())['result']['objects'][0]
        self.assertEqual([c['state'] for c in result['conditions']], ['unknown', 'unknown'])

    def test_missing_basis_or_unique_rule_blocks_before_learning_read(self):
        self.context(rule={'state': 'published', 'confirmation': {'accepted': True}, 'payload': RULE})
        output = adapter.execute('G-CHECK', INPUT, actor())
        self.assertEqual(output['status'], 'blocked')
        self.assertIn('learningBasis', output['summary'])

    def test_no_guess_year_or_population_and_no_silent_truncation(self):
        self.assertEqual(adapter.execute('G-CHECK', {**INPUT, 'year': None}, actor())['status'], 'blocked')
        self.assertEqual(adapter.execute('G-CHECK', {**INPUT, 'populationRef': 'client-list'}, actor())['status'], 'blocked')
        self.context(students=[{'student_id': str(i)} for i in range(adapter.MAX_OBJECTS + 1)])
        with self.assertRaises(ApiError):
            adapter.read_learning_results({'plan_id': 'p', 'populationRef': 'plan:p'}, actor())

    def test_condition_preview_does_not_remove_overlap_rule(self):
        rule = deepcopy(RULE)
        rule['conditions'].append({'conditionId': 'another', 'category': 'degree', 'type': 'credit_pool', 'courseIds': ['c2'], 'minCredits': '2'})
        self.context(rule={'state': 'published', 'confirmation': {'accepted': True}, 'payload': {**rule, 'learningBasis': BASIS}})
        result = adapter.execute('G-CHECK', {**INPUT, 'conditionIds': ['pool']}, actor())['result']
        self.assertEqual(len(result['objects'][0]['conditions']), 1)
        self.assertEqual(result['objects'][0]['conditions'][0]['state'], 'unknown')

    def test_missing_plan_binding_does_not_report_zero_population_success(self):
        self.context(students=[])
        with self.assertRaises(ApiError) as error:
            adapter.read_learning_results({'plan_id': 'p', 'populationRef': 'plan:p'}, actor())
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn('零返回', error.exception.msg)

    def test_real_primary_assignment_must_match_student_program(self):
        self.context(students=[{'student_id': 'PRIVATE_S1', 'assignment_plan_id': 'other', 'assignment_primary': 1, 'assignment_source': 'real'}])
        with self.assertRaises(ApiError) as error:
            adapter.read_learning_results({'plan_id': 'p', 'populationRef': 'plan:p'}, actor())
        self.assertIn('不一致', error.exception.msg)

from copy import deepcopy
import unittest

from backend.api.envelope import ApiError
from backend.expert_resources.policy_tasks import execute_task
from backend.tests.test_expert_resources_matching import RULE, COVERAGE, achievement


class PolicyTasksTests(unittest.TestCase):
    def test_formal_requires_trusted_sources_and_published_rule(self):
        data = {'rule': RULE, 'achievements': [achievement('c1')], 'coverage': COVERAGE}
        self.assertEqual(execute_task('G-CHECK', data)['status'], 'blocked')
        self.assertEqual(execute_task('G-CHECK', data, trusted_inputs=True)['status'], 'blocked')
        data['rule'] = {'payload': RULE, 'state': 'published', 'confirmation': {'accepted': True}}
        result = execute_task('G-CHECK', data, trusted_inputs=True)
        self.assertEqual(result['status'], 'passed')
        self.assertIsNone(result['result']['wholeEligibility'])

    def test_candidate_distinguished_from_formal_and_fixture(self):
        data = {'rule': {'payload': RULE, 'state': 'confirmed', 'confirmation': {'accepted': True}}, 'coverage': COVERAGE}
        self.assertEqual(execute_task('G-CHECK', data, 'candidate', trusted_inputs=True)['purpose'], 'candidate')
        self.assertEqual(execute_task('G-CHECK', data, 'formal', trusted_inputs=True)['status'], 'blocked')
        result = execute_task('G-CHECK', {'rule': RULE, 'coverage': COVERAGE}, 'fixture')
        self.assertIn('开发夹具', result['limitations'][0])

    def test_transfer_direction_and_recognition(self):
        source = deepcopy(RULE)
        source['ruleId'] = 'from'
        source['conditions'] = source['conditions'][:1]
        target = deepcopy(RULE)
        target['ruleId'] = 'to'
        forward = execute_task('T-REQUIREMENTS', {'sourceRule': source, 'rule': target}, 'fixture')['result']
        reverse = execute_task('T-REQUIREMENTS', {'sourceRule': target, 'rule': source}, 'fixture')['result']
        self.assertEqual(len(forward['targetAdditional']), 1)
        self.assertEqual(len(reverse['targetAdditional']), 0)
        recognition = execute_task('T-RECOGNITION', {'rule': target, 'achievements': [achievement('c1'), achievement('c2')], 'coverage': COVERAGE}, 'fixture')['result']
        self.assertEqual(recognition['conditions'][1]['gap'], '2')

    def test_rank_precision_ties_and_incomplete_population(self):
        rule = {'ranking': {'method': 'explicit_score', 'tiePolicy': 'competition'}}
        rows = [{'objectRef': 'a', 'score': '80.004', 'scoreConfirmed': True, 'sourceRef': 'fixture:a'},
                {'objectRef': 'b', 'score': '80.003', 'scoreConfirmed': True, 'sourceRef': 'fixture:b'},
                {'objectRef': 'c', 'score': '80.003', 'scoreConfirmed': True, 'sourceRef': 'fixture:c'}]
        result = execute_task('R-RANK', {'rule': rule, 'objects': rows, 'coverage': {'populationComplete': True}}, 'fixture')['result']
        self.assertEqual([r['rank'] for r in result['rows']], [1, 2, 2])
        self.assertEqual([r['displayScore'] for r in result['rows']], ['80.00'] * 3)
        rows.append({'objectRef': 'd'})
        incomplete = execute_task('R-RANK', {'rule': rule, 'objects': rows, 'coverage': {'populationComplete': True}}, 'fixture')['result']
        self.assertEqual(incomplete['rankingKind'], 'known_subset')
        self.assertEqual(incomplete['denominator'], 4)
        self.assertEqual(len(incomplete['excluded']), 1)

    def test_recommendation_unknown_and_scenario_baseline_immutable(self):
        rule = {'conditions': [{'conditionId': 'score', 'type': 'threshold', 'threshold': '80', 'category': 'recommendation'},
                               {'conditionId': 'discipline', 'type': 'boolean', 'expected': True, 'category': 'recommendation'}],
                'scenarioAllowedConditionIds': ['score']}
        data = {'rule': rule, 'objects': [{'objectRef': 's1', 'values': {'score': {'value': '81', 'confirmed': True, 'sourceRef': 'fixture:score'}}}],
                'thresholds': {'score': '82'}}
        original = deepcopy(data)
        baseline = execute_task('R-CHECK', data, 'fixture')['result']
        scenario = execute_task('R-SCENARIO', data, 'fixture')['result']
        self.assertEqual([r['state'] for r in baseline['objects'][0]['conditions']], ['satisfied', 'unknown'])
        self.assertEqual([r['state'] for r in scenario['objects'][0]['conditions']], ['unsatisfied', 'unknown'])
        self.assertEqual(data, original)
        self.assertIsNone(scenario['quotaChange'])

    def test_material_year_and_support_explicit_mapping_only(self):
        data = {'rule': {'requiredMaterials': [{'materialId': 'annual'}]}, 'context': {'year': 2026, 'organization': 'A'},
                'materials': [{'materialId': 'annual', 'year': 2025, 'organization': 'A', 'sourceRef': 'old', 'body': '条例', 'confirmed': True}]}
        self.assertEqual(execute_task('R-PREPARE', data, 'fixture')['result']['materials'][0]['state'], 'unknown')
        documents = [{'documentId': 'd', 'body': '同目标', 'sourceRef': 'doc:1', 'hash': 'fixture:hash', 'year': 2026, 'confirmed': True}]
        support = {'documents': documents, 'targets': ['goal'], 'context': {'year': 2026}, 'mappings': []}
        self.assertEqual(execute_task('P-SUPPORT', support, 'fixture')['result']['targets'][0]['state'], 'unknown')
        support['mappings'] = [{'documentId': 'd', 'targetId': 'goal', 'role': 'teaching', 'sourceLocation': '第1段', 'confirmed': True}]
        result = execute_task('C-SUPPORT', support, 'fixture')['result']
        self.assertEqual(result['targets'][0]['missingRoles'], ['assessment'])
        self.assertIsNone(result['attainmentRate'])

    def test_path_change_assumptions_do_not_modify_baseline(self):
        data = {'courses': [{'courseId': 'a', 'semester': 1}, {'courseId': 'b', 'semester': 2}],
                'constraints': [{'type': 'prerequisite', 'beforeCourseId': 'a', 'afterCourseId': 'b'}],
                'constraintsConfirmed': True, 'changes': [{'action': 'update', 'courseId': 'a', 'values': {'semester': 3}}]}
        before = deepcopy(data)
        result = execute_task('P-CHANGE', data, 'fixture')['result']
        self.assertEqual(len(result['violations']), 1)
        self.assertEqual(data, before)
        self.assertIsNone(result['overallFeasible'])
        self.assertEqual(result['courseChanges']['modified'], ['a'])
        self.assertIsNone(result['creditChange'])
        data['changes'][0]['action'] = 'guess'
        with self.assertRaises(ApiError):
            execute_task('P-CHANGE', data, 'fixture')

    def test_change_exact_credits_and_unknown_source(self):
        data = {'courses': [{'courseId': 'a', 'credits': '0.1'}], 'creditsConfirmed': True,
                'changes': [{'action': 'add', 'courseId': 'b', 'values': {'credits': '0.2'}}]}
        result = execute_task('P-CHANGE', data, 'fixture')['result']
        self.assertEqual(result['creditChange'], {'baseline': '0.1', 'scenario': '0.3', 'delta': '0.2'})
        self.assertTrue(result['unknown'])

    def test_transfer_policy_scenario_uses_same_population_and_preserves_baseline(self):
        rule = deepcopy(RULE)
        rule['scenarioAllowedConditionIds'] = ['pool']
        data = {'rule': rule, 'objects': [{'objectRef': 's1', 'achievements': [achievement('c1'), achievement('c2')], 'coverage': COVERAGE}],
                'populationKind': 'hypothetical', 'changes': [{'conditionId': 'pool', 'proposedValue': '2'}]}
        before = deepcopy(data)
        baseline = execute_task('T-POLICY', data, 'fixture')['result']
        scenario = execute_task('T-POLICY-SCENARIO', data, 'fixture')['result']
        self.assertEqual(baseline['objectCounts']['unsatisfied'], 1)
        self.assertEqual(scenario['objectCounts']['satisfied'], 1)
        self.assertEqual(scenario['populationKind'], 'hypothetical')
        self.assertEqual(data, before)
        self.assertIsNone(scenario['capacityConclusion'])
        data['changes'][0]['conditionId'] = 'required'
        with self.assertRaises(ApiError):
            execute_task('T-POLICY-SCENARIO', data, 'fixture')

    def test_transfer_policy_known_conditions_keep_other_unknowns(self):
        rule = deepcopy(RULE)
        rule['conditions'].append({'conditionId': 'discipline', 'type': 'boolean', 'expected': True, 'category': 'transfer'})
        data = {'rule': rule, 'objects': [{'objectRef': 's1', 'achievements': [achievement('c1'), achievement('c2'), achievement('c3')], 'coverage': COVERAGE}]}
        result = execute_task('T-POLICY', data, 'fixture')['result']
        self.assertEqual(result['objectCounts']['unknown'], 1)
        self.assertEqual([row['state'] for row in result['objects'][0]['conditions']], ['satisfied', 'satisfied', 'unknown'])

    def test_schedule_actual_records_not_plan_semesters_and_capacity_unknown(self):
        data = {'requirements': [{'courseId': 'c', 'requiredByTermOrder': 4}],
                'offerings': [{'courseId': 'c', 'termOrder': 3, 'actual': True, 'confirmed': True, 'sourceRef': 'fixture:offering', 'status': 'published'}],
                'prerequisites': [{'beforeCourseId': 'before', 'afterCourseId': 'c', 'confirmed': True, 'sourceRef': 'fixture:prereq'}],
                'completedCourses': ['before'], 'coverage': {'remainingTimeConfirmed': True, 'prerequisitesConfirmed': True, 'offeringsComplete': False}}
        result = execute_task('T-SCHEDULE', data, 'fixture')['result']
        self.assertEqual(result['courses'][0]['state'], 'satisfied')
        self.assertEqual(result['courses'][0]['capacityState'], 'unknown')
        self.assertIsNone(result['overallFeasible'])
        data['offerings'][0]['actual'] = False
        self.assertEqual(execute_task('T-SCHEDULE', data, 'fixture')['result']['courses'][0]['state'], 'unknown')

    def test_schedule_missing_opening_unknown_until_coverage_confirmed(self):
        data = {'requirements': [{'courseId': 'c', 'requiredByTermOrder': 4}], 'offerings': [], 'prerequisites': [],
                'coverage': {'remainingTimeConfirmed': True, 'prerequisitesConfirmed': True, 'offeringsComplete': False}}
        self.assertEqual(execute_task('T-SCHEDULE', data, 'fixture')['result']['courses'][0]['state'], 'unknown')
        data['coverage']['offeringsComplete'] = True
        self.assertEqual(execute_task('T-SCHEDULE', data, 'fixture')['result']['courses'][0]['state'], 'unsatisfied')
        data['coverage']['remainingTimeConfirmed'] = False
        self.assertEqual(execute_task('T-SCHEDULE', data, 'fixture')['result']['courses'][0]['state'], 'unknown')

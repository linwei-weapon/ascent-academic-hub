from copy import deepcopy
import unittest

from backend.expert_resources.matching import evaluate_requirements, evaluate_group

RULE = {'ruleId': 'fixture', 'version': '1.0.0', 'conditions': [
    {'conditionId': 'required', 'category': 'graduation', 'type': 'course_completion', 'courseId': 'c1'},
    {'conditionId': 'pool', 'category': 'graduation', 'type': 'credit_pool', 'courseIds': ['c2', 'c3'], 'minCredits': '4'}]}
COVERAGE = {'sourceComplete': True, 'validityConfirmed': True, 'creditsConfirmed': True}


def achievement(course, credits='2', **kwargs):
    return {'courseId': course, 'effective': True, 'valid': True, 'passed': True, 'credits': credits,
            'evidenceId': 'e:' + course, 'sourceRef': 'fixture:' + course, **kwargs}


class MatchingTests(unittest.TestCase):
    def test_VR_G01_all_and_G08_partial_not_whole(self):
        result = evaluate_requirements(RULE, [achievement('c1'), achievement('c2'), achievement('c3')], COVERAGE, 's1')
        self.assertEqual([c['state'] for c in result['conditions']], ['satisfied', 'satisfied'])
        self.assertEqual(result['conditions'][1]['observed'], '4')
        self.assertEqual(len(result['adopted']), 3)
        self.assertIsNone(result['wholeEligibility'])

    def test_VR_G02_complete_pool_gap_not_all_missing_courses(self):
        result = evaluate_requirements(RULE, [achievement('c1'), achievement('c2')], COVERAGE)
        pool = result['conditions'][1]
        self.assertEqual((pool['state'], pool['observed'], pool['gap']), ('unsatisfied', '2', '2'))

    def test_VR_G03_duplicate_only_effective_attempt(self):
        records = [achievement('c1'), achievement('c2'), achievement('c2', effective=False, evidenceId='old')]
        result = evaluate_requirements(RULE, records, COVERAGE)
        self.assertEqual(result['conditions'][1]['observed'], '2')
        self.assertTrue(any(e.get('evidenceId') == 'old' for e in result['excluded']))

    def test_VR_G04_invalid_and_credit_conflict_keep_independent(self):
        result = evaluate_requirements(RULE, [achievement('c1'), achievement('c2', creditConflict=True)], COVERAGE)
        self.assertEqual([c['state'] for c in result['conditions']], ['satisfied', 'unknown'])
        result = evaluate_requirements(RULE, [achievement('c1'), achievement('c2', validityConfirmed=False)],
                                       {**COVERAGE, 'validityConfirmed': False})
        self.assertEqual(result['conditions'][1]['state'], 'unknown')

    def test_VR_G05_overlap_and_cycles_unknown(self):
        rule = deepcopy(RULE)
        rule['conditions'].append({'conditionId': 'pool2', 'category': 'degree', 'type': 'credit_pool', 'courseIds': ['c2'], 'minCredits': '2'})
        result = evaluate_requirements(rule, [achievement('c1'), achievement('c2')], COVERAGE)
        self.assertEqual([c['state'] for c in result['conditions']], ['satisfied', 'unknown', 'unknown'])
        rule = deepcopy(RULE)
        rule['substitutions'] = [{'fromCourseId': 'c2', 'toCourseId': 'c3'}, {'fromCourseId': 'c3', 'toCourseId': 'c2'}]
        self.assertEqual(evaluate_requirements(rule, [achievement('c1'), achievement('c2')], COVERAGE)['conditions'][1]['state'], 'unknown')

    def test_VR_G07_group_preserves_unknown_and_deduplicates(self):
        objects = [
            {'objectRef': 's1', 'achievements': [], 'coverage': COVERAGE},
            {'objectRef': 's2', 'achievements': [achievement('c1')], 'coverage': {**COVERAGE, 'sourceComplete': False}},
            {'objectRef': 's3', 'achievements': [achievement('c1'), achievement('c2'), achievement('c3')], 'coverage': COVERAGE}]
        result = evaluate_group(RULE, objects)
        self.assertEqual(result['denominator'], 3)
        self.assertEqual(result['objectCounts'], {'satisfied': 1, 'unsatisfied': 1, 'unknown': 1, 'not_applicable': 0})
        self.assertEqual(result['affectedObjectRefs'], ['s1', 's2'])

    def test_VR_G10_missing_rows_source_complete_vs_unknown(self):
        rows = [achievement('c1'), achievement('c2')]
        complete = evaluate_requirements(RULE, rows, COVERAGE)['conditions'][1]
        incomplete = evaluate_requirements(RULE, rows, {**COVERAGE, 'sourceComplete': False})['conditions'][1]
        self.assertEqual(complete['gap'], '2')
        self.assertEqual(incomplete['state'], 'unknown')
        self.assertIsNone(incomplete['gap'])
        failed = evaluate_requirements(RULE, [achievement('c1'), achievement('c2', passed=False)], {**COVERAGE, 'sourceComplete': False})
        self.assertEqual(failed['conditions'][1]['state'], 'unknown')

    def test_decimal_precision_not_float_and_explicit_not_applicable(self):
        rule = deepcopy(RULE)
        rule['conditions'][0]['applicable'] = False
        rule['conditions'][1]['minCredits'] = '0.3'
        result = evaluate_requirements(rule, [achievement('c2', '0.1'), achievement('c3', '0.2')], COVERAGE)
        self.assertEqual(result['conditions'][0]['state'], 'not_applicable')
        self.assertEqual(result['conditions'][1]['observed'], '0.3')
        self.assertEqual(result['conditions'][1]['state'], 'satisfied')

    def test_same_evidence_cannot_be_credited_as_two_courses(self):
        result = evaluate_requirements(RULE, [achievement('c1'), achievement('c2', evidenceId='shared'),
                                              achievement('c3', evidenceId='shared')], COVERAGE)
        self.assertEqual(result['conditions'][0]['state'], 'satisfied')
        self.assertEqual(result['conditions'][1]['state'], 'unknown')
        self.assertIsNone(result['conditions'][1]['gap'])

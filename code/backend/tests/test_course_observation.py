"""Explicit fixture and fault cases for the C-BRIEF-01 publication method."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from jsonschema import Draft202012Validator, ValidationError

from backend.expert_resources import course_observation as method, runtime, tasks


def course(key, n, p, **extra):
    return {'course_id': key, 'semester_id': 'fixture-term', 'organization_id': 'fixture-college',
            'course_name': 'explicit development fixture', 'first_attempts': n, 'first_pass': p,
            'failures': 987, 'rule_version': 'fixture-rule', 'calculated_at': 'fixture-source-time', **extra}


def proof(records, **extra):
    return {'state': 'read', 'queriedAt': 'fixture-query-time', 'reference': 'fixture-three-layer',
        'factCourseRows': [{'course_id': r['course_id'], 'first_n': r['first_attempts'], 'first_p': r['first_pass'],
            'unknown_retake': 0, 'unknown_pass': 0, 'missing_source': 0, 'source_field_mismatches': 0,
            'linked_source_n': r['first_attempts'], 'linked_source_p': r['first_pass'],
            'distinct_first_source_keys': r['first_attempts']} for r in records],
        'fieldMapping': [{'course_id': r['course_id'], 'organization_matches': 1} for r in records], **extra}


def registration():
    return {'registered': True, 'metrics': [{'metricCode': code, 'registered': True, 'version': 'fixture-v1'}
            for code in method.METRIC_CODES],
            'algorithmBasis': {'state': 'confirmed', 'reviewedReference': 'explicit development fixture'},
            'mappingRef': {'moduleId': 'ai-briefing', 'revisionId': 'fixture-revision', 'current': True}}


class ObservationTests(TestCase):
    args = {'semester_id': 'fixture-term'}

    def evaluate(self, records, checked=None, registered=None):
        return method.observations(records, self.args, checked or proof(records),
                                   registered if registered is not None else registration())

    def test_weighted_baseline_and_unpassed_are_not_raw_failures(self):
        data = [course('large', 100, 90), course('small', 4, 0)]
        calculated, basis, gate = self.evaluate(data)
        self.assertEqual(calculated['baseline']['firstAttempts'], 104)
        self.assertEqual(calculated['baseline']['firstPass'], 90)
        self.assertEqual(calculated['baseline']['ratePct'], 86.54)
        self.assertEqual([r['course_id'] for r in calculated['observations']], ['small'])
        self.assertEqual(calculated['observations'][0]['first_unpassed'], 4)
        self.assertEqual(calculated['observations'][0]['failures'], 987)
        self.assertEqual(gate['publishMode'], 'observation')
        self.assertEqual(basis['independentRecompute']['state'], 'passed')
        self.assertIsNone(basis['threeLayerCheck']['comparableAt'])

    def test_exact_boundary_and_display_rounding_never_decide_selection(self):
        equal = [course('a', 3, 2), course('b', 6, 4)]
        calculated, _, gate = self.evaluate(equal)
        self.assertEqual(calculated['observations'], [])
        self.assertEqual(calculated['populationState'], 'no_observations')
        self.assertEqual(gate['publishMode'], 'observation')
        close = [course('below', 100000, 90000), course('above', 100000, 90001)]
        calculated, _, _ = self.evaluate(close)
        self.assertEqual(calculated['validRows'][0]['first_pass_pct'], calculated['validRows'][1]['first_pass_pct'])
        self.assertEqual([r['course_id'] for r in calculated['observations']], ['below'])

    def test_sort_unpassed_then_exact_rate_then_identifier(self):
        data = [course('z', 10, 6), course('a', 10, 6), course('lower-rate', 5, 1),
                course('more-unpassed', 20, 15), course('reference', 100, 100)]
        calculated, _, _ = self.evaluate(data)
        self.assertEqual([r['course_id'] for r in calculated['observations']],
                         ['more-unpassed', 'lower-rate', 'a', 'z'])

    def test_preview_does_not_limit_baseline_or_retained_selection(self):
        data = [course('low-%02d' % i, 10, 0) for i in range(8)] + [course('reference', 1000, 1000)]
        calculated, _, _ = self.evaluate(data)
        self.assertEqual(len(calculated['preview']), 5)
        self.assertEqual(calculated['observationCount'], 8)
        self.assertEqual(calculated['baseline']['courseCount'], 9)
        self.assertEqual(calculated['baseline']['firstAttempts'], 1080)
        self.assertEqual(len(calculated['input']), 9)

    def test_exclusions_preserve_duplicate_missing_zero_and_orphan_causes(self):
        data = [course('duplicate', 4, 3), course('duplicate', 6, 5), course('zero', 0, 0),
                course('missing', None, 0), course('bad-pass', 2, 3), course('bool', True, 1),
                course('fraction', 2.5, 1), course('orphan', 3, 2, organization_id=None),
                course('different', 3, 2, semester_id='other'), course('nan', float('nan'), 0),
                course('valid', Decimal('8'), Decimal('6'))]
        calculated = method.calculate(data, 'fixture-term')
        self.assertEqual(calculated['baseline']['firstAttempts'], 8)
        self.assertEqual(calculated['baseline']['courseCount'], 1)
        self.assertEqual(calculated['exclusionCounts']['duplicate_course_semester'], 2)
        self.assertEqual(calculated['exclusionCounts']['zero_denominator'], 1)
        self.assertEqual(calculated['exclusionCounts']['missing_opening_organization'], 1)
        self.assertEqual(len(calculated['input']), 11)
        self.assertEqual(method.independent_recompute(data, 'fixture-term', calculated)['state'], 'passed')

    def test_no_data_no_valid_and_one_course_are_distinct(self):
        self.assertEqual(method.calculate([], 'fixture-term')['populationState'], 'no_data')
        self.assertEqual(method.calculate([course('zero', 0, 0)], 'fixture-term')['populationState'], 'no_valid_courses')
        calculated, _, gate = self.evaluate([course('single', 10, 5)])
        self.assertEqual(calculated['populationState'], 'one_course')
        self.assertEqual(calculated['observations'], [])
        self.assertEqual(gate['publishMode'], 'observation')

    def test_independent_recompute_detects_tampered_counts_hash_selection_and_unpassed(self):
        data = [course('low', 10, 3), course('high', 100, 100)]
        original = method.calculate(data, 'fixture-term')
        for alter in ('baseline', 'selection', 'unpassed', 'hash', 'baseline_rate', 'course_rate', 'flags', 'count'):
            calculated = deepcopy(original)
            if alter == 'baseline':
                calculated['baseline']['firstPass'] += 1
            elif alter == 'selection':
                calculated['observations'] = []
            elif alter == 'unpassed':
                calculated['validRows'][0]['first_unpassed'] = 999
            elif alter == 'hash':
                calculated['inputSha256'] = 'client-forged-hash'
            elif alter == 'baseline_rate':
                calculated['baseline']['ratePct'] = 12.34
            elif alter == 'course_rate':
                calculated['validRows'][0]['first_pass_pct'] = 12.34
            elif alter == 'flags':
                calculated['validRows'][0]['observation'] = False
            else:
                calculated['observationCount'] = 99
            with self.subTest(alter=alter):
                independent = method.independent_recompute(data, 'fixture-term', calculated)
                self.assertEqual(independent['state'], 'failed')
                basis = {'independentRecompute': independent}
                self.assertEqual(method.publication_gate(basis)['publishMode'], 'blocked')

    def test_missing_registration_or_mapping_never_approves_observations(self):
        data = [course('a', 10, 5), course('b', 20, 20)]
        for registered in ({'registered': False}, {**registration(), 'mappingRef': None},
                           {**registration(), 'metrics': registration()['metrics'][:-1]}):
            with self.subTest(registration=registered):
                _, basis, gate = self.evaluate(data, registered=registered)
                self.assertEqual(gate['publishMode'], 'facts_only')
                self.assertEqual(basis['independentRecompute']['state'], 'passed')

    def test_unknown_retake_missing_source_duplicate_key_or_wrong_college_block_new_derivatives(self):
        data = [course('a', 10, 5), course('b', 20, 20)]
        for field, value in [('unknown_retake', 1), ('missing_source', 1), ('source_field_mismatches', 1),
                             ('distinct_first_source_keys', 9), ('linked_source_n', 9)]:
            checked = proof(data)
            checked['factCourseRows'][0][field] = value
            with self.subTest(field=field):
                _, _, gate = self.evaluate(data, checked)
                self.assertEqual(gate['publishMode'], 'facts_only')
        checked = proof(data)
        checked['fieldMapping'][0]['organization_matches'] = 0
        self.assertEqual(self.evaluate(data, checked)[2]['publishMode'], 'facts_only')

    def test_unknown_pass_is_excluded_not_mislabelled_as_unpassed(self):
        data = [course('a', 10, 5), course('b', 20, 20)]
        checked = proof(data)
        checked['factCourseRows'][0]['unknown_pass'] = 18
        calculated, _, gate = self.evaluate(data, checked)
        self.assertEqual(calculated['observations'][0]['first_unpassed'], 5)
        self.assertEqual(gate['publishMode'], 'observation')

    def test_current_numerical_difference_without_historical_batch_is_pending(self):
        data = [course('a', 10, 5), course('b', 20, 20)]
        checked = proof(data)
        checked['factCourseRows'][0]['first_n'] = 11
        _, basis, gate = self.evaluate(data, checked)
        self.assertEqual(gate['publishMode'], 'facts_only')
        self.assertEqual(basis['threeLayerCheck']['state'], 'pending')
        self.assertEqual(basis['threeLayerCheck']['mismatchedCourses'], ['a'])
        self.assertIsNone(basis['threeLayerCheck']['comparableAt'])

    def test_multiple_or_missing_version_labels_use_actual_shared_semantic_proof(self):
        data = [course('a', 10, 5, rule_version='v1'), course('b', 20, 20, rule_version=None)]
        _, basis, gate = self.evaluate(data)
        self.assertEqual(gate['publishMode'], 'observation')
        self.assertTrue(basis['ruleCompatibility']['missingVersionLabel'])
        self.assertEqual(basis['ruleVersions'], ['v1'])
        self.assertEqual(basis['ruleCompatibility']['state'], 'confirmed_current_input')

    def test_missing_aggregate_course_keeps_limited_baseline_and_coverage_unknown(self):
        data = [course('a', 10, 5), course('b', 20, 20)]
        checked = proof(data)
        checked['factCourseRows'].append({'course_id': 'not-aggregated', 'first_n': 7, 'first_p': 6})
        calculated, basis, gate = self.evaluate(data, checked)
        self.assertEqual(gate['publishMode'], 'observation')
        self.assertEqual(calculated['baseline']['firstAttempts'], 30)
        self.assertEqual(basis['threeLayerCheck']['factCoursesWithoutAggregate'], ['not-aggregated'])
        self.assertEqual(basis['threeLayerCheck']['aggregateCoverage'], 'partial')
        self.assertEqual(basis['sourceBasis']['sourceCoverage'], 'unknown')

    def test_runtime_retains_raw_fields_and_omits_new_observations_without_proof(self):
        data = [course('a', 10, 5), course('b', 20, 20)]
        with patch.object(method, 'registration_basis', return_value=registration()):
            result = runtime._course_performance(data, self.args)
        self.assertEqual(result['publishMode'], 'facts_only')
        self.assertNotIn('observations', result)
        self.assertNotIn('observationBaseline', result)
        self.assertFalse(any(f['factId'].endswith('first-unpassed') for f in result['facts']))
        raw = next(e for e in result['evidence'] if e['evidenceId'] == 'course-aggregate-input')
        self.assertEqual(raw['records'], data)
        self.assertNotIn('first_pass_pct', raw['records'][0])

    def test_generated_c_strict_schema_accepts_observation_facts_only_and_blocked_contracts(self):
        schema_path = Path(__file__).parents[2] / 'expert-resources' / 'skills' / 'course-performance' / 'output.schema.json'
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('observations', schema['required'])
        validator = Draft202012Validator(schema)
        records = [course('a', 10, 5), course('b', 20, 20)]
        with patch.object(method, 'registration_basis', return_value=registration()):
            for data, checked, expected in [(records, proof(records), 'observation'),
                                            (records, None, 'facts_only'), ([], None, 'blocked')]:
                with self.subTest(mode=expected):
                    result = runtime._course_performance(data, self.args, checked)
                    result = tasks._adapt_result(tasks.definition('C-PERFORMANCE'), result)
                    self.assertEqual(result['publishMode'], expected)
                    validator.validate(result)
        with self.assertRaises(ValidationError):
            validator.validate({**result, 'unexpectedPrototypeField': True})

    def test_runtime_observation_keeps_all_selected_evidence_and_raw_freeze(self):
        data = [course('low-%02d' % i, 10, 0) for i in range(8)] + [course('reference', 1000, 1000)]
        with patch.object(method, 'registration_basis', return_value=registration()):
            result = runtime._course_performance(data, self.args, proof(data))
        self.assertEqual(result['publishMode'], 'observation')
        self.assertEqual(result['tables'][0]['returnedRows'], 5)
        self.assertEqual(result['tables'][0]['totalRows'], 8)
        self.assertTrue(result['tables'][0]['truncated'])
        retained = next(e for e in result['evidence'] if e['evidenceId'] == 'course-observations')
        self.assertEqual(retained['retainedRowCount'], 8)
        self.assertEqual(result['validationBasis']['frozenInput']['evidenceId'], 'course-aggregate-input')
        self.assertEqual(result['validationBasis']['independentRecompute']['inputSha256'],
                         result['validationBasis']['frozenInput']['sha256'])

    def test_c_release_fingerprint_covers_helper_and_mapping_registration(self):
        manifest = runtime.task_fingerprint(['C-PERFORMANCE'])
        paths = {row['path'] for row in manifest['runtimeDependencies']}
        self.assertIn('code/backend/expert_resources/course_observation.py', paths)
        self.assertIn('code/backend/metric_verification/mapping_store.py', paths)
        self.assertIn('code/backend/metric_verification/mapping_contract.py', paths)
        self.assertIn(method.REVIEWED_PACKAGE_REF, paths)
        with patch.object(method, 'LOADED_FINGERPRINT', 'changed-test-helper'):
            self.assertNotEqual(runtime.task_fingerprint(['C-PERFORMANCE'])['runtimeFingerprint'], manifest['runtimeFingerprint'])


class DefinitionCompatibilityTests(TestCase):
    def setUp(self):
        self.package = json.loads(method.REVIEWED_PACKAGE_PATH.read_text(encoding='utf-8'))
        self.reviewed = method.algorithm_definition(self.package)

    def test_provenance_descriptions_do_not_change_algorithm_compatibility(self):
        package = deepcopy(self.package)
        package['analysisId'] = 'new-provenance-analysis'
        package['sourceManifest'][0]['title'] = 'updated source description only'
        package['metrics'][0]['definition']['businessPurpose'] = 'updated readable purpose only'
        self.assertEqual(method.algorithm_compatibility(package, self.reviewed)['state'], 'confirmed')

    def test_actual_u_definition_change_disables_fixed_method_even_if_sys_registry_matches(self):
        package = deepcopy(self.package)
        metric = next(m for m in package['metrics'] if m['id'] == 'AI-C-04')
        metric['definition']['formula'] = 'first_attempts + first_pass'
        status = method.algorithm_compatibility(package, self.reviewed)
        self.assertEqual(status['state'], 'unconfirmed')
        self.assertIn('AI-C-04', status['mismatchedMetricIds'])
        registered = {**registration(), 'algorithmBasis': status}
        records = [course('a', 10, 5), course('b', 20, 20)]
        computed, basis, gate = method.observations(records, {'semester_id': 'fixture-term'}, proof(records), registered)
        self.assertTrue(basis['metricRegistration'])
        self.assertEqual(gate['publishMode'], 'facts_only')

    def test_application_sql_change_without_definition_change_is_rejected(self):
        package = deepcopy(self.package)
        metric = next(m for m in package['metrics'] if m['id'] == 'AI-C-04')
        query = next(q for q in package['queries'] if q['id'] == metric['actualBinding']['queryId'])
        query['sql'] = 'SELECT 999 AS first_unpassed FROM agg_course_pass_stat a WHERE a.semester_id=:semester_id'
        status = method.algorithm_compatibility(package, self.reviewed)
        self.assertEqual(status['state'], 'unconfirmed')
        self.assertEqual(status['mismatchedMetricIds'], [])
        self.assertEqual(status['mismatchedApplicationQueryIds'], ['AI-C-04'])

    def test_source_sql_prose_or_technical_change_does_not_redefine_fixed_application_math(self):
        package = deepcopy(self.package)
        source = next(q for q in package['queries'] if q['layer'] == 'source')
        source['sql'] += '\n-- changed source SQL comment only'
        self.assertEqual(method.algorithm_compatibility(package, self.reviewed)['state'], 'confirmed')

    def test_unrelated_extra_metric_does_not_change_six_reviewed_c_definitions(self):
        package = deepcopy(self.package)
        extra = deepcopy(package['metrics'][0])
        extra['id'] = 'AI-OTHER-01'
        package['metrics'].append(extra)
        self.assertEqual(method.algorithm_compatibility(package, self.reviewed)['state'], 'confirmed')

    def test_registration_rechecks_active_algorithm_and_real_sys_rows(self):
        from backend.metric_verification import mapping_store
        package = deepcopy(self.package)
        query = next(q for q in package['queries'] if q['id'] == package['metrics'][0]['actualBinding']['queryId'])
        query['sql'] += '\nAND 1=0'
        with patch.object(mapping_store, 'get_head', return_value={'revisionId': 'fixture-active'}), \
                patch.object(mapping_store, 'registration_status', return_value=registration()) as actual, \
                patch.object(mapping_store, 'get_revision', return_value={'package': package}), \
                patch.object(method, 'LOADED_REVIEWED_DEFINITION', self.reviewed):
            status = method.registration_basis()
        actual.assert_called_once_with('fixture-active', module_id='ai-briefing')
        self.assertFalse(status['registered'])
        self.assertEqual(status['algorithmBasis']['state'], 'unconfirmed')

    def test_reference_hash_is_part_of_c_release_only(self):
        c_before = runtime.task_fingerprint(['C-PERFORMANCE'])['runtimeFingerprint']
        p_before = runtime.task_fingerprint(['P-COMPARE'])['runtimeFingerprint']
        with patch.object(method, 'LOADED_REFERENCE_SHA256', 'changed reviewed package fixture'):
            self.assertNotEqual(runtime.task_fingerprint(['C-PERFORMANCE'])['runtimeFingerprint'], c_before)
            self.assertEqual(runtime.task_fingerprint(['P-COMPARE'])['runtimeFingerprint'], p_before)


class ReadBasisTests(TestCase):
    def test_registered_scope_and_course_key_are_bound_and_attempt_type_is_unused(self):
        db = MagicMock()
        db.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        config = SimpleNamespace(engine='mysql', host='fixture-rds', database='fixture_source')
        with patch.object(method, 'database_config', return_value=config):
            result = method.read_basis(db, 'c.organization_id IN (%s)', ['fixture-college'],
                                      {'semester_id': 'fixture-term', 'course_id': 'fixture-course'}, [])
        executed = db.cursor.return_value.__enter__.return_value.execute.call_args_list
        self.assertEqual(executed[0].args[1], ['fixture-term', 'fixture-college', 'fixture-course'])
        self.assertIn('c.organization_id IN (%s)', executed[0].args[0])
        self.assertIn('g.semester_id=%s', executed[0].args[0])
        self.assertIn('g.is_retake=0', executed[0].args[0])
        self.assertNotIn('attempt_type', executed[0].args[0])
        self.assertEqual(result['sourceCoverage'], 'unknown')

    def test_sql_failure_is_explicit_and_safe(self):
        db = MagicMock()
        db.cursor.side_effect = RuntimeError('private connection password must not leave server')
        config = SimpleNamespace(engine='mysql', host='fixture-rds', database='fixture_source')
        with patch.object(method, 'database_config', return_value=config):
            result = method.read_basis(db, '1=1', [], {'semester_id': 'fixture-term'}, [])
        self.assertEqual(result['state'], 'pending')
        self.assertIn('RuntimeError', result['reason'])
        self.assertNotIn('password', result['reason'])
        self.assertIsNone(result.get('reference'))

"""Independent hand-calculated P/C cases; all rows are explicit development fixtures."""
from copy import deepcopy
import hashlib
import json
from unittest import TestCase
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.expert_resources import runtime, tasks


def actor(scope=None):
    return {'username': 'fixture-user', 'identity_id': 'fixture', 'permission_context': {
        'authorized': True, 'activeIdentityId': 'fixture', 'scopeFingerprint': 'fixture-scope',
        'actionPermissions': ['ai.analyze'], 'detailScope': scope or {'type': 'all'}}}


def course(course_id, module='fixture-module'):
    return {'course_id': course_id, 'course_name': 'fixture course', 'module': module,
            'requirement_type': 'fixture', 'credits': 2, 'recorded_plan_credits': 2,
            'credit_check': '字段值相同', 'suggested_term': '1', 'source_rows': 1,
            'updated_at': '2026-01-01'}


def aggregate(course_id='fixture-course', attempts=4, passed=3, failures=2, students=3):
    return {'course_id': course_id, 'semester_id': 'fixture-term', 'course_name': 'fixture course',
            'first_attempts': attempts, 'first_pass': passed, 'failures': failures, 'students': students,
            'rule_version': 'fixture-rule', 'calculated_at': '2026-01-01', 'organization_id': '35'}


def dependencies(task_id, legacy=False):
    item = tasks.definition(task_id)
    if legacy:
        catalog = json.loads(runtime.CATALOG.read_text(encoding='utf-8'))
        # transfer-plan-gap retains the original comparison handler and schema.
        fixture_id = 'transfer-plan-gap' if item['skillId'] == 'program-comparison' else item['skillId']
        content = deepcopy(next(s for s in catalog['skills'] if s['id'] == fixture_id))
        content['id'] = item['skillId']
    else:
        content = {'execution': {'processorId': item['processorId']},
                   'inputSchema': item['inputSchema'],
                   'outputSchema': {'type': 'object', 'required': ['schemaVersion', 'facts', 'coverage', 'evidence',
                                                                'conditions', 'issues', 'tables']},
                   'toolBindings': [{'serverId': 'fixture-data', 'toolName': item['handler']}]}
    server_id = content['toolBindings'][0]['serverId']
    return {'skills': [{'id': item['skillId'], 'name': 'fixture Skill', 'version': '1.0', 'content': content}],
            'mcps': [{'id': server_id, 'name': 'fixture server', 'version': '1.0',
                      'content': {'tools': [{'name': b['toolName']} for b in content['toolBindings']]}}],
            'snapshot': [{'kind': 'skills', 'id': item['skillId'], 'version': '1.0', 'enabled': True},
                         {'kind': 'mcps', 'id': server_id, 'version': '1.0', 'enabled': True}]}


class RegistryTests(TestCase):
    def test_policy_editor_domains_follow_registered_rule_consumers(self):
        from backend.expert_resources.metadata import policy_domains
        self.assertEqual(policy_domains('course-performance'), [])
        self.assertEqual(policy_domains('graduation-progress'), [])
        self.assertEqual(policy_domains('graduation-audit'), [])
        self.assertEqual(policy_domains('graduation-condition-check'), ['graduation', 'degree'])
        self.assertEqual(policy_domains('transfer-recognition'), ['transfer'])
        self.assertEqual(policy_domains('recommendation-ranking'), ['recommendation'])
        self.assertEqual(policy_domains('unknown-custom-skill'), [])

    def test_seven_existing_methods_map_to_registered_tools_and_json_definitions(self):
        definitions = tasks.task_definitions()
        json.dumps(definitions)
        available = [d for d in definitions if d['available']]
        self.assertEqual(len(available), 8)
        self.assertEqual({d['skillId'] for d in available}, {'program-structure', 'program-comparison',
            'course-performance', 'transfer-plan-gap', 'transfer-history', 'graduation-progress', 'graduation-audit',
            'graduation-condition-check'})
        self.assertFalse(next(d for d in definitions if d['taskId'] == 'R-PREPARE')['available'])
        definitions[0]['inputSchema']['properties'].clear()
        self.assertTrue(tasks.definition('P-COMPARE')['inputSchema']['properties'])

    def test_only_bound_fixed_available_published_methods_resolve(self):
        deps = dependencies('P-COMPARE')
        expert = {'skillIds': ['program-comparison']}
        self.assertEqual(tasks.resolve_task('P-COMPARE', expert, deps)['skillVersion'], '1.0')
        for changed_expert, changed_deps in [({'skillIds': []}, deps), (expert, {**deps, 'snapshot': []}),
                (expert, {**deps, 'skills': []})]:
            with self.subTest(expert=changed_expert), self.assertRaises(ApiError):
                tasks.resolve_task('P-COMPARE', changed_expert, changed_deps)
        deps['snapshot'][0]['enabled'] = False
        with self.assertRaises(ApiError):
            tasks.resolve_task('P-COMPARE', expert, deps)

    def test_unregistered_wrong_or_double_entry_rejected_without_business_query(self):
        deps = dependencies('P-COMPARE')
        inputs = {'plan_id': 'A', 'target_plan_id': 'B', 'comparisonMode': 'all_course_ids'}
        with patch.object(runtime, 'connection') as db:
            for execution in [{'processorId': 'import:anything'},
                              {'processorId': 'program-comparison-v2', 'handler': 'compare_programs'},
                              {'handler': 'read_course_performance'}]:
                deps['skills'][0]['content']['execution'] = execution
                with self.subTest(execution=execution), self.assertRaises(ApiError):
                    tasks.run_task('P-COMPARE', inputs, actor(), deps)
            db.assert_not_called()

    def test_tool_binding_missing_or_wrong_version_rejected(self):
        deps = dependencies('C-PERFORMANCE')
        deps['mcps'][0]['content']['tools'] = []
        with self.assertRaises(ApiError):
            tasks.resolve_task('C-PERFORMANCE', {'skillIds': ['course-performance']}, deps)

    def test_policy_tasks_expose_real_adapter_and_algorithm_readiness_separately(self):
        catalog = {item['taskId']: item for item in tasks.task_definitions()}
        expected = {'P-SUPPORT', 'C-SUPPORT', 'C-CHANGE', 'T-RECOGNITION', 'T-POLICY', 'T-POLICY-SCENARIO',
                    'R-RANK', 'R-CHECK', 'R-SCENARIO', 'G-CHECK', 'G-CHANGE', 'P-PATH', 'P-CHANGE', 'P-DOCUMENT'}
        self.assertTrue(expected <= set(catalog))
        self.assertTrue(catalog['G-CHECK']['realAdapterAvailable'])
        self.assertTrue(catalog['G-CHECK']['algorithmImplemented'])
        self.assertTrue(catalog['G-CHECK']['available'])
        self.assertFalse(catalog['G-CHECK']['formalAvailable'])
        self.assertTrue(any('learningBasis' in value for value in catalog['G-CHECK']['requiredDependencies']))
        self.assertFalse(catalog['P-SUPPORT']['realAdapterAvailable'])
        self.assertTrue(catalog['P-SUPPORT']['algorithmImplemented'])
        with patch.object(runtime, 'connection') as db:
            with self.assertRaises(ApiError):
                tasks.run_task('G-CHECK', {'plan_id': 'fixture', 'populationRef': 'plan:fixture', 'year': '2026',
                    'ruleRef': {'ruleId': 'fixture', 'version': '1'}, 'achievements': [{'passed': True}]}, actor(), {})
            db.assert_not_called()

    def test_single_comparison_mode_defaults_and_fields_have_chinese_labels(self):
        item = tasks.definition('P-COMPARE')
        self.assertEqual(item['inputSchema']['properties']['previewLimit']['title'], '预览记录数')
        inputs = tasks._task_inputs(item, {'plan_id': 'A', 'target_plan_id': 'B'})
        self.assertEqual(inputs['comparisonMode'], 'all_course_ids')
        deps = dependencies('C-PERFORMANCE')
        deps['snapshot'][1]['version'] = 'other'
        with self.assertRaises(ApiError):
            tasks.resolve_task('C-PERFORMANCE', {'skillIds': ['course-performance']}, deps)

    def test_unsupported_conditions_and_sql_fail_before_query(self):
        base = {'plan_id': 'A', 'target_plan_id': 'B', 'comparisonMode': 'all_course_ids'}
        with patch.object(runtime, 'connection') as db:
            for extra in [{'excludePublicCourses': True}, {'sql': 'select 1'},
                          {'comparisonMode': 'professional_courses'}, {'previewLimit': True}]:
                with self.subTest(extra=extra), self.assertRaises(ApiError):
                    tasks.run_task('P-COMPARE', {**base, **extra}, actor(), dependencies('P-COMPARE'))
            db.assert_not_called()

    def test_legacy_adapter_does_not_change_original_or_query_current_rows(self):
        original = {'status': 'passed', 'result': {'data': {'count': 4}, 'tables': [{'rows': [{'course_id': 'c1'}]}]}}
        with patch.object(runtime, 'connection') as db:
            adapted = tasks.legacy_result(original, 'fixture-turn')
            db.assert_not_called()
        self.assertEqual(adapted['legacyResultId'], 'legacy:fixture-turn')
        self.assertEqual(adapted['result']['schemaVersion'], 'legacy')
        self.assertFalse(adapted['result']['comparisonCapability']['replayFromRetainedInput'])
        self.assertNotIn('schemaVersion', original['result'])
        self.assertNotIn('evidence', adapted['result'])

    def test_new_fingerprint_covers_tasks_shared_sources_and_keeps_old_scheme(self):
        self.assertEqual(runtime.fingerprint(), runtime._LOADED_FINGERPRINT)
        self.assertEqual(runtime.fingerprint('runtime-v1'), runtime._LOADED_FINGERPRINT)
        manifest = runtime.task_fingerprint(['P-COMPARE'])
        paths = {item['path'] for item in manifest['runtimeDependencies']}
        self.assertIn('code/backend/expert_resources/tasks.py', paths)
        self.assertIn('code/backend/metric_verification/database.py', paths)
        self.assertIn('code/backend/expert_resources/auth.py', paths)
        self.assertFalse(any('frontend' in p or 'store.py' in p for p in paths))
        with patch.object(tasks, 'LOADED_FINGERPRINT', hashlib.sha256(b'changed fixture task').hexdigest()):
            self.assertNotEqual(runtime.task_fingerprint(['P-COMPARE'])['runtimeFingerprint'], manifest['runtimeFingerprint'])
            self.assertEqual(runtime.fingerprint(), runtime._LOADED_FINGERPRINT)
        with patch.dict(runtime._LOADED_SHARED_HASHES, {'metric_verification/database.py': 'changed'}):
            self.assertNotEqual(runtime.task_fingerprint(['P-COMPARE'])['runtimeFingerprint'], manifest['runtimeFingerprint'])
        policy_paths = {item['path'] for item in runtime.task_fingerprint(['G-CHECK'])['runtimeDependencies']}
        self.assertTrue({'code/backend/expert_resources/policy_adapter.py', 'code/backend/expert_resources/matching.py',
                         'code/backend/expert_resources/policy_tasks.py', 'code/backend/expert_resources/rules.py'} <= policy_paths)


class ProgramTests(TestCase):
    def run_comparison(self, a, b, limit=20, grades=('2026', '2026'), legacy=False):
        plans = {'A': {'plan_id': 'A', 'plan_name': 'Fixture A', 'grade': grades[0]},
                 'B': {'plan_id': 'B', 'plan_name': 'Fixture B', 'grade': grades[1]}}
        with patch.object(runtime, 'connection'), patch.object(runtime, 'now', return_value='fixture-time'), \
                patch.object(runtime, 'authorized_plan', side_effect=lambda db, user, plan_id: plans[plan_id]), \
                patch.object(runtime, 'plan_courses', side_effect=lambda db, plan_id: deepcopy(a if plan_id == 'A' else b)):
            return tasks.run_task('P-COMPARE', {'plan_id': 'A', 'target_plan_id': 'B',
                'comparisonMode': 'all_course_ids', 'previewLimit': limit}, actor(), dependencies('P-COMPARE', legacy))

    def test_vf_p01_hand_calculated_sets_duplicates_and_both_directions(self):
        # Independent expected sets: A=1,2,3,4; B=3,4,5,6. Duplicate 1 does not add a course.
        result = self.run_comparison([course(str(n)) for n in [1, 1, 2, 3, 4]],
                                     [course(str(n)) for n in [3, 4, 5, 6]])['result']
        self.assertEqual(result['data']['来源方案课程种数'], 4)
        self.assertEqual(result['data']['目标方案课程种数'], 4)
        self.assertEqual(result['data']['共同课程种数'], 2)
        self.assertEqual(result['data']['合并去重课程种数'], 6)
        self.assertEqual(result['data']['来源独有课程种数'], 2)
        self.assertEqual(result['data']['目标独有课程种数'], 2)
        overlap = next(f for f in result['facts'] if f['factId'] == 'structure-overlap')
        target = next(f for f in result['facts'] if f['factId'] == 'target-coverage')
        self.assertEqual((overlap['numerator'], overlap['denominator'], overlap['value']), (2, 6, 33.33))
        self.assertEqual((target['numerator'], target['denominator'], target['value']), (2, 4, 50))
        self.assertEqual({r['course_id'] for r in result['tables'][0]['rows'] if r['对照状态'] == '来源独有'}, {'1', '2'})
        self.assertEqual({r['course_id'] for r in result['tables'][1]['rows'] if r['对照状态'] == '目标独有'}, {'5', '6'})

    def test_vf_p02_full_evidence_and_facts_independent_of_preview(self):
        a, b = [course(str(n)) for n in [1, 2, 3, 4]], [course(str(n)) for n in [3, 4, 5, 6]]
        small = self.run_comparison(a, b, 1)['result']
        large = self.run_comparison(a, b, 20)['result']
        for field in ['data', 'facts', 'coverage', 'evidence']:
            self.assertEqual(small[field], large[field], field)
        self.assertEqual([len(e['records']) for e in small['evidence']], [4, 4])
        self.assertEqual(small['tables'][0]['returnedRows'], 1)
        self.assertEqual(small['tables'][0]['totalRows'], 4)
        self.assertTrue(small['tables'][0]['truncated'])

    def test_vf_p03_unknown_ids_empty_sets_and_same_plan(self):
        result = self.run_comparison([course('1'), course(None)], [course('1'), course('2')])['result']
        self.assertEqual(result['coverage']['unknownCount'], 1)
        self.assertEqual(result['data']['来源方案课程种数'], 1)
        self.assertEqual(len(result['evidence'][0]['records']), 2)
        self.assertIn('子集', result['missingEvidence'][0])
        blocked = self.run_comparison([], [course('1')])
        self.assertEqual(blocked['status'], 'blocked')
        self.assertTrue(all(f['value'] is None for f in blocked['result']['facts'] if f['unit'] == '%'))
        with patch.object(runtime, 'connection'), patch.object(runtime, 'authorized_plan',
                return_value={'plan_id': 'A'}), patch.object(runtime, 'plan_courses', return_value=[course('1')]):
            with self.assertRaises(ApiError):
                runtime.run_tool('compare_programs', {'plan_id': 'A', 'target_plan_id': 'A'}, actor())

    def test_vf_p04_missing_classification_and_different_grade_disclosed(self):
        result = self.run_comparison([course('1', None)], [course('1')], grades=('2025', '2026'))['result']
        self.assertEqual(result['data']['模块分类缺失安排条数'], 1)
        self.assertTrue(any('年级不同' in text for text in result['limitations']))
        self.assertTrue(any(i['issueId'] == 'unknown-course-classification' for i in result['issues']))

    def test_old_published_handler_uses_same_calculation_with_old_schema_projection(self):
        result = self.run_comparison([course('1'), course('2')], [course('2'), course('3')], legacy=True)['result']
        self.assertEqual(result['data']['共同课程种数'], 1)
        self.assertEqual(result['schemaVersion'], '2.0')
        self.assertEqual(len(result['evidence']), 2)


class CourseTests(TestCase):
    def run_course(self, records, inputs=None, user=None, valid_term=True):
        inputs = {'semester_id': 'fixture-term', **(inputs or {})}
        queries = []
        def query(db, sql, params=()):
            queries.append((sql, list(params)))
            if 'FROM act_semester' in sql:
                return [{'semester_id': inputs['semester_id']}] if valid_term else []
            self.assertIn('agg_course_pass_stat', sql)
            return deepcopy(records)
        with patch.object(runtime, 'connection'), patch.object(runtime, 'now', return_value='fixture-time'), \
                patch.object(runtime, 'rows', side_effect=query):
            result = tasks.run_task('C-PERFORMANCE', inputs, user or actor(), dependencies('C-PERFORMANCE'))
        return result, queries

    def test_vf_c01_hand_calculated_person_times_and_failure_count(self):
        result, queries = self.run_course([aggregate()])
        rows = result['result']['tables'][0]['rows']
        self.assertEqual(rows[0]['first_pass_pct'], 75)
        self.assertEqual(rows[0]['failures'], 2)
        rate = next(f for f in result['result']['facts'] if f['factId'].endswith('first-pass-rate'))
        self.assertEqual((rate['numerator'], rate['denominator'], rate['value']), (3, 4, 75))
        self.assertEqual(result['result']['data']['跨行唯一学生人数'], None)
        self.assertNotIn('LIMIT', queries[1][0])

    def test_vf_c02_zero_and_missing_denominator_keep_distinct_reasons(self):
        result, _ = self.run_course([aggregate('zero', 0, 0), aggregate('missing', None, 0)])
        rows = result['result']['evidence'][0]['records']
        self.assertIsNone(rows[0]['first_pass_pct'])
        self.assertIsNone(rows[1]['first_pass_pct'])
        self.assertIn('为0', rows[0]['rate_reason'])
        self.assertIn('缺失', rows[1]['rate_reason'])
        self.assertEqual(rows[0]['first_attempts'], 0)
        self.assertIsNone(rows[1]['first_attempts'])

    def test_vf_c03_duplicate_grain_preserved_without_summing_students_or_ratios(self):
        result, _ = self.run_course([aggregate(), aggregate(attempts=6, passed=5, students=3)])
        self.assertEqual(result['status'], 'blocked')
        evidence = result['result']['evidence'][0]['records']
        self.assertEqual(len(evidence), 2)
        self.assertEqual([row['first_attempts'] for row in evidence], [4, 6])
        self.assertTrue(all(row['first_pass_pct'] is None for row in evidence))
        self.assertIsNone(result['result']['coverage']['uniqueStudentCount'])

    def test_vf_c04_conflicting_ratio_blocked_independent_facts_remain(self):
        result, _ = self.run_course([aggregate(passed=5)])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['result']['evidence'][0]['records'][0]['first_pass'], 5)
        self.assertIsNone(result['result']['tables'][0]['rows'][0]['first_pass_pct'])
        self.assertIn('大于', result['missingEvidence'][0] if '大于' in result['missingEvidence'][0] else result['result']['issues'][0]['requiredEvidence'])

    def test_vf_c05_new_full_input_single_course_college_and_preview(self):
        records = [aggregate('a'), aggregate('b')]
        small, queries = self.run_course(records, {'college_id': '35', 'course_id': 'a', 'previewLimit': 1})
        large, _ = self.run_course(records, {'college_id': '35', 'course_id': 'a', 'previewLimit': 20})
        for key in ['facts', 'coverage', 'evidence']:
            self.assertEqual(small['result'][key], large['result'][key])
        self.assertIn('a.course_id=%s', queries[1][0])
        self.assertEqual(queries[1][1], ['fixture-term', '35', 'a'])
        fresh, clear_queries = self.run_course(records, {'semester_id': 'new-term'})
        self.assertNotIn('a.course_id=%s', clear_queries[1][0])
        self.assertEqual(clear_queries[1][1], ['new-term'])
        self.assertNotIn('college_id', fresh['result']['scope'])
        self.assertEqual(small['result']['tables'][0]['returnedRows'], 1)
        self.assertEqual(small['result']['evidence'][0]['retainedRowCount'], 2)

    def test_invalid_term_and_cross_college_fail_closed(self):
        with self.assertRaises(ApiError):
            self.run_course([], valid_term=False)
        with patch.object(runtime, 'connection'), patch.object(runtime, 'rows') as query:
            with self.assertRaises(ApiError):
                tasks.run_task('C-PERFORMANCE', {'semester_id': 'fixture', 'college_id': '34'},
                    actor({'type': 'college', 'collegeIds': ['35']}), dependencies('C-PERFORMANCE'))
            query.assert_not_called()

    def test_privately_supplied_authorization_callback_runs_before_business_query(self):
        user = actor()
        user['_authorize'] = lambda: actor({'type': 'missing'})
        with patch.object(runtime, 'connection') as db:
            with self.assertRaises(ApiError):
                runtime.run_tool('read_course_performance', {'semester_id': 'fixture'}, user, schema_version='2.0')
            db.assert_not_called()

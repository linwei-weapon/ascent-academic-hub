"""Publication, purpose isolation, delegation and physical-slot regressions.

All school values below are explicit isolated test fixtures. Integration evidence
is recorded separately from these tests.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from uuid import uuid4

from backend.api.envelope import ApiError
from backend.expert_resources import store, execution, processing, briefing, rules
from backend.tests.test_expert_resources_store import success

ACTOR = {'username': 'fixture-manager', 'identity_id': 'fixture-identity', 'menus': [],
         'permission_context': {'authorized': True, 'activeIdentityId': 'fixture-identity',
          'scopeFingerprint': 'fixture-scope', 'actionPermissions': ['system.manage', 'ai.analyze'],
          'detailScope': {'type': 'all', 'collegeIds': []}}}


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'EXPERT_RESOURCES_DB_PATH': str(Path(self.tmp.name) / 'control.sqlite')})
        self.env.start()
        catalog = json.loads((store.CODE / 'expert-resources/catalog.json').read_text(encoding='utf-8'))
        mcp = {'id': 'education-data', 'name': 'fixture server', 'tools': [t for t in catalog['mcps'][0]['tools'] if t['name'] in {'read_course_performance', 'read_program_structure'}]}
        skill = {'id': 'course-performance', 'name': 'fixture skill', 'execution': {'handler': 'read_course_performance'},
                 'toolBindings': [{'serverId': 'education-data', 'toolName': 'read_course_performance'}]}
        second = {'id': 'program-structure', 'name': 'fixture structure', 'execution': {'handler': 'read_program_structure'},
                  'toolBindings': [{'serverId': 'education-data', 'toolName': 'read_program_structure'}]}
        seed = Path(self.tmp.name) / 'seed.json'
        seed.write_text(json.dumps({'mcps': [mcp], 'skills': [skill, second], 'experts': [
          {'id': 'course', 'name': 'fixture course expert', 'skillIds': ['course-performance']},
          {'id': 'program', 'name': 'fixture program expert', 'skillIds': ['program-structure']}]}), encoding='utf-8')
        store.initialize(seed)
        rules.initialize()
        execution.initialize()
        processing.initialize()
        briefing.initialize()
        for kind, rid in [('mcps', 'education-data'), ('skills', 'course-performance'), ('skills', 'program-structure'), ('experts', 'course'), ('experts', 'program')]:
            item = store.test_resource(kind, rid, 1, {}, ACTOR, success)
            if kind != 'mcps':
                store.review_resource(kind, rid, 1, item['draft']['test']['runId'], True, 'explicit isolated test', ACTOR)
            store.publish_resource(kind, rid, 1, ACTOR)
        self.ready = patch.dict(processing._state, {'ready': True, 'recoveryState': 'ready'})
        self.ready.start()
        self.start = patch.object(execution, 'start_execution')
        self.start.start()
        self.mapping = patch.object(briefing, 'mapping_condition', return_value={'moduleId':'ai-briefing','revisionId':'fixture-map'})
        self.mapping.start()

    def tearDown(self):
        self.start.stop()
        self.mapping.stop()
        self.ready.stop()
        self.env.stop()
        self.tmp.cleanup()

    def preset(self, **changes):
        return briefing.save({'name': 'fixture observations', 'question': '查看首修表现', 'expertId': 'course',
            'taskId': 'C-PERFORMANCE', 'input': {'semester_id': 'fixture-semester'},
            'scope': {'type': 'all', 'collegeIds': []}, **changes}, ACTOR)

    def operation(self, revision=1):
        return {'expectedRevision': revision, 'clientRequestId': str(uuid4())}

    def outcome(self, mode='observation'):
        return {'status': 'passed', 'summary': 'fixture facts saved', 'trace': [], 'missingEvidence': [],
                'result': {'status': 'limited', 'taskId': 'C-PERFORMANCE', 'scope': {'semester_id': 'fixture-semester'},
                'facts': [], 'issues': [], 'publishMode': mode, 'validationBasis': {
                  'firstAttemptSemantics': {'state': 'confirmed_current_input'},
                  'ruleCompatibility': {'state': 'confirmed_current_input'}, 'metricRegistration': True,
                  'metricAlgorithmBasis': {'state': 'confirmed'},
                  'frozenInput': {'sha256': 'fixture-sha'},
                  'independentRecompute': {'state': 'passed', 'inputSha256': 'fixture-sha', 'checks': {'recomputed': True}},
                  'metricRefs': [{'metricCode': 'AI-C-0' + str(i), 'registered': True} for i in range(1, 7)],
                  'mappingRef': {'revisionId': 'fixture-map'}},
                'evidence': [{'evidenceId': 'fixture-evidence', 'records': [{'course_id': 'fixture-course', 'N': 10, 'P': 7}]}]}}

    def trial(self, preset):
        view = briefing.execute(preset['id'], self.operation(preset['revision']), ACTOR, operation='trial')
        execution._terminal(view['id'], 'partial', 'fixture trial', outcome=self.outcome(), validated_actor=ACTOR)
        return view

    def publish(self, preset):
        self.trial(preset)
        view = briefing.execute(preset['id'], self.operation(preset['revision']), ACTOR, operation='run')
        execution._terminal(view['id'], 'partial', 'fixture formal', outcome=self.outcome(), validated_actor=ACTOR)
        with store._db() as db:
            return dict(db.execute('SELECT * FROM er_brief_publication WHERE result_id=?', (view['id'],)).fetchone())

    def test_additive_migrations_repeat_without_reset(self):
        preset = self.preset()
        execution.initialize(); processing.initialize(); briefing.initialize()
        self.assertEqual(briefing.presets(ACTOR)['items'][0]['id'], preset['id'])
        self.assertEqual(processing.view(ACTOR)['effective']['revision'], 1)

    def test_manual_run_does_not_require_automatic_fields_or_grant(self):
        preset = self.preset()
        self.assertIsNone(preset['schedule'])
        publication = self.publish(preset)
        self.assertEqual(publication['status'], 'published')
        self.assertFalse(processing.effective()['automaticEnabled'])

    def test_college_grant_uses_school_organization_key_and_rejects_unknown_college(self):
        cursor = Mock()
        cursor.fetchone.return_value = {'organization_id': '39'}
        db = Mock()
        db.cursor.return_value.__enter__ = Mock(return_value=cursor)
        db.cursor.return_value.__exit__ = Mock(return_value=False)
        connection = Mock()
        connection.return_value.__enter__ = Mock(return_value=db)
        connection.return_value.__exit__ = Mock(return_value=False)
        body = {'scope': {'type': 'college', 'collegeIds': ['39']},
                'taskIds': ['C-PERFORMANCE'],
                'validUntil': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        with patch.object(processing, 'connection', connection):
            result = processing.grant(body, ACTOR)
            cursor.execute.assert_called_once_with(
                'SELECT organization_id FROM act_organization WHERE organization_id=%s AND is_college=1', ('39',))
            self.assertEqual(result['grants'][0]['scope'], body['scope'])
            cursor.fetchone.return_value = None
            with self.assertRaises(ApiError):
                processing.grant({**body, 'scope': {'type': 'college', 'collegeIds': ['missing']}}, ACTOR)
        with store._db() as control:
            self.assertEqual(control.execute('SELECT COUNT(*) FROM er_service_grant').fetchone()[0], 1)

    def test_trial_is_private_and_not_in_personal_history(self):
        preset = self.preset()
        trial = self.trial(preset)
        self.assertEqual(store.list_research(ACTOR)['total'], 0)
        self.assertEqual(briefing.publications(ACTOR)['total'], 0)
        for fn in [lambda: execution.get(trial['id'], ACTOR), lambda: execution.get_result(trial['id'], ACTOR), lambda: store.get_research(trial['researchId'], ACTOR)]:
            with self.assertRaises(ApiError): fn()
        other = deepcopy(ACTOR); other['username'] = 'different-manager'
        self.assertEqual(briefing.executions(preset['id'], other)['total'], 0)
        with self.assertRaises(ApiError):
            briefing.candidate_evidence(preset['id'], trial['id'], 'fixture-evidence', other)

    def test_candidate_evidence_owner_and_scope(self):
        preset = self.preset(); trial = self.trial(preset)
        evidence = briefing.candidate_evidence(preset['id'], trial['id'], 'fixture-evidence', ACTOR)
        self.assertEqual(evidence['rows'][0]['N'], 10)
        self.assertNotIn('records', briefing.executions(preset['id'], ACTOR)['items'][0]['outcome']['result']['evidence'][0])

    def test_run_requires_current_trial_and_requeries(self):
        preset = self.preset()
        with self.assertRaises(ApiError): briefing.execute(preset['id'], self.operation(), ACTOR, operation='run')
        trial = self.trial(preset)
        formal = briefing.execute(preset['id'], self.operation(), ACTOR, operation='run')
        self.assertNotEqual(formal['id'], trial['id'])
        self.assertEqual(formal['state'], 'queued')

    def test_condition_change_invalidates_trial_schedule_change_does_not(self):
        preset = self.preset(); self.trial(preset)
        updated = briefing.save({**{k: preset[k] for k in briefing.FIELDS if k in preset}, 'expectedRevision': 1,
          'schedule': {'kind': 'weekly', 'weekday': 0, 'time': '08:00', 'timezone': 'Asia/Shanghai'}}, ACTOR, preset['id'])
        self.assertTrue(updated['trialValid'])
        updated = briefing.save({**{k: updated[k] for k in briefing.FIELDS if k in updated}, 'expectedRevision': 2,
          'input': {'semester_id': 'other-semester'}}, ACTOR, preset['id'])
        self.assertFalse(updated['trialValid'])

    def test_formal_save_and_publication_rollback_together(self):
        preset = self.preset(); self.trial(preset)
        run = briefing.execute(preset['id'], self.operation(), ACTOR, operation='run')
        with patch.object(execution, 'MAX_BYTES', 20), self.assertRaises(ApiError):
            execution._terminal(run['id'], 'partial', 'too big', outcome=self.outcome(), validated_actor=ACTOR)
        self.assertEqual(briefing.publications(ACTOR)['total'], 0)
        self.assertEqual(briefing.executions(preset['id'], ACTOR)['items'][0]['state'], 'queued')

    def test_observation_rejected_if_recompute_or_registered_basis_missing(self):
        preset = self.preset(); self.trial(preset)
        run = briefing.execute(preset['id'], self.operation(), ACTOR, operation='run')
        outcome = self.outcome(); outcome['result']['validationBasis']['metricRefs'] = []
        with self.assertRaises(ApiError): execution._terminal(run['id'], 'partial', 'fixture invalid basis', outcome=outcome, validated_actor=ACTOR)
        self.assertEqual(briefing.publications(ACTOR)['total'], 0)

    def test_fact_only_is_labeled_and_not_silently_observation(self):
        preset = self.preset(); self.trial(preset)
        run = briefing.execute(preset['id'], self.operation(), ACTOR, operation='run')
        execution._terminal(run['id'], 'partial', 'raw fields', outcome=self.outcome('facts_only'), validated_actor=ACTOR)
        self.assertEqual(briefing.publications(ACTOR)['items'][0]['outcome']['result']['publishMode'], 'facts_only')

    def test_saved_reference_derives_server_inputs_without_query_or_task_selection(self):
        publication = self.publish(self.preset())
        with patch('backend.expert_resources.runtime.connection') as business_query:
            request = {'clientRequestId':str(uuid4()),'expertId':'program','mode':'selected_task',
                       'readMode':'saved','publicationId':publication['id'],'sourceResultId':publication['result_id'],'input':{}}
            result = execution.submit(request, ACTOR, start=False)
            self.assertEqual(result['submittedRequest']['input']['taskId'], 'C-PERFORMANCE')
            self.assertEqual(result['submittedRequest']['input']['semester_id'], 'fixture-semester')
            business_query.assert_not_called()

    def test_withdrawn_ancestor_blocks_saved_clones_and_live_consumption(self):
        publication = self.publish(self.preset())
        source = {'publicationId': publication['id'], 'sourceResultId': publication['result_id']}
        copies = []
        for mode in ['saved', 'live', 'saved']:
            request = {'clientRequestId': str(uuid4()), 'expertId': 'course', 'mode': 'selected_task',
                       'readMode': mode, 'input': {'taskId': 'C-PERFORMANCE', 'semester_id': 'fixture-semester'}, **source}
            copy = execution.submit(request, ACTOR, start=False)
            outcome = briefing.resolve_reference(request, ACTOR) if mode == 'saved' else self.outcome()
            execution._terminal(copy['id'], 'partial', 'fixture copy', outcome=outcome, validated_actor=ACTOR)
            self.assertEqual(execution.get_result(copy['id'], ACTOR)['sourcePublicationRef'],
                             {'publicationId': publication['id'], 'resultId': publication['result_id']})
            copies.append(copy['id'])
            source = {'sourceResultId': copy['id']}
        briefing.withdraw(publication['id'], {**self.operation(), 'reason': 'fixture ancestor correction'}, ACTOR)
        for rid in copies:
            # Historical viewing is retained; starting a new use is rejected.
            self.assertEqual(execution.get_result(rid, ACTOR)['kind'], 'analysis')
            with self.assertRaises(ApiError): briefing.resolve_reference({'sourceResultId': rid}, ACTOR)
            for mode in ['saved', 'live']:
                with self.assertRaises(ApiError):
                    execution.submit({'clientRequestId': str(uuid4()), 'expertId': 'course', 'mode': 'selected_task',
                                      'readMode': mode, 'sourceResultId': rid,
                                      'input': {'taskId': 'C-PERFORMANCE', 'semester_id': 'fixture-semester'}}, ACTOR, start=False)

    def test_saved_course_explanation_uses_full_observation_set_without_database(self):
        publication = self.publish(self.preset())
        observed = [{'course_id': str(i), 'course_name': 'fixture-'+str(i), 'first_attempts':100,
                     'first_pass':70, 'first_unpassed':30, 'first_pass_pct':70, 'observation':True,
                     'below_scope_baseline':True} for i in range(1, 8)]
        with store._db(write=True) as db:
            er = execution._row(db, publication['result_id'])
            saved = json.loads(db.execute('SELECT outcome FROM er_turn WHERE id=?', (er['turn_id'],)).fetchone()['outcome'])
            saved['result'].update({'observations':observed,'observationBaseline':{'ratePct':85,'population':'fixture scope'},
                                   'limitations':['fixture unknown historical alignment']})
            saved['result']['evidence'].append({'evidenceId':'course-observations','records':observed})
            db.execute('UPDATE er_turn SET outcome=? WHERE id=?', (store._json(saved), er['turn_id']))
        with patch('backend.expert_resources.runtime.connection') as query:
            selected = briefing.resolve_reference({'publicationId':publication['id'],'objectId':'6'}, ACTOR)
            explanation = selected['result']['interpretation']
            self.assertIn('第6条，共7条', explanation['text'])
            self.assertIn('U=30', explanation['text'])
            self.assertIn('85%', explanation['text'])
            self.assertIn('fixture unknown historical alignment', explanation['text'])
            self.assertEqual(explanation['objectRef'], {'course_id':'6'})
            query.assert_not_called()
        unselected = briefing.resolve_reference({'publicationId':publication['id'],'objectId':'fixture-course'}, ACTOR)
        self.assertIn('没有可用的已保存观察选入依据', unselected['result']['interpretation']['text'])

    def test_withdrawn_facts_are_removed_from_new_analysis_context_but_history_remains(self):
        publication = self.publish(self.preset())
        request = {'clientRequestId':str(uuid4()), 'expertId':'course', 'mode':'selected_task',
                   'readMode':'live','publicationId':publication['id'],
                   'input':{'taskId':'C-PERFORMANCE','semester_id':'fixture-semester'}}
        run = execution.submit(request, ACTOR, start=False)
        outcome = self.outcome(); outcome['result']['facts'] = [{'factId':'fixture-fact','value':123}]
        execution._terminal(run['id'],'partial','fixture live reference',outcome=outcome,validated_actor=ACTOR)
        with store._db() as db:
            turn = db.execute('SELECT * FROM er_turn WHERE id=?',(run['turnId'],)).fetchone()
            self.assertEqual(execution._history_entry(db,turn,ACTOR)['facts'][0]['value'],123)
        briefing.withdraw(publication['id'],{**self.operation(),'reason':'fixture reference invalid'},ACTOR)
        with store._db() as db:
            turn = db.execute('SELECT * FROM er_turn WHERE id=?',(run['turnId'],)).fetchone()
            context = execution._history_entry(db,turn,ACTOR)
        self.assertEqual(context['facts'],[])
        self.assertEqual(context['scope'],{})
        self.assertEqual(context['referenceState'],'invalid')
        self.assertEqual(execution.get_result(run['id'],ACTOR)['result']['facts'][0]['value'],123)

    def test_history_marks_withdrawn_source_without_rewriting_saved_facts(self):
        publication = self.publish(self.preset())
        run = execution.submit({'clientRequestId': str(uuid4()), 'expertId': 'course',
                                'mode': 'selected_task', 'readMode': 'live',
                                'publicationId': publication['id'],
                                'input': {'taskId': 'C-PERFORMANCE', 'semester_id': 'fixture-semester'}},
                               ACTOR, start=False)
        outcome = self.outcome()
        outcome['result']['facts'] = [{'factId': 'fixture-fact', 'value': 123}]
        execution._terminal(run['id'], 'partial', 'fixture reference', outcome=outcome, validated_actor=ACTOR)
        with store._db() as db:
            before = db.execute('SELECT outcome FROM er_turn WHERE id=?', (run['turnId'],)).fetchone()['outcome']
        briefing.withdraw(publication['id'], {**self.operation(), 'reason': 'fixture withdrawal'}, ACTOR)
        with patch('backend.expert_resources.runtime.connection') as query:
            history = store.get_research(run['researchId'], ACTOR)
            query.assert_not_called()
        turn = history['turns'][0]
        self.assertEqual(turn['referenceState'], 'invalid')
        self.assertIn('撤回', turn['referenceReason'])
        self.assertEqual(turn['result']['facts'][0]['value'], 123)
        with store._db() as db:
            after = db.execute('SELECT outcome FROM er_turn WHERE id=?', (run['turnId'],)).fetchone()['outcome']
        self.assertEqual(before, after)

    def test_scope_change_does_not_expose_old_full_school_execution(self):
        preset = self.preset(); publication = self.publish(preset)
        updated = briefing.save({**{k:preset[k] for k in briefing.FIELDS if k in preset},'expectedRevision':1,
            'input':{'semester_id':'fixture-semester','college_id':'A'},'scope':{'type':'college','collegeIds':['A']}},ACTOR,preset['id'])
        academy = deepcopy(ACTOR); academy['permission_context']['detailScope']={'type':'college','collegeIds':['A']}
        self.assertIsNone(briefing.presets(academy)['items'][0]['latestExecution'])
        self.assertEqual(briefing.executions(preset['id'],academy)['total'],0)
        self.assertEqual(briefing.service_executions(academy)['total'],0)

    def test_current_instance_recovery_recheck_does_not_interrupt_live_queued_work(self):
        preset=self.preset(); run=briefing.execute(preset['id'],self.operation(),ACTOR)
        self.assertTrue(processing.recover()['ready'])
        self.assertEqual(briefing.executions(preset['id'],ACTOR)['items'][0]['state'],'queued')

    def test_mapping_change_invalidates_trial_without_relabeling_old_facts_wrong(self):
        preset=self.preset(); publication=self.publish(preset)
        with patch.object(briefing,'mapping_condition',return_value={'moduleId':'ai-briefing','revisionId':'changed-fixture-map'}):
            self.assertFalse(briefing.presets(ACTOR)['items'][0]['trialValid'])
            self.assertFalse(briefing.publication(publication['id'],ACTOR)['currentAnalysisConditions'])
            self.assertTrue(briefing.publication(publication['id'],ACTOR)['applicable'])

    def test_withdraw_idempotent_revision_and_reference_invalidity(self):
        publication = self.publish(self.preset())
        body = {**self.operation(), 'reason': 'fixture confirmed error'}
        first = briefing.withdraw(publication['id'], body, ACTOR)
        self.assertEqual(first['status'], 'withdrawn')
        self.assertEqual(briefing.withdraw(publication['id'], body, ACTOR)['publicationSequence'], first['publicationSequence'])
        self.assertEqual(briefing.publications(ACTOR)['total'], 0)
        self.assertEqual(briefing.publications(ACTOR, history=True)['total'], 1)
        with self.assertRaises(ApiError): briefing.resolve_reference({'publicationId': publication['id']}, ACTOR)
        self.assertEqual(briefing.evidence(publication['id'], 'fixture-evidence', ACTOR)['publicationStatus'], 'withdrawn')

    def test_late_explanation_cannot_revive_withdrawn_publication(self):
        publication = self.publish(self.preset())
        briefing.withdraw(publication['id'], {**self.operation(), 'reason': 'fixture correction'}, ACTOR)
        with store._db(write=True) as db:
            db.execute("UPDATE er_execution SET lease='fixture-lease',explanation_state='running' WHERE id=?", (publication['result_id'],))
            row = execution._row(db, publication['result_id'])
            self.assertFalse(briefing.append_explanation(db, row, {'result': {'explanation': {'mode': 'validated_references'}}}, 'fixture-lease'))

    def test_publication_reader_scope_without_private_owner_bypass(self):
        publication = self.publish(self.preset())
        reader = deepcopy(ACTOR); reader['username'] = 'another-reader'; reader['permission_context']['actionPermissions'] = ['ai.analyze']
        self.assertTrue(briefing.publication(publication['id'], reader)['applicable'])
        with self.assertRaises(ApiError): execution.get_result(publication['result_id'], reader)
        reader['permission_context']['detailScope'] = {'type': 'college', 'collegeIds': ['A']}
        with self.assertRaises(ApiError): briefing.publication(publication['id'], reader)

    def test_logical_submission_deduplicates_and_changed_payload_conflicts(self):
        preset = self.preset(); body = self.operation()
        one = briefing.execute(preset['id'], body, ACTOR)
        self.assertEqual(briefing.execute(preset['id'], body, ACTOR)['id'], one['id'])
        with self.assertRaises(ApiError): briefing.execute(preset['id'], {**body, 'expectedRevision': 2}, ACTOR)

    def test_physical_explanation_occupies_preset_after_fact_terminal(self):
        preset = self.preset(); trial = self.trial(preset)
        with store._db(write=True) as db: db.execute('UPDATE er_execution SET worker_finished=0 WHERE id=?', (trial['id'],))
        with self.assertRaises(ApiError): briefing.execute(preset['id'], self.operation(), ACTOR, operation='run')

    def test_registered_service_has_no_manage_and_revocation_is_immediate(self):
        gid = str(uuid4()); until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with store._db(write=True) as db:
            db.execute('INSERT INTO er_service_grant VALUES (?,1,\'active\',?,?,?,?,?,?,NULL)', (gid, store._json({'type':'college','collegeIds':['A']}), store._json(['C-PERFORMANCE']), until, ACTOR['username'], ACTOR['identity_id'], store._now()))
        service = processing.service_actor(gid, 'C-PERFORMANCE', {'type': 'college', 'collegeIds': ['A']})
        self.assertEqual(service['permission_context']['actionPermissions'], ['ai.analyze'])
        with self.assertRaises(ApiError): processing.publication_manager(service)
        with self.assertRaises(ApiError): processing.service_actor(gid, 'C-PERFORMANCE', {'type':'all','collegeIds':[]})
        processing.revoke(gid, 1, ACTOR)
        with self.assertRaises(ApiError): processing.service_actor(gid, 'C-PERFORMANCE', {'type':'college','collegeIds':['A']})

    def test_grant_renewal_keeps_authority_fingerprint_and_revocation_still_blocks(self):
        gid = str(uuid4()); now = datetime.now(timezone.utc)
        scope = {'type':'all','collegeIds':[]}
        with store._db(write=True) as db:
            db.execute('INSERT INTO er_service_grant VALUES (?,1,\'active\',?,?,?,?,?,?,NULL)',
                       (gid, store._json(scope), store._json(['C-PERFORMANCE']), (now+timedelta(minutes=10)).isoformat(),
                        ACTOR['username'], ACTOR['identity_id'], store._now()))
        before = processing.service_actor(gid, 'C-PERFORMANCE', scope)
        processing.renew(gid, 1, (now+timedelta(hours=1)).isoformat(), ACTOR)
        self.assertEqual(store._identity(before), store._identity(processing.service_actor(gid, 'C-PERFORMANCE', scope)))
        processing.revoke(gid, 2, ACTOR)
        with self.assertRaises(ApiError): processing.service_actor(gid, 'C-PERFORMANCE', scope)

    def test_no_automatic_enabling_without_actual_config_and_grant(self):
        preset = self.preset(); self.trial(preset)
        with self.assertRaises(ApiError): briefing.enable(preset['id'], self.operation(), ACTOR)
        self.assertFalse(briefing.presets(ACTOR)['items'][0]['enabled'])

    def test_recovery_blocks_live_old_worker_and_recycled_pid_is_not_killed(self):
        preset = self.preset(); run = briefing.execute(preset['id'], self.operation(), ACTOR)
        with store._db(write=True) as db:
            db.execute("UPDATE er_execution SET worker_pid=123,worker_created='old-time',service_instance='old-instance',worker_finished=0 WHERE id=?", (run['id'],))
        with patch.object(processing, 'process_identity', return_value='old-time'):
            self.assertFalse(processing.recover()['ready'])
        with patch.object(processing, 'process_identity', return_value='new-unrelated-time'):
            self.assertTrue(processing.recover()['ready'])
        self.assertEqual(briefing.executions(preset['id'], ACTOR)['items'][0]['state'], 'failed')

    def test_recheck_blocks_unheld_current_worker_then_recovers_once(self):
        preset = self.preset(); run = briefing.execute(preset['id'], self.operation(), ACTOR)
        with store._db(write=True) as db:
            db.execute("UPDATE er_execution SET worker_pid=123,worker_created='owned-time',service_instance=?,worker_finished=0,phase='recovery_blocked' WHERE id=?",
                       (processing.INSTANCE, run['id']))
        with patch.object(processing, 'process_identity', return_value='owned-time'):
            self.assertFalse(processing.recover()['ready'])
        with patch.object(processing, 'process_identity', return_value=None), patch.object(briefing, 'recover_registered') as resume:
            self.assertTrue(processing.recover()['ready'])
            self.assertTrue(processing.recover()['ready'])
            resume.assert_called_once()
        self.assertEqual(briefing.executions(preset['id'], ACTOR)['items'][0]['state'], 'failed')

    def test_recheck_preserves_current_held_worker(self):
        preset = self.preset(); run = briefing.execute(preset['id'], self.operation(), ACTOR)
        with store._db(write=True) as db:
            db.execute("UPDATE er_execution SET worker_pid=123,worker_created='owned-time',service_instance=?,worker_finished=0,phase='querying',lease='fixture-lease' WHERE id=?",
                       (processing.INSTANCE, run['id']))
        with patch.dict(execution._supervisor_active, {run['id']: 'fixture-lease'}), patch.object(processing, 'process_identity') as inspect:
            self.assertTrue(processing.recover()['ready'])
            inspect.assert_not_called()
        self.assertEqual(briefing.executions(preset['id'], ACTOR)['items'][0]['state'], 'queued')

    def test_service_queue_claim_uses_frozen_window_and_started_work_may_finish(self):
        now = datetime.now(timezone.utc)
        window = {'start': (now-timedelta(minutes=1)).isoformat(), 'end': (now+timedelta(minutes=1)).isoformat()}
        preset = self.preset(activeWindow=window)
        self.trial(preset)
        gid = str(uuid4())
        with store._db(write=True) as db:
            db.execute('INSERT INTO er_service_grant VALUES (?,1,\'active\',?,?,?,?,?,?,NULL)',
                       (gid, store._json({'type':'all','collegeIds':[]}), store._json(['C-PERFORMANCE']),
                        (now+timedelta(hours=1)).isoformat(), ACTOR['username'], ACTOR['identity_id'], store._now()))
        service = processing.service_actor(gid, 'C-PERFORMANCE', {'type':'all','collegeIds':[]})
        with store._db(write=True) as db:
            run = briefing._submit(db, briefing._row(db, preset['id']), service, 'run', str(uuid4()), trigger='fixture-automatic')
            frozen = json.loads(execution._row(db, run['id'])['request'])
        self.assertEqual(frozen['_activeWindow'], window)
        updated = briefing.save({**{k:preset[k] for k in briefing.FIELDS if k in preset},'expectedRevision':1,
            'activeWindow': {'start': window['start'], 'end': (now+timedelta(hours=1)).isoformat()}}, ACTOR, preset['id'])
        with patch.object(execution, 'datetime', wraps=datetime) as clock, patch.object(execution.multiprocessing, 'get_context') as worker:
            clock.now.return_value = now+timedelta(minutes=2)
            execution._supervise(run['id'])
            worker.assert_not_called()
        with store._db(write=True) as db:
            blocked = execution._row(db, run['id'])
            self.assertEqual(blocked['state'], 'failed')
            self.assertIsNone(blocked['started_at'])
            self.assertIn('生效窗口已结束', blocked['summary'])
            # A task that claimed its slot in time isn't cancelled at window end.
            db.execute("UPDATE er_execution SET state='running',started_at=? WHERE id=?", (now.isoformat(), run['id']))
        with patch.object(execution, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = now+timedelta(minutes=2)
            self.assertEqual(execution._authenticate(run['id'])['grantId'], gid)

    def test_stop_keeps_exclusive_lock_until_slow_checker_exits(self):
        checker = Mock(); checker.is_alive.return_value = True
        previous_lock = processing._lock_file
        processing._lock_file = None
        try:
            processing.acquire()
            handle = processing._lock_file
            with patch.object(processing, '_thread', checker):
                processing.stop()
                checker.join.assert_called_once_with(2)
                self.assertFalse(handle.closed)
                self.assertFalse(processing.status()['ready'])
                with self.assertRaises(ApiError): processing.ensure_ready()
                with self.assertRaises(RuntimeError): processing.acquire()
                checker.is_alive.return_value = False
                processing.stop()
                self.assertTrue(handle.closed)
                processing.acquire()
                processing.stop()
        finally:
            if processing._lock_file: processing._lock_file.close()
            processing._lock_file = previous_lock
            processing._stop.clear()

    def test_retry_and_clarification_cannot_silently_upgrade_original_method(self):
        request = {'clientRequestId':str(uuid4()),'expertId':'course','expertSelection':'per_turn',
                   'mode':'selected_task','input':{'taskId':'C-PERFORMANCE','semester_id':'fixture-semester'}}
        first = execution.submit(request, ACTOR, start=False)
        execution._terminal(first['id'], 'failed', 'fixture failure')
        with self.assertRaises(ApiError) as failed:
            execution.submit({**request,'clientRequestId':str(uuid4()),'expectedTurn':1,
                'retryOfExecutionId':first['id'],'upgradeToVersion':'9.0.0'},ACTOR,start=False)
        self.assertEqual(failed.exception.status_code,409)
        with self.assertRaises(ApiError) as clarification:
            execution.submit({**request,'clientRequestId':str(uuid4()),'expectedTurn':1,'researchId':first['researchId'],
                'mode':'clarification_answer','originalTurnId':first['turnId'],'upgradeToVersion':'9.0.0'},ACTOR,start=False)
        self.assertIn('保留原方法版本',clarification.exception.msg)

    def test_each_turn_can_change_expert_without_changing_original_identity(self):
        request = {'expertId': 'course', 'expertSelection': 'per_turn', 'mode': 'selected_task', 'clientRequestId': str(uuid4()),
                   'input': {'taskId': 'C-PERFORMANCE', 'semester_id': 'fixture-semester'}}
        first = execution.submit(request, ACTOR, start=False)
        execution._terminal(first['id'], 'partial', 'fixture first', outcome=self.outcome())
        second = execution.submit({**request, 'clientRequestId': str(uuid4()), 'researchId': first['researchId'],
                                   'expectedTurn': 1, 'expertId': 'program', 'input': {'taskId': 'P-STRUCTURE', 'plan_id': 'fixture-plan'}}, ACTOR, start=False)
        execution._terminal(second['id'], 'partial', 'fixture second', outcome=self.outcome())
        turns = store.get_research(first['researchId'], ACTOR)['turns']
        self.assertEqual([t['expertId'] for t in turns], ['course', 'program'])
        with self.assertRaises(ApiError): execution.submit({**request, 'clientRequestId': str(uuid4()), 'researchId': first['researchId'],
               'expectedTurn': 2, 'originalTurnId': first['turnId'], 'expertId':'program', 'input':{'taskId':'P-STRUCTURE','plan_id':'fixture-plan'}}, ACTOR, start=False)

    def test_history_search_is_literal_and_paginated(self):
        for question in ['fixture % literal', 'fixture other']:
            execution.submit({'expertId': 'course', 'mode': 'selected_task', 'clientRequestId': str(uuid4()),
              'question': question, 'input': {'taskId': 'C-PERFORMANCE', 'semester_id': 'fixture-semester'}}, ACTOR, start=False)
        self.assertEqual(store.list_research(ACTOR, search='%')['total'], 1)
        self.assertEqual(store.list_research(ACTOR, limit=1)['total'], 2)
        self.assertEqual(len(store.list_research(ACTOR, offset=1, limit=1)['items']), 1)

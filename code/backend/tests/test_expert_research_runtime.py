"""Synthetic temporary-database tests; never write school or live workspace data."""
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.expert_research import runtime, store
from backend.expert_team import storage as legacy


def user(name='fixture', identity='i1', scope='s1'):
    return dict(username=name, permission_context=dict(authorized=True, activeIdentityId=identity, scopeFingerprint=scope))


def allow(payload):
    if payload['scope'].get('deny_publish') and payload.get('actual_experts'):
        raise ApiError('revoked', code=403, status_code=403)
    return True


def fixture_execute(payload):
    fault = payload['scope'].get('fault')
    if fault == 'lease_probe':
        with closing(sqlite3.connect(payload['store_path'])) as conn:
            conn.execute('INSERT INTO test_execution VALUES(?,?)', (payload['run_id'], time.time()))
            conn.commit()
        time.sleep(10)
    if fault == 'sleep':
        time.sleep(10)
    if fault == 'crash':
        os._exit(7)
    state = 'needs_input' if fault == 'clarify' else 'completed'
    return dict(status=state, result=dict(body='核对课程共同部分', management_note='保留判断边界',
                actual_experts=['program'], dependency_plan_ids=['plan-A']), actual_experts=['program'],
                source_bundle=dict(plan_ids=['plan-A'], original_text='固定原文', slice=[{'code': 'C1', 'credits': 2}]))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'EXPERT_RESEARCH_READ_ONLY': '0'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix='expert-research-test-')
        self.path = Path(self.tmp.name) / 'research.sqlite'
        self.conn = sqlite3.connect(self.path)
        store.migrate(self.conn)
        self.user = user()
        self.scope = {'plan_id': 'plan-A'}

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def create(self, request='first', who=None, scope=None):
        return store.create_research(self.conn, who or self.user, '比较专业共同课程', scope or self.scope, request)

    def completed(self, research=None):
        research = research or self.create()
        claimed = store.claim_next(self.conn, 'test-worker')
        self.assertEqual(claimed['payload']['research_id'], research['id'])
        self.assertTrue(store.publish(self.conn, claimed['id'], claimed['lease_generation'], 'test-worker', fixture_execute(claimed['payload'])))
        return store.detail(self.conn, self.user, research['id'])

    def assert_api(self, status, callable, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            callable(*args, **kwargs)
        self.assertEqual(caught.exception.status_code, status)

    def test_migration_is_repeatable(self):
        self.create()
        store.migrate(self.conn)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM er_research').fetchone()[0], 1)

    def test_incomplete_schema_returns_503_without_automatic_migration(self):
        incomplete = Path(self.tmp.name) / 'incomplete.sqlite'
        with closing(sqlite3.connect(incomplete)) as conn:
            conn.execute('CREATE TABLE er_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            conn.execute("INSERT INTO er_meta VALUES('schema_version','1')")
            conn.commit()
        original = incomplete.read_bytes()
        self.assert_api(503, store.connect, incomplete)
        self.assertEqual(incomplete.read_bytes(), original)
        absent = Path(self.tmp.name) / 'missing.sqlite'
        self.assert_api(503, store.connect, absent)
        self.assertFalse(absent.exists())

    def test_read_only_rejects_public_writes_but_preserves_history(self):
        item = self.completed()
        research_id, result_id = item['id'], item['current_result']['id']
        question = store.add_question(self.conn, self.user, research_id, {'text': '待补充来源'})
        queued = self.create('queued')
        claimed = store.claim_next(self.conn, 'worker')
        before = self.conn.total_changes
        with patch.dict(os.environ, {'EXPERT_RESEARCH_READ_ONLY': '1'}):
            operations = [
                lambda: self.create('blocked'),
                lambda: store.add_turn(self.conn, self.user, research_id, '继续', self.scope, 'blocked', 1),
                lambda: store.update_metadata(self.conn, self.user, research_id, 1, title='改名'),
                lambda: store.update_participants(self.conn, self.user, research_id, item['participants_revision'], 'course'),
                lambda: store.save_text(self.conn, self.user, research_id, 'opinion', '新意见', 0, 'blocked'),
                lambda: store.save_text(self.conn, self.user, 'new', 'draft', '草稿', 0, 'blocked'),
                lambda: store.add_question(self.conn, self.user, research_id, {'text': '新增'}),
                lambda: store.update_question(self.conn, self.user, research_id, question['id'], 1, 'deferred'),
                lambda: store.create_material(self.conn, self.user, research_id, result_id, 0, {question['id']: 1}),
            ]
            for operation in operations:
                self.assert_api(503, operation)
            self.assertIsNone(store.claim_next(self.conn, 'blocked-worker'))
            self.assertFalse(store.publish(self.conn, claimed['id'], claimed['lease_generation'], 'worker', fixture_execute(claimed['payload'])))
            self.assertEqual(self.conn.total_changes, before)
            self.assertEqual(store.detail(self.conn, self.user, research_id)['current_result']['id'], result_id)
            self.assertEqual(len(store.list_researches(self.conn, self.user)['items']), 2)
            stopped = runtime.Runtime(self.path, fixture_execute, allow).start()
            self.assertIsNone(stopped._thread)
            self.assertTrue(stopped.stop())
            # Reclamation remains permitted after a read-only cutover.
            store.cancel_run(self.conn, self.user, queued['active_run']['id'])
            self.assertTrue(store.finish_cancel(self.conn, claimed['id'], 'worker'))

    def test_idempotent_first_submit_and_conflicting_key(self):
        a = self.create()
        self.assertEqual(a['id'], self.create()['id'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM er_run').fetchone()[0], 1)
        self.assert_api(409, store.create_research, self.conn, self.user, '不同内容', self.scope, 'first')

    def test_owner_and_identity_and_scope_isolation(self):
        a = self.create()
        for other in (user('another'), user(identity='i2'), user(scope='s2')):
            self.assert_api(404, store.detail, self.conn, other, a['id'])
            self.assert_api(404, store.get_run, self.conn, other, a['active_run']['id'])
            self.assertEqual(store.list_researches(self.conn, other)['items'], [])
        self.assert_api(403, store.list_researches, self.conn, {'username': 'fixture'})

    def test_user_capacity_no_empty_research_on_rejection(self):
        self.create('a'); self.create('b')
        self.assert_api(429, self.create, 'c')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM er_research').fetchone()[0], 2)

    def test_global_queue_limit_atomic(self):
        for index in range(20):
            self.create(str(index), user(str(index)))
        self.assert_api(429, self.create, 'overflow', user('overflow'))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM er_turn').fetchone()[0], 20)

    def test_same_research_active_unique_and_turn_idempotency(self):
        a = self.create()
        self.assert_api(409, store.add_turn, self.conn, self.user, a['id'], '继续', self.scope, 'next', 1)
        store.cancel_run(self.conn, self.user, a['active_run']['id'])
        first = store.add_turn(self.conn, self.user, a['id'], '继续', self.scope, 'next', 1)
        second = store.add_turn(self.conn, self.user, a['id'], '继续', self.scope, 'next', 1)
        self.assertEqual(first['active_run']['id'], second['active_run']['id'])
        self.assert_api(409, store.add_turn, self.conn, self.user, a['id'], '变更', self.scope, 'next', 1)

    def test_participant_preferences_freeze_on_claim_not_queue(self):
        a = self.create()
        a = store.update_participants(self.conn, self.user, a['id'], 1, 'course', 'add')
        a = store.update_participants(self.conn, self.user, a['id'], 2, 'program', 'exclude')
        claim = store.claim_next(self.conn, 'worker')
        self.assertEqual(claim['payload']['chosen'], ['course'])
        self.assertEqual(claim['payload']['excluded'], ['program'])
        store.update_participants(self.conn, self.user, a['id'], 3, 'course', 'exclude')
        self.assertEqual(claim['payload']['chosen'], ['course'])
        out = fixture_execute(claim['payload']); out['actual_experts'] = ['course']
        store.publish(self.conn, claim['id'], claim['lease_generation'], 'worker', out)
        self.assertEqual({p['expert_id']: p['status'] for p in store.detail(self.conn, self.user, a['id'])['participants']}['course'], 'excluded')

    def test_global_execution_slots_and_competing_claim(self):
        for i in range(3): self.create(str(i), user(str(i)))
        c1 = store.claim_next(self.conn, 'worker-1')
        with closing(store.connect(self.path)) as conn:
            c2 = store.claim_next(conn, 'worker-2')
            self.assertIsNone(store.claim_next(conn, 'worker-3'))
        self.assertNotEqual(c1['id'], c2['id'])

    def test_cancel_wins_and_late_output_cannot_publish(self):
        a = self.create(); claim = store.claim_next(self.conn, 'worker')
        self.assertEqual(store.cancel_run(self.conn, self.user, claim['id'])['status'], 'cancel_requested')
        self.assertFalse(store.publish(self.conn, claim['id'], claim['lease_generation'], 'worker', fixture_execute(claim['payload'])))
        self.assertTrue(store.finish_cancel(self.conn, claim['id'], 'worker'))
        self.assertIsNone(store.detail(self.conn, self.user, a['id'])['current_result'])

    def test_completed_wins_before_cancel(self):
        a = self.completed()
        run_id = a['turns'][0]['run']['id']
        self.assertEqual(store.cancel_run(self.conn, self.user, run_id)['status'], 'completed')

    def test_cancel_racing_reclaimed_failure_finishes_without_waiting_for_lease(self):
        self.create()
        supervisor = runtime.Runtime(self.path, fixture_execute, allow)
        claim = store.claim_next(self.conn, supervisor.worker_id)
        store.cancel_run(self.conn, self.user, claim['id'])
        supervisor._finish_reclaimed(self.conn, claim['id'], claim['lease_generation'], 'worker_interrupted')
        self.assertEqual(store.get_run(self.conn, self.user, claim['id'])['status'], 'cancelled')

    def test_expired_lease_fences_old_worker(self):
        self.create(); claim = store.claim_next(self.conn, 'worker')
        self.conn.execute('UPDATE er_run SET lease_until=? WHERE id=?', (time.time() - 1, claim['id'])); self.conn.commit()
        self.assertFalse(store.publish(self.conn, claim['id'], claim['lease_generation'], 'worker', fixture_execute(claim['payload'])))
        store.reap_expired(self.conn)
        self.assertEqual(store.get_run(self.conn, self.user, claim['id'])['error'], 'lease_expired')

    def test_queue_timeout_and_heartbeat_cannot_revive(self):
        a = self.create()
        self.conn.execute('UPDATE er_run SET queue_deadline=0'); self.conn.commit()
        store.reap_expired(self.conn)
        self.assertEqual(store.get_run(self.conn, self.user, a['active_run']['id'])['error'], 'queue_timeout')
        self.assertFalse(store.heartbeat(self.conn, a['active_run']['id'], 0, 'worker'))

    def test_old_scope_result_does_not_replace_current_pointer(self):
        a = self.create(); claim = store.claim_next(self.conn, 'worker')
        store.update_metadata(self.conn, self.user, a['id'], 1, scope={'plan_id': 'plan-B'}, expected_epoch=1)
        self.assertTrue(store.publish(self.conn, claim['id'], claim['lease_generation'], 'worker', fixture_execute(claim['payload'])))
        after = store.detail(self.conn, self.user, a['id'])
        self.assertEqual(after['context_epoch'], 2)
        self.assertIsNone(after['current_result'])
        self.assertIsNotNone(after['turns'][0]['result'])

    def test_reference_completed_keeps_current_result_and_cannot_be_material(self):
        item = self.completed()
        current_id = item['current_result']['id']
        before = self.conn.execute('SELECT COUNT(*) FROM er_progress').fetchone()[0]
        store.add_turn(self.conn, self.user, item['id'], '解释口径', self.scope, 'explain', item['context_epoch'])
        claim = store.claim_next(self.conn, 'worker')
        output = fixture_execute(claim['payload'])
        output['publish_current'] = False
        output['result'].update(status='reference', based_on_result_id=current_id)
        self.assertTrue(store.publish(self.conn, claim['id'], claim['lease_generation'], 'worker', output))
        after = store.detail(self.conn, self.user, item['id'])
        self.assertEqual(after['turns'][-1]['run']['status'], 'completed')
        self.assertEqual(after['turns'][-1]['result']['status'], 'reference')
        self.assertEqual(after['current_result']['id'], current_id)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM er_progress').fetchone()[0], before)
        self.assert_api(422, store.create_material, self.conn, self.user, item['id'], after['turns'][-1]['result']['id'], 0, {})

    def test_effective_scope_is_current_but_submitted_turn_remains_frozen(self):
        item = self.create()
        claim = store.claim_next(self.conn, 'worker')
        output = fixture_execute(claim['payload'])
        output['result']['scope'] = {**self.scope, 'compare_plan_ids': ['plan-B', 'plan-C']}
        self.assertTrue(store.publish(self.conn, claim['id'], claim['lease_generation'], 'worker', output))
        after = store.detail(self.conn, self.user, item['id'])
        self.assertEqual(after['scope'], output['result']['scope'])
        self.assertEqual(after['current_result']['scope'], output['result']['scope'])
        self.assertEqual(after['context_epoch'], 2)
        self.assertEqual(after['turns'][0]['scope'], self.scope)
        self.assertEqual(after['turns'][0]['context_epoch'], 1)

    def test_detail_uses_one_snapshot_when_another_connection_publishes_mid_read(self):
        original = self.completed()
        store.add_turn(self.conn, self.user, original['id'], '继续分析', self.scope, 'second', original['context_epoch'])
        claim = store.claim_next(self.conn, 'publishing-worker')
        read_research = store._research
        published = []
        with closing(store.connect(self.path)) as writer:
            def publish_after_first_read(conn, user, research_id):
                row = read_research(conn, user, research_id)
                if conn is self.conn and not published:
                    published.append(store.publish(writer, claim['id'], claim['lease_generation'],
                        'publishing-worker', fixture_execute(claim['payload'])))
                return row
            with patch.object(store, '_research', side_effect=publish_after_first_read):
                snapshot = store.detail(self.conn, self.user, original['id'])
        self.assertEqual(published, [True])
        self.assertEqual(snapshot['current_result']['id'], original['current_result']['id'])
        self.assertEqual(snapshot['turns'][-1]['run']['status'], 'running')
        self.assertIsNone(snapshot['turns'][-1]['result'])
        self.assertEqual(snapshot['active_run']['id'], claim['id'])
        self.assertFalse(self.conn.in_transaction)
        latest = store.detail(self.conn, self.user, original['id'])
        self.assertEqual(latest['turns'][-1]['run']['status'], 'completed')
        self.assertEqual(latest['current_result']['id'], latest['turns'][-1]['result']['id'])
        self.assertIsNone(latest['active_run'])

    def test_detail_reuses_callers_transaction_and_never_commits_or_rolls_it_back(self):
        item = self.create()
        self.conn.execute('BEGIN')
        self.conn.execute('UPDATE er_research SET title=? WHERE id=?', ('未提交标题', item['id']))
        self.assertEqual(store.detail(self.conn, self.user, item['id'])['title'], '未提交标题')
        self.assertTrue(self.conn.in_transaction)
        self.assert_api(404, store.detail, self.conn, user('other'), item['id'])
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertEqual(store.detail(self.conn, self.user, item['id'])['title'], item['title'])
        self.assertFalse(self.conn.in_transaction)
        self.assert_api(404, store.detail, self.conn, user('other'), item['id'])
        self.assertFalse(self.conn.in_transaction)

    def test_material_rejects_old_result_with_new_scope_and_current_opinion(self):
        initial = self.completed()
        original_material = store.create_material(self.conn, self.user, initial['id'], initial['current_result']['id'], 0, {})
        newer = store.add_turn(self.conn, self.user, initial['id'], '改查另一专业', {'plan_id': 'plan-B'}, 'new-scope', 1)
        current = self.completed(newer)
        opinion = store.save_text(self.conn, self.user, initial['id'], 'opinion', '针对新范围的意见', 0, 'opinion')
        self.assert_api(409, store.create_material, self.conn, self.user, initial['id'], initial['current_result']['id'], opinion['revision'], {})
        material = store.create_material(self.conn, self.user, current['id'], current['current_result']['id'], opinion['revision'], {})
        self.assertEqual(material['snapshot']['result']['scope'], {'plan_id': 'plan-B'})
        self.assertEqual(store.get_material(self.conn, self.user, original_material['id'])['snapshot']['result']['scope'], self.scope)

    def test_archived_research_reads_sources_and_material_but_requires_restore_to_continue(self):
        item = self.completed()
        archived = store.update_metadata(self.conn, self.user, item['id'], 1, status='archived')
        self.assertEqual(store.list_researches(self.conn, self.user)['items'], [])
        self.assertEqual(len(store.list_researches(self.conn, self.user, status='archived')['items']), 1)
        self.assert_api(409, store.add_turn, self.conn, self.user, item['id'], '继续', self.scope, 'next', 1)
        self.assertEqual(store.get_source_bundle(self.conn, self.user, item['current_result']['source_bundle_id'])['original_text'], '固定原文')
        material = store.create_material(self.conn, self.user, item['id'], item['current_result']['id'], 0, {})
        self.assertEqual(store.get_material(self.conn, self.user, material['id'])['snapshot']['result_id'], item['current_result']['id'])
        store.update_metadata(self.conn, self.user, item['id'], archived['metadata_revision'], status='active')
        self.assertEqual(store.add_turn(self.conn, self.user, item['id'], '继续', self.scope, 'next', 1)['active_run']['status'], 'queued')

    def test_independent_text_versions_conflict_and_retransmission(self):
        a = self.create()
        opinion = store.save_text(self.conn, self.user, a['id'], 'opinion', '我的看法', 0, 'op1')
        store.save_text(self.conn, self.user, a['id'], 'draft', '下次问题', 0, 'dr1')
        store.update_metadata(self.conn, self.user, a['id'], 1, title='新名称')
        store.update_participants(self.conn, self.user, a['id'], 1, 'course')
        self.assertEqual(store.get_text(self.conn, self.user, a['id'], 'opinion'), opinion)
        self.assertEqual(store.save_text(self.conn, self.user, a['id'], 'opinion', '我的看法', 0, 'op1'), opinion)
        self.assert_api(409, store.save_text, self.conn, self.user, a['id'], 'opinion', '冲突内容', 0, 'op2')
        restored = store.save_text(self.conn, self.user, a['id'], 'opinion', '', 1, 'op3')
        self.assertEqual(restored['revision'], 2)
        self.assertEqual(len(store.text_versions(self.conn, self.user, a['id'])), 2)

    def test_new_draft_owner_scoped_and_durable(self):
        store.save_text(self.conn, self.user, 'new', 'draft', '待发研究', 0, 'new1')
        with closing(store.connect(self.path)) as conn:
            self.assertEqual(store.get_text(conn, self.user, 'new', 'draft')['text'], '待发研究')
            self.assertEqual(store.get_text(conn, user(identity='other'), 'new', 'draft')['text'], '')

    def test_material_freezes_exact_versions_and_optional_opinion(self):
        a = self.completed()
        op = store.save_text(self.conn, self.user, a['id'], 'opinion', '不自动纳入', 0, 'op1')
        q = store.add_question(self.conn, self.user, a['id'], {'text': '缺少年度资料', 'kind': 'data'})
        args = (self.conn, self.user, a['id'], a['current_result']['id'], op['revision'], {q['id']: q['revision']})
        material = store.create_material(*args, include_opinion=False)
        self.assertIsNone(material['snapshot']['opinion'])
        store.save_text(self.conn, self.user, a['id'], 'opinion', '修改后', 1, 'op2')
        self.assertEqual(store.get_material(self.conn, self.user, material['id'])['content_hash'], material['content_hash'])
        self.assert_api(409, store.create_material, *args)
        self.assert_api(422, store.update_question, self.conn, self.user, a['id'], q['id'], 1, 'resolved')

    def test_frozen_source_is_not_replaced_and_cannot_cross_owner(self):
        a = self.completed(); result = a['current_result']
        bundle = store.get_source_bundle(self.conn, self.user, result['source_bundle_id'])
        self.assertEqual(bundle['original_text'], '固定原文')
        self.assert_api(404, store.get_source_bundle, self.conn, user('other'), result['source_bundle_id'])

    def test_history_over_eighty_and_pagination(self):
        a = self.create()
        for i in range(85):
            current = store.detail(self.conn, self.user, a['id'])
            store.cancel_run(self.conn, self.user, current['active_run']['id'])
            store.add_turn(self.conn, self.user, a['id'], '历史问题' + str(i), self.scope, 'turn' + str(i), 1)
        page = store.detail(self.conn, self.user, a['id'])
        seen = list(page['turns'])
        while page['next_before']:
            page = store.detail(self.conn, self.user, a['id'], before=page['next_before'])
            seen.extend(page['turns'])
        self.assertEqual(len({x['id'] for x in seen}), 86)
        self.assertEqual(len(store.list_researches(self.conn, self.user, q='历史问题0')['items']), 1)

    def test_legacy_repeatable_archive_not_fake_history(self):
        old = sqlite3.connect(':memory:'); old.row_factory = sqlite3.Row; legacy.migrate(old)
        entry = legacy.create_session(old, self.user, {'expert_id': 'program'}, {'title': '旧记录'})
        before = [tuple(r) for r in old.execute('SELECT * FROM team_session')]
        self.assertEqual(store.import_legacy(self.conn, old, 'fixture')['imported'], 1)
        self.assertEqual(store.import_legacy(self.conn, old, 'fixture')['unchanged'], 1)
        archived = store.list_legacy(self.conn, self.user)['items'][0]
        self.assertTrue(store.read_legacy(self.conn, self.user, archived['id'])['read_only'])
        self.assertEqual(before, [tuple(r) for r in old.execute('SELECT * FROM team_session')])
        old.execute('UPDATE team_session SET revision=revision+1'); old.commit()
        self.assertEqual(store.import_legacy(self.conn, old, 'fixture')['conflicts'], [entry['id']])
        old.close()


class ProcessRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'EXPERT_RESEARCH_READ_ONLY': '0'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix='expert-process-test-')
        self.path = Path(self.tmp.name) / 'research.sqlite'
        self.conn = sqlite3.connect(self.path); store.migrate(self.conn)
        self.user = user(); self.runtime = None

    def tearDown(self):
        if self.runtime:
            self.assertTrue(self.runtime.stop())
            self.assertEqual(self.runtime.running_processes, 0)
        self.conn.close(); self.tmp.cleanup()

    def start_run(self, scope, budget=20):
        item = store.create_research(self.conn, self.user, '测试隔离执行', scope, 'first')
        self.runtime = runtime.Runtime(self.path, fixture_execute, allow,
            dict(run_seconds=budget, lease_seconds=30, heartbeat_seconds=2, poll_seconds=0.05)).start()
        return item

    def await_state(self, run_id, states, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = store.get_run(self.conn, self.user, run_id)
            if state['status'] in states:
                return state
            time.sleep(0.05)
        self.fail('run did not reach expected state: ' + str(state))

    def test_real_subprocess_completion_and_clarification(self):
        item = self.start_run({'fault': 'clarify'})
        self.await_state(item['active_run']['id'], {'needs_input'})
        detail = store.detail(self.conn, self.user, item['id'])
        self.assertIsNone(detail['current_result'])
        self.assertIsNotNone(detail['turns'][0]['result'])

    def test_real_hard_timeout_reclaims_process(self):
        item = self.start_run({'fault': 'sleep'}, budget=5)
        state = self.await_state(item['active_run']['id'], {'failed'})
        self.assertEqual(state['error'], 'run_timeout')
        self.assertEqual(self.runtime.running_processes, 0)

    def test_real_cancel_reclaims_process_and_ignores_late_result(self):
        item = self.start_run({'fault': 'sleep'})
        run_id = item['active_run']['id']
        self.await_state(run_id, {'running'})
        store.cancel_run(self.conn, self.user, run_id)
        self.await_state(run_id, {'cancelled'})
        self.assertEqual(self.runtime.running_processes, 0)
        self.assertIsNone(store.detail(self.conn, self.user, item['id'])['current_result'])

    def test_real_worker_crash_and_restart_recovery(self):
        item = self.start_run({'fault': 'crash'})
        state = self.await_state(item['active_run']['id'], {'failed'})
        self.assertEqual(state['error'], 'worker_interrupted')
        self.assertTrue(self.runtime.stop())
        new = store.add_turn(self.conn, self.user, item['id'], '重试新分析', {'plan_id': 'plan-A'}, 'retry', 1)
        self.runtime.start()
        self.await_state(new['active_run']['id'], {'completed'})

    def test_permission_revoked_before_publication(self):
        item = self.start_run({'deny_publish': True})
        state = self.await_state(item['active_run']['id'], {'failed'})
        self.assertEqual(state['error'], 'authorization_revoked')
        self.assertIsNone(store.detail(self.conn, self.user, item['id'])['current_result'])

    def test_read_only_cutover_reclaims_active_process_without_publication(self):
        item = self.start_run({'fault': 'sleep'})
        self.await_state(item['active_run']['id'], {'running'})
        with patch.dict(os.environ, {'EXPERT_RESEARCH_READ_ONLY': '1'}):
            state = self.await_state(item['active_run']['id'], {'failed'})
            self.assertEqual(state['error'], 'service_stopped')
            self.assertEqual(self.runtime.running_processes, 0)
            self.assertIsNone(store.detail(self.conn, self.user, item['id'])['current_result'])

    def test_stalled_supervisor_workers_lose_lease_before_other_runtime_executes(self):
        self.conn.execute('CREATE TABLE test_execution(run_id TEXT PRIMARY KEY,started REAL)')
        self.conn.commit()
        runs = [store.create_research(self.conn, user(str(i)), '租约隔离', {'fault': 'lease_probe'}, str(i)) for i in range(3)]
        cfg = dict(run_seconds=25, lease_seconds=30, heartbeat_seconds=2, poll_seconds=0.05)
        self.runtime = runtime.Runtime(self.path, fixture_execute, allow, cfg)
        other = runtime.Runtime(self.path, fixture_execute, allow, cfg)
        self.addCleanup(other.stop)
        with patch.object(self.runtime, '_inspect', return_value=None):
            self.runtime.start()
            deadline = time.monotonic() + 8
            while self.conn.execute('SELECT COUNT(*) FROM test_execution').fetchone()[0] < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM test_execution').fetchone()[0], 2)
            old_processes = [child['process'] for child in self.runtime._children.values()]
            self.assertEqual(len(old_processes), 2)
            self.conn.execute("UPDATE er_run SET lease_until=? WHERE status='running'", (time.time() - 1,))
            self.conn.commit()
            other.start()
            deadline = time.monotonic() + 8
            while self.conn.execute('SELECT COUNT(*) FROM test_execution').fetchone()[0] < 3 and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM test_execution').fetchone()[0], 3)
            # The old supervisor is alive but cannot heartbeat/reclaim. Workers
            # self-terminate; the OS slots prevent an overlapping third analysis.
            self.assertTrue(self.runtime._thread.is_alive())
            self.assertLessEqual(sum(process.is_alive() for process in old_processes) + other.running_processes, 2)
            deadline = time.monotonic() + 3
            while any(process.is_alive() for process in old_processes) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(any(process.is_alive() for process in old_processes))
            self.assertTrue(other.stop())
            self.assertEqual(other.running_processes, 0)

    def test_os_execution_slots_block_analysis_until_actual_release(self):
        self.conn.execute('CREATE TABLE test_execution(run_id TEXT PRIMARY KEY,started REAL)')
        self.conn.commit()
        releases = [runtime._try_execution_slot(self.path, slot) for slot in range(2)]
        self.assertTrue(all(releases))
        try:
            item = self.start_run({'fault': 'lease_probe'})
            self.await_state(item['active_run']['id'], {'running'})
            time.sleep(0.6)
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM test_execution').fetchone()[0], 0)
            releases.pop()()
            deadline = time.monotonic() + 5
            while self.conn.execute('SELECT COUNT(*) FROM test_execution').fetchone()[0] < 1 and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM test_execution').fetchone()[0], 1)
            store.cancel_run(self.conn, self.user, item['active_run']['id'])
            self.await_state(item['active_run']['id'], {'cancelled'})
            self.assertEqual(self.runtime.running_processes, 0)
        finally:
            for release in releases:
                release()


class MigrationCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='expert-migration-test-')
        self.directory = Path(self.tmp.name)
        self.target, self.source = self.directory / 'research.sqlite', self.directory / 'legacy.sqlite'
        self.script = Path(__file__).resolve().parents[2] / 'scripts' / 'migrate_expert_research.py'
        with closing(sqlite3.connect(self.source)) as conn:
            conn.row_factory = sqlite3.Row
            legacy.migrate(conn)
            legacy.create_session(conn, user(), {'expert_id': 'program'}, {'title': '只读旧记录'})
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
        self.tmp.cleanup()

    def cli(self, *args, expected=0, target=None):
        completed = subprocess.run([sys.executable, '-X', 'utf8', str(self.script),
            '--target', str(target or self.target), '--legacy', str(self.source), *args],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout) if expected == 0 else completed

    def test_default_dry_run_creates_nothing_and_apply_only_initializes_new_store(self):
        report = self.cli()
        self.assertEqual(report['mode'], 'dry_run')
        self.assertEqual(report['legacy_records'], 1)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.directory.glob('*.backup')), [])
        report = self.cli('--apply')
        self.assertEqual(report['integrity_check'], 'ok')
        self.assertEqual(report['archive']['imported'], 0)
        with closing(store.connect(self.target)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM er_legacy_archive').fetchone()[0], 0)
        self.assertEqual(report['backups'], [])

    def test_repeat_apply_backs_up_existing_store_and_preserves_data(self):
        self.cli('--apply')
        with closing(store.connect(self.target)) as conn:
            with patch.dict(os.environ, {'EXPERT_RESEARCH_READ_ONLY': '0'}):
                research = store.create_research(conn, user(), '保留新研究', {'plan_id': 'plan-A'}, 'first')
        report = self.cli('--apply')
        self.assertEqual(len(report['backups']), 1)
        backup_path = Path(report['backups'][0])
        self.assertTrue(backup_path.is_file())
        for candidate in (self.target, backup_path):
            with closing(store.connect(candidate)) as conn:
                self.assertEqual(store.detail(conn, user(), research['id'])['title'], '保留新研究')
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_legacy_import_is_explicit_confirmed_repeatable_and_never_overwrites_source(self):
        self.cli('--apply', '--import-legacy', expected=2)
        self.assertFalse(self.target.exists())
        report = self.cli('--apply', '--import-legacy', '--confirm-legacy-read-only')
        self.assertEqual(report['archive']['imported'], 1)
        self.assertEqual(len(report['backups']), 1)
        with closing(sqlite3.connect(report['backups'][0])) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM team_session').fetchone()[0], 1)
        repeat = self.cli('--apply', '--import-legacy', '--confirm-legacy-read-only')
        self.assertEqual(repeat['archive'], {'imported': 0, 'unchanged': 1, 'conflicts': []})
        self.assertEqual(len(repeat['backups']), 2)
        with closing(store.connect(self.target)) as conn:
            self.assertEqual(len(store.list_legacy(conn, user())['items']), 1)
        self.cli('--apply', target=self.source, expected=2)


if __name__ == '__main__':
    unittest.main()

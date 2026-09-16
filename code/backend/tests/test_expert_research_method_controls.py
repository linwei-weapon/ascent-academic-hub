"""Method retirement and request-owned connection contracts; temporary stores only."""
import copy
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.api.routers import expert_research as api
from backend.expert_research import service, store
from backend.tests.test_expert_team import user


class MethodControlsTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{'EXPERT_RESEARCH_READ_ONLY':'0','EXPERT_RESEARCH_DISABLED':''})
        env.start(); self.addCleanup(env.stop)
        self.tmp=tempfile.TemporaryDirectory(prefix='research-method-test-')
        self.path=Path(self.tmp.name)/'research.sqlite'
        with closing(sqlite3.connect(self.path)) as conn:store.migrate(conn)
        self.conn=store.connect(self.path)
        self.user=user('director')
        self.scope={'plan_id':'plan-A'}
        self.item=store.create_research(self.conn,self.user,'研究共同课程',self.scope,'first')

    def tearDown(self):
        self.conn.close(); self.tmp.cleanup()

    def output(self,expert='program'):
        return {'status':'completed','actual_experts':[],
            'result':{'expert_id':expert,'scenario':'similarity','title':'课程比较','headline':'保留原数字',
                'body':'既有分析','scope':self.scope,'tables':[],'methods':['固定口径'],
                'sources':[],'missing':[],'limitations':[],'dependency_plan_ids':['plan-A']},
            'source_bundle':{'plan_ids':['plan-A'],'calculation_slices':[{'expert_id':expert}]}}

    def complete(self,output=None):
        claim=store.claim_next(self.conn,'worker')
        self.assertTrue(store.publish(self.conn,claim['id'],claim['lease_generation'],'worker',output or self.output()))
        return store.detail(self.conn,self.user,self.item['id'])

    def next_turn(self,request='next'):
        current=store.detail(self.conn,self.user,self.item['id'])
        return store.add_turn(self.conn,self.user,self.item['id'],'继续研究',self.scope,request,current['context_epoch'])

    def test_all_historical_turn_results_and_current_are_marked_without_hiding(self):
        self.complete(); self.next_turn(); current=self.complete()
        with patch.dict(os.environ,{'EXPERT_RESEARCH_DISABLED':'program'}):
            view=api.decorate(self.conn,self.user,current)
            self.assertTrue(view['current_result']['method_unavailable'])
            self.assertEqual(len(view['turns']),2)
            self.assertTrue(all(t['result']['method_unavailable'] for t in view['turns']))
            self.assertTrue(all(t['result']['unavailable_methods']==['program'] for t in view['turns']))
        restored=api.decorate(self.conn,self.user,store.detail(self.conn,self.user,self.item['id']))
        self.assertFalse(restored['current_result']['method_unavailable'])

    def test_decorate_preserves_questions_already_in_read_snapshot(self):
        snapshot=self.complete()
        self.assertEqual(snapshot['questions'],[])
        store.add_question(self.conn,self.user,self.item['id'],{'text':'读取后新增的事项'})
        with patch.object(store,'list_questions',side_effect=AssertionError('snapshot questions reread')):
            view=api.decorate(self.conn,self.user,snapshot)
        self.assertEqual(view['questions'],[])

    def test_material_status_uses_questions_from_same_current_snapshot(self):
        current=self.complete()
        question=store.add_question(self.conn,self.user,self.item['id'],{'text':'待明确资料'})
        material=store.create_material(self.conn,self.user,self.item['id'],current['current_result']['id'],0,{question['id']:1})
        snapshot=store.detail(self.conn,self.user,self.item['id'])
        store.update_question(self.conn,self.user,self.item['id'],question['id'],1,'deferred')
        with patch.object(store,'detail',return_value=snapshot), \
                patch.object(store,'list_questions',side_effect=AssertionError('mixed question version')):
            self.assertFalse(api.material_view(self.conn,self.user,material)['stale'])
        self.assertTrue(api.material_view(self.conn,self.user,material)['stale'])

    def test_retirement_blocks_new_material_but_old_material_and_download_remain(self):
        current=self.complete(); result=current['current_result']
        saved=store.create_material(self.conn,self.user,self.item['id'],result['id'],0,{})
        before=self.conn.execute('SELECT COUNT(*) FROM er_material').fetchone()[0]
        with patch.dict(os.environ,{'EXPERT_RESEARCH_DISABLED':'program'}), \
                patch.object(api.analysis,'plans',return_value=[{'plan_id':'plan-A'}]):
            with self.assertRaises(ApiError) as error:
                api.create_material(self.item['id'],api.Material(result_id=result['id'],opinion_revision=0),self.user,None,self.conn)
            self.assertEqual(error.exception.status_code,409)
            existing=api.material(saved['id'],self.user,None,self.conn)['data']
            self.assertTrue(existing['method_unavailable'])
            self.assertEqual(existing['content_hash'],saved['content_hash'])
            with patch('backend.expert_research.materials.render_docx',return_value=b'existing-frozen-document'):
                self.assertEqual(api.download(saved['id'],self.user,None,self.conn).body,b'existing-frozen-document')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM er_material').fetchone()[0],before)

    def test_correction_cannot_reuse_retired_program_even_when_actual_experts_empty(self):
        self.complete()
        payload={'user':{},'research_id':self.item['id'],'scope':self.scope,
                 'message':'这些课程已经共同开设','store_path':str(self.path)}
        with patch.dict(os.environ,{'EXPERT_RESEARCH_DISABLED':'program'}), \
                patch.object(service,'authorize',return_value=self.user):
            with self.assertRaises(ApiError) as error:service.execute(payload)
            self.assertEqual(error.exception.status_code,409)

    def test_publish_rechecks_source_bundle_method_not_just_executed_experts(self):
        original=self.complete(); self.next_turn()
        claim=store.claim_next(self.conn,'worker')
        output=self.output('course');output['actual_experts']=['course']
        output['source_bundle']['calculation_slices']=[{'expert_id':'program'}]
        with patch.dict(os.environ,{'EXPERT_RESEARCH_DISABLED':'program'}):
            self.assertFalse(store.publish(self.conn,claim['id'],claim['lease_generation'],'worker',output))
        after=store.detail(self.conn,self.user,self.item['id'])
        self.assertEqual(after['turns'][-1]['run']['error'],'method_unavailable')
        self.assertIsNone(after['turns'][-1]['result'])
        self.assertEqual(after['current_result']['id'],original['current_result']['id'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM er_source_bundle').fetchone()[0],1)

    def test_publish_checks_inherited_result_id_even_when_output_omits_methods(self):
        original=self.complete(); self.next_turn()
        claim=store.claim_next(self.conn,'worker')
        output=self.output('course');output['source_bundle']=None
        output['result']['based_on_result_id']=original['current_result']['id']
        with patch.dict(os.environ,{'EXPERT_RESEARCH_DISABLED':'program'}):
            self.assertFalse(store.publish(self.conn,claim['id'],claim['lease_generation'],'worker',output))
        self.assertEqual(store.get_run(self.conn,self.user,claim['id'])['status'],'failed')

    def test_nested_contribution_method_is_checked_for_material(self):
        output=self.output('program')
        output['result']['contributions']=[{'expert_id':'course','result':{'expert_id':'course','actual_experts':[]}}]
        current=self.complete(output)
        with patch.dict(os.environ,{'EXPERT_RESEARCH_DISABLED':'course'}):
            with self.assertRaises(ApiError):
                store.create_material(self.conn,self.user,self.item['id'],current['current_result']['id'],0,{})

    def test_historical_reference_remains_readable_but_carries_retired_dependency(self):
        original=self.complete(); self.next_turn()
        claim=store.claim_next(self.conn,'worker')
        reference=service._read_only_answer(original['current_result'],'解释计算口径',self.scope)
        with patch.dict(os.environ,{'EXPERT_RESEARCH_DISABLED':'program'}):
            self.assertTrue(store.publish(self.conn,claim['id'],claim['lease_generation'],'worker',reference))
            current=api.decorate(self.conn,self.user,store.detail(self.conn,self.user,self.item['id']))
            self.assertTrue(current['turns'][-1]['result']['method_unavailable'])
            self.assertEqual(current['turns'][-1]['result']['status'],'reference')
            self.assertEqual(current['current_result']['id'],original['current_result']['id'])

    def test_authorize_checks_inherited_method_dependency(self):
        with patch.object(service,'fresh_user',return_value=self.user), \
                patch.object(service.dbm,'get_v2_conn',side_effect=lambda:sqlite3.connect(':memory:')), \
                patch.object(service,'check_scope'),patch.dict(os.environ,{'EXPERT_RESEARCH_DISABLED':'program'}):
            with self.assertRaises(ApiError) as error:
                service.authorize({'user':{},'scope':{},'actual_experts':[],'method_experts':['program']})
            self.assertEqual(error.exception.status_code,409)

    def test_request_connection_can_move_between_worker_threads_without_sharing(self):
        created_on=threading.get_ident()
        def use_and_close():
            self.assertNotEqual(threading.get_ident(),created_on)
            result=store.save_text(self.conn,self.user,'new','draft','跨工作线程',0,'cross-thread')
            self.assertEqual(store.get_text(self.conn,self.user,'new','draft'),result)
        with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(use_and_close).result(timeout=5)

    def test_concurrent_requests_own_distinct_connections_and_owner_scoped_drafts(self):
        from fastapi import FastAPI, Header
        from fastapi.testclient import TestClient
        app=FastAPI(); app.include_router(api.router)
        opened=[]; lock=threading.Lock()
        def caller(x_test_owner: str=Header()):
            value=copy.deepcopy(self.user);value['username']=x_test_owner;return value
        def connection():
            conn=store.connect(self.path)
            with lock:opened.append(conn)
            try:yield conn
            finally:conn.close()
        app.dependency_overrides[api.require_user]=caller
        app.dependency_overrides[api.research_db]=connection
        with TestClient(app) as client:
            def request(index):
                owner='parallel-'+str(index);headers={'x-test-owner':owner}
                saved=client.put('/api/admin/expert-research/v3/drafts/new',headers=headers,
                    json={'revision':0,'text':owner,'client_request_id':'request-'+str(index)})
                self.assertEqual(saved.status_code,200,saved.text)
                read=client.get('/api/admin/expert-research/v3/drafts/new',headers=headers)
                self.assertEqual(read.status_code,200,read.text)
                self.assertEqual(read.json()['data']['text'],owner)
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(request,range(12)))
        self.assertEqual(len(opened),24)
        self.assertEqual(len({id(conn) for conn in opened}),24)


if __name__=='__main__':unittest.main()

"""Permissions, missing data and actual MCP protocol boundaries, without school writes."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.envelope import ApiError
from backend.expert_resources import runtime, auth, store, selection_options
from backend.expert_resources.app import app


def actor(scope=None, actions=None):
    return {'username': 'fixture-admin', 'identity_id': 'fixture', 'permission_context': {
        'authorized': True, 'activeIdentityId': 'fixture', 'scopeFingerprint': 'test-scope',
        'actionPermissions': ['system.manage'] if actions is None else actions,
        'detailScope': scope or {'type': 'all'}}, 'menus': []}


class ScopeTests(unittest.TestCase):
    def test_course_picker_uses_semester_and_authorized_teaching_college(self):
        user = actor({'type': 'college', 'collegeIds': ['35']})
        with patch.object(selection_options, 'connection') as connection, \
                patch.object(selection_options, 'rows', return_value=[{'id': '10774', 'name': '高等数学A2'}]) as rows:
            value = selection_options.course_options(user, '301')
        self.assertEqual(value['items'][0]['id'], '10774')
        sql, params = rows.call_args.args[1:]
        self.assertIn('a.semester_id=%s', sql)
        self.assertIn('c.organization_id IN (%s)', sql)
        self.assertEqual(params, ['301', '35'])
        connection.assert_called_once_with('analytics', consistent=True)

    def test_course_picker_refuses_cross_college_before_database(self):
        with patch.object(selection_options, 'connection') as connection:
            with self.assertRaises(ApiError):
                selection_options.course_options(actor({'type': 'college', 'collegeIds': ['35']}), '301', '34')
            connection.assert_not_called()

    def test_course_picker_has_no_missing_scope_fallback(self):
        with patch.object(selection_options, 'connection') as connection:
            with self.assertRaises(ApiError):
                selection_options.course_options(actor({'type': 'missing'}), '301')
            connection.assert_not_called()

    def test_resource_and_processing_menus_share_existing_parent(self):
        user = actor()
        user['menus'] = [{'menu_id': 'system-existing', 'parent_id': None, 'title': '系统管理', 'path': '/admin/system'}]
        menus = auth.access(user)['menus']
        peers = [m for m in menus if m.get('parent_id') == 'system-existing']
        self.assertEqual([m['title'] for m in peers], ['专家管理', '技能管理', 'MCP管理', '后台处理服务'])
        self.assertEqual(len([m for m in menus if m['menu_id'] == 'system-existing']), 1)
        self.assertEqual(len({m['path'] for m in peers}), 4)
        reader_menus = auth.access(actor(actions=['ai.analyze']))['menus']
        self.assertFalse(any(m.get('parent_id') and m['path'].startswith('/admin/system/') for m in reader_menus))

    def test_existing_ai_permission_supports_leader_but_does_not_grant_management(self):
        user = actor(actions=['ai.analyze'])
        self.assertEqual(auth.require_use(user), user)
        with self.assertRaises(ApiError):
            auth.require_manage(user)

    def test_unknown_scope_and_cross_college_fail_closed(self):
        for scope, selected in [({'type': 'missing'}, None), ({'type': 'college', 'collegeIds': []}, None),
                                 ({'type': 'college', 'collegeIds': ['35']}, '34')]:
            with self.subTest(scope=scope), self.assertRaises(ApiError):
                runtime.scope_sql(actor(scope), 'organization_id', selected)

    def test_two_colleges_never_share_query_scope(self):
        a = runtime.scope_sql(actor({'type': 'college', 'collegeIds': ['35']}), 'x.org')
        b = runtime.scope_sql(actor({'type': 'college', 'collegeIds': ['34']}), 'x.org')
        self.assertIn('%s', a[0])
        self.assertEqual(a[1], ['35'])
        self.assertEqual(b[1], ['34'])

    def test_staff_relation_is_not_silently_schoolwide(self):
        for role in ['counselor', 'mentor', 'class_adviser']:
            user = actor({'type': 'staff_relation'}, ['ai.analyze'])
            user['permission_context']['activeRole'] = role
            with self.assertRaises(ApiError):
                auth.require_use(user)

    def test_identity_mismatch_is_rejected(self):
        with self.assertRaises(ApiError):
            auth.normalize_actor({'username': 'a', 'activeIdentityId': 'one', 'permissionContext': {
                'authorized': True, 'activeIdentityId': 'two', 'scopeFingerprint': 'fp'}})

    def test_unregistered_inputs_rejected_before_database(self):
        with patch.object(runtime, 'connection') as connection:
            with self.assertRaises(ApiError):
                runtime.run_tool('compare_programs', {'sql': 'select * from students'}, actor())
            connection.assert_not_called()

    def test_missing_policy_is_blocked_without_database(self):
        policy = next(s for s in json.loads(runtime.CATALOG.read_text(encoding='utf-8'))['skills'] if s['id']=='recommendation-policy')
        with patch.object(runtime, 'connection') as connection:
            result = runtime.execute_resource('skills', policy, {}, actor(), {})
            self.assertEqual(result['status'], 'blocked')
            self.assertTrue(result['missingEvidence'])
            connection.assert_not_called()

    def test_skill_uses_tool_in_selected_published_internal_service(self):
        catalog = json.loads(runtime.CATALOG.read_text(encoding='utf-8'))
        skill = next(s for s in catalog['skills'] if s['id'] == 'program-structure')
        skill['toolBindings'] = [{'serverId': 'program-tools', 'toolName': 'read_program_structure'}]
        server = {'id': 'program-tools', 'content': {'tools': [{'name': 'read_program_structure'}]}}
        result = {'status': 'completed', 'summary': 'checked', 'scope': {}, 'data': {}, 'sources': [], 'limitations': [], 'missingEvidence': []}
        with patch.object(runtime, 'run_tool', return_value=result):
            outcome = runtime.execute_resource('skills', skill, {'plan_id': '2'}, actor(), {'mcps': [server]})
            self.assertEqual(outcome['status'], 'passed')
            server['content']['tools'] = []
            with self.assertRaises(ApiError):
                runtime.execute_resource('skills', skill, {'plan_id': '2'}, actor(), {'mcps': [server]})

    def test_learning_tool_keeps_raw_authorized_object_evidence_contract(self):
        from backend.expert_resources import policy_adapter
        fixture = {'status': 'limited', 'summary': 'fixture', 'objects': [{'objectRef': 'fixture-object',
            'achievements': [], 'coverage': {'sourceComplete': False}}], 'coverage': {'sourceComplete': False},
            'scope': {}, 'sources': [], 'limitations': []}
        with patch.object(policy_adapter, 'read_learning_results', return_value=fixture) as read:
            result = runtime.run_tool('read_learning_results', {'plan_id': 'fixture', 'populationRef': 'plan:fixture'}, actor())
            self.assertEqual(result, fixture)
            self.assertEqual(len(result['objects']), 1)
            read.assert_called_once()


class McpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'EXPERT_RESOURCES_DB_PATH': str(Path(self.tmp.name)/'resources.sqlite')})
        self.env.start()
        store.initialize()
        self.actor = actor()
        app.dependency_overrides[auth.current_actor] = lambda: self.actor
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.env.stop()
        self.tmp.cleanup()

    def rpc(self, method, params=None, **kwargs):
        return self.client.post('/api/admin/expert-resources/mcp', json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}, **kwargs)

    def test_initialize_ping_notifications_and_unknown_method(self):
        self.assertEqual(self.rpc('initialize').json()['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(self.rpc('ping').json()['result'], {})
        self.assertEqual(self.rpc('unknown').json()['error']['code'], -32601)
        self.assertEqual(self.client.post('/api/admin/expert-resources/mcp', json={'jsonrpc':'2.0','method':'notifications/initialized'}).status_code, 202)
        self.assertEqual(self.client.get('/api/admin/expert-resources/mcp').status_code, 405)

    def test_origin_and_protocol_are_enforced(self):
        self.assertEqual(self.rpc('initialize', headers={'Origin':'https://untrusted.example'}).status_code, 403)
        self.assertEqual(self.rpc('ping', headers={'MCP-Protocol-Version':'invalid'}).status_code, 400)

    def test_new_internal_service_has_its_own_actual_tool_list(self):
        resource = store.copy_resource('mcps', 'education-data', 1, '方案工具', self.actor, 'program-tools')
        content = resource['draft']['content']
        content['tools'] = [t for t in content['tools'] if t['name'] == 'read_program_structure']
        resource = store.save_resource('mcps', 'program-tools', 1, content, self.actor)
        with patch.object(runtime, 'analysis_options', return_value={'plans': [], 'semesters': [], 'colleges': []}):
            store.test_resource('mcps', 'program-tools', resource['draft']['revision'], {}, self.actor)
        store.publish_resource('mcps', 'program-tools', resource['draft']['revision'], self.actor)
        response = self.client.post('/api/admin/expert-resources/mcp?server_id=program-tools', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        self.assertEqual([t['name'] for t in response.json()['result']['tools']], ['read_program_structure'])
        self.assertIn('error', self.rpc('tools/list').json())

    def test_tools_unavailable_before_published_and_stop_after_disabled(self):
        self.assertIn('error', self.rpc('tools/list').json())
        with patch.object(runtime, 'analysis_options', return_value={'plans': [],'semesters':[],'colleges':[]}):
            result = store.test_resource('mcps','education-data',1,{},self.actor)
        store.publish_resource('mcps','education-data',result['draft']['revision'],self.actor)
        self.assertEqual({item['name'] for item in self.rpc('tools/list').json()['result']['tools']}, runtime.HANDLERS)
        store.set_enabled('mcps','education-data',False,self.actor)
        self.assertIn('error', self.rpc('tools/list').json())

    def test_output_contract_is_checked_and_no_raw_sql_allowed(self):
        with patch.object(runtime, 'analysis_options', return_value={'plans': [],'semesters':[],'colleges':[]}):
            store.test_resource('mcps','education-data',1,{},self.actor)
        store.publish_resource('mcps','education-data',1,self.actor)
        bad = self.rpc('tools/call', {'name':'read_program_structure','arguments':{'plan_id':'2','sql':'SELECT 1'}}).json()
        self.assertEqual(bad['error']['code'], -32602)
        with patch.object(runtime,'run_tool',return_value={'unexpected':'shape'}):
            bad = self.rpc('tools/call', {'name':'read_program_structure','arguments':{'plan_id':'2'}}).json()
        self.assertTrue(bad['result']['isError'])


if __name__ == '__main__':
    unittest.main()

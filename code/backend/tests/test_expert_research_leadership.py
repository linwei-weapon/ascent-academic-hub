"""Leadership cleanliness without weakening provenance or authorization."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.expert_research import store, memo
from backend.tests import test_expert_research_runtime as fixtures
from scripts import quarantine_expert_validation as quarantine


class LeadershipTests(unittest.TestCase):
    setUp = fixtures.StoreTests.setUp
    tearDown = fixtures.StoreTests.tearDown
    create = fixtures.StoreTests.create
    completed = fixtures.StoreTests.completed
    assert_api = fixtures.StoreTests.assert_api

    def test_isolation_is_reversible_and_preserves_contents(self):
        record = self.completed()
        original = tuple(self.conn.execute('SELECT * FROM er_research WHERE id=?', (record['id'],)).fetchone())
        rows = [{'id': record['id'], 'title': record['title']}]
        quarantine.mark(self.conn, rows)
        quarantine.mark(self.conn, rows)
        self.assertEqual(store.list_researches(self.conn, self.user)['items'], [])
        self.assert_api(404, store.detail, self.conn, self.user, record['id'])
        self.assertEqual(tuple(self.conn.execute('SELECT * FROM er_research WHERE id=?', (record['id'],)).fetchone()), original)
        quarantine.mark(self.conn, rows, restore=True)
        self.assertEqual(store.detail(self.conn, self.user, record['id'])['title'], record['title'])

    def test_isolation_covers_search_results_sources_and_materials(self):
        record = self.completed(); result = record['current_result']
        material = store.create_material(self.conn, self.user, record['id'], result['id'], 0, {})
        quarantine.mark(self.conn, [{'id': record['id'], 'title': record['title']}])
        self.assertEqual(store.list_researches(self.conn, self.user, q='共同')['items'], [])
        for function, identifier in [(store.get_result, result['id']), (store.get_source_bundle, result['source_bundle_id']), (store.get_material, material['id'])]:
            self.assert_api(404, function, self.conn, self.user, identifier)

    def test_clean_records_and_owner_permissions_are_unchanged(self):
        first = self.completed(); second = self.completed(self.create('second'))
        quarantine.mark(self.conn, [{'id': first['id'], 'title': first['title']}])
        listed = store.list_researches(self.conn, self.user, limit=1)
        self.assertEqual([r['id'] for r in listed['items']], [second['id']])
        self.assert_api(404, store.detail, self.conn, fixtures.user('another'), second['id'])

    def test_inventory_refuses_changed_business_records(self):
        record = self.completed()
        with patch.object(quarantine, 'REVIEWED', {record['id']}):
            with self.assertRaises(ValueError): quarantine.selected(self.conn)

    def test_restore_does_not_remove_another_operations_marker(self):
        record = self.completed()
        self.conn.execute('INSERT INTO er_meta VALUES(?,?)', ('qa:research:'+record['id'], json.dumps({'operation':'another'})))
        self.conn.commit()
        quarantine.mark(self.conn, [{'id': record['id']}], restore=True)
        self.assert_api(404, store.detail, self.conn, self.user, record['id'])

    def test_test_runtime_uses_explicit_database(self):
        with patch.dict(os.environ, {'EXPERT_RESEARCH_DB_PATH': str(self.path)}):
            self.assertEqual(store.path(), self.path.resolve())

    def test_material_freezes_full_question_and_only_selected_objects(self):
        r={'scope':{'plan_id':'a','target_plan_id':'b','semester':'2025-2026-1'},'scope_label':'本院','documents':[], 'headline':'有待研究'}
        snap={'title':'短标题…','question':'完整管理问题，不应被列表标题截断。','result':r,
              'frozen_plans':[{'plan_id':'a','plan_name':'人工智能2022级','grade':2022}, {'plan_id':'b','plan_name':'电子信息','grade':2022}, {'plan_id':'c','plan_name':'候选但未选择','grade':2022}]}
        content=memo.build(snap); text=' '.join(content['sections'][0]['paragraphs'])
        self.assertIn(snap['question'],text);self.assertIn('人工智能2022级 与 电子信息 · 2022级',text)
        self.assertIn('2025-2026-1',text);self.assertNotIn('候选但未选择',text)
        snap['question']='事后更改';self.assertNotIn('事后更改',str(content))

    def test_material_persists_actual_turn_not_short_research_title(self):
        record=self.completed();result=record['current_result']
        material=store.create_material(self.conn,self.user,record['id'],result['id'],0,{})
        self.assertEqual(material['snapshot']['question'],record['turns'][0]['message'])
        self.assertEqual(material['snapshot']['research_question'],record['turns'][0]['message'])
        self.assertEqual(material['snapshot']['discussion_memo']['version'],'discussion-memo/2.2')

    def test_followup_does_not_erase_the_management_question_in_memo(self):
        content=memo.build({'result':{'expert_id':'course'},'research_question':'本院哪些课程需要重点建设？','question':'比较建设做法'})
        self.assertEqual(content['sections'][0]['paragraphs'][:2],['本院哪些课程需要重点建设？','本轮关注：比较建设做法'])
        self.assertEqual(content['title'],'课程质量建设研究')


if __name__=='__main__':unittest.main()

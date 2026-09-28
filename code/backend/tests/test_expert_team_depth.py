"""Second-round formulas, personal scope and atomic conversation contracts."""
import unittest
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.api.routers import expert_team as api
from backend.expert_team import analysis as a, curriculum as c, conversation, storage, transfer
from backend.tests import test_expert_team as fixtures
user = fixtures.user


class ExpertDepthTests(unittest.TestCase):
    plan = fixtures.ExpertTeamTests.plan
    course = fixtures.ExpertTeamTests.course
    tearDown = fixtures.ExpertTeamTests.tearDown

    def setUp(self):
        fixtures.ExpertTeamTests.setUp(self)
        self.v2.executescript('''
            ALTER TABLE dim_student ADD COLUMN display_name;
            ALTER TABLE dim_student ADD COLUMN entry_grade;
            ALTER TABLE dim_student ADD COLUMN major_name;
            ALTER TABLE dim_student ADD COLUMN source;
            CREATE TABLE data_batch(ingested_at);
            CREATE TABLE curriculum_plan_goal(plan_id,goal_text,source_file);
            CREATE TABLE curriculum_graduation_requirement(plan_id,requirement_text,source_file);
            INSERT INTO data_batch VALUES('2026-09-01');
            CREATE TABLE student_course_result(student_id,course_id,rule_version,is_pass,effective_attempt_id,calculated_at);
            CREATE TABLE grade_attempt(attempt_id,student_id,course_id,is_pass,is_published,is_void,source,semester_id,credits,score);
            CREATE TABLE student_course_substitution(student_id,original_course_id,approval_status,workflow_status,source);
        ''')
        self.plan('a','甲'); self.plan('b','乙'); self.plan('c','丙')
        for pid in ('a','b','c'): self.course(pid,'pub','通识必修'); self.course(pid,'base','专业基础课')
        self.course('a','main','专业主干课'); self.course('b','unique','专业主干课'); self.course('c','main','专业主干课')

    def student(self,sid='s1',org='org1',grade=2022):
        self.v2.execute('''INSERT INTO dim_student(student_id,plan_id,organization_id,major_code,class_code,
            student_status,display_name,entry_grade,major_name,source) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (sid,'a',org,'m1','c1','在校','测试学生',grade,'甲','real'))

    def result(self, **kwargs):
        req={'expert_id':'program','scenario':'similarity','plan_id':'a','target_plan_id':'b',**kwargs}
        return a.analyze(self.v2,self.team,self.user,req)

    def test_layer_counts_partition_courses_and_focus_changes_ranking(self):
        left=a.courses(self.v2,self.team,'a');right=a.courses(self.v2,self.team,'b')
        layers=c.layer_comparison(left,right)
        self.assertEqual(sum(x['a'] for x in layers),len(left))
        self.assertEqual(next(x for x in layers if x['layer']=='专业基础')['shared'],1)
        self.assertEqual(a.compare_sets(left,right,focus='main')['focus_similarity'],0)
        ranking=a.nearest(self.v2,self.team,self.user,a.assert_plan(self.v2,self.user,'a'),focus='main')
        self.assertEqual([x['plan_id'] for x in ranking],['c'])
        self.assertEqual(ranking[0]['focus_similarity'],100)

    def test_choice_and_required_elective_pool_are_not_individual_obligations(self):
        self.course('b','choice','必修环节（二选一）')
        self.course('b','elective','专业选修课')
        values=a.compare_sets(a.courses(self.v2,self.team,'a'),a.courses(self.v2,self.team,'b'),True)
        self.assertEqual(values['target_required'],3)
        self.assertEqual(values['choice_required'],2)
        self.assertEqual(values['additional_required'],1)
        self.assertEqual(values['required_coverage'],66.7)

    def test_explicit_source_module_not_overridden_by_flattened_word_heading(self):
        self.team.execute('INSERT INTO team_document VALUES(?,?,?,?,?,?,?,?)',
            ('a','a.doc','hash','专业选修课\rmain','[]','extracted','[]','now'))
        course=a.courses(self.v2,self.team,'a')['main']
        self.assertEqual(course['layer'],'main')
        self.assertEqual(course['classification_basis'],'课程源表明确模块')

    def test_incomplete_credits_are_never_a_complete_total(self):
        self.course('b','unique','专业主干课',credit=3)
        required=a.courses(self.v2,self.team,'b')
        summary=c.credit_summary(required.values())
        self.assertEqual(summary['unresolved'],1); self.assertIsNone(summary['credits'])
        self.assertIn('待确认',c.credit_text(required.values()))

    def test_original_module_credits_prevent_counting_all_alternative_required_rows(self):
        for cid in ('en1','en2','en3'): self.course('b',cid,'大学英语',credit=4)
        self.course('b','outside','必修',credit=2)
        self.team.execute('INSERT INTO team_document VALUES(?,?,?,?,?,?,?,?)',
            ('b','b.doc','hash','大学英语\r\x07en1\r必修\r4\ren2\r必修\r4\ren3\r必修\r4\r要求学分: 4','[]','extracted','[]','now'))
        target=a.courses(self.v2,self.team,'b')
        self.assertTrue(all(not target[cid]['mandatory'] for cid in ('en1','en2','en3')))
        self.assertIn('要求 4 学分',target['en1']['requirement_basis'])
        values=a.compare_sets(a.courses(self.v2,self.team,'a'),target,True)
        self.assertEqual(values['target_required'],4)
        self.assertEqual(values['choice_required'],3)
        # A separately explicit requirement outside the pool still applies.
        self.course('b','en1','专业基础课',credit=4)
        self.assertTrue(a.courses(self.v2,self.team,'b')['en1']['mandatory'])

    def test_incomplete_or_conflicting_original_blocks_do_not_invent_a_credit_pool(self):
        for cid in ('en1','en2'): self.course('b',cid,'大学英语',credit=4)
        for text in ('大学英语\ren1\r要求学分: 4',
                     '大学英语\ren1\ren2\r要求学分: 4\r大学英语\ren1\ren2\r要求学分: 8',
                     '大学英语\ren1\ren2\r要求学分: 8'):
            with self.subTest(text=text):
                self.team.execute('INSERT OR REPLACE INTO team_document VALUES(?,?,?,?,?,?,?,?)',
                    ('b','b.doc','hash',text,'[]','extracted','[]','now'))
                self.assertTrue(a.courses(self.v2,self.team,'b')['en1']['mandatory'])

    def test_multiterm_and_seasonal_schedule_is_not_invented(self):
        values=list(a.courses(self.v2,self.team,'a').values())
        values[0]['terms']=['1','2']; values[1]['terms']=['春,秋']; values[2]['terms']=['3']
        grouped=c.term_groups(values)
        self.assertEqual(sum(r['count'] for r in grouped),3)
        self.assertEqual(next(r for r in grouped if r['term']=='安排待明确')['count'],2)

    def test_original_names_require_unique_exact_correspondence(self):
        own=a.courses(self.v2,self.team,'a'); own['main']['name']='数据结构（全英文）'
        doc={'plan':'甲','file':'甲.doc','sections':[{'title':'主要课程','text':'数据结构、base。'}]}
        values=c.named_courses(doc,own,{})
        self.assertEqual(values[0]['id'],'未唯一对应'); self.assertEqual(values[1]['id'],'base')

    def test_reading_requirements_conflict_is_not_a_single_value(self):
        doc={'plan':'甲','file':'甲.doc','sections':[{'title':'修读要求','text':'最低总学分 145 最低总学分 150 必修课 87'}]}
        values=c.reading_requirements(doc)
        self.assertIn('多个值',values[0]['value']);self.assertEqual(values[1]['value'],'87 学分')

    def test_student_scope_is_checked_even_inside_an_accessible_plan(self):
        self.student();self.student('s2','org2')
        self.v2.execute('INSERT INTO access_scope_mapping VALUES(?,?,?,?,?,?,?)',('college_dean','college','old1','org1',None,None,'mapped'))
        limited=user('college_dean'); limited['permission_context']['detailScope']={'type':'college','sourceScopeIds':['old1']}
        self.assertEqual([s['student_id'] for s in transfer.students(self.v2,limited,'a')],['s1'])
        with self.assertRaises(ApiError):transfer.assert_student(self.v2,limited,'a','s2')
        with self.assertRaises(ApiError):api.validate_session(self.v2,limited,{'request':{'plan_id':'a','student_id':'s2'},'result':{}})

    def test_personal_results_reuse_effective_records_and_do_not_grant_recognition(self):
        self.student()
        self.v2.execute("INSERT INTO grade_attempt VALUES('g1','s1','pub',1,1,0,'real','2025-2026-1',2,80)")
        self.v2.execute("INSERT INTO student_course_result VALUES('s1','pub','grade-effective-v1',1,'g1','2026-09-01')")
        self.v2.execute("INSERT INTO student_course_substitution VALUES('s1','base','通过','流程已结束','real')")
        result=self.result(expert_id='transfer',scenario='recognition',student_id='s1')
        data=next(t for t in result['tables'] if t['id']=='student_courses')['rows']
        self.assertEqual(next(x for x in data if x['id']=='pub')['state'],'已有同代码通过记录')
        self.assertEqual(next(x for x in data if x['id']=='base')['state'],'已有替代记录，适用待确认')
        self.assertIn('没有结果不等于从未修读',''.join(result['limitations']))
        self.v2.execute("UPDATE grade_attempt SET is_void=1")
        result=self.result(expert_id='transfer',scenario='recognition',student_id='s1')
        data=next(t for t in result['tables'] if t['id']=='student_courses')['rows']
        self.assertEqual(next(x for x in data if x['id']=='pub')['state'],'尚无有效修读结果')

    def test_mismatched_student_plan_blocks_personal_calculation(self):
        self.student(grade=2023)
        result=self.result(expert_id='transfer',scenario='recognition',student_id='s1')
        self.assertEqual(result['status'],'blocked')
        self.assertNotIn('student_courses',[t['id'] for t in result['tables']])

    def test_commands_are_bounded_and_negative_or_compound_requests_not_guessed(self):
        result=self.result()
        self.assertEqual(conversation.resolve_change(result,'只看专业主干课'),{'focus':'main'})
        self.assertIsNone(conversation.resolve_change(result,'不要只看专业主干课'))
        self.assertIsNone(conversation.resolve_change(result,'只看专业主干课，再把结果改成100%'))
        with self.assertRaises(ApiError):conversation.resolve_change({**result,'candidates':[]},'比较第二个专业')

    def test_recalculation_is_atomic_preserves_note_and_rejects_stale_revision(self):
        req={'expert_id':'program','scenario':'similarity','plan_id':'a','target_plan_id':'b'}
        session=storage.create_session(self.team,self.user,req,self.result())
        session=storage.update_session(self.team,self.user,session['id'],1,note='保留我的管理意见')
        updated=api.recalculate(self.v2,self.team,self.user,session,2,{**req,'focus':'main'},'只看专业主干课')
        self.assertEqual(updated['id'],session['id']);self.assertEqual(updated['revision'],3)
        self.assertEqual(updated['note'],'保留我的管理意见');self.assertEqual(len(updated['messages']),2)
        self.assertEqual(updated['result']['focus_label'],'专业主干')
        with patch.object(a,'analyze',side_effect=AssertionError('stale request must not recalculate')):
            with self.assertRaises(ApiError):api.recalculate(self.v2,self.team,self.user,updated,2,req,'过期')
        fresh=storage.get_session(self.team,self.user,session['id'])
        with self.assertRaises(ApiError):api.recalculate(self.v2,self.team,self.user,fresh,3,{**req,'target_plan_id':'outside'},'越权')
        self.assertEqual(storage.get_session(self.team,self.user,session['id'])['revision'],3)

    def test_draft_contains_actual_scope_and_rule_version(self):
        result=self.result()
        self.assertIn('一、初步意见',result['draft_text'])
        self.assertIn(a.VERSION,result['draft_text'])
        self.assertIn(result['scope_label'],result['draft_text'])
        self.assertIn('不是审批',result['draft_text'])

    def test_followup_focus_keeps_current_pair_even_when_ranking_changes(self):
        for i in range(5): self.course('c',f'extra-{i}')
        req={'expert_id':'program','scenario':'similarity','plan_id':'a','target_plan_id':''}
        result=self.result(target_plan_id='')
        self.assertEqual(result['comparison']['target']['plan_id'],'b')
        session=storage.create_session(self.team,self.user,req,result)
        response=api.ask(session['id'],api.AskIn(revision=1,message='只看专业主干课'),self.user,self.v2,self.team)['data']
        self.assertEqual(response['result']['comparison']['target']['plan_id'],'b')
        self.assertEqual(response['result']['comparison']['focus_similarity'],0)
        self.assertEqual(response['result']['candidates'][0]['plan_id'],'c')


if __name__=='__main__':unittest.main()

"""Scene separation, graduation module semantics and immutable scoped records."""
import json
import unittest

from backend.api.envelope import ApiError
from backend.api.routers import expert_team as api
from backend.expert_team import analysis, course_quality, graduation, storage, conversation
from backend.tests import test_expert_team as base_tests, test_expert_team_depth as depth_tests

user=base_tests.user


class ExpertQualityTests(unittest.TestCase):
    plan=base_tests.ExpertTeamTests.plan
    course=base_tests.ExpertTeamTests.course
    student=depth_tests.ExpertDepthTests.student
    tearDown=base_tests.ExpertTeamTests.tearDown

    def setUp(self):
        depth_tests.ExpertDepthTests.setUp(self)
        self.v2.executescript('''
            ALTER TABLE grade_attempt ADD COLUMN course_name;
            ALTER TABLE grade_attempt ADD COLUMN attempt_type;
            CREATE TABLE student_plan_progress_summary(student_id,plan_id,binding_status,evidence_status,
                module_count,assessable_modules,completed_modules,rule_version,calculated_at,source);
            CREATE TABLE student_plan_module_status(student_id,plan_id,module_name,rule_type,rule_label,
                source_reference,is_complete,is_assessable,evidence_status,rule_version,source);
            CREATE TABLE student_plan_course_status(student_id,plan_id,course_id,module,
                completion_status,is_overdue,requirement_type,rule_version,source);
        ''')
        self.student('s1');self.student('s2')
        self.v2.execute("UPDATE dim_student SET class_code='c2' WHERE student_id='s2'")

    def grade(self,aid,sid='s1',cid='base',term='2025-2026-1',passed=0,kind='regular',published=1,void=0,source='real'):
        self.v2.execute('INSERT INTO grade_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (aid,sid,cid,passed,published,void,source,term,2,80 if passed else 40,'课程'+cid,kind))

    def progress(self,sid='s1',state='explicit_gap',complete=0,assessable=1,module='专业基础课',binding='matched',version='growth-v1'):
        self.v2.execute('INSERT INTO student_plan_progress_summary VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (sid,'a',binding,state,1,assessable,complete,version,'2026-09-01','derived'))
        self.v2.execute('INSERT INTO student_plan_module_status VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                        (sid,'a',module,'minimum_courses','至少1门','方案原文',complete,assessable,state,version,'derived'))

    def course_status(self,sid='s1',status='failed',overdue=1,module='专业基础课'):
        self.v2.execute('INSERT INTO student_plan_course_status VALUES(?,?,?,?,?,?,?,?,?)',
                        (sid,'a','base',module,status,overdue,'必修','growth-v1','derived'))

    def analyze(self,expert='course',scene='priority',**kwargs):
        return analysis.analyze(self.v2,self.team,self.user,{'expert_id':expert,'scenario':scene,'plan_id':'a',**kwargs})

    def test_latest_semester_ignores_unpublished_void_makeup_and_unknown_pass(self):
        self.grade('ok',passed=1)
        self.grade('void',term='2099-2100-1',void=1)
        self.grade('unpublished',term='2099-2100-1',published=0)
        self.grade('retake',term='2099-2100-1',kind='retake')
        self.grade('unknown',term='2099-2100-1',passed=None)
        self.grade('demo',term='2099-2100-1',source='simulated')
        result=self.analyze()
        self.assertEqual(result['semester'],'2025-2026-1')
        self.assertEqual(result['tables'][0]['rows'][0]['attempts'],1)

    def test_null_and_deferred_attempts_remain_first_attempts(self):
        self.grade('null',kind=None);self.grade('deferred',sid='s2',kind='deferred',passed=1)
        self.assertEqual(self.analyze()['tables'][0]['rows'][0]['fail_rate'],50)

    def test_missing_grade_course_name_uses_same_code_plan_name(self):
        self.grade('missing-name')
        self.v2.execute('UPDATE grade_attempt SET course_name=NULL')
        result=self.analyze()
        self.assertEqual(result['tables'][0]['rows'][0]['name'],'base')
        self.assertEqual(result['course_options'][0]['name'],'base')

    def test_course_scenes_have_distinct_useful_tables(self):
        self.grade('g1');self.grade('g2',sid='s2',passed=1)
        scenes={scene:{t['id'] for t in self.analyze(scene=scene,course_id='base')['tables']}
                for scene in ('priority','diagnosis','alignment','options','outcomes')}
        self.assertEqual(len({tuple(sorted(ids)) for ids in scenes.values()}),5)
        self.assertIn('class_distribution',scenes['diagnosis'])
        self.assertIn('course_arrangement',scenes['alignment'])
        self.assertIn('course_options',scenes['options'])
        self.assertIn('trend',scenes['outcomes'])

    def test_change_is_percentage_points_and_never_uses_future_period(self):
        self.grade('prior',term='2024-2025-1',passed=1)
        self.grade('now',passed=0);self.grade('future',term='2026-2027-1',passed=1)
        result=self.analyze(scene='outcomes',course_id='base',semester='2025-2026-1')
        trend=next(t['rows'] for t in result['tables'] if t['id']=='trend')
        self.assertEqual(len(trend),2);self.assertIsNone(trend[0]['change']);self.assertEqual(trend[1]['change'],100)

    def test_missing_current_course_period_is_not_zero(self):
        self.grade('past',term='2024-2025-1')
        result=self.analyze(scene='diagnosis',course_id='base',semester='2025-2026-1')
        self.assertNotIn('course_current',[t['id'] for t in result['tables']])
        self.assertIn('不能把缺失结果记作0',''.join(result['missing']))

    def test_class_counts_are_scoped_and_course_cannot_escape_scope(self):
        self.student('s3','org2');self.grade('own');self.grade('outside','s3',cid='secret')
        self.v2.execute('INSERT INTO access_scope_mapping VALUES(?,?,?,?,?,?,?)',('college_dean','college','old1','org1',None,None,'mapped'))
        limited=user('college_dean');limited['permission_context']['detailScope']={'type':'college','sourceScopeIds':['old1']}
        data=course_quality.history(self.v2,limited,'a')
        self.assertEqual({r['course_id'] for r in data},{'base'})
        with self.assertRaises(ApiError):
            analysis.analyze(self.v2,self.team,limited,{'expert_id':'course','scenario':'diagnosis','plan_id':'a','course_id':'secret'})

    def test_satisfied_choice_module_does_not_create_course_debt(self):
        self.progress(complete=1,state='no_due_issue');self.course_status()
        data=graduation.facts(self.v2,self.user,'a')['snapshot']
        self.assertEqual(data['courses'],[])
        self.assertEqual(data['counts']['no_due_issue'],1)

    def test_course_counts_deduplicate_students_and_failed_takes_precedence(self):
        self.progress();self.course_status();self.course_status(status='unknown')
        row=graduation.facts(self.v2,self.user,'a')['snapshot']['courses'][0]
        self.assertEqual((row['failed'],row['pending']),(1,0))

    def test_unassessable_modules_are_shown_as_rule_questions(self):
        self.progress(assessable=0,state='not_assessable')
        result=self.analyze('graduation','records')
        table=next(t for t in result['tables'] if t['id']=='record_modules')
        self.assertEqual(table['rows'][0]['unknown'],1)
        self.assertEqual(table['columns'][0],{'key':'module','label':'模块'})
        self.assertTrue(all(c['key'] in table['rows'][0] for c in table['columns']))
        self.assertEqual(result['snapshot']['counts']['rule_gap'],1)

    def test_old_progress_and_wrong_grade_are_not_failure_counts(self):
        self.progress(version='old-growth');self.progress('s2')
        self.v2.execute("UPDATE dim_student SET entry_grade=2021 WHERE student_id='s2'")
        counts=graduation.facts(self.v2,self.user,'a')['snapshot']['counts']
        self.assertEqual(counts['unknown'],1);self.assertEqual(counts['binding_issue'],1);self.assertEqual(counts['explicit_gap'],0)

    def test_snapshot_is_idempotent_and_contains_no_student_identifiers(self):
        self.progress();snap=graduation.facts(self.v2,self.user,'a')['snapshot']
        first=storage.save_snapshot(self.team,self.user,snap);self.team.commit()
        second=storage.save_snapshot(self.team,self.user,snap);self.team.commit()
        self.assertEqual(first['id'],second['id'])
        self.assertNotIn('student_id',json.dumps(first));self.assertNotIn('s1',json.dumps(first['snapshot']['counts']))
        storage.migrate(self.team);storage.migrate(self.team)
        self.assertEqual(len(storage.list_snapshots(self.team,self.user,'a')),1)

    def test_snapshot_owner_and_identity_isolation(self):
        self.progress();saved=storage.save_snapshot(self.team,self.user,graduation.facts(self.v2,self.user,'a')['snapshot'])
        self.team.commit()
        other=user('college_dean',identity='college-identity',scope='college-scope')
        with self.assertRaises(ApiError):storage.get_snapshot(self.team,other,saved['id'])
        self.assertEqual(storage.list_snapshots(self.team,other,'a'),[])

    def test_comparison_without_baseline_is_explicitly_unavailable(self):
        result=self.analyze('graduation','changes')
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['tables'],[])

    def test_comparison_rejects_changed_cohort_or_rule(self):
        self.progress();snap=graduation.facts(self.v2,self.user,'a')['snapshot']
        saved=storage.save_snapshot(self.team,self.user,snap);self.team.commit()
        self.student('s3')
        result=self.analyze('graduation','changes',baseline_id=saved['id'])
        self.assertEqual(result['status'],'blocked');self.assertIn('学生范围',result['headline'])
        self.v2.execute("DELETE FROM dim_student WHERE student_id='s3'")
        snap['rule_version']='old-rule';snap['source_hash']='other'
        saved=storage.save_snapshot(self.team,self.user,snap);self.team.commit()
        self.assertIn('进度规则',self.analyze('graduation','changes',baseline_id=saved['id'])['headline'])

    def test_same_cohort_delta_is_calculated_and_unchanged_state_is_not_invented(self):
        self.progress();saved=storage.save_snapshot(self.team,self.user,graduation.facts(self.v2,self.user,'a')['snapshot'])
        self.team.commit()
        self.assertIn('未变化',self.analyze('graduation','changes',baseline_id=saved['id'])['headline'])
        self.v2.execute("UPDATE student_plan_progress_summary SET evidence_status='candidate'")
        result=self.analyze('graduation','changes',baseline_id=saved['id'])
        delta=next(t for t in result['tables'] if t['id']=='graduation_changes')['rows']
        self.assertEqual(delta[0]['delta'],-1);self.assertEqual(delta[1]['delta'],1)

    def test_comparison_rejects_changed_plan_applicable_grade(self):
        self.progress();saved=storage.save_snapshot(self.team,self.user,graduation.facts(self.v2,self.user,'a')['snapshot'])
        self.team.commit()
        self.v2.execute("UPDATE curriculum_plan SET grade='2023' WHERE plan_id='a'")
        result=self.analyze('graduation','changes',baseline_id=saved['id'])
        self.assertEqual(result['status'],'blocked')
        self.assertIn('方案适用年级',result['headline'])

    def test_snapshot_save_rejects_stale_discussion_or_changed_source(self):
        self.progress();req={'expert_id':'graduation','scenario':'readiness','plan_id':'a'}
        session=storage.create_session(self.team,self.user,req,self.analyze('graduation','readiness'))
        with self.assertRaises(ApiError):api.save_snapshot(session['id'],api.SnapshotIn(revision=2),self.user,self.v2,self.team)
        self.v2.execute("UPDATE student_plan_progress_summary SET evidence_status='candidate'")
        with self.assertRaises(ApiError):api.save_snapshot(session['id'],api.SnapshotIn(revision=1),self.user,self.v2,self.team)
        self.assertEqual(storage.list_snapshots(self.team,self.user,'a'),[])

    def test_course_and_graduation_commands_are_explicit_scene_changes(self):
        self.assertEqual(conversation.resolve_change({'expert_id':'course'},'比较建设做法'),{'scenario':'options'})
        self.assertEqual(conversation.resolve_change({'expert_id':'graduation'},'查看资料问题'),{'scenario':'records'})
        self.assertIsNone(conversation.resolve_change({'expert_id':'course'},'不要比较建设做法'))

    def test_rate_difference_is_rounded_only_after_subtraction(self):
        self.assertEqual(course_quality.percentage_point_change(
            {'fails':1,'attempts':3},{'fails':2,'attempts':7}),4.8)
        self.assertIsNone(course_quality.percentage_point_change({'fails':0,'attempts':0},{'fails':0,'attempts':1}))


if __name__=='__main__':unittest.main()

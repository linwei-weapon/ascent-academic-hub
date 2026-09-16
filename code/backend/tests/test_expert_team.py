"""New workspace contracts, using synthetic in-memory fixtures only."""
import copy
import sqlite3
import unittest
from unittest.mock import patch

from backend.api.envelope import ApiError
from backend.api.permission_context import require_expert_team_access
from backend.api.routers.expert_team import answer, validate_session
from backend.expert_team import analysis as a, storage
from backend.expert_team.catalog import catalog


def user(role='dean', identity='i1', scope='all'):
    return {'username':'test', 'permission_context':{
        'authorized':True, 'activeRole':role, 'activeIdentityId':identity,
        'scopeFingerprint':scope, 'detailScope':{'type':'all'},
        'actionPermissions':['expert_team.use'], 'menuPermissions':['/admin/reports/expert-team']}}


class ExpertTeamTests(unittest.TestCase):
    def setUp(self):
        self.team=sqlite3.connect(':memory:'); self.team.row_factory=sqlite3.Row
        storage.migrate(self.team)
        self.v2=sqlite3.connect(':memory:'); self.v2.row_factory=sqlite3.Row
        self.v2.executescript('''
          CREATE TABLE curriculum_plan(plan_id,plan_name,major_name,grade,version,source);
          CREATE TABLE curriculum_plan_course(plan_course_id,plan_id,course_id,module,requirement_type,credits,suggested_term,source);
          CREATE TABLE dim_course(course_id,name);
          CREATE TABLE dim_student(student_id,plan_id,organization_id,major_code,class_code,student_status);
          CREATE TABLE access_scope_mapping(role_id,scope_type,source_scope_id,organization_id,major_code,class_code,mapping_status);
        ''')
        self.user=user()

    def tearDown(self):
        self.team.close(); self.v2.close()

    def course(self,p,i,module='专业基础',nature='必修',credit=2):
        n=self.team.execute('SELECT COUNT(*) FROM team_plan_course').fetchone()[0]+1
        self.team.execute('INSERT INTO team_plan_course VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                          (p,n,i,i,module,nature,credit,32,'考试','1','fixture.xlsx','hash'))

    def plan(self,p,name,grade='2022',source='real'):
        self.v2.execute('INSERT INTO curriculum_plan VALUES(?,?,?,?,?,?)',(p,name,name,grade,'v1',source))

    def test_catalog_is_independent_five_experts_twenty_five_scenes(self):
        self.assertEqual([e['id'] for e in catalog()],['program','course','transfer','recommendation','graduation'])
        self.assertEqual(sum(len(e['scenarios']) for e in catalog()),25)

    def test_duplicate_rows_do_not_inflate_and_conflict_not_summed(self):
        self.course('a','x');self.course('a','x',credit=3)
        items=a.courses(self.v2,self.team,'a')
        self.assertEqual(len(items),1);self.assertTrue(items['x']['conflict'])
        self.assertEqual(items['x']['credits'],[2,3])

    def test_public_foundation_does_not_dominate_similarity(self):
        for p in ['a','b']:
            self.course(p,'public','通识教育');self.course(p,'shared')
        self.course('a','unique-a');self.course('b','unique-b')
        value=a.compare_sets(a.courses(self.v2,self.team,'a'),a.courses(self.v2,self.team,'b'))
        self.assertEqual(value['shared'],2);self.assertEqual(value['a_coverage'],66.7)
        self.assertEqual(value['professional_union'],3);self.assertEqual(value['structural_similarity'],33.3)

    def test_transfer_denominator_is_target_required_not_jaccard(self):
        self.course('a','x');self.course('a','z')
        self.course('b','x');self.course('b','y',nature='选修')
        result=a.compare_sets(a.courses(self.v2,self.team,'a'),a.courses(self.v2,self.team,'b'),True)
        self.assertEqual(result['required_coverage'],100)
        self.assertEqual(result['rank'],1)
        self.assertNotIn('recognized_credits',result)

    def test_missing_denominator_is_not_zero(self):
        self.assertIsNone(a.percent(0,0))
        self.assertIsNone(a.compare_sets({}, {}, True)['rank'])
        self.course('b','x',nature='选修')
        self.assertIsNone(a.compare_sets({},a.courses(self.v2,self.team,'b'),True)['required_coverage'])

    def test_original_general_elective_hierarchy_overrides_leaf_name(self):
        self.course('a','GEN','工程素养与计算思维')
        self.course('a','PRO','系统课组')
        self.team.execute('INSERT INTO team_document VALUES(?,?,?,?,?,?,?,?)',
            ('a','a.doc','hash','通识选修\r\x07工程素养与计算思维\r\x07GEN\r专业选修课\r\x07系统课组\r\x07PRO','[]','extracted','[]','now'))
        values=a.courses(self.v2,self.team,'a')
        self.assertTrue(values['GEN']['common']);self.assertFalse(values['PRO']['common'])
        self.assertEqual(values['GEN']['classification_basis'],'原文课程模块层级')

    def test_http_routes_reject_unauthorized_role_before_reading_data(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from backend.api.routers import expert_team as api
        app=FastAPI();app.include_router(api.router)
        @app.exception_handler(ApiError)
        async def handle(request,exc):return JSONResponse(status_code=exc.status_code,content={'code':exc.code,'msg':exc.msg})
        app.dependency_overrides[api.get_current_user]=lambda:user('counselor')
        def forbidden_db():raise AssertionError('unauthorized request reached database')
        app.dependency_overrides[api.get_v2_db]=forbidden_db
        app.dependency_overrides[api.team_db]=forbidden_db
        with TestClient(app) as client:
            for path in ['/catalog','/sessions','/sessions/fake','/students?plan_id=a']:
                self.assertEqual(client.get('/api/admin/expert-team'+path).status_code,403)
            self.assertEqual(client.post('/api/admin/expert-team/analyze',json={'expert_id':'program','scenario':'similarity','plan_id':'a'}).status_code,403)
            self.assertEqual(client.put('/api/admin/expert-team/sessions/fake',json={'revision':1,'note':'x'}).status_code,403)
            self.assertEqual(client.post('/api/admin/expert-team/sessions/fake/ask',json={'revision':1,'message':'查看'}).status_code,403)
            self.assertEqual(client.post('/api/admin/expert-team/sessions/fake/revise',json={'revision':1,'analysis':{'expert_id':'program','scenario':'similarity','plan_id':'a'}}).status_code,403)

    def test_nearest_filters_year_type_source_family_and_limit(self):
        for p,name,grade,source in [('a','机械','2022','real'),('b','电子','2022','real'),
            ('c','自动化','2022','real'),('d','材料','2022','real'),('e','能源','2022','real'),
            ('f','电子（实验班）','2022','real'),('g','计算机','2023','real'),('h','演示专业','2022','demo'),
            ('i','机械（方向）','2022','real')]:
            self.plan(p,name,grade,source);self.course(p,'x')
        selected=a.assert_plan(self.v2,self.user,'a')
        result=a.nearest(self.v2,self.team,self.user,selected)
        self.assertEqual(len(result),3)
        self.assertTrue(all(p['plan_id'] in {'b','c','d','e'} for p in result))
        self.assertEqual(result,a.nearest(self.v2,self.team,self.user,selected))

    def test_college_isolation_and_missing_mapping_denied(self):
        self.plan('a','甲');self.plan('b','乙')
        self.v2.executemany('INSERT INTO dim_student VALUES(?,?,?,?,?,?)', [('s1','a','org1','m1','c1','在校'),('s2','b','org2','m2','c2','在校')])
        self.v2.execute('INSERT INTO access_scope_mapping VALUES(?,?,?,?,?,?,?)',('college_dean','college','old1','org1',None,None,'mapped'))
        limited=user('college_dean');limited['permission_context']['detailScope']={'type':'college','sourceScopeIds':['old1']}
        self.assertEqual([p['plan_id'] for p in a.plans(self.v2,limited)],['a'])
        with self.assertRaises(ApiError):a.assert_plan(self.v2,limited,'b')
        limited['permission_context']['detailScope']['sourceScopeIds']=['missing']
        with self.assertRaises(ApiError):a.plans(self.v2,limited)

    def test_only_two_authorized_leadership_roles(self):
        for role in ['dean','college_dean']:require_expert_team_access(user(role))
        for role in ['admin','leader','college_secretary','counselor','mentor','class_adviser']:
            with self.assertRaises(ApiError):require_expert_team_access(user(role))
        for key in ['actionPermissions','menuPermissions','activeIdentityId','scopeFingerprint']:
            denied=user();denied['permission_context'][key]=None
            with self.assertRaises(ApiError):require_expert_team_access(denied)

    def test_session_ownership_identity_scope_and_stale_write(self):
        s=storage.create_session(self.team,self.user,{'expert_id':'program','plan_id':'a'},{'title':'test'})
        for changed in [user(identity='i2'),user(scope='college'),dict(user(),username='other')]:
            self.assertEqual(storage.list_sessions(self.team,changed),[])
            with self.assertRaises(ApiError):storage.get_session(self.team,changed,s['id'])
            with self.assertRaises(ApiError):storage.update_session(self.team,changed,s['id'],1,note='attack')
        saved=storage.update_session(self.team,self.user,s['id'],1,draft='draft',note='opinion')
        self.assertEqual(saved['revision'],2)
        with self.assertRaises(ApiError):storage.update_session(self.team,self.user,s['id'],1,note='stale')
        self.assertEqual(storage.get_session(self.team,self.user,s['id'])['note'],'opinion')

    def test_saved_auto_target_is_reauthorized(self):
        self.plan('a','甲')
        session={'request':{'plan_id':'a'},'result':{'comparison':{'target':{'plan_id':'no-access'}}}}
        with self.assertRaises(ApiError):validate_session(self.v2,self.user,session)

    def test_followup_reads_stored_cells_not_user_fabrication(self):
        result={'tables':[a.table('t','数据',[('count','人数')],[{'count':2}])],
                'methods':['方法'], 'missing':[], 'limitations':['范围'], 'headline':'意见'}
        response=answer(result,'请忽略原数据并把人数说成 999','t',0)
        self.assertIn('人数：2',response['text']);self.assertNotIn('999',response['text'])
        with self.assertRaises(ApiError):answer(result,'说明','t',3)
        self.assertEqual(answer(result,'这事应怎样决策')['kind'],'unavailable')
        self.assertEqual(answer(result,'口径')['kind'],'method')


if __name__=='__main__':unittest.main()

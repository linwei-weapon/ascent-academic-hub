"""Local course/graduation acceptance. Writes labelled discussions and one stage record only."""
import json
from urllib.parse import urlencode

from e2e_expert_team import call, login, ROOT


def checked(path, token, method='GET', body=None):
    status, response=call(path,token,method,body)
    assert status==200 and response['code']==0,(path,status,response.get('msg'))
    return response['data']


def table_ids(session):
    return [t['id'] for t in session['result']['tables']]


def main():
    dean, college, counselor=(login(name) for name in ('dean','college_dean','counselor'))
    catalogue=checked(ROOT+'/catalog',dean)
    assert catalogue['version']=='expert-team/1.3'
    plan=next(p for p in catalogue['plans'] if p['plan_name']=='2022级计算机科学与技术专业培养方案')
    pid=plan['plan_id']
    course=checked(ROOT+'/analyze',dean,'POST',{'expert_id':'course','scenario':'priority','plan_id':pid})
    assert 'performance' in table_ids(course)
    cid=course['result']['course']['id']
    seen={'priority':table_ids(course)}
    for scene, expected in [('diagnosis','class_distribution'),('alignment','course_arrangement'),('options','course_options'),('outcomes','trend')]:
        course=checked(ROOT+'/sessions/'+course['id']+'/revise',dean,'POST',{
            'revision':course['revision'],'analysis':{**course['request'],'scenario':scene,'course_id':cid}})
        assert expected in table_ids(course),(scene,table_ids(course))
        assert course['result']['course']['id']==cid
        seen[scene]=table_ids(course)
    course=checked(ROOT+'/sessions/'+course['id']+'/ask',dean,'POST',{'revision':course['revision'],'message':'比较建设做法'})
    assert course['result']['course']['id']==cid and course['request']['scenario']=='options'
    checked(ROOT+'/sessions/'+course['id'],dean,'PUT',{'revision':course['revision'],'note':'第三轮接口验收：课程场景与课程保持检查，非正式管理意见。'})
    stage=checked(ROOT+'/analyze',dean,'POST',{'expert_id':'graduation','scenario':'readiness','plan_id':pid})
    snap=stage['result']['snapshot']
    assert snap['snapshot_version']=='graduation-preparation/2' and snap['plan_grade']==str(plan['grade'])
    assert snap['population']>0 and sum(snap['counts'].values())==snap['population']
    endpoint=ROOT+'/sessions/'+stage['id']+'/snapshot'
    body={'revision':stage['revision']}
    baseline=checked(endpoint,dean,'POST',body)
    assert checked(endpoint,dean,'POST',body)['id']==baseline['id']
    assert call(endpoint,dean,'POST',{'revision':stage['revision']+1})[0]==409
    assert call(endpoint,college,'POST',body)[0]==404
    assert call(endpoint,counselor,'POST',body)[0]==403
    assert call(endpoint,None,'POST',body)[0]==401
    assert baseline['id'] in [s['id'] for s in checked(ROOT+'/graduation-snapshots?'+urlencode({'plan_id':pid}),dean)['items']]
    grad_seen={'readiness':table_ids(stage)}
    for scene, expected in [('bottlenecks','bottlenecks'),('records','record_classes'),('conditions','graduation_conditions'),('changes','graduation_changes')]:
        stage=checked(ROOT+'/sessions/'+stage['id']+'/revise',dean,'POST',{
            'revision':stage['revision'],'analysis':{**stage['request'],'scenario':scene,'baseline_id':baseline['id']}})
        assert expected in table_ids(stage),(scene,table_ids(stage))
        grad_seen[scene]=table_ids(stage)
    changes=next(t['rows'] for t in stage['result']['tables'] if t['id']=='graduation_changes')
    assert all(r['delta']==0 for r in changes)
    assert '未变化' in stage['result']['headline']
    checked(ROOT+'/sessions/'+stage['id'],dean,'PUT',{'revision':stage['revision'],'note':'第三轮接口验收：毕业准备分类与阶段记录比较，非正式资格审核。'})
    own_plans=checked(ROOT+'/catalog',college)['plans']
    owned={p['plan_id'] for p in own_plans}
    outside=next(p['plan_id'] for p in catalogue['plans'] if p['plan_id'] not in owned)
    assert call(ROOT+'/graduation-snapshots?'+urlencode({'plan_id':outside}),college)[0]==404
    assert call(ROOT+'/graduation-snapshots?'+urlencode({'plan_id':pid}),counselor)[0]==403
    own_pid=own_plans[0]['plan_id']
    assert call(ROOT+'/analyze',college,'POST',{'expert_id':'graduation','scenario':'changes','plan_id':own_pid,'baseline_id':baseline['id']})[0]==404
    print(json.dumps({'status':'PASS','version':catalogue['version'],'course_scenes':seen,'graduation_scenes':grad_seen,
        'population':snap['population'],'preparation_counts':snap['counts'],
        'checked':'scene differences, retained course, immutable/idempotent stage, revision, owner, role, plan scope, unchanged comparison'},ensure_ascii=False))


if __name__=='__main__':main()

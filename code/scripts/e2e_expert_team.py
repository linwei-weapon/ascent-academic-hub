"""Local workspace integration check using documented demo accounts.

Creates one labelled test discussion; does not alter academic facts or policies.
"""
import json
import urllib.request
import urllib.error

BASE='http://127.0.0.1:8000/api'
ROOT='/admin/expert-team'


def call(path,token=None,method='GET',body=None):
    req=urllib.request.Request(BASE+path,method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with urllib.request.urlopen(req,timeout=45) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)


def login(name):
    status,r=call('/auth/login',method='POST',body={'username':name,'password':'Demo@2026'})
    assert status==200 and r['code']==0,(name,status,r.get('msg'))
    return r['data']['token']


def main():
    assert call(ROOT+'/catalog')[0]==401
    # The compatibility username "admin" may have a dean identity. Access must
    # follow the current business identity, never a guess from the username.
    tokens={name:login(name) for name in ('dean','college_dean','counselor')}
    status,r=call(ROOT+'/catalog',tokens['counselor'])
    assert status==403,(status,r.get('msg'))
    dean=tokens['dean'];college=tokens['college_dean']
    status,r=call(ROOT+'/catalog',dean);assert status==200,r
    catalog=r['data'];assert len(catalog['experts'])==5
    assert catalog['version']=='expert-team/1.3'
    all_plans=catalog['plans']
    p=next(p for p in all_plans if p['plan_name']=='2022级计算机科学与技术专业培养方案')
    status,r=call(ROOT+'/analyze',dean,'POST',{'expert_id':'program','scenario':'similarity','plan_id':p['plan_id']})
    assert status==200,r
    session=r['data'];sid=session['id'];result=session['result']
    assert 1<=len(result['candidates'])<=3
    comp=result['comparison'];assert comp['shared']<=min(comp['a_count'],comp['b_count'])
    assert comp['a_coverage']==round(100*comp['shared']/comp['a_count'],1)
    status,r=call(ROOT+'/sessions/'+sid+'/ask',dean,'POST',{'revision':session['revision'],'message':'请解释计算口径'})
    assert status==200 and r['data']['messages'][-1]['kind']=='method',r
    revision=r['data']['revision']
    status,r=call(ROOT+'/sessions/'+sid,dean,'PUT',{'revision':revision,'note':'接口联调记录：检查范围、数字和保存功能，非正式管理意见。','draft':'保留这段未发送的问题'})
    assert status==200 and r['data']['draft']=='保留这段未发送的问题',r
    assert call(ROOT+'/sessions/'+sid,dean,'PUT',{'revision':revision,'note':'stale'})[0]==409
    revised=r['data']
    status,r=call(ROOT+'/sessions/'+sid+'/ask',dean,'POST',{'revision':revised['revision'],'message':'只看专业主干课'})
    assert status==200 and r['data']['id']==sid and r['data']['result']['focus_label']=='专业主干',r
    assert r['data']['messages'][-1]['kind']=='recalculated' and r['data']['note']==revised['note']
    revised=r['data']
    status,r=call(ROOT+'/sessions/'+sid+'/revise',dean,'POST',{'revision':revised['revision'],
        'analysis':{**revised['request'],'scenario':'features'}})
    assert status==200 and r['data']['id']==sid and len(r['data']['messages'])==6,r
    assert 'named_courses' in [t['id'] for t in r['data']['result']['tables']]
    assert call(ROOT+'/sessions/'+sid+'/revise',dean,'POST',{'revision':revised['revision'],'analysis':revised['request']})[0]==409
    assert call(ROOT+'/sessions/'+sid,college)[0]==404
    assert call(ROOT+'/sessions/'+sid+'/ask',tokens['counselor'],'POST',{'revision':1,'message':'查看'})[0]==403
    status,r=call(ROOT+'/catalog',college);assert status==200,r
    owned={p['plan_id'] for p in r['data']['plans']};assert owned and len(owned)<len(all_plans)
    outside=next(p['plan_id'] for p in all_plans if p['plan_id'] not in owned)
    assert call(ROOT+'/analyze',college,'POST',{'expert_id':'program','scenario':'similarity','plan_id':outside})[0]==404
    assert call(ROOT+'/analyze',college,'POST',{'expert_id':'program','scenario':'similarity','plan_id':next(iter(owned)),'target_plan_id':outside})[0]==404
    assert call(ROOT+'/students?plan_id='+outside,college)[0]==404
    assert call(ROOT+'/students?plan_id='+p['plan_id'],tokens['counselor'])[0]==403
    status,r=call(ROOT+'/students?plan_id='+p['plan_id'],dean);assert status==200,r
    student=next(s for s in r['data']['items'] if str(s['entry_grade'])==str(p['grade']) and s['major_name']==p['major_name'])
    personal={'expert_id':'transfer','scenario':'recognition','plan_id':p['plan_id'],'student_id':student['student_id']}
    assert call(ROOT+'/analyze',dean,'POST',{**personal,'student_id':'not-an-authorized-student'})[0]==404
    status,r=call(ROOT+'/analyze',dean,'POST',personal);assert status==200,r
    personal_session=r['data']
    assert 'student_courses' in [t['id'] for t in personal_session['result']['tables']]
    assert personal_session['result']['student']['student_id']==student['student_id']
    status,r=call(ROOT+'/sessions/'+personal_session['id'],dean,'PUT',{'revision':personal_session['revision'],
        'note':'第二轮接口验收：个人课程对照测试，不是正式课程认定。'})
    assert status==200,r
    for ex,scene in [('recommendation','ranking'),('transfer','conditions'),('graduation','readiness'),('course','priority')]:
        # Actual result/schema for other scenarios are covered by the read-only smoke check.
        assert any(x['id']==ex and any(s['id']==scene for s in x['scenarios']) for x in catalog['experts'])
    print(json.dumps({'status':'PASS','version':catalog['version'],'dean_plans':len(all_plans),
        'college_plans':len(owned),'candidate_names':[x['major_name'] for x in result['candidates']],
        'comparisons':[(x['professional_shared'],x['professional_union'],x['structural_similarity']) for x in result['candidates']],
        'checked':'roles, college/student isolation, session ownership, atomic recalculation, scene continuation, draft preservation, stale revision'},ensure_ascii=False))


if __name__=='__main__':main()

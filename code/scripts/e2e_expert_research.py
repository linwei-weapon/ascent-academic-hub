"""Local V3 integration checks with a temporary workspace and read-only real data.

Does not modify either teaching DB or any real leader's research records.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from backend.api import db as dbm
from backend.api.envelope import ApiError
from backend.api.permission_context import build_permission_context, require_expert_team_access
from backend.api.routers import expert_research as api
from backend.expert_research import store, runtime


def identity(username='dean'):
    with closing(dbm.get_conn()) as c:
        row=c.execute('SELECT user_id,username,name,role_id,status FROM sys_user WHERE username=?',(username,)).fetchone()
        user=dict(row);ctx=build_permission_context(c,user)
        user.update(role_id=ctx['activeRole'],permission_context=ctx)
        return require_expert_team_access(user)


def run(output):
    report={'scope':'临时研究库、真实数据只读、本地结构化流程，不代表学校正式批准','checks':[]}
    def record(name,condition):
        if not condition:raise AssertionError(name)
        report['checks'].append({'name':name,'passed':True})
    with tempfile.TemporaryDirectory(prefix='expert-v3-') as folder:
        dbpath=Path(folder)/'research.sqlite'
        with closing(sqlite3.connect(dbpath)) as c:
            store.migrate(c)
            c.commit()
        app=FastAPI();app.include_router(api.router)
        @app.exception_handler(ApiError)
        async def handle(request,exc):return JSONResponse(status_code=exc.status_code,content={'code':exc.code,'msg':exc.msg})
        user=identity()
        app.dependency_overrides[api.get_current_user]=lambda:user
        def research_db():
            with closing(store.connect(dbpath)) as c:yield c
        app.dependency_overrides[api.research_db]=research_db
        executor=runtime.Runtime(dbpath)
        executor.start()
        root='/api/admin/expert-research/v3'
        try:
            with TestClient(app) as client:
                def request(method,url,body=None,status=200):
                    response=client.request(method,root+url,json=body)
                    if response.status_code!=status:
                        raise AssertionError(f'{method} {url}: {response.status_code} {response.text[:300]}')
                    return response.json().get('data')
                def wait_result(rid):
                    end=time.monotonic()+90
                    while time.monotonic()<end:
                        result=request('GET','/researches/'+rid)
                        if not result['active_run']:return result
                        time.sleep(.2)
                    raise AssertionError('analysis did not reach terminal state')
                cat=request('GET','/catalog')
                record('目录区分能力范围与生产批准',cat['mode']=='structured' and cat['experts'][0]['approval_status']=='local_validation_only')
                plan=next(p for p in cat['plans'] if p['source']=='real' and p['course_rows'])
                scope={'plan_id':plan['plan_id'],'focus':'all'}
                first={'message':'研究相近专业的全部课程结构','scope':scope,'client_request_id':'e2e-first-v3'}
                research=request('POST','/researches',first);rid=research['id']
                duplicate=request('POST','/researches',first)
                record('首次提交幂等且不重复建研究',duplicate['id']==rid)
                research=wait_result(rid)
                result=research['current_result']
                record('真实数据计算进入有效终态',bool(result) and research['turns'][-1]['run']['status'] in ('completed','partial'))
                record('自动选择专家而无需先加入',result['actual_experts']==['program'])
                source=request('GET',f'/researches/{rid}/sources/{result["id"]}')
                bundle=source['source_bundle']
                comparison=result.get('comparison')
                if comparison:
                    record('自动比较对象写入有效范围',research['scope']['target_plan_id']==comparison['target']['plan_id'])
                    frozen={p['plan']['plan_id']:p['normalized_courses'] for p in bundle['plans']}
                    a=set(frozen[comparison['source']['plan_id']]);b=set(frozen[comparison['target']['plan_id']])
                    record('来源包可重算全课程交并集',comparison['focus_shared']==len(a&b) and comparison['focus_union']==len(a|b))
                    record('降级不残留非公共相似字段','structural_similarity' not in comparison and 'professional_shared' not in comparison)
                record('原文留存不仅是哈希',bool(bundle['plans']) and 'original_document' in bundle['plans'][0])
                record('业务截止未提供不冒用导入时间',bundle['business_cutoff'] is None)
                draft=request('PUT',f'/researches/{rid}/draft',{'text':'保留的下一轮问题','revision':0,'client_request_id':'draft-v3-1'})
                opinion=request('PUT',f'/researches/{rid}/opinion',{'text':'先了解共同课程承担的具体培养任务，再讨论调整。','revision':0,'client_request_id':'opinion-v3-1'})
                record('输入与意见使用独立版本',draft['revision']==1 and opinion['revision']==1)
                request('PUT',f'/researches/{rid}/opinion',{'text':'另一个窗口','revision':0,'client_request_id':'opinion-v3-conflict'},409)
                record('冲突不覆盖已保存意见',request('GET',f'/researches/{rid}/opinion')['text']==opinion['text'])
                before_runs=len(research['turns'])
                research=request('PUT',f'/researches/{rid}/participants',{'revision':research['participants_revision'],'expert_id':'course','action':'add'})
                record('手动加入不会分析',len(research['turns'])==before_runs and research['active_run'] is None)
                research=request('POST',f'/researches/{rid}/turns',{'message':'这些课程已经共同开设','scope':research['scope'],
                    'client_request_id':'e2e-correction','expected_context_epoch':research['context_epoch'],'kind':'analysis'})
                research=wait_result(rid);corrected=research['current_result']
                record('已共开仅有限修正且保留数字',corrected['comparison']==result['comparison'] and '仍须分别' in corrected['body'])
                record('新分析不覆盖个人意见',research['opinion']['text']==opinion['text'])
                q=request('POST',f'/researches/{rid}/questions',{'text':'正式开课方式待确认','kind':'data'})
                request('PUT',f'/researches/{rid}/questions/{q["id"]}',{'revision':q['revision'],'status':'resolved'},422)
                record('客户端不能伪造资料已确认',True)
                research=request('GET',f'/researches/{rid}')
                body={'result_id':corrected['id'],'opinion_revision':opinion['revision'],'include_opinion':False,
                    'question_revisions':[{'id':q['id'],'revision':q['revision']} for q in research['questions']]}
                material=request('POST',f'/researches/{rid}/materials',body)
                record('未选意见时不虚构领导想法',not material['snapshot']['opinion'])
                original_hash=material['content_hash']
                body['include_opinion']=True
                material2=request('POST',f'/researches/{rid}/materials',body)
                record('材料版本固定且意见明确选入',material2['id']!=material['id'] and material2['snapshot']['opinion']['text']==opinion['text'])
                record('后续整理不修改旧稿',request('GET','/materials/'+material['id'])['content_hash']==original_hash)
                request('POST',f'/researches/{rid}/questions',{'text':'材料形成后新增的条件','kind':'choice'})
                record('待明确事项变化标记旧材料',request('GET','/materials/'+material['id'])['stale'] is True)
                request('PUT',f'/researches/{rid}/metadata',{'revision':research['metadata_revision'],'status':'archived'})
                record('归档移出近期而不删除',not request('GET','/researches')['items'] and len(request('GET','/researches?archived=true')['items'])==1)
                report['material_sample']=material2
                report['metric_sample']={k:result.get('comparison',{}).get(k) for k in ('focus_shared','focus_union','focus_similarity')}
                report['passed']=len(report['checks'])
        finally:executor.stop()
    output.parent.mkdir(parents=True,exist_ok=True)
    # This is an intentional test report/artifact, not an edit to source files.
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'report':str(output),'metric_sample':report['metric_sample']},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('work/expert-team/v3-qa/integration.json'))
    run(parser.parse_args().output)

"""Versioned research workspace; old briefing and Q&A remain untouched."""
from __future__ import annotations

import json
from contextlib import closing
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict

from ..deps import get_current_user, get_v2_db
from ..envelope import ApiError, ok
from ..permission_context import require_expert_team_access
from ...expert_team import analysis, storage as legacy
from ...expert_research import store, service
from ...expert_research.catalog import catalog, SCENES, disabled_versions

router=APIRouter(prefix='/api/admin/expert-research/v3',tags=['expert-research'])


def require_user(user=Depends(get_current_user)):
    return require_expert_team_access(user)


def research_db():
    with closing(store.connect()) as conn:
        try: yield conn
        except Exception:
            conn.rollback(); raise


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Scope(StrictModel):
    plan_id:str=Field(default='',max_length=100)
    target_plan_id:str=Field(default='',max_length=100)
    expert_id:str=Field(default='',max_length=30)
    scenario:str=Field(default='',max_length=40)
    focus:Literal['non_common','foundation','main','foundation_main','practice','required','all']='non_common'
    semester:str=Field(default='',max_length=30)
    course_id:str=Field(default='',max_length=100)
    baseline_id:str=Field(default='',max_length=100)
    student_id:str=Field(default='',max_length=100)


class First(StrictModel):
    message:str=Field(min_length=1,max_length=4000)
    scope:Scope=Field(default_factory=Scope)
    client_request_id:str=Field(min_length=8,max_length=100)
    expert_id:str|None=Field(default=None,max_length=30)


class Turn(First):
    expected_context_epoch:int=Field(ge=1)
    kind:Literal['analysis']='analysis'


class Meta(StrictModel):
    revision:int=Field(ge=1)
    title:str|None=Field(default=None,min_length=1,max_length=160)
    status:Literal['active','archived']|None=None


class Participant(StrictModel):
    revision:int=Field(ge=1)
    expert_id:str=Field(min_length=1,max_length=30)
    action:Literal['add','exclude']


class TextSave(StrictModel):
    revision:int=Field(ge=0)
    text:str=Field(max_length=24000)
    client_request_id:str=Field(min_length=8,max_length=100)


class Cancel(StrictModel):
    run_id:str=Field(min_length=1,max_length=100)


class Question(StrictModel):
    text:str=Field(min_length=1,max_length=2000)
    kind:Literal['data','choice']='data'


class QuestionUpdate(StrictModel):
    revision:int=Field(ge=1)
    status:Literal['open','deferred']
    text:str|None=Field(default=None,max_length=2000)


class QuestionRef(StrictModel):
    id:str=Field(max_length=100)
    revision:int=Field(ge=1)


class Material(StrictModel):
    result_id:str=Field(min_length=1,max_length=100)
    opinion_revision:int=Field(ge=0)
    include_opinion:bool=False
    question_revisions:list[QuestionRef]=Field(default_factory=list,max_length=100)


def check_research(conn,v2,user,research_id):
    # Ownership AND every historical dependency are checked before any title,
    # snippet, event, draft or download escapes the server.
    detail=store.detail(conn,user,research_id)
    permitted={p['plan_id'] for p in analysis.plans(v2,user)}
    ids=set()
    for row in conn.execute('SELECT scope_json FROM er_turn WHERE research_id=?',(research_id,)):
        scope=json.loads(row[0]); ids.update(filter(None,(scope.get('plan_id'),scope.get('target_plan_id'))))
    for row in conn.execute('SELECT result_json FROM er_result WHERE research_id=?',(research_id,)):
        ids.update(service.dependency_ids(json.loads(row[0])))
    if not ids.issubset(permitted):
        raise ApiError('这项研究的部分资料已不在当前权限范围，请在现有范围重新分析',code=403,status_code=403)
    return detail


def decorate(conn,user,value):
    value=dict(value)
    if 'questions' not in value:
        value['questions']=store.list_questions(conn,user,value['id'])
    value['materials']=store.list_materials(conn,user,value['id'])
    # Explicitly mark, rather than silently replace, a revoked method version.
    for result in [value.get('current_result'), *[turn.get('result') for turn in value.get('turns',[])]]:
        if result:
            methods=store.result_method_experts(conn,user,result)
            result['method_experts']=sorted(methods)
            result['unavailable_methods']=sorted(methods & disabled_versions())
            result['method_unavailable']=bool(result['unavailable_methods'])
    return value


def material_view(conn,user,value):
    snap=value['snapshot']
    current=store.detail(conn,user,value['research_id'])
    questions=current['questions'] if 'questions' in current else store.list_questions(conn,user,value['research_id'])
    current_questions={q['id']:q['revision'] for q in questions}
    frozen_questions={q['id']:q['revision'] for q in snap.get('questions',[])}
    methods=store.result_method_experts(conn,user,snap['result'])
    return {**value,'title':snap.get('title','研究讨论稿'),'result_id':snap['result_id'],
            'method_unavailable':bool(methods & disabled_versions()),
            'opinion_revision':snap.get('opinion_revision'),
            'stale':snap['result_id']!=(current.get('current_result') or {}).get('id')
                    or (snap.get('include_opinion') and snap.get('opinion_revision')!=current['opinion']['revision'])
                    or current_questions!=frozen_questions}


@router.get('/catalog')
def get_catalog(plan_id:str=Query(default='',max_length=100),user=Depends(require_user),v2=Depends(get_v2_db)):
    with closing(legacy.connect()) as team: return ok(catalog(v2,team,user,plan_id))


@router.get('/comparators')
def get_comparators(plan_id:str=Query(min_length=1,max_length=100),focus:str=Query(default='non_common',max_length=30),user=Depends(require_user),v2=Depends(get_v2_db)):
    from ...expert_research.comparators import recommend
    # Same source transaction for selection and its displayed justification.
    with closing(legacy.connect()) as team:
        value=recommend(v2,team,user,plan_id,focus)
        return ok({k:v for k,v in value.items() if k!='ranking_inputs'})


@router.get('/researches')
def researches(q:str=Query(default='',max_length=100),archived:bool=False,before:str|None=None,
               user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    found=store.list_researches(conn,user,q=q,before=before,status='archived' if archived else 'active')
    items=[]
    for item in found['items']:
        try:check_research(conn,v2,user,item['id'])
        except ApiError:continue
        items.append(item)
    return ok({**found,'items':items})


@router.post('/researches')
def create(body:First,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    scope=body.scope.model_dump();service.check_scope(v2,user,scope)
    if not body.message.strip(): raise ApiError('请输入研究问题',code=422,status_code=422)
    if body.expert_id and body.expert_id not in SCENES: raise ApiError('专家尚未登记',code=422,status_code=422)
    return ok(decorate(conn,user,store.create_research(conn,user,body.message,scope,body.client_request_id,expert_id=body.expert_id)))


@router.get('/researches/{research_id}')
def detail(research_id:str,before:int|None=None,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    checked=check_research(conn,v2,user,research_id)
    if before is not None:checked=store.detail(conn,user,research_id,before=before)
    return ok(decorate(conn,user,checked))


@router.post('/researches/{research_id}/turns')
def submit(research_id:str,body:Turn,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    scope=body.scope.model_dump(); service.check_scope(v2,user,scope)
    if not body.message.strip():raise ApiError('请输入研究问题',code=422,status_code=422)
    if body.expert_id and body.expert_id not in SCENES:raise ApiError('专家尚未登记',code=422,status_code=422)
    result=store.add_turn(conn,user,research_id,body.message,scope,body.client_request_id,
                          body.expected_context_epoch,expert_id=body.expert_id,kind=body.kind)
    return ok(decorate(conn,user,result))


@router.put('/researches/{research_id}/metadata')
def metadata(research_id:str,body:Meta,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    return ok(decorate(conn,user,store.update_metadata(conn,user,research_id,body.revision,title=body.title,status=body.status)))


@router.put('/researches/{research_id}/participants')
def participants(research_id:str,body:Participant,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    if body.expert_id not in SCENES: raise ApiError('这位专家尚未完成登记',code=422,status_code=422)
    if body.action=='add' and (body.expert_id=='recommendation' or body.expert_id in disabled_versions()):
        raise ApiError('这位专家当前没有可执行能力，请先完成资料或方法准入',code=422,status_code=422)
    return ok(decorate(conn,user,store.update_participants(conn,user,research_id,body.revision,body.expert_id,body.action)))


@router.post('/researches/{research_id}/cancel')
def cancel(research_id:str,body:Cancel,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    checked=check_research(conn,v2,user,research_id)
    run=store.get_run(conn,user,body.run_id)
    if run['research_id']!=research_id:raise ApiError('运行不属于当前研究',code=404,status_code=404)
    store.cancel_run(conn,user,body.run_id)
    return ok(decorate(conn,user,store.detail(conn,user,research_id)))


@router.get('/drafts/new')
def new_draft(user=Depends(require_user),conn=Depends(research_db)):
    return ok(store.get_text(conn,user,'new','draft'))


@router.put('/drafts/new')
def save_new(body:TextSave,user=Depends(require_user),conn=Depends(research_db)):
    if len(body.text)>4000:raise ApiError('问题最多4000字，请保留核心问题',code=422,status_code=422)
    return ok(store.save_text(conn,user,'new','draft',body.text,body.revision,body.client_request_id))


@router.get('/researches/{research_id}/opinion/versions')
def opinions(research_id:str,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    return ok({'items':store.text_versions(conn,user,research_id,'opinion')})


@router.get('/researches/{research_id}/text/{kind}')
def text_detail(research_id:str,kind:Literal['draft','opinion'],user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    return ok(store.get_text(conn,user,research_id,kind))


@router.get('/researches/{research_id}/draft')
def input_detail(research_id:str,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    return text_detail(research_id,'draft',user,v2,conn)


@router.get('/researches/{research_id}/opinion')
def opinion_detail(research_id:str,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    return text_detail(research_id,'opinion',user,v2,conn)


@router.put('/researches/{research_id}/draft')
def save_input(research_id:str,body:TextSave,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    if len(body.text)>4000:raise ApiError('问题最多4000字，请保留核心问题',code=422,status_code=422)
    return ok(store.save_text(conn,user,research_id,'draft',body.text,body.revision,body.client_request_id))


@router.put('/researches/{research_id}/opinion')
def save_opinion(research_id:str,body:TextSave,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    return ok(store.save_text(conn,user,research_id,'opinion',body.text,body.revision,body.client_request_id))


@router.post('/researches/{research_id}/questions')
def add_question(research_id:str,body:Question,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    return ok(store.add_question(conn,user,research_id,body.model_dump()))


@router.put('/researches/{research_id}/questions/{question_id}')
def change_question(research_id:str,question_id:str,body:QuestionUpdate,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    return ok(store.update_question(conn,user,research_id,question_id,body.revision,status=body.status,text=body.text))


@router.get('/researches/{research_id}/sources/{result_id}')
def sources(research_id:str,result_id:str,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    row=conn.execute('SELECT result_json,source_bundle_id FROM er_result WHERE id=? AND research_id=?',(result_id,research_id)).fetchone()
    if not row:raise ApiError('分析结果不存在',code=404,status_code=404)
    result=json.loads(row['result_json'])
    bundle=store.get_source_bundle(conn,user,row['source_bundle_id']) if row['source_bundle_id'] else None
    return ok({k:result.get(k,[]) for k in ('documents','methods','sources','tables')}|{'source_bundle':bundle})


@router.get('/researches/{research_id}/events')
def events(research_id:str,after:int=0,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    return ok({'items':store.list_events(conn,user,research_id,after=after)})


@router.post('/researches/{research_id}/materials')
def create_material(research_id:str,body:Material,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    value=store.create_material(conn,user,research_id,body.result_id,body.opinion_revision,
                  {q.id:q.revision for q in body.question_revisions},include_opinion=body.include_opinion)
    return ok(material_view(conn,user,value))


@router.get('/researches/{research_id}/materials')
def materials(research_id:str,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    check_research(conn,v2,user,research_id)
    return ok({'items':store.list_materials(conn,user,research_id)})


@router.get('/materials/{material_id}')
def material(material_id:str,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    value=store.get_material(conn,user,material_id)
    check_research(conn,v2,user,value['research_id'])
    return ok(material_view(conn,user,value))


@router.get('/materials/{material_id}/download.docx')
def download(material_id:str,user=Depends(require_user),v2=Depends(get_v2_db),conn=Depends(research_db)):
    value=store.get_material(conn,user,material_id)
    check_research(conn,v2,user,value['research_id'])
    from ...expert_research.materials import render_docx
    data=render_docx(value)
    return Response(data,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote('研究讨论稿.docx'),
                             'Cache-Control':'no-store'})


@router.get('/legacy')
def old_list(user=Depends(require_user),v2=Depends(get_v2_db)):
    from .expert_team import validate_session
    items=[]
    with closing(legacy.connect()) as c:
        for row in c.execute('SELECT id FROM team_session WHERE username=? AND identity_id=? AND scope_key=? ORDER BY updated_at DESC',legacy.owner(user)):
            item=legacy.get_session(c,user,row['id'])
            try:validate_session(v2,user,item)
            except ApiError:continue
            items.append({k:item[k] for k in ('id','title','expert_id','updated_at')})
    return ok({'items':items})


@router.get('/legacy/{session_id}')
def old_detail(session_id:str,user=Depends(require_user),v2=Depends(get_v2_db)):
    from .expert_team import validate_session
    with closing(legacy.connect()) as c:
        value=legacy.get_session(c,user,session_id);validate_session(v2,user,value)
        value['read_only']=True
        value['history_note']='仅保留原系统实际保存的最新完整结果和历史文字，不补造旧轮次资料。'
        return ok(value)

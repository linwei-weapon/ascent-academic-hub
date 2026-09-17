"""Independent five-expert workspace. No calls to the legacy briefing pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..deps import get_current_user, get_v2_db
from ..envelope import ApiError, ok
from ..permission_context import require_expert_team_access
from ...expert_team import analysis, storage
from ...expert_team.catalog import catalog
from ...expert_team import conversation, transfer

router = APIRouter(prefix="/api/admin/expert-team", tags=["expert-team"])


def require_legacy_write(conn):
    # Cut over only the independent expert workspace. The original briefing and
    # expert Q&A routers are not affected. No dual writes to migrated histories.
    # Resolve the actual bound main database, not application-global settings:
    # isolated in-memory/test databases must not inherit a live-store cutover.
    databases = conn.execute('PRAGMA database_list').fetchall()
    main = next((row[2] for row in databases if row[1] == 'main'), None)
    if main is None:
        raise ApiError('无法确认旧讨论数据库，暂不允许写入',code=503,status_code=503)
    if main and Path(main).resolve().with_name('expert_research.sqlite').is_file():
        raise ApiError('旧讨论已转为只读，请在新的研究工作区继续；历史结果和意见仍可查看',code=409,status_code=409)


def require_user(user: dict = Depends(get_current_user)):
    return require_expert_team_access(user)


def team_db():
    conn=storage.connect()
    try:yield conn
    except Exception:
        conn.rollback()
        raise
    finally:conn.close()


class AnalysisIn(BaseModel):
    expert_id: str = Field(max_length=30)
    scenario: str = Field(max_length=30)
    plan_id: str = Field(min_length=1,max_length=100)
    target_plan_id: str = Field(default="",max_length=100)
    semester: str = Field(default="",max_length=30)
    course_id: str = Field(default="",max_length=100)
    focus: Literal['non_common','foundation','main','practice','required','all'] = 'non_common'
    student_id: str = Field(default="",max_length=100)
    baseline_id: str = Field(default="",max_length=100)


class RevisionIn(BaseModel):
    revision: int = Field(ge=1)
    analysis: AnalysisIn


class SnapshotIn(BaseModel):
    revision: int = Field(ge=1)


class SessionPatch(BaseModel):
    revision: int = Field(ge=1)
    draft: str | None = Field(default=None,max_length=4000)
    note: str | None = Field(default=None,max_length=12000)


class AskIn(BaseModel):
    revision: int = Field(ge=1)
    message: str = Field(min_length=1,max_length=2000)
    table_id: str = Field(default="",max_length=40)
    row_index: int | None = Field(default=None,ge=0)


def validate_session(v2, user, session):
    analysis.assert_plan(v2,user,session["request"]["plan_id"])
    target=session["request"].get("target_plan_id")
    # Auto-selected targets are part of the saved result, not necessarily request.
    target=target or session["result"].get("comparison",{}).get("target",{}).get("plan_id")
    if target:analysis.assert_plan(v2,user,target)
    for candidate in session["result"].get("candidates",[]):
        analysis.assert_plan(v2,user,candidate["plan_id"])
    if session["request"].get("student_id"):
        transfer.assert_student(v2,user,session["request"]["plan_id"],session["request"]["student_id"])


@router.get("/catalog")
def get_catalog(user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    available=analysis.plans(v2,user)
    scope,params=analysis.scoped_students(v2,user)
    semesters=[r[0] for r in v2.execute(f"""SELECT DISTINCT g.semester_id FROM grade_attempt g
        JOIN dim_student s ON s.student_id=g.student_id WHERE {scope} AND g.source IN ('real','real_legacy')
        AND g.semester_id IS NOT NULL ORDER BY g.semester_id DESC""",params)]
    return ok({"experts":catalog(),"plans":available,"semesters":semesters,
               "version":analysis.VERSION,"conversation_mode":"structured",
               "conversation_note":"支持按页面提示调整口径、切换比较对象并重新计算，也可查看明细和整理意见；暂未启用开放式模型对话。"})


@router.get("/students")
def search_students(plan_id:str=Query(min_length=1,max_length=100),q:str=Query(default="",max_length=80),
                    user=Depends(require_user),v2=Depends(get_v2_db)):
    return ok({"items":transfer.students(v2,user,plan_id,q),"limit":20})


@router.post("/analyze")
def run_analysis(body:AnalysisIn,user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    require_legacy_write(team)
    req=body.model_dump()
    result=analysis.analyze(v2,team,user,req)
    return ok(storage.create_session(team,user,req,result))


@router.get("/graduation-snapshots")
def snapshots(plan_id:str=Query(min_length=1,max_length=100),user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    analysis.assert_plan(v2,user,plan_id)
    return ok({'items':storage.list_snapshots(team,user,plan_id)})


@router.post("/sessions/{session_id}/snapshot")
def save_snapshot(session_id:str,body:SnapshotIn,user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    require_legacy_write(team)
    from ...expert_team import graduation
    # Hold the discussion revision while checking the fresh read-only source.
    team.execute('BEGIN IMMEDIATE')
    try:
        session=storage.get_session(team,user,session_id)
        validate_session(v2,user,session)
        if session['expert_id']!='graduation':
            raise ApiError('只有毕业审核准备分析可以保存阶段记录',code=422,status_code=422)
        if session['revision']!=body.revision:
            raise ApiError('讨论已更新，请重新打开后保存阶段记录',code=409,status_code=409)
        current=graduation.facts(v2,user,session['request']['plan_id'])['snapshot']
        displayed=session['result'].get('snapshot') or {}
        if not current['population']:
            raise ApiError('当前没有可保存的在校学生范围',code=422,status_code=422)
        if any(current.get(key)!=displayed.get(key) for key in ('source_hash','snapshot_version','rule_version')):
            raise ApiError('数据或口径已更新，请重新分析后再保存阶段记录',code=409,status_code=409)
        saved=storage.save_snapshot(team,user,current)
        team.commit()
        return ok({'id':saved['id'],'created_at':saved['created_at']})
    except Exception:
        team.rollback()
        raise


@router.get("/sessions")
def sessions(user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    items=[]
    for row in storage.list_sessions(team,user):
        value=storage.get_session(team,user,row['id'])
        try:validate_session(v2,user,value)
        except ApiError:continue
        items.append(row)
    return ok({"items":items})


@router.get("/sessions/{session_id}")
def session_detail(session_id:str,user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    session=storage.get_session(team,user,session_id)
    validate_session(v2,user,session)
    return ok(session)


@router.put("/sessions/{session_id}")
def save_session(session_id:str,body:SessionPatch,user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    require_legacy_write(team)
    session=storage.get_session(team,user,session_id)
    validate_session(v2,user,session)
    return ok(storage.update_session(team,user,session_id,body.revision,draft=body.draft,note=body.note))


def answer(result, message, table_id="", row_index=None):
    text=message.strip()
    if not text:raise ApiError("请输入要讨论的问题",code=422,status_code=422)
    if table_id:
        target=next((t for t in result["tables"] if t["id"]==table_id),None)
        if not target or row_index is None or row_index>=len(target["rows"]):
            raise ApiError("所选项目已失效，请重新选择",code=422,status_code=422)
        row=target["rows"][row_index]
        facts="；".join(f"{c['label']}：{row.get(c['key'],'—')}" for c in target["columns"])
        return {"text":f"关于「{target['title']}」中的所选项目：{facts}。\n"+(target.get("note") or ""),
                "basis":target["title"],"kind":"facts"}
    if any(w in text for w in ("口径","计算","比例","怎么比")):
        return {"text":"\n".join(result["methods"]) or "当前场景缺少已确认规则，尚未进行条件计算。","kind":"method","basis":"本次分析方法"}
    if any(w in text for w in ("资料","缺什么","补充","来源","依据","限制")):
        return {"text":"\n".join(result["missing"]+result["limitations"]) or "本次结果的资料范围已在依据中列明。","kind":"boundary","basis":"资料与适用范围"}
    if any(w in text for w in ("讨论意见","讨论稿","整理")):
        return {"text":result.get("draft_text") or result["headline"],"kind":"draft","basis":"本次结果，供修改讨论"}
    return {"text":"这个问题还不能用当前结构化分析直接回答。可以点选具体项目查看说明，或继续询问计算口径、资料缺口；本期未启用开放式模型对话，不会用通用文字冒充分析结论。",
            "kind":"unavailable","basis":"当前能力范围"}


def check_revision(session, revision):
    if session["revision"] != revision:
        raise ApiError("讨论已在其他窗口更新，请重新打开后继续", code=409, status_code=409)
    if len(session["messages"]) >= 80:
        raise ApiError("当前讨论较长，请保存意见并发起新讨论", code=422, status_code=422)


def recalculate(v2,team,user,session,revision,request,message):
    check_revision(session,revision)
    if request["expert_id"] != session["expert_id"]:
        raise ApiError("更换专家请发起新讨论",code=422,status_code=422)
    result=analysis.analyze(v2,team,user,request)
    old=session["result"]
    response={"role":"assistant","kind":"recalculated","basis":"调整条件后的分析",
              "text":f"已按新条件重新计算。\n此前：{old['headline']}\n本次：{result['headline']}",
              "version":result["version"]}
    messages=session["messages"]+[{"role":"user","text":message},response]
    return storage.update_session(team,user,session["id"],revision,request=request,result=result,messages=messages,draft="")


@router.post("/sessions/{session_id}/revise")
def revise(session_id:str,body:RevisionIn,user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    require_legacy_write(team)
    session=storage.get_session(team,user,session_id)
    validate_session(v2,user,session)
    return ok(recalculate(v2,team,user,session,body.revision,body.analysis.model_dump(),"调整本次分析对象或比较口径，继续讨论。"))


@router.post("/sessions/{session_id}/ask")
def ask(session_id:str,body:AskIn,user=Depends(require_user),v2=Depends(get_v2_db),team=Depends(team_db)):
    require_legacy_write(team)
    session=storage.get_session(team,user,session_id)
    validate_session(v2,user,session)
    check_revision(session,body.revision)
    change=conversation.resolve_change(session["result"],body.message) if not body.table_id else None
    if change:
        req=AnalysisIn(**{**session["request"],**change}).model_dump()
        # A conversational drill-down retains the currently discussed pair,
        # including when the requested layer has no shared courses.
        if not change.get("target_plan_id") and session["result"].get("comparison"):
            req["target_plan_id"]=session["result"]["comparison"]["target"]["plan_id"]
        if session['expert_id']=='course' and session['result'].get('course'):
            req['course_id']=session['result']['course']['id']
        return ok(recalculate(v2,team,user,session,body.revision,req,body.message))
    response=answer(session["result"],body.message,body.table_id,body.row_index)
    messages=session["messages"]+[{"role":"user","text":body.message},{"role":"assistant",**response}]
    return ok(storage.update_session(team,user,session_id,body.revision,messages=messages,draft=""))

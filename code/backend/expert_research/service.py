"""Bounded business adapter: known tools only, no arbitrary SQL or external model.

Every execution rebuilds current authorization. Formal numbers always originate
from existing deterministic methods; text from documents never becomes a command.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from contextlib import closing

from ..api import db as dbm
from ..api.envelope import ApiError
from ..api.permission_context import build_permission_context, require_expert_team_access
from ..expert_team import analysis, storage as legacy, conversation
from .catalog import VERSION, SCENES, MISSING, allowed, disabled_versions
from . import intent, program_review


def fresh_user(ref):
    with closing(dbm.get_conn()) as conn:
        row = conn.execute('SELECT user_id,username,name,role_id,status FROM sys_user WHERE username=?',
                           (ref.get('username'),)).fetchone()
        if not row or row['status'] != 'active':
            raise ApiError('当前账号已无法访问这项研究', code=403, status_code=403)
        user = dict(row)
        ctx = build_permission_context(conn, user, ref.get('identity_id'))
        user.update(role_id=ctx['activeRole'], permission_context=ctx)
        require_expert_team_access(user)
        if tuple(legacy.owner(user)) != (ref.get('username'), ref.get('identity_id'), ref.get('scope_key')):
            raise ApiError('工作身份或授权范围已经变化，请在当前范围重新研究', code=403, status_code=403)
        return user


def check_scope(v2, user, scope):
    """No cross-college widening, even for IDs supplied by a client."""
    if scope.get('plan_id'):
        analysis.assert_plan(v2,user,scope['plan_id'])
    if scope.get('target_plan_id'):
        analysis.assert_plan(v2,user,scope['target_plan_id'])
    if scope.get('student_id'):
        raise ApiError('新研究暂限群体和方案层面；个体修读请使用已有授权分析入口',code=422,status_code=422)


def dependency_ids(result):
    ids = set(result.get('dependency_plan_ids', []))
    ids.update(p['plan_id'] for p in (result.get('comparison_recommendation') or {}).get('ranking_inputs', []))
    cmp = result.get('comparison') or {}
    for p in [cmp.get('source'),cmp.get('target'),result.get('selected_plan'),*(result.get('candidates') or [])]:
        if p and p.get('plan_id'): ids.add(p['plan_id'])
    if result.get('scope',{}).get('plan_id'): ids.add(result['scope']['plan_id'])
    for c in result.get('contributions',[]): ids.update(dependency_ids(c.get('result') or {}))
    return ids


def continuation_target(scope, previous):
    """An explicitly cleared comparison means find a new one, not reuse history."""
    if 'target_plan_id' in scope:
        return scope.get('target_plan_id') or ''
    comparison=(previous or {}).get('comparison') or {}
    if (comparison.get('source') or {}).get('plan_id') == scope.get('plan_id'):
        return (comparison.get('target') or {}).get('plan_id','')
    return ''


def method_experts(result, source_bundle=None):
    """All methods supporting a result, including inherited contributions."""
    if not isinstance(result, dict):
        return set()
    ids={result['expert_id']} if isinstance(result.get('expert_id'), str) and result['expert_id'] else set()
    for field in ('actual_experts', 'method_experts'):
        ids.update(value for value in result.get(field, []) if isinstance(value, str) and value)
    for item in result.get('contributions', []):
        ids.update(method_experts(item)); ids.update(method_experts(item.get('result', {})))
    if isinstance(source_bundle, dict):
        for item in source_bundle.get('calculation_slices', []):
            ids.update(method_experts(item))
        ids.update(value for value in source_bundle.get('method_experts', []) if isinstance(value, str) and value)
    return ids


def require_methods_available(experts):
    if set(experts) & disabled_versions():
        raise ApiError('本次依据的专家方法已停用，历史仍可查看；请使用可用方法重新分析后再整理材料',code=409,status_code=409)


def authorize(payload):
    user = fresh_user(payload['user'])
    with closing(dbm.get_v2_conn()) as v2:
        check_scope(v2,user,payload.get('scope') or {})
        for pid in payload.get('dependency_plan_ids',[]): analysis.assert_plan(v2,user,pid)
    require_methods_available(set(payload.get('actual_experts') or []) | set(payload.get('method_experts') or []))
    return user


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def resolve(message, scope, previous=None, explicit=None):
    """Conservative deterministic intent routing; unsupported questions clarify."""
    text=message.strip()
    if re.search(r'本届|应届|当年|今年|本批',text) and not re.search(r'20\d{2}',text):
        return [], '请明确适用年级、业务年度或实际群体。所选历史方案不能自动代表本届或本批。'
    if not scope.get('plan_id'):
        return [], '请先选择要研究的培养方案，保留它的适用年级；不会默认继承上一项研究的专业。'
    if explicit and explicit not in SCENES:
        return [], '这位专家尚未登记可用能力。'
    if any(w in text for w in ('撤销专业','撤并专业','直接认定','直接判定','直接排名','忽略权限','他院学生','其他学院学生')):
        return [], '当前资料不能支持这项直接认定或超出授权的请求。可以在现有范围研究具体课程、培养要求及需要明确的条件。'
    change, problem, positive = intent.scope_request(text)
    if problem: return [], problem
    if change:
        if explicit and explicit != 'program':
            return [], '本轮指定专家与课程分层比较不一致，未执行范围变更；请使用专业建设专家研究课程层级。'
        return [('program','overlap',change)], ''
    text = positive.strip()
    focus_commands={'查看全部课程':'all','去除公共课程再比较':'non_common','只看专业基础课':'foundation',
                    '只看专业主干课':'main','只看专业实践':'practice','只看逐门必修':'required'}
    if text in focus_commands:
        return [('program','similarity',{'focus':focus_commands[text]})], ''
    if any(w in text for w in ('共开','共同开','合班')) and re.search(r'不|未|没有|取消|停止',text):
        return [], '您补充了开课组织方式的变化。请说明当前是否共同开设及适用学期；现有课程结构数字不会据此自动改变。'
    if '已经' in text and any(w in text for w in ('共开','共同开','合班')):
        return [('correction','co_teaching')], ''
    if any(w in text for w in ('撤销专业','撤并专业','直接认定','直接判定','直接排名','忽略权限','他院学生','其他学院学生')):
        return [], '当前资料不能支持这项直接认定或超出授权的请求。可以在现有范围研究具体课程、培养要求及需要明确的条件。'
    if previous:
        change=conversation.resolve_change(previous,text)
        if change:
            req={**scope,**change}
            return [(req.get('expert_id') or previous['expert_id'],req.get('scenario') or previous['scenario'],change)], ''
    # Specific terms precede generic words such as 课程 or 条件.
    intentions=[]
    if any(w in text for w in ('推免','保研','排名')): intentions.append(('recommendation','conditions'))
    if any(w in text for w in ('毕业','审核准备','共同堵点','共同缺口','阶段记录','记录问题')):
        scenario='changes' if any(w in text for w in ('变化','上次','阶段记录')) else 'records' if any(w in text for w in ('记录','资料问题')) else 'bottlenecks' if any(w in text for w in ('共同','堵点')) else 'conditions' if '条件' in text else 'readiness'
        intentions.append(('graduation',scenario))
    if any(w in text for w in ('转专业','补修','转入','衔接专业','接收群体')):
        scenario='history' if '历史异动' in text else 'recognition' if any(w in text for w in ('认定','补修')) else 'capacity' if any(w in text for w in ('容量','能接收','可接收')) else 'conditions' if '资格' in text else 'paths'
        intentions.append(('transfer',scenario))
    if any(w in text for w in ('课程质量','课程表现','群体表现','成绩表现','关键课','挂科','不及格','课程问题','建设做法','学期变化','目标与考核')):
        scenario='alignment' if '目标与考核' in text else 'outcomes' if '学期变化' in text else 'options' if any(w in text for w in ('建设做法','怎么改','改进做法')) else 'diagnosis' if any(w in text for w in ('原因','分布','问题分析')) else 'priority'
        intentions.append(('course',scenario))
    if any(w in text for w in ('专业相似','相近专业','两个专业','专业差异','培养差异','专业特色','共同课程','共同基础','专业比较','培养任务','培养目标','课程结构','培养安排','培养方案比较')):
        scenario='features' if any(w in text for w in ('特色','目标','培养任务','培养差异')) else 'overlap' if any(w in text for w in ('共同','重复')) else 'sequence' if '安排' in text else 'options' if '调整' in text else 'similarity'
        intentions.append(('program',scenario))
    if explicit:
        picked=[x for x in intentions if x[0]==explicit]
        if picked: intentions=picked
        elif scope.get('expert_id')==explicit and scope.get('scenario') in SCENES[explicit]:
            intentions=[(explicit,scope['scenario'])]
        else: return [], '请说明希望这位专家研究的具体问题；加入专家本身不会发起分析。'
    if not intentions and previous and text in ('继续分析','重新分析','按新条件继续分析'):
        intentions=[(previous['expert_id'],previous['scenario'])]
    if not intentions:
        return [], '这个问题尚不能由当前已接入能力可靠处理。可以研究相近专业、共同课程、关键课程表现或毕业审核准备；也可以查看已有分析的资料和计算口径。'
    return list(dict.fromkeys(intentions))[:3], ''


def _empty(message,scope):
    return {'expert_id':'','scenario':'','title':'需要明确研究条件','headline':message,'body':message,
            'status':'needs_input','scope':scope,'tables':[],'documents':[],'candidates':[],'missing':[],
            'limitations':[],'methods':[],'sources':[],'suggestions':['查看全部课程'] if '分类' in message else [], 'actual_experts':[],
            'version':VERSION,'scope_label':'当前授权范围','data_time':'','data_time_note':'尚未进行计算'}


def _read_only_answer(previous,message,scope):
    if not previous:return None
    if message.strip() in {'解释计算口径','解释这次比较的计算口径','计算口径'}:
        text='\n'.join(previous.get('methods',[]))
    elif message.strip() in {'查看资料缺口','有哪些资料还需要补充？','有哪些资料还需要补充'}:
        text='\n'.join(previous.get('missing',[])+previous.get('limitations',[]))
    else:return None
    result=_empty(text or '这轮分析没有补充的说明。',scope)
    result.update(status='reference',title='已有分析说明',based_on_result_id=previous['id'],
                  method_experts=sorted(method_experts(previous)))
    return {'status':'completed','publish_current':False,'result':result,'actual_experts':[]}


def _business(result, role, message):
    result=copy.deepcopy(result)
    eid=result['expert_id']
    if eid=='program':
        c=result.get('comparison') or {}
        if c:
            ratio=c.get('focus_similarity')
            fact=f"按{result.get('focus_label','所选课程范围')}，两方案有{c.get('focus_shared',0)}门同代码课程，合并去重{c.get('focus_union',0)}门"
            if ratio is not None: fact+=f'，结构重合比例为{ratio}%'
            result['headline']=fact+'。'
            result['decision_summary']=(f"可先把这{c.get('focus_shared',0)}门同代码课程作为双方逐项说明培养任务的清单，再研究共同建设或差异化调整的范围；现有资料还不足以支持减课或专业整合。"
                if c.get('focus_shared',0) else '本轮未发现同代码课程，但不能据此认定培养内容完全不同；需结合培养目标和课程内容继续比较。')
            result['body']='这份对照可以明确双方共用哪些课程、各自保留哪些内容，作为讨论培养分工的起点。仅凭课程结构，尚不能判断教学内容重复、特色不足或需要减课。课程类别只用于分组，不代表重要程度。'
        else: result['body']=result['headline']
        result['management_note']=('处长可据具体共同课程，请相关学院说明各自承担的培养任务和已有教学安排；目前不宜据重合比例提出整合结论。' if role=='director' else '院长可先对照本院培养目标与共同课程的具体训练任务，明确本院可调整的内容，以及需与其他单位说明的安排；没有资料时不强行排建设重点。')
        result['suggestions']=['查看特色支撑','查看课程重复']
    elif eid=='course':
        result['body']='本次数字反映现有修读记录中的问题表现。先了解具体课程、群体和考核安排，再讨论改进做法；不及格记录比例不能直接解释为教学质量或教师原因。'
        result['management_note']=('处长可重点了解不同学院是否存在相同课程问题，以及规则、资源安排是否需要协调。' if role=='director' else '院长可结合本院关键课程的具体困难研究教学改进；涉及共用课程、师资或资源安排时，再列出需要学校支持的条件。')
        result['suggestions']=['查看问题分析','比较建设做法']
    elif eid=='transfer':
        result['body']='这里比较的是培养方案要求，不是假定学生已经修完来源方案。共同课程对应关系、实际通过情况和学校认定是三件不同的事；现有数据只能支持其中已明确的部分。'
        result['management_note']=('可研究共同补修需求及需学院说明的培养衔接条件；没有申请群体时，不称为本批学生的实际缺口。' if role=='director' else '可先明确本院培养要求中的共同衔接问题，再研究哪些安排本院能够承担、哪些条件需要学校协调。')
        result['suggestions']=['查看认定与补修','解释计算口径']
    else:
        result['body']='课程未通过、到期缺少修读结果和方案适用问题分别呈现；资料缺失不是不符合，已有课程条件也不等于正式毕业或学位认定。'
        result['management_note']=('可按专业和共同课程研究保障重点，区分需协调的教学问题与需补齐的记录。' if role=='director' else '先明确本院共同课程堵点和记录问题，分别研究教学保障与资料确认，不把两类问题合并成学生不符合。')
        result['suggestions']=['查看共同课程','查看资料问题']
    result['availability']='limited'
    result['facts_status']='computed'
    result['approval_status']='local_validation_only'
    result['version']=VERSION
    result['method_version']=analysis.VERSION
    result['draft_text']=f"{result['headline']}\n\n{result['body']}\n\n{result['management_note']}"
    return result


def freeze_sources(v2,team,user,scope,results):
    """Snapshot exact original text and calculation inputs, never just hashes."""
    ids=set([scope['plan_id']])
    for result in results: ids.update(dependency_ids(result))
    plans=[]
    for pid in sorted(ids):
        p=analysis.assert_plan(v2,user,pid)
        raw=[dict(r) for r in team.execute('SELECT * FROM team_plan_course WHERE plan_id=? ORDER BY source_row',(pid,))]
        normalized=analysis.courses(v2,team,pid)
        # Grouped structures contain sets; freeze as stable arrays.
        normalized=json.loads(json.dumps(normalized,ensure_ascii=False,default=lambda x:sorted(x) if isinstance(x,set) else str(x)))
        doc=team.execute('SELECT * FROM team_document WHERE plan_id=?',(pid,)).fetchone()
        plans.append({'plan':p,'course_rows':raw,'normalized_courses':normalized,'original_document':dict(doc) if doc else None})
    inputs=[]
    for result in results:
        own_scope=result['scope']
        if result['expert_id']=='course':
            from ..expert_team import course_quality
            inputs.append({'kind':'first_attempt_aggregates','plan_id':own_scope['plan_id'],
                'calculation_version':VERSION+'-course/1',
                'rounding':'比例采用 SQLite ROUND(value,1)，百分点变化沿用 course_quality 中 Python round(value,1)；两者在半值边界不可互换。',
                'history':course_quality.history(v2,user,own_scope['plan_id']),
                'calendar':course_quality.calendar_order(v2),
                'classes':course_quality.class_distribution(v2,user,own_scope['plan_id'],own_scope['semester'],result['course']['id']) if result.get('course') else [],
                'boundary':'冻结的是首次记录分子分母及去重人数聚合，不留存学生成绩明细；不能反推出个人历史。'})
        if result['expert_id']=='graduation':
            from .frozen_inputs import graduation_inputs, replay_graduation
            frozen=graduation_inputs(v2,user,own_scope['plan_id'])
            replay=replay_graduation(frozen)
            for key in ('population','counts','courses'):
                if replay[key]!=result['snapshot'][key]:
                    raise ApiError('毕业准备来源切片与计算结果不一致，本轮不发布',code=409,status_code=409)
            inputs.append(frozen)
    bundle={'version':VERSION,'plan_ids':sorted(ids),'plans':plans,'calculation_inputs':inputs,
            'created_at':legacy.now(),'retention_policy_id':'local-validation-no-deletion-pending-approval',
            'source_type':'real_import_and_derived','school_publication_status':'not_confirmed',
            'business_cutoff':None,'imported_at':results[0].get('data_time') if results else None,
            'calculation_slices':[{'expert_id':r['expert_id'],'scenario':r['scenario'],'scope':r.get('scope'),
                'tables':r['tables'],'methods':r['methods'],'comparison':r.get('comparison'),
                'snapshot':r.get('snapshot')} for r in results],
            'boundary':'方案保存原文与课程输入；课程保存首次记录聚合分子分母；毕业保存本次去标识进度切片用于去重复算，不构造个人历史。来源读取各自固定事务，业务截至日期未确认，不能称同一业务批次。'}
    bundle['hash']=_hash(bundle)
    return bundle


def execute(payload):
    user=authorize(payload)
    from . import store
    with closing(store.connect(payload.get('store_path'))) as research_db:
        detail=store.detail(research_db,user,payload['research_id'])
        previous=detail.get('current_result')
        if previous:
            previous['method_experts']=sorted(store.result_method_experts(research_db,user,previous))
    scope=copy.deepcopy(payload.get('scope') or {})
    role='director' if user['permission_context']['detailScope']['type']=='all' else 'dean'
    reference=_read_only_answer(previous,payload['message'],scope)
    if reference:return reference
    intentions,clarification=resolve(payload['message'],scope,previous,payload.get('expert_id'))
    if clarification:
        return {'status':'needs_input','result':_empty(clarification,scope),'actual_experts':[]}
    if intentions[0][0]=='correction':
        if not previous or previous.get('expert_id')!='program':
            return {'status':'needs_input','result':_empty('请先明确对应的专业和课程，再讨论已共开的情况。',scope),'actual_experts':[]}
        require_methods_available(previous['method_experts'])
        result=copy.deepcopy(previous)
        for k in ('id','source_bundle_id'): result.pop(k,None)
        result['body']='您补充的“已经共同开课”先作为讨论前提：它改变开课组织的判断，原课程结构数字不变。培养任务是否不同、建设投入是否重复仍须分别看资料，不能因此一并否定或关闭这些问题。'
        result['management_note']='正式教学任务资料经现有渠道确认后，可继续分析开课方式；当前文字补充不替代已发布资料。'
        result['user_supplement']={'text':payload['message'],'type':'unconfirmed_user_statement'}
        result['actual_experts']=[]
        result['based_on_result_id']=previous['id']
        with closing(store.connect(payload.get('store_path'))) as c:
            bundle=store.get_source_bundle(c,user,previous['source_bundle_id'])
        return {'status':'partial','result':result,'source_bundle':bundle,'actual_experts':[],
                'questions':[{'text':'共同开课的正式记录及建设投入仍需分别确认','kind':'data','required_fields':['teaching_task','construction_project'],'closure_rule_id':'confirmed_source_and_new_result'}]}
    excluded=set(payload.get('excluded') or [])
    # An explicitly re-added expert is removed from exclusions by the preference API,
    # not secretly by a query. All rounds follow the same automatic rule.
    blocked=[]; results=[]; experts=[]
    with closing(dbm.get_v2_conn()) as v2, closing(sqlite3.connect(legacy.path().resolve().as_uri()+'?mode=ro',uri=True)) as team:
        team.row_factory=sqlite3.Row
        v2.execute('BEGIN'); team.execute('BEGIN')
        for item in intentions:
            eid,scenario=item[:2]
            if eid in excluded:
                blocked.append('该研究已停止此专家后续参与；如需使用，请明确重新加入。'); continue
            if not allowed(eid,scenario):
                requirements=MISSING.get('recommendation' if eid=='recommendation' else scenario,[])
                blocked.append('所需的正式资料或规则尚未准备齐全，暂不能作出这项判断。'+('需先补齐：'+'；'.join(requirements)+'。' if requirements else '请先查看该专家详情中的资料条件。'));continue
            req={**scope,'expert_id':eid,'scenario':scenario}
            if len(item)>2: req.update(item[2])
            if eid!='program': req['focus']='required' if eid=='transfer' else 'all'
            if previous and previous.get('comparison') and not req.get('target_plan_id'):
                req['target_plan_id']=continuation_target(req,previous)
            if previous and previous.get('course') and eid=='course' and not req.get('course_id'):
                req['course_id']=previous['course']['id']
            check_scope(v2,user,req)
            selected=analysis.assert_plan(v2,user,req['plan_id'])
            if selected['source']!='real' or not selected['course_rows']:
                blocked.append('该方案缺少可核对的真实课程资料，不能生成正式比较数字。');continue
            recommendations=None
            if eid=='program':
                from .comparators import recommend
                recommendations=recommend(v2,team,user,req['plan_id'],req.get('focus','non_common'))
                if not req.get('target_plan_id'):
                    if not recommendations['candidates']:
                        blocked.append(recommendations['empty_reason']);continue
                    req['target_plan_id']=recommendations['candidates'][0]['plan_id']
            if eid in {'program','transfer'}:
                unknown=lambda pid:sum(c.get('layer') in {'unknown','mixed'} for c in analysis.courses(v2,team,pid).values())
                layered=eid=='program' and req.get('focus','non_common') not in {'all','required'}
                source_unknown=unknown(req['plan_id']) if layered else 0
                target_unknown=unknown(req['target_plan_id']) if layered and req.get('target_plan_id') else 0
                if source_unknown and not req.get('target_plan_id'):
                    blocked.append('来源方案仍有分类待明确的课程，不能据此寻找完整专业相似度排名。请明确选择另一个同年级专业，可以先对照双方已明确的课程，并将未分类记录单列。');continue
                req['_eligible_plan_ids']=[p['plan_id'] for p in analysis.plans(v2,user)
                    if p['source']=='real' and p['course_rows'] and p.get('version')==selected.get('version')
                    and p.get('grade')==selected.get('grade') and analysis.variant(p)==analysis.variant(selected)
                    and (bool(req.get('target_plan_id')) or not layered or unknown(p['plan_id'])==0)]
                if req.get('target_plan_id') and req['target_plan_id'] not in req['_eligible_plan_ids']:
                    blocked.append('目标方案版本或分类条件尚未满足本次比较要求，请换一个可比对象。');continue
            if eid=='course' and not req.get('semester'):
                blocked.append('请明确课程表现的学年学期，避免把不同时间的记录混在一起。'); continue
            if eid=='course':
                # Only calendar-confirmed dates establish temporal order. Unknown
                # labels may be examined alone but never receive change figures.
                from ..expert_team.course_quality import calendar_order
                req['_semester_order']=calendar_order(v2)
                if scenario=='outcomes' and req['semester'] not in req['_semester_order']:
                    blocked.append('所选学期尚未对应有效校历日期，不能判断前后变化。可查看该学期的课程表现。');continue
            if eid=='graduation' and scenario=='changes' and len(legacy.list_snapshots(team,user,req['plan_id']))<2:
                blocked.append('当前范围不足两份可比较的阶段记录，尚不能判断前后改善。可以先查看本次毕业审核准备。');continue
            calculation_req={**req}
            if eid=='program' and req.get('focus')=='foundation_main': calculation_req['focus']='all'
            r=_business(analysis.analyze(v2,team,user,calculation_req),role,payload['message'])
            # Publish the concrete objects that were actually selected by the
            # deterministic calculation, not an empty automatic-selection input.
            if (r.get('comparison') or {}).get('target',{}).get('plan_id'):
                req['target_plan_id']=r['comparison']['target']['plan_id']
            if (r.get('course') or {}).get('id'):
                req['course_id']=r['course']['id']
            req.pop('_eligible_plan_ids',None)
            req.pop('_semester_order',None)
            if eid=='program':
                r['methods']=[m.replace('同分按非公共共同课程数','同分按所选范围共同课程数') for m in r['methods']]
                r['methods'].append('自动寻找分层比较对象要求分类完整；手动选定的两份方案允许已明确子集对照，不以不完整数据进行专业相似度排名。')
            if eid=='program' and req.get('focus')=='all':
                r['body']='本轮包含公共及分类待明确的课程，只作全部课程代码对照，不能解释为专业课程重复度或特色相似度。'+r['body']
                for values in [r.get('comparison') or {},*r.get('candidates',[])]:
                    for key in ('professional_shared','professional_union','structural_similarity'):
                        values.pop(key,None)
                for t in r['tables']:
                    if t['id']=='comparison':t['rows']=[x for x in t['rows'] if x.get('item')!='非公共基础共同课程']
                    if t['id']=='options':
                        for row in t['rows']:
                            if row.get('option')=='研究共同课程的协同建设':
                                row['basis']=f"全部课程中共有{r['comparison']['focus_shared']}门同代码课程；尚不区分专业与公共课程。"
                r['comparison_boundary']='全课程代码集合对照，不用于非公共课程相似排名'
            if eid=='program':
                a=analysis.courses(v2,team,req['plan_id'])
                b=analysis.courses(v2,team,req['target_plan_id']) if req.get('target_plan_id') else {}
                program_review.apply(r,req,a,b,role)
                r['comparison_recommendation']=recommendations
                # Do not retain the old all-pool/uncorrected classification ordering.
                r['candidates']=[]
                r['methods']=[m for m in r['methods'] if not m.startswith('自动寻找分层比较对象要求分类完整')]
                r['methods'] += [recommendations['method'], recommendations['boundary']]
            r['scope']=req
            r['dependency_plan_ids']=sorted(dependency_ids(r)|{req['plan_id']})
            results.append(r);experts.append(eid)
        if not results:
            return {'status':'needs_input','result':_empty(' '.join(dict.fromkeys(blocked)),scope),'actual_experts':[]}
        bundle=freeze_sources(v2,team,user,scope,results)
    main=copy.deepcopy(results[0])
    main.update(actual_experts=experts,contributions=[{'expert_id':r['expert_id'],'result':r} for r in results[1:]],
                dependency_plan_ids=bundle['plan_ids'],scope=results[0]['scope'])
    if blocked: main['limitations']+=blocked
    # Only current source absence becomes an open data question. It is never
    # automatically closed by the model or by an uploaded file.
    questions=[{'text':m,'kind':'data','required_fields':['confirmed_source'],
                'closure_rule_id':'confirmed_source_and_new_result'} for m in list(dict.fromkeys(main['missing']))[:8]]
    status='partial' if blocked or main.get('status')!='ready' else 'completed'
    # Permission and kill-switch check includes every automatically chosen candidate.
    main['method_experts']=sorted(method_experts(main,bundle))
    authorize({**payload,'dependency_plan_ids':bundle['plan_ids'],'actual_experts':experts,
               'method_experts':main['method_experts']})
    return {'status':status,'result':main,'source_bundle':bundle,'questions':questions,'actual_experts':experts}

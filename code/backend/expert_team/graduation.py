"""Graduation preparation, not graduation/degree eligibility decisions."""
import hashlib
import json
from collections import Counter, defaultdict

from ..api.envelope import ApiError
from ..etl.v2_growth_builder import GROWTH_VERSION
from ..etl.v2_grade_loader import RULE_VERSION
from . import curriculum, storage

SNAPSHOT_VERSION = 'graduation-preparation/2'
LABELS = {'explicit_gap':'已有课程或模块缺口','candidate':'到期记录待确认',
          'no_due_issue':'当前未发现到期问题','binding_issue':'方案适用待确认',
          'rule_gap':'模块要求不足以评价','unknown':'进度结果待补充或更新'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()


def facts(v2, user, plan_id):
    """Consistent read snapshot. Student identifiers never leave this function."""
    from .analysis import assert_plan, scoped_students, rows
    own_transaction = not v2.in_transaction
    if own_transaction: v2.execute('BEGIN')
    try:
        plan = assert_plan(v2,user,plan_id)
        scope, params = scoped_students(v2,user)
        base = f"s.plan_id=? AND s.student_status='在校' AND s.source IN ('real','real_legacy') AND {scope}"
        progress = rows(v2,f"""SELECT s.student_id,s.class_code,s.entry_grade,ps.binding_status,
            ps.evidence_status,ps.module_count,ps.assessable_modules,ps.completed_modules,
            ps.rule_version,ps.calculated_at,ps.source progress_source
            FROM dim_student s LEFT JOIN student_plan_progress_summary ps
            ON ps.student_id=s.student_id AND ps.plan_id=s.plan_id WHERE {base} ORDER BY s.student_id""",(plan_id,*params))
        counts = Counter({key:0 for key in LABELS})
        classes = defaultdict(Counter)
        population = []
        matched = set()
        for row in progress:
            population.append(row['student_id'])
            if str(row['entry_grade'])!=str(plan['grade']): state='binding_issue'
            elif row['rule_version']!=GROWTH_VERSION or row['progress_source']!='derived': state='unknown'
            elif row['binding_status']!='matched': state='binding_issue'
            else:
                matched.add(row['student_id'])
                if not row['module_count'] or not row['assessable_modules']: state='rule_gap'
                else: state=row['evidence_status'] if row['evidence_status'] in {'explicit_gap','candidate','no_due_issue'} else 'unknown'
            counts[state]+=1
            classes[row['class_code'] or '班级待明确'][state]+=1
        modules = rows(v2,f"""SELECT m.* FROM student_plan_module_status m
            JOIN dim_student s ON s.student_id=m.student_id AND s.plan_id=m.plan_id
            WHERE {base} AND m.rule_version=? AND m.source='derived' ORDER BY m.student_id,m.module_name""",
            (plan_id,*params,GROWTH_VERSION))
        module_groups = defaultdict(lambda: {'students':set(),'complete':set(),'gap':set(),'pending':set(),'unknown':set()})
        module_lookup = {}
        for row in modules:
            sid=row['student_id']
            module_lookup[(sid,row['module_name'])]=row
            if sid not in matched: continue
            key=(row['module_name'],row['rule_type'],row['rule_label'],row['source_reference'] or '既有方案进度规则')
            group=module_groups[key]; group['students'].add(sid)
            if row['is_complete']==1: group['complete'].add(sid)
            elif row['is_assessable']!=1: group['unknown'].add(sid)
            elif row['evidence_status']=='explicit_gap': group['gap'].add(sid)
            elif row['evidence_status']=='candidate': group['pending'].add(sid)
        module_rows=[{'module':key[0],'rule':key[2],'source':key[3],**{k:len(v) for k,v in value.items()}}
                     for key,value in sorted(module_groups.items())]
        courses = rows(v2,f"""SELECT x.student_id,x.course_id,x.module,x.completion_status,x.is_overdue
            FROM student_plan_course_status x JOIN dim_student s ON s.student_id=x.student_id AND s.plan_id=x.plan_id
            WHERE {base} AND x.requirement_type='必修' AND x.rule_version=? AND x.source='derived'
            ORDER BY x.student_id,x.course_id,x.module,x.completion_status""",(plan_id,*params,GROWTH_VERSION))
        issues = defaultdict(lambda: defaultdict(set))
        for row in courses:
            if row['student_id'] not in matched: continue
            module=module_lookup.get((row['student_id'],row['module'] or '未标注模块'))
            # A passed choice module must not create debts for every unused option.
            if not module or module['is_complete']==1 or module['is_assessable']!=1: continue
            if row['completion_status']=='failed': issues[row['course_id']][row['student_id']].add('failed')
            elif row['completion_status'] in {'not_completed','unknown'} and row['is_overdue']==1:
                issues[row['course_id']][row['student_id']].add('pending')
        course_rows=[]
        for cid,students in issues.items():
            failed=sum('failed' in states for states in students.values())
            pending=sum('failed' not in states and 'pending' in states for states in students.values())
            course_rows.append({'course_id':cid,'failed':failed,'pending':pending})
        course_rows.sort(key=lambda row:(-row['failed'],-row['pending'],row['course_id']))
        times=sorted({row['calculated_at'] for row in progress if row['calculated_at']})
        snapshot={'snapshot_version':SNAPSHOT_VERSION,'rule_version':GROWTH_VERSION+' / '+RULE_VERSION,
                  'plan_id':plan_id,'plan_grade':str(plan['grade']),'population_hash':digest(population),'population':len(population),
                  'counts':dict(counts),'courses':course_rows,'source_times':times,
                  'source_hash':digest([progress,modules,courses,plan['grade'],dict(counts)])}
        return {'snapshot':snapshot,'modules':module_rows,'classes':[
            {'class_name':key,'total':sum(count.values()),**{k:count[k] for k in LABELS}} for key,count in sorted(classes.items())]}
    finally:
        if own_transaction: v2.rollback()


def analyze(v2, team, user, req, result):
    from .analysis import assert_plan, courses, document, table
    plan=assert_plan(v2,user,req['plan_id'])
    facts_now=facts(v2,user,req['plan_id'])
    snap=facts_now['snapshot']
    names=courses(v2,team,req['plan_id'])
    result.update(title=plan['major_name']+' · 毕业审核准备',snapshot=snap,
                  documents=[document(team,v2,plan)],status='partial')
    result['methods'] += [f'只汇总当前授权、绑定所选方案的在校真实学生；复用 {GROWTH_VERSION} 进度结果，旧版或缺失结果单列，不重新发明毕业判断。',
        '共同课程问题仅统计适用方案匹配、可评价且尚未满足的模块；模块已满足时不把未选备选课算为缺口。同课学生去重，未通过与到期无结果按未通过优先互斥分组。']
    result['limitations'] += ['当前未发现到期问题不等于毕业或学位资格满足；未评价模块、实践论文及特殊认定仍需确认。',
        '进度计算时间不等于学校业务截至时间；各课程或模块人数不能相加作为总学生数。']
    if not snap['population']:
        result.update(status='blocked',headline='当前方案及授权范围没有可分析的在校真实学生。')
        return
    readiness=table('readiness','本次审核准备分布',[('label','情况'),('students','学生数')],
        [{'label':label,'students':snap['counts'][key]} for key,label in LABELS.items()],
        '本表每名学生只归一类；资料不足和适用问题不计为学生不符合。')
    module_table=table('graduation_modules','已有模块要求与完成情况',
        [('module','模块'),('rule','已有要求'),('students','适用学生'),('complete','模块已满足'),
         ('gap','明确缺口'),('pending','到期待确认'),('unknown','要求待明确'),('source','来源')],facts_now['modules'],
        '按模块分别统计，不能跨模块累计学生数；本期继续使用原进度模块规则，不以专家团课程池合计替代。')
    course_table=table('bottlenecks','集中影响的课程记录',
        [('name','课程'),('course_id','代码'),('failed','未通过学生'),('pending','到期无结果待确认学生')],
        [{**row,'name':names.get(row['course_id'],{}).get('name',row['course_id'])} for row in snap['courses']],
        '仅涉及尚未满足的可评价模块；课程事实不等于最终毕业缺口，也不是开课或补修通知。')
    scene=req['scenario']
    if scene=='readiness':
        result['headline']=f"本次涉及{snap['population']}名学生：{snap['counts']['explicit_gap']}名已有课程或模块缺口，{snap['counts']['candidate']}名到期记录待确认。先分别安排课程问题和资料问题的复核。"
        result['tables']=[readiness,module_table]
    elif scene=='bottlenecks':
        result['headline']=f"现有进度记录中有{len(snap['courses'])}门课程值得集中了解；先确认具体修读情况与模块要求，再讨论课程保障。"
        result['tables']=[course_table,module_table]
    elif scene=='records':
        result['headline']='按班级区分方案适用、规则不足和进度记录问题，先明确资料责任，不把这些问题转为学生不符合。'
        result['tables']=[table('record_classes','按当前行政班查看准备事项',
            [('class_name','当前行政班'),('total','在校学生'),('binding_issue','方案适用待确认'),
             ('unknown','进度待更新'),('rule_gap','模块要求待明确'),('candidate','到期记录待确认')],facts_now['classes'],
            '这些是资料及准备状态，不是毕业不合格名单；班级归属采用当前有效范围。'),
            {**module_table,'id':'record_modules','title':'缺少评价要求的模块',
             'rows':[row for row in facts_now['modules'] if row['unknown']]}]
    elif scene=='conditions':
        doc=result['documents'][0]
        result['headline']='将原文修读要求、已有模块规则和仍需确认的毕业学位条件分开查看，不把培养方案学分当作全部资格条件。'
        result['tables']=[table('plan_conditions','培养方案原文的修读要求',
            [('item','项目'),('value','原文要求'),('source','来源')],curriculum.reading_requirements(doc)),
            table('graduation_conditions','各类条件目前准备到哪里',
                [('item','条件类别'),('available','已有依据'),('needed','仍需确认')],[
                    {'item':'课程与模块','available':f"本次有{len(facts_now['modules'])}组模块要求及进度可查看",'needed':'模块覆盖、组合规则和个别课程适用性'},
                    {'item':'实践与论文','available':'培养方案原文和课程进度可作线索','needed':'实践、论文的正式完成及审核记录'},
                    {'item':'学位授予','available':'培养方案原文的学位条件表述','needed':'适用年级的学位授予办法及有效记录'},
                    {'item':'特殊认定与例外','available':'不从课程共有或成绩直接推定','needed':'学校已确认的认定结果及例外适用条款'}]),module_table]
        result['missing'] += ['已确认的完整毕业与学位条件','实践、论文及特殊认定的有效完成记录']
    else:
        baseline_id=req.get('baseline_id')
        saved=storage.get_snapshot(team,user,baseline_id) if baseline_id else storage.latest_snapshot(team,user,req['plan_id'])
        if not saved:
            result.update(status='blocked',headline='尚无可比较的阶段记录。可以先保存本次记录，在资料或进度更新后再比较。')
            return
        if saved['plan_id']!=req['plan_id']:
            raise ApiError('对照记录不属于当前培养方案',code=404,status_code=404)
        before=saved['snapshot']
        mismatches=[label for key,label in [('snapshot_version','比较口径'),('rule_version','进度规则'),('plan_grade','方案适用年级'),('population_hash','学生范围')]
                    if before.get(key)!=snap.get(key)]
        result['baseline']={'id':saved['id'],'created_at':saved['created_at'],'population':before['population']}
        if mismatches:
            result.update(status='blocked',headline='前后'+ '、'.join(mismatches)+'不一致，不能直接计算人数变化。')
            result['missing'] += ['请选择相同学生范围和规则的阶段记录；不把范围变化解释为审核改善。']
            return
        result['headline']=('前后源记录未变化，本次没有新增变化可说明。' if before['source_hash']==snap['source_hash']
                            else '已按同一学生范围和规则比较准备情况；人数变化不代表同一学生逐项改善。')
        result['tables']=[table('graduation_changes','与所选阶段记录比较',
            [('label','情况'),('before','此前人数'),('current','本次人数'),('delta','人数变化')],
            [{'label':label,'before':before['counts'].get(key,0),'current':snap['counts'][key],
              'delta':snap['counts'][key]-before['counts'].get(key,0)} for key,label in LABELS.items()],
            f"此前记录保存于 {saved['created_at']}；只比较同群体数量，不推断具体学生流转或管理措施效果。"),readiness]

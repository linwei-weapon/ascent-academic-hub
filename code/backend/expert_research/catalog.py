"""Controlled local capabilities. Availability is not school publication approval."""
from copy import deepcopy

from ..expert_team.catalog import catalog as legacy_catalog
from ..expert_team import analysis

VERSION = 'expert-research/3.1'
# Business IDs survive migration; unavailable annual rules are never executed.
SCENES = {
    'program': {'similarity':'P1','overlap':'P2','features':'P3','sequence':'P4','options':'P5'},
    'course': {'priority':'C1','diagnosis':'C2','alignment':'C3','options':'C4','outcomes':'C5'},
    'transfer': {'paths':'T1','recognition':'aux-plan-gap','conditions':'T5','capacity':'T4/T5','history':'aux-history'},
    'recommendation': {'conditions':'R1/R2','gaps':'R2/R4','ranking':'R3','rules':'R5','targets':'aux-targets'},
    'graduation': {'readiness':'G1','conditions':'G2','bottlenecks':'G3','records':'G4','changes':'G5'},
}
DEFERRED = {('course','alignment'), ('transfer','capacity'), ('transfer','conditions')}
MISSING = {
    'recommendation': ['当年度已确认的推免办法、排名与并列规则、名额及适用群体'],
    'alignment': ['已核对的课程大纲、教学任务、考核和评分要求及对应关系'],
    'capacity': ['经确认的接收群体、剩余培养时间、实际开课容量与冲突规则'],
    'conditions': ['当年度申请与接收规则、适用对象和批准版本'],
}
PURPOSES = {
    'program': '比较培养安排与共同课程，明确需要论证的专业差异',
    'course': '了解关键课程的问题表现，比较改进做法与所需条件',
    'transfer': '比较转入前后的课程要求，明确需确认的衔接事项',
    'recommendation': '依照当年确认规则研究推免条件与工作准备',
    'graduation': '区分课程缺口与记录问题，研究共性保障事项',
}


def disabled_versions():
    """Deployment kill switch, never controlled by query text or client input."""
    import os
    return set(filter(None, os.getenv('EXPERT_RESEARCH_DISABLED', '').split(',')))


def allowed(expert_id, scenario):
    return (expert_id in SCENES and scenario in SCENES[expert_id]
            and expert_id != 'recommendation' and (expert_id, scenario) not in DEFERRED
            and expert_id not in disabled_versions())


def catalog(v2, team, user, plan_id=''):
    plans = analysis.plans(v2, user)
    selected = next((p for p in plans if p['plan_id'] == plan_id), None)
    if plan_id and not selected:
        analysis.assert_plan(v2, user, plan_id)
    scope, params = analysis.scoped_students(v2, user)
    semesters = [r[0] for r in v2.execute(f'''SELECT DISTINCT g.semester_id FROM grade_attempt g
        JOIN dim_student s ON s.student_id=g.student_id WHERE {scope}
        AND g.source IN ('real','real_legacy') AND g.semester_id IS NOT NULL
        ORDER BY g.semester_id DESC''', params)]
    from ..expert_team.course_quality import calendar_order
    period_order = calendar_order(v2)
    mapped = sorted((s for s in semesters if s in period_order),key=lambda s:period_order[s],reverse=True)
    unmapped = sorted(s for s in semesters if s not in period_order)
    semesters = mapped + unmapped
    experts = deepcopy(legacy_catalog())
    for e in experts:
        e['purpose'] = PURPOSES[e['id']]
        for s in e['scenarios']:
            s['scene_id'] = SCENES[e['id']][s['id']]
            enabled = allowed(e['id'], s['id'])
            missing = MISSING.get(e['id'], MISSING.get(s['id'], [])) if not enabled else []
            if selected and (selected['source'] != 'real' or not selected['course_rows']):
                enabled = False
                missing = ['本对象缺少可核对的真实方案课程记录']
            s.update(release='limited' if enabled else 'deferred', enabled=enabled, missing=missing)
            if e['id']=='program' and s['id']=='overlap':
                s['name']='共同课程'
            if e['id']=='course' and s['id']=='outcomes':
                s['name']='学期变化'
            if e['id']=='transfer' and s['id']=='recognition':
                s['name']='两份方案的必修课程差异'
                s['description']='仅对照两份培养方案，不结合学生已修成绩，不代表群体补修清单或课程认定。'
                s['missing']=['形成补修清单还需明确学生范围、已修成绩和学校课程认定规则']
        e['enabled'] = any(s['enabled'] for s in e['scenarios'])
        e['availability'] = '可研究已接入资料，正式判断另需业务确认' if e['enabled'] else '资料待准备'
        e['version'] = VERSION
        e['approval_status'] = 'local_validation_only'
    detail = user['permission_context']['detailScope']
    return {'version':VERSION, 'mode':'structured', 'role_view':'director' if detail['type']=='all' else 'dean',
            'experts':experts, 'plans':plans, 'semesters':semesters, 'unmapped_semesters':unmapped,
            'notice':'可研究培养方案、课程表现和毕业准备等问题。系统按已接入资料和既定分析方法处理；超出支持范围的问题会说明所缺条件。研究意见供讨论参考，正式认定仍按学校制度办理。',
            'cross_college_summary_enabled':False,
            'unimplemented_scenes':['T2','T3'],
            'retention_policy':'local_validation_pending_school_approval'}

"""Minimal frozen calculation inputs; no names or original student identifiers."""
from collections import Counter, defaultdict
import hashlib
import secrets

from ..expert_team import analysis, graduation
from ..etl.v2_growth_builder import GROWTH_VERSION


def graduation_inputs(v2, user, plan_id):
    plan = analysis.assert_plan(v2, user, plan_id)
    scope, params = analysis.scoped_students(v2, user)
    base = f"s.plan_id=? AND s.student_status='在校' AND s.source IN ('real','real_legacy') AND {scope}"
    progress = analysis.rows(v2, f'''SELECT s.student_id,s.class_code,s.entry_grade,
        ps.binding_status,ps.evidence_status,ps.module_count,ps.assessable_modules,
        ps.rule_version,ps.source progress_source FROM dim_student s
        LEFT JOIN student_plan_progress_summary ps ON ps.student_id=s.student_id AND ps.plan_id=s.plan_id
        WHERE {base} ORDER BY s.student_id''', (plan_id,*params))
    modules = analysis.rows(v2, f'''SELECT m.student_id,m.module_name,m.rule_type,m.rule_label,
        m.source_reference,m.is_complete,m.is_assessable,m.evidence_status
        FROM student_plan_module_status m JOIN dim_student s
        ON s.student_id=m.student_id AND s.plan_id=m.plan_id
        WHERE {base} AND m.rule_version=? AND m.source='derived'
        ORDER BY m.student_id,m.module_name''', (plan_id,*params,GROWTH_VERSION))
    courses = analysis.rows(v2, f'''SELECT x.student_id,x.course_id,x.module,x.completion_status,x.is_overdue
        FROM student_plan_course_status x JOIN dim_student s ON s.student_id=x.student_id AND s.plan_id=x.plan_id
        WHERE {base} AND x.requirement_type='必修' AND x.rule_version=? AND x.source='derived'
        ORDER BY x.student_id,x.course_id,x.module,x.completion_status''', (plan_id,*params,GROWTH_VERSION))
    # Per-bundle random salt is deliberately not retained. The join key permits
    # distinct counts inside this bundle, not identification or cross-bundle tracking.
    salt = secrets.token_bytes(32)
    for rows in (progress, modules, courses):
        for row in rows:
            row['subject_key'] = hashlib.sha256(salt+str(row.pop('student_id')).encode()).hexdigest()
    return dict(kind='deidentified_progress_inputs',plan_grade=str(plan['grade']),
                progress_rule_version=GROWTH_VERSION,progress=progress,modules=modules,courses=courses)


def replay_graduation(inputs):
    counts=Counter({key:0 for key in graduation.LABELS});matched=set();classes=defaultdict(Counter)
    for row in inputs['progress']:
        if str(row['entry_grade'])!=inputs['plan_grade']:state='binding_issue'
        elif row['rule_version']!=inputs['progress_rule_version'] or row['progress_source']!='derived':state='unknown'
        elif row['binding_status']!='matched':state='binding_issue'
        else:
            matched.add(row['subject_key'])
            if not row['module_count'] or not row['assessable_modules']:state='rule_gap'
            else:state=row['evidence_status'] if row['evidence_status'] in {'explicit_gap','candidate','no_due_issue'} else 'unknown'
        counts[state]+=1;classes[row['class_code'] or '班级待明确'][state]+=1
    lookup={};groups=defaultdict(lambda:{key:set() for key in ('students','complete','gap','pending','unknown')})
    for row in inputs['modules']:
        key=row['subject_key'];lookup[key,row['module_name']]=row
        if key not in matched:continue
        group=groups[row['module_name'],row['rule_type'],row['rule_label'],row['source_reference'] or '既有方案进度规则']
        group['students'].add(key)
        if row['is_complete']==1:group['complete'].add(key)
        elif row['is_assessable']!=1:group['unknown'].add(key)
        elif row['evidence_status']=='explicit_gap':group['gap'].add(key)
        elif row['evidence_status']=='candidate':group['pending'].add(key)
    issues=defaultdict(lambda:defaultdict(set))
    for row in inputs['courses']:
        key=row['subject_key']
        if key not in matched:continue
        module=lookup.get((key,row['module'] or '未标注模块'))
        if not module or module['is_complete']==1 or module['is_assessable']!=1:continue
        if row['completion_status']=='failed':issues[row['course_id']][key].add('failed')
        elif row['completion_status'] in {'not_completed','unknown'} and row['is_overdue']==1:
            issues[row['course_id']][key].add('pending')
    courses=[dict(course_id=cid,failed=sum('failed' in state for state in students.values()),
        pending=sum('failed' not in state and 'pending' in state for state in students.values())) for cid,students in issues.items()]
    courses.sort(key=lambda row:(-row['failed'],-row['pending'],row['course_id']))
    return dict(population=len(inputs['progress']),counts=dict(counts),courses=courses,
        modules=[{'module':key[0],'rule':key[2],'source':key[3],**{k:len(v) for k,v in group.items()}} for key,group in sorted(groups.items())],
        classes=[{'class_name':key,'total':sum(count.values()),**{k:count[k] for k in graduation.LABELS}} for key,count in sorted(classes.items())])

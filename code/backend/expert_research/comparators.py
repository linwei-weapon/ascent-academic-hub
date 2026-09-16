"""Research-only comparable plans, ranked by real course structure, never names."""
from fractions import Fraction
from ..expert_team import analysis
from .program_review import safe_courses, selected as in_scope

VERSION = 'curriculum-comparators/1'
FOCUSES = {'non_common', 'foundation', 'main', 'foundation_main', 'practice', 'required', 'all'}
METHOD = '同年级、同方案版本、同培养类别、不同专业；按已明确课程代码交集/并集降序，同分按共同门数、方案编号排序。公共课程不参与推荐，名称不参与计分；分类待明确课程不纳入。'
BOUNDARY = '推荐用于寻找课程结构上值得对照的对象，不是完整专业相似度排名，不代表培养目标、教学内容相同或可以课程认定。'


def recommend(v2, team, user, plan_id, focus='non_common'):
    source = analysis.assert_plan(v2, user, plan_id)
    if focus not in FOCUSES:
        from ..api.envelope import ApiError
        raise ApiError('不支持的课程比较范围', code=400, status_code=400)
    # Public elective pools cannot dominate the choice, even in all-course views.
    focus = 'non_common' if focus == 'all' else focus
    permitted = analysis.plans(v2, user)
    pool = [p for p in permitted if p['source'] == 'real' and p['course_rows']
            and p.get('grade') == source.get('grade') and p.get('version') == source.get('version')
            and analysis.variant(p) == analysis.variant(source)]
    profiles = []
    for plan in pool:
        doc = analysis.document(team, v2, plan)
        courses = safe_courses(analysis.courses(v2, team, plan['plan_id']), doc)
        codes = sorted(i for i,c in courses.items() if c['layer'] not in {'common','unknown','mixed'} and in_scope(c, focus))
        profiles.append({'plan': plan, 'codes': codes,
                         'pending': sum(c['layer'] in {'unknown','mixed'} for c in courses.values()),
                         'courses': courses})
    a = next((p for p in profiles if p['plan']['plan_id'] == plan_id), None)
    rows = []
    if a:
        aa = set(a['codes'])
        for b in profiles:
            if analysis.family(b['plan']) == analysis.family(source): continue
            bb = set(b['codes']); common = aa & bb; union = aa | bb
            if not common: continue
            # Illustrations favour explicitly classified foundation/main courses;
            # this affects examples only, not the quantitative rank.
            examples=sorted(common,key=lambda i:(-sum(side['courses'][i]['layer'] in {'foundation','main'} for side in (a,b)),i))
            rows.append({**b['plan'], 'shared': len(common), 'union': len(union),
                         'subset_overlap': analysis.percent(len(common), len(union)),
                         'source_count': len(aa), 'target_count': len(bb),
                         'source_pending': a['pending'], 'target_pending': b['pending'],
                         'examples': [{'id': i, 'name': a['courses'][i]['name']} for i in examples[:4]]})
    rows.sort(key=lambda r: (-Fraction(r['shared'], r['union']), -r['shared'], r['plan_id']))
    # Preserve compact, reproducible ranking inputs in the saved result. No text similarity.
    inputs = [{'plan_id': p['plan']['plan_id'], 'family': analysis.family(p['plan']),
               'codes': p['codes'], 'pending': p['pending']} for p in profiles]
    return {'version': VERSION, 'focus': focus, 'source_plan_id': plan_id,
            'method': METHOD, 'boundary': BOUNDARY, 'candidates': rows[:3],
            'source_count': len(a['codes']) if a else 0, 'source_pending': a['pending'] if a else 0,
            'eligible_count': sum(analysis.family(p['plan']) != analysis.family(source) for p in profiles),
            'ranking_inputs': inputs,
            'empty_reason': '' if rows else '当前权限和年级范围内，未找到双方均已明确的共同专业课程；可手动选择方案逐项对照，不能据此断言专业内容不同。'}

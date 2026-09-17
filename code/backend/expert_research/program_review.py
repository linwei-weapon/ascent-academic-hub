"""V3 management reading of existing code-level facts; no source writes."""
import copy
import re
from ..expert_team import analysis, curriculum
from .intent import LABELS

VERSION = 'program-review/1.1'


def disputed(doc):
    return doc.get('status') == 'conflict' or any(
        re.search(r'不一致|归属需确认|归属.*冲突', issue) for issue in doc.get('issues', []))


def safe_courses(courses, doc):
    result = copy.deepcopy(courses)
    if disputed(doc):
        for c in result.values():
            c['common'] = bool(c['modules']) and all(
                analysis.COMMON_MODULE.search(m) or m in analysis.COMMON_LEAVES for m in c['modules'])
            curriculum.decorate(c, {})
            c['classification_basis'] = '课程源表模块；未使用归属有冲突的原文'
    return result


def selected(course, focus):
    if focus == 'all': return True
    if focus == 'required': return course.get('mandatory', False)
    if course['layer'] in {'unknown', 'mixed'}: return False
    if focus == 'non_common': return course['layer'] != 'common'
    if focus == 'foundation_main': return course['layer'] in {'foundation', 'main'}
    return course['layer'] == focus


def apply(result, req, a, b, role):
    """Mutates the new result only; raw all-course facts remain in appendix."""
    focus = req.get('focus', 'all')
    docs = result.get('documents', [])
    warnings = [{'plan': d['plan'], 'file': d['file'], 'text': '；'.join(d.get('issues', [])) or '原文归属存在冲突，暂不用于培养定位判断。'} for d in docs if disputed(d)]
    result['critical_issues'] = warnings
    bad_plans = {w['plan'] for w in warnings}
    for t in result['tables']:
        if t['id'] in {'positioning','named_courses','reading_requirements'}:
            t['rows'] = [row for row in t['rows'] if row.get('plan') not in bad_plans]
            if warnings: t['note'] += ' 归属有冲突的原文已退出此表，原文仅在资料区保留供确认。'
    result['request_receipt'] = f"本轮采用：{LABELS[focus]}；比较对象仍为本次所选的两份方案。"
    result['review_version'] = VERSION
    if not result.get('comparison'):
        result['decision_summary'] = result['headline']
        return result
    a, b = safe_courses(a, docs[0]), safe_courses(b, docs[1])
    aa, bb = ({i for i, c in side.items() if selected(c, focus)} for side in (a,b))
    common = sorted(aa & bb)
    pending = sorted({i for side in (a,b) for i,c in side.items() if c['layer'] in {'unknown','mixed'}})
    partial = bool(pending and focus not in {'all','required'})
    comparison = result['comparison']
    comparison.update(focus_shared=len(common), focus_union=len(aa | bb),
        focus_similarity=None if partial else analysis.percent(len(common),len(aa | bb)))
    for key in ('professional_shared','professional_union','structural_similarity'): comparison.pop(key,None)
    for t in result['tables']:
        if t['id']=='comparison':
            t['title']='全部课程池背景（不是本轮分层统计）'
            t['rows']=[row for row in t['rows'] if row.get('item')!='非公共基础共同课程']
        if t['id'] in {'courses','paired'}: t['title']='全部课程背景 · '+t['title']
        if t['id']=='courses':
            for row in t['rows']:
                own=b if row.get('side')=='目标方案独有' else a
                if row.get('id') in own: row['domain']=own[row['id']]['layer_label']
            t['note']+=' 有原文归属冲突时，类别仅依课程源表与已说明的通识目录判断。'
        if t['id']=='options':
            for row in t['rows']:
                row['basis']='以本轮课程清单及其适用范围组织讨论；不将全部课程池比例作为专业重复建设的依据。'
    result['methods']=[m for m in result['methods'] if not m.startswith('本次排序口径：')]
    result['focus_label'] = LABELS[focus]
    result['coverage_partial'] = partial
    if partial:
        result['missing'].append('部分课程分类待明确，本轮只列已明确的课程；不能据此给出完整专业相似度或排序。')
    def row(cid):
        left, right = a.get(cid), b.get(cid)
        return {'id': cid, 'name': (left or right)['name'],
                'a_layer': left['layer_label'] if left else '未列出',
                'b_layer': right['layer_label'] if right else '未列出',
                'a_module': ' / '.join(left['modules']) if left else '—',
                'b_module': ' / '.join(right['modules']) if right else '—',
                'a_source': left.get('source','课程表') if left else '—',
                'b_source': right.get('source','课程表') if right else '—'}
    cols=[('name','课程'),('id','课程代码'),('a_layer','来源类别'),('b_layer','比较方类别'),('a_module','来源模块'),('b_module','比较方模块')]
    selected_table = analysis.table('selected_shared','本轮范围内的共同课程',cols,[row(i) for i in common],
        '同代码且双方均满足本轮范围才列入；基础与主干合并时允许两侧分属这两类，并分别展示。类别不代表重要程度，同代码不代表教学内容等价。')
    pending_table = analysis.table('classification_pending','分类待明确的课程（不计入分层比较）',cols,[row(i) for i in pending],
        '任一方分类不明或跨层级即单列；这里是课程代码并集，不是完整专业共同课程数。')
    summary = analysis.table('scope_summary','本轮实际采用的课程范围', [('item','内容'),('value','情况')],[
        {'item':'课程范围','value':LABELS[focus]}, {'item':'来源已纳入课程','value':len(aa)},
        {'item':'比较方已纳入课程','value':len(bb)}, {'item':'双方共同课程','value':len(common)},
        {'item':'分类待明确代码（双方并集）','value':len(pending)}],
        '本表只说明实际采用范围，不把不完整分类计算成完整专业相似度。')
    result['tables'] = [summary,selected_table,pending_table]+[t for t in result['tables'] if t['id'] not in {'layers'}]
    result['tables'].append(analysis.table('layers','全部课程分类背景',
        [('layer','课程层级'),('a','来源门数'),('b','比较方门数'),('shared','同层同代码')],curriculum.layer_comparison(a,b),
        '双方分类不同的同代码课程不能通过同层数字简单相加得到；仅作背景，不用于重要性排序。'))
    if focus == 'all':
        shared_public = sum(i in b and c['layer']=='common' and b[i]['layer']=='common' for i,c in a.items())
        result['headline'] = '先明确专业培养分工，不能凭全部课程的重合比例判断重复建设。'
        result['body'] = f'两份方案共有{len(common)}门同代码课程，其中双方均列为公共课程的有{shared_public}门。公共课程池包含共同基础及选修备选，整体比例不适合作为专业特色不足的结论。课程类别不代表重要程度。'
        result['decision_summary'] = '目前可以先梳理共同基础；是否需要调整专业课程，应继续查看已明确的专业基础与主干，并结合培养目标和课程大纲。'
        result['suggestions'] = ['只看专业基础和专业主干的共同课程','查看特色支撑']
        # All-course pools must not masquerade as a professional nearest-neighbour ranking.
        result['candidates'] = []
    else:
        result['headline'] = f'已明确课程中有{len(common)}门共同课程，可先研究其培养任务与协同建设条件。' if common else '已明确范围内暂未找到同代码课程，仍需进一步比较培养内容。'
        result['body'] = (f'另有{len(pending)}个课程代码分类待明确，已单列且未计入本轮；以上不是完整专业相似度。' if partial else '本轮按双方已明确类别对照。') + '同代码是否意味着教学内容相同，还需结合课程大纲和教学安排。'
        source_name = comparison['source'].get('major_name') or '本专业'
        target_name = comparison['target'].get('major_name') or '对照专业'
        result['decision_summary'] = f'按{LABELS[focus]}，{source_name}纳入{len(aa)}门，{target_name}纳入{len(bb)}门；分别有{len(aa-bb)}门和{len(bb-aa)}门未在对方同范围出现。' + ('可在“课程与数据”中先看共同课程，再看差异是否支撑各自的培养定位。' if common else '未找到同代码课程不等于教学内容完全不同，可继续对照培养目标和课程大纲。')
        result['suggestions'] = ['查看特色支撑','解释计算口径']
        result['candidates'] = [] if partial or focus=='foundation_main' else result.get('candidates', [])
    tasks=[]
    if warnings:
        tasks.append({'title':'先确认培养方案原文归属','detail':'；'.join(w['plan']+'：'+w['text'] for w in warnings),
                      'needed':'请提供名称、适用年级与专业一致的培养目标及主要课程原文；未确认前不判断专业定位差异。','source':'documents'})
    names = '、'.join(a[i]['name']+'（'+i+'）' for i in common[:3]) if focus != 'all' else ''
    tasks.append({'title':'说明共同课程承担的培养任务' if names else '先缩小到可以论证的课程范围',
                  'detail': f'可从{names}开始说明；这是按课程代码展示的例子，不是重要性排名。' if names else '先查看已明确的专业基础与主干；没有共同课程时，可分别说明两专业的核心训练任务，不据此认定没有相同教学内容。',
                  'needed':'对应课程的大纲、学时、实践任务、考核要求，以及已经共同开设的教学安排。','source':'selected_shared'})
    if pending: tasks.append({'title':'明确课程分类后再补充完整比较','detail':f'目前有{len(pending)}个课程代码至少一方分类待明确，具体记录已经单列。',
                              'needed':'两份课程源表中的明确模块归属；不要求凭印象将未知课程归入专业核心。','source':'classification_pending'})
    result['discussion_points']=tasks
    result['management_note']=('处长可请相关学院围绕这些具体事项说明差异，再决定是否组织课程协同论证。' if role=='director' else '院长可先由本院课程团队说明培养任务与现有安排；本院可调整的内容先研究，涉及共用课程或跨院安排的条件再提请学校协调。')
    if warnings:
        result['headline']=('培养目标原文归属需先确认；课程结构可继续作限定对照。' if focus=='all' else f'目前可列出{len(common)}门共同课程；专业定位待原文确认。' if common else '在已明确的课程范围内，暂未找到同代码课程；不能据此判断培养内容没有重合。')
        if focus!='all': result['body']=f'按{LABELS[focus]}，目前列出{len(common)}门共同课程。'+result['body']
        result['decision_summary']='暂不判断专业特色是否不足。先确认冲突原文归属，再结合下列可用的课程对照组织论证。'
    result['methods'].append('已明确课程的比较方法：双方分别按课程源表分类筛选，按代码取交集；任一方未知或跨层级不进入分层共同数。存在归属冲突的原文不参与分类补充。')
    result['draft_text']='\n\n'.join(result.get(k,'') for k in ('headline','decision_summary','body','management_note'))
    return result

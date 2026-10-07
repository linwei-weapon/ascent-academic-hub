"""Build the audited 106 indicator view. Local files only; no database access.

The existing requirement IDs, decisions and runtime evidence are retained.
Run without arguments to update the catalog, or --check for a read-only check.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'code/metric-verification/catalog/teaching-overview.json'
QUERIES = ROOT / 'code/metric-verification/queries/teaching-overview.json'
VERSION = '2.0.0'
PAGES = [{'id': key, 'name': name} for key, name in [
    ('home', '总览首页'), ('history', '历年学期变化'), ('college', '学院详情'),
    ('major', '专业详情'), ('course', '课程详情'), ('students', '学生画像'),
    ('evidence', '学生证据与预警核查'), ('profile', '完整学生档案')]]

def mid(key):
    return key if key.startswith(('O-', 'MV106-')) else 'MV106-' + key

def unique(values):
    return list(dict.fromkeys(values))

# key, name, kind, unit, original sections, formula, unresolved business question
NEW = [
    ('COLLEGE-EXCESS-IMPACT', '学院估算超额影响人数', 'comparison', '人', '3.6', '取学院挂科学生率减全校同口径率与0中的较大值，乘学院有效成绩学生数；比例按0至1计算', ''),
    ('COURSE-TOP10-MEAN-SCORE', 'TOP10榜单平均分（学生分母）', 'average', '分', '3.11', '当前课程有效成绩分数之和 ÷ 有效成绩学生数', '与7.3记录均分不同，多次修读时不能互相判等。'),
    ('COURSE-TOP6-MEAN-SCORE', 'TOP6榜单平均分（口径待明确）', 'average', '分', '5.7', '106要求展示平均分，但未明确按成绩记录还是学生作分母', '分母及多次修读处理待明确，不默认继承TOP10或课程详情。'),
    ('COURSE-EXCELLENT-COUNT', '课程优秀人次', 'count', '人次', '7.3', '当前课程有效百分制成绩不低于90分的记录条数', '优秀率卡片主值写优秀人次，主次展示待明确，人数不能代替比率。'),
    ('FILTERED-STUDENT-COUNT', '筛选学生总数', 'count', '人', '8.2.2,8.3.2', '符合全部筛选条件的完整学生集合去重人数，不以分页计数', ''),
    ('STUDENT-PERIOD-GPA', '个人筛选期GPA', 'average', 'GPA', '8.2.3,8.3.3', '个人筛选期纳入课程GP×学分之和 ÷ 计入学分之和', '学年及课程/修读性质筛选如何影响GPA组成待明确。'),
    ('STUDENT-COURSE-RESULT', '个人课程成绩与GP', 'collection', '分/GP', '8.3.3', '展示当前学生、课程、筛选期选中的成绩与GP原值', '同课多次尝试选哪条待明确；不能用课程平均GPA替代个人GP。'),
    ('TERM-FAILED-COURSE-COUNT', '学期未通过课程数', 'count', '门', '9.4', '逐学期对符合该场景未通过条件的课程去重计数', '学期内多次修读按任一失败或期末最新结果未明确。'),
    ('TERM-EARNED-CREDITS', '本学期获得学分', 'sum', '学分', '9.4,10.5', '对归属该学期获得的课程学分去重求和', '学分落期、重修通过与重复获学分处理待明确，不能复用累计值。'),
    ('CURRENT-PASSED-COURSE-COUNT', '当前已通过课程数', 'count', '门', '10.7', '每课程当前有效结果为通过的去重课程数', '当前结果排序及同时间取舍待明确；历史曾通过不等于当前通过。'),
    ('CURRENT-FAILED-COURSE-COUNT', '当前未通过课程数', 'count', '门', '10.7', '每课程当前有效结果为未通过的去重课程数', '当前结果排序待明确；与9.3集合在选择规则一致后才能共用。'),
    ('CURRENT-EARNED-CREDITS', '当前已获学分', 'sum', '学分', '10.7', '当前有效结果为通过的课程所获学分去重合计', '当前结果、学分版本和认定替代待明确，不能复用历史通过学分。'),
    ('EVIDENCE-RULE-COUNT', '证据周期触发规则数', 'count', '条', '9.2', '在当前证据周期的触发规则集合中计数，保留规则名称和版本', '观察周期、规则/版本/重复命中去重未明确，不自动使用当前有效规则数。'),
    ('CURRENT-ALERT-RECORD-COUNT', '当前有效预警记录数', 'count', '条', '10.3,10.4', '学生预警记录中当前有效标记is_active=1的记录条数', ''),
    ('HIGHEST-ALERT-LEVEL', '当前最高预警等级', 'classification', '等级', '6.7,8.2.3,8.3.3,10.3', '当前有效预警按严重、警告、提醒取最高等级，无记录按场景显示正常或无', '有效规则与预警记录的关联及统计时点待明确；核查状态不等于风险状态。'),
    ('MANAGEMENT-ATTENTION', '管理关注分类', 'classification', '类别', '8.2.3,8.3.3', '先判AI重点：严重且（失败记录≥2或GPA<2.0），或失败记录≥3，或GPA<1.8且有失败；否则警告/严重且（有失败或GPA<2.3）判需核查；其余常规查看', '缺GPA行为待明确，失败数按记录而非课程。'),
    ('ALERT-CHANGE', '预警变化类型', 'classification', '类别', '9.6,10.4', '与学生上一条预警比较：无前序为首次，同规则为持续，不同规则按等级升/降/相同判升级、缓解、类型变化', '同时间预警次序待明确，工作流关闭不自动等于风险缓解。'),
    ('HISTORICAL-FAILED-COURSES', '历史未通过课程证据', 'collection', '门/次', '9.5,10.9', '保留曾失败课程、全部失败尝试及后续通过证据，展示当前未解决、重复未解决或历史已解决状态', '结果排序、认定替代与状态归属待明确，已解决课程不得从历史集合删除。'),
    ('DIFFICULTY-EVIDENCE', '学业困难证据', 'collection', '门/次', '10.7', '当前失败2门为中等、≥3门为高；同课≥2次已发布失败为高并计失败尝试总次数；必修失败1至4门为中等、≥5门为高', '必修失败后续通过/认定排除条件需挂接；重复失败不要求最新仍失败。'),
    ('R2-UNRESOLVED-COURSES', 'R2/R2W观察窗内从未通过课程', 'collection', '门', '10.5', '最近两个观察学期失败且截至观察点历史从未通过的去重课程集合；≥3门为R2，恰好2门为R2W', '观察窗口、截至时间及认定通过待明确；历史通过后最新失败不进入该集合。'),
]

FORMULAS = {mid(k): v for k, v in {
    'O-01': '统计时点、授权范围内有效在籍学生去重人数',
    'O-02': '所选学期至少有一条真实有效成绩的去重学生数',
    'O-03': '有效数值成绩×对应正学分之和 ÷ 计入学分之和',
    'O-05': '先算每学生学期学分加权GPA，再对有GPA学生求算术平均',
    'O-06': '每课程先取最新真实有效结果，再以纳入课程GP×学分之和 ÷ 计入学分之和',
    'O-08': '观察期至少一门未通过的去重学生数',
    'O-09': '真实有效且结果未通过的成绩记录条数',
    'O-10': '当期挂科去重学生数 ÷ 当期有效成绩学生数 × 100%',
    'O-11': '未通过有效成绩记录数 ÷ 全部有效成绩记录数 × 100%',
    'O-13': '当前至少命中一条有效预警规则的去重学生数',
    'O-14': '当前有效预警学生数 ÷ 当前范围在籍学生数 × 100%',
    'O-16': '已获得学分 ÷ 有效绑定培养方案要求总学分 × 100%',
    'O-17': '当前组织挂科学生率 − 比较范围同口径挂科学生率，差值用百分点',
    'O-18': '本期值 − 相邻上一学期同口径值，缺可比数据时无数据',
    'O-19': '当期有效成绩学生数 ÷ 当前范围在籍学生数 × 100%',
    'O-20': '当期该课程至少一次失败的去重学生数',
    'O-21': '依场景候选和排序选择课程，使用影响人数、属性、变化和未通过率解释原因',
    'O-22': '每生最后有效结果未通过人数 ÷ 有最终有效结果学生数 × 100%',
    'O-23': '各学生最后有效课程GP之和 ÷ 有最终课程GP学生数；缺GP回退顺序待明确',
    'TERM-COURSE-COUNT': '所选学期教学任务中课程编号去重数',
    'TEACHER-COUNT': '当前有效在职专任教师去重人数，不随成绩学期变化',
    'FIRST-PASS-RATE': '首次通过人次 ÷ 首次有效修读人次 × 100%',
    'MAKEUP-PASS-RATE': '补考通过人次 ÷ 补考有效人次 × 100%',
    'RETAKE-PASS-RATE': '重修通过人次 ÷ 重修有效人次 × 100%',
    'PUBLIC-FIRST-PASS-RATE': '公共必修首次通过人次 ÷ 该类别首次有效人次 × 100%',
    'GPA-DISTRIBUTION': '个人学期GPA归入原文五档；各档人数 ÷ 有GPA学生总数 × 100%',
    'GPA-RANK': '在有GPA的可比学院集合内排名，同时保留可比学院数',
    'PRIORITY-MAJOR-COUNT': '专业挂科率高于学院至少3个百分点或覆盖率<70%的去重专业数',
    'CREDIT-PASS-RATIO': '当期通过成绩记录学分和 ÷ 当期全部有效修读记录学分和 × 100%',
    'VALID-ATTEMPT-COUNT': '已发布、未作废、通过判定明确的真实成绩记录数',
    'COURSE-MEAN-SCORE': '有效百分制分数之和 ÷ 有百分制分数的成绩记录数',
    'COURSE-EXCELLENT-RATE': '百分制成绩≥90分人次 ÷ 有百分制分数人次 × 100%',
    'SCORE-DISTRIBUTION': '按原文五段计人次；各段人次 ÷ 有数值分数人次 × 100%',
    'GRADE-COURSE-COUNT': '专业、年级、学期有有效结果的课程去重数，包含零失败课程',
    'STUDENT-TERM-GPA': '个人学期纳入课程GP×正学分之和 ÷ 计入GPA学分之和',
    'UNRESOLVED-COURSE-COUNT': '历史曾失败且每课程最新有效结果仍失败的去重课程数',
    'REPEAT-UNRESOLVED-COUNT': '历史失败≥2次且最新有效结果仍失败的去重课程数',
    'ACTIVE-RULE-COUNT': '当前仍有效的规则命中数；重复记录及规则版本去重待明确',
    'EARNED-CREDITS': '按课程去重的历史通过课程学分合计',
    'PASSED-COURSE-COUNT': '历史至少一次有效通过的去重课程数',
    'STUDY-HOURS': '已修读课程学分合计 × 16；已修读范围待明确',
    'PLAN-MODULE-COMPLETION': '达到优先选定规则的完成模块数 / 可评价模块数',
    'PLAN-RULE-COVERAGE': '可评价模块数 ÷ 全部方案模块数 × 100%',
    'PLAN-GAP-MODULES': '可评价、未完成且有明确必修失败证据的模块去重数',
    'PLAN-CANDIDATE-MODULES': '可评价未完成、无明确失败且有已过建议学期未完成或未知必修课的模块数',
    'ALERT-HISTORY-COUNT': '全部历史预警记录条数，包含当前有效及历史非有效',
    'FOLLOWUP-COUNT': '实际登记预警跟进记录条数，不按被跟进预警去重',
    'ALERT-TRAJECTORY': '同规则×等级分别统计事件数、学生数、解除/关闭占比和已知毕业结果分布',
    'GROWTH-EVENT-COUNT': '分别统计学期表现、课程学期失败、预警、干预/流转、学籍/毕业事件条数',
    'GPA-ARITHMETIC': '全部已发布未作废且有GP记录的GP和 ÷ 记录数',
    'RETAKE-ATTEMPT-COUNT': '修读类型为重修的成绩尝试记录数',
    'STATUS-EVENT-COUNT': '已接入学生学籍异动事件条数',
    'REQUIRED-FAILURE-COUNT': '有效方案内明确失败且未被后续通过或正式替代认定解决的必修课程数',
    'REPEAT-FAILURE-ATTEMPTS': '对至少两次已发布失败的课程合计全部失败尝试数',
    'PLAN-CANDIDATE-COURSES': '有效方案中尚无完成证据、需核对选课/认定/免修/替代的课程集合及完整数',
}.items()}

def definitions(catalog):
    metrics = {m['id']: m for m in catalog['metrics']}
    for key, name, kind, unit, sections, formula, issue in NEW:
        key = mid(key)
        FORMULAS[key] = formula
        if key in metrics:
            continue
        metric = dict(id=key, officialId=None, name=name, type=kind, definition=name+'：'+formula,
            formula=formula, grain='依所关联106场景的学生、课程、组织及时间范围', unit=unit,
            numerator=None, denominator=None, scope=['当前工作身份授权范围', '场景规定的学期或观察时点'],
            nullPolicy='真实0与缺数据分开；分母为0或必需证据缺失时不补0。',
            sourceSections=sections.split(','), pagePaths=[], issues=[issue] if issue else [],
            mappingStatus='needs_confirmation', registrationNote='106未提供独立正式编号；MV106为内部核验键。',
            definitionStatus='needs_confirmation' if issue else 'documented',
            mappingNote='本指标专用SQL尚未登记，不复制其他指标的执行或验收状态。')
        metrics[key] = metric
        catalog['metrics'].append(metric)
    revisions = {
        'O-23': '最后结果缺GP时是否回退较早有GP记录待明确；不回退仅为建议解释。',
        'O-16': '已获得、认定及替代学分集合待明确；106没有100%封顶要求。',
        'GPA-DISTRIBUTION': '原文五档临界点开闭待明确，不将半开区间假称已确认。',
        'SCORE-DISTRIBUTION': '原文整数成绩段的小数及开闭边界待明确。',
        'COURSE-MEAN-SCORE': '此定义用于7.3/7.5/7.6记录均分；TOP10学生分母与TOP6待定均分独立登记。',
        'EARNED-CREDITS': '10.3历史通过学分；10.7当前通过学分独立登记，多次通过学分及认定仍待明确。',
        'PASSED-COURSE-COUNT': '10.3历史曾通过课程；10.7当前通过另作定义，两者不能互换。',
        'STUDENT-TERM-GPA': '个人学期GPA；学生画像学年和课程筛选期另作待明确定义。',
    }
    for key, note in revisions.items():
        m = metrics[mid(key)]
        m.update(definition=note, formula=FORMULAS[mid(key)], issues=[note], definitionStatus='needs_confirmation')
        m['calculationSteps'] = [FORMULAS[mid(key)], note]
        m['boundaryChecks'] = [note, m['nullPolicy']]
        if 'pageVerification' in m:
            m['pageVerification'].update(expectedResult=FORMULAS[mid(key)], specificCheck=note)
        if 'analysisCompletion' in m:
            m['analysisCompletion']['formula'] = 'needs_confirmation'
            m['analysisCompletion']['remainingWork'] = [note]
    metrics[mid('STUDENT-TERM-GPA')]['name'] = '学生学期GPA'
    metrics[mid('EARNED-CREDITS')]['name'] = '历史通过课程学分'
    metrics[mid('PASSED-COURSE-COUNT')]['name'] = '历史通过课程门数'
    return metrics


def build(catalog):
    metrics = definitions(catalog)
    # These chapters contain several separately registered requirements. Keep
    # their original subjects instead of attaching every scene to the first row.
    specific = {
        ('9.4', 'STUDENT-TERM-GPA'): 'R106-09-04-TERM',
        ('9.4', 'PLAN-MODULE-COMPLETION'): 'R106-09-04-COMPLETE',
        ('9.4', 'PLAN-RULE-COVERAGE'): 'R106-09-04-COVERAGE',
        ('9.4', 'PLAN-GAP-MODULES'): 'R106-09-04-GAP',
        ('9.4', 'PLAN-CANDIDATE-MODULES'): 'R106-09-04-CANDIDATE',
        ('10.3', 'O-06'): 'R106-10-03-GPA',
        **{('10.3', k): 'R106-10-03-CREDITS' for k in ['EARNED-CREDITS','STUDY-HOURS','PASSED-COURSE-COUNT','O-16']},
        ('10.3', 'HIGHEST-ALERT-LEVEL'): 'R106-10-03-STATUS',
        ('10.4', 'STUDENT-TERM-GPA'): 'R106-10-04-GPA',
        **{('10.4', k): 'R106-10-04-ALERT' for k in ['ALERT-HISTORY-COUNT','CURRENT-ALERT-RECORD-COUNT','FOLLOWUP-COUNT','ALERT-CHANGE']},
        ('10.5', 'GROWTH-EVENT-COUNT'): 'R106-10-05-NAV',
        ('10.5', 'ACTIVE-RULE-COUNT'): 'R106-10-05-R2',
        ('10.6', 'REQUIRED-FAILURE-COUNT'): 'R106-10-06-REQUIRED',
        ('10.6', 'GPA-ARITHMETIC'): 'R106-10-06-GPA',
        ('10.6', 'O-11'): 'R106-10-06-HISTORY',
        ('10.7', 'DIFFICULTY-EVIDENCE'): 'R106-10-07-DIFFICULTY',
    }
    cleaned = {
        'R106-09-04-TERM': ['STUDENT-TERM-GPA','TERM-FAILED-COURSE-COUNT','TERM-EARNED-CREDITS'],
        'R106-10-03-GPA': ['O-06'],
        'R106-10-03-CREDITS': ['EARNED-CREDITS','STUDY-HOURS','PASSED-COURSE-COUNT','O-16'],
        'R106-10-03-STATUS': ['HIGHEST-ALERT-LEVEL','CURRENT-ALERT-RECORD-COUNT'],
        'R106-10-04-GPA': ['STUDENT-TERM-GPA'],
        'R106-10-07-METRICS': ['CURRENT-PASSED-COURSE-COUNT','CURRENT-FAILED-COURSE-COUNT','CURRENT-EARNED-CREDITS','GPA-ARITHMETIC','RETAKE-ATTEMPT-COUNT','STATUS-EVENT-COUNT'],
        'R106-10-07-DIFFICULTY': ['DIFFICULTY-EVIDENCE','CURRENT-FAILED-COURSE-COUNT','REPEAT-FAILURE-ATTEMPTS','REQUIRED-FAILURE-COUNT'],
    }
    for req in catalog['requirements']:
        if req['id'] in cleaned:
            req['metricIds'] = [mid(k) for k in cleaned[req['id']]]
        if req['section'] in {'3.11','5.7'}:
            req['metricIds'] = [m for m in req['metricIds'] if m != mid('COURSE-MEAN-SCORE')]
        if 'metricVariants' in req:
            req['metricVariants'] = [v for v in req['metricVariants'] if v['metricId'] in req['metricIds']]
    entries = []
    page_names = {p['id']: p['name'] for p in PAGES}
    new_issues = {mid(row[0]): row[-1] for row in NEW}

    def add(page, group, key, section, name=None, components=(), *, formula=None, kind='scalar',
            pending=None, confirmed=False, evidence=(), suffix=None, meaning=None):
        key = mid(key)
        metric = metrics[key]
        candidates = [r for r in catalog['requirements'] if r['section'] == section]
        if not candidates:
            candidates = [r for r in catalog['requirements'] if r['section'].startswith(section + '.')]
        if not candidates:
            candidates = [r for r in catalog['requirements'] if section.startswith(r['section'] + '.')]
            candidates.sort(key=lambda r: len(r['section']), reverse=True)
        if not candidates:
            raise ValueError('No source requirement: ' + section)
        preferred = specific.get((section, key.removeprefix('MV106-')))
        req = next((r for r in candidates if r['id'] == preferred), candidates[0])
        dependencies = unique([mid(e) for e in evidence if mid(e) != key])
        req['metricIds'] = unique(req['metricIds'] + [key] + dependencies)
        issue = new_issues.get(key, '') if pending is None else pending
        title = name or metric['name']
        entry = dict(id=f'{page}-{suffix or key.lower()}', metricId=key, requirementId=req['id'],
            pageId=page, group=group, name=title,
            meaning=meaning or formula or FORMULAS.get(key, metric['formula']),
            formula=formula or FORMULAS.get(key, metric['formula']), components=list(components),
            sourceSections=[section], aliases=unique([metric['name'], key]),
            status='pending' if issue else 'confirmed' if confirmed else 'explicit',
            pendingIssues=[issue] if issue else [], comparisonKind=kind, evidenceMetricIds=dependencies)
        entries.append(entry)
        return entry

    core = [('O-19','有效成绩覆盖率',['有效成绩学生数','在籍学生数'],['O-02','O-01']),
            ('O-10','当前挂科学生率',['挂科学生数','有效成绩学生数'],['O-08','O-02']),
            ('O-05','学生平均GPA',['有GPA学生数','个人学期GPA'],['STUDENT-TERM-GPA']),
            ('O-14','当前有效预警学生率',['有效预警学生数','在籍学生数'],['O-13','O-01'])]
    rates = [('FIRST-PASS-RATE','首次通过率'),('MAKEUP-PASS-RATE','补考通过率'),
             ('RETAKE-PASS-RATE','重修通过率'),('PUBLIC-FIRST-PASS-RATE','公共必修首次通过率')]
    for key in ('O-01','TERM-COURSE-COUNT','TEACHER-COUNT'):
        add('home','规模背景',key,'3.4')
    for key,name,parts,deps in core:
        add('home','核心学业',key,'3.5',name,parts+['较上期变化'],evidence=deps)
    for key,name in rates:
        add('home','修读通过',key,'3.7',name,['通过人次','有效修读人次'],pending='首次/补考/重修分类及其重叠条件尚需明确。')
    for key,name,parts in [('O-17','学院挂科率较范围偏离',['学院挂科学生率','范围同口径率']),
                            ('O-18','学院挂科率较上期变化',['本期挂科学生率','上期挂科学生率']),
                            ('GPA-RANK','学院GPA排名',['各学院GPA','可比学院数','名次'])]:
        add('home','学院比较',key,'3.8',name,parts,pending='GPA同值排名规则待明确。' if key=='GPA-RANK' else '')
    add('home','GPA结构','GPA-DISTRIBUTION','3.10',components=['五档人数','五档占比','有GPA学生总数'],kind='distribution',pending='分档临界点开闭待明确。')
    add('home','重点对象','COLLEGE-EXCESS-IMPACT','3.6','优先核查学院TOP1',['学院','超额影响人数','学院挂科率','全校同口径率','学院有效成绩学生数'],kind='ranking',confirmed=True,evidence=['O-17','O-10','O-02'])
    top10parts=['课程及顺序','受影响学生数','未通过人次率','较上期变化','首次通过率','榜单平均分','入选原因']
    topdeps=['O-20','O-11','FIRST-PASS-RATE','COURSE-TOP10-MEAN-SCORE']
    topissue='影响人数与人次冲突、历史>10%条件及历史窗口待明确；保留106既定排序。'
    add('home','重点对象','O-21','3.11','重点核查课程TOP10',top10parts,kind='ranking',pending=topissue,evidence=topdeps)
    add('home','重点对象','O-21','3.6','优先核查课程TOP1',top10parts,kind='ranking',pending=topissue,evidence=topdeps,suffix='course-top1',formula='取本学期重点核查课程TOP10的首项，不另建优先级算法')
    for i,(key,name,parts,deps) in enumerate(core,1):
        add('history','核心学业变化',key,f'4.3.{i}',name+'历年变化',['真实学期',*parts,'较上期变化'],kind='series',evidence=deps,pending='历史预警时点和快照待明确。' if key=='O-14' else '')
    for i,(key,name) in enumerate(rates,5):
        add('history','修读通过变化',key,f'4.3.{i}',name+'历年变化',['真实学期','通过人次','有效修读人次','较上期变化'],kind='series',pending='修读类型分类待明确；按各期同口径保留分母。')
    for key,name,parts,deps in core:
        add('college','学院核心学业',key,'5.4',name,parts,evidence=deps)
    add('college','专业与年级','PRIORITY-MAJOR-COUNT','5.4',components=['命中专业数','专业总数','专业集合及命中原因'],evidence=['O-10','O-19'],confirmed=True)
    add('college','专业与年级','CREDIT-PASS-RATIO','5.5','专业修读结果与优先顺序',['专业','学分通过占比','有效成绩人数','平均GPA','挂科学生率','较学院偏离','在籍人数','覆盖率','预警率','核查原因'],kind='collection',evidence=['O-02','O-05','O-10','O-17','O-01','O-19','O-14'],formula=FORMULAS[mid('CREDIT-PASS-RATIO')]+'；专业按阈值命中优先、偏离降序、名称排序')
    add('college','专业与年级','CREDIT-PASS-RATIO','5.6','各年级修读结果',['年级','学分通过占比','有效成绩人数','学生平均GPA','挂科学生率'],kind='collection',suffix='grade-results',evidence=['O-02','O-05','O-10'])
    add('college','重点课程','O-21','5.7','学院重点课程TOP6',['课程及顺序','未通过人次率','失败人次','影响人数','较上期','入选原因','平均分','首次通过率','补考通过率','重修通过率'],kind='ranking',formula='有效成绩人次≥0，以影响学生数为主，再参考未通过人次率，取前6项',pending='≥0门槛已按用户确认；零样本候选、并列及均分分母待明确。',evidence=['O-11','O-09','O-20','COURSE-TOP6-MEAN-SCORE',*[x[0] for x in rates[:3]]])
    for key,name,parts,deps in core:
        add('college','学院比较',key,'5.8',name+'（学院比较）',parts,evidence=deps,suffix='comparison-'+key.lower())
    for key in ('O-17','O-18','GPA-RANK'):
        add('college','学院比较',key,'5.8',pending='并列排名规则待明确。' if key=='GPA-RANK' else '')
    add('college','待定位指标','O-03','12',components=['加权成绩和','计入学分和','参与记录'],pending='公式原文明确；具体页面落点及重复成绩选取待明确。')
    for key,name,parts,deps in core[:3]:
        add('major','专业核心学业',key,'6.3',name,parts,evidence=deps)
    for key in ('O-01','O-13'):
        add('major','专业核心学业',key,'6.3')
    add('major','年级与课程','O-10','6.4','年级风险与学业结果',['有效成绩人数/在籍数','挂科率','平均GPA','学分通过占比','覆盖率','挂科人数','预警人数','风险原因与顺序'],kind='collection',suffix='grade-risk',evidence=['O-02','O-01','O-05','CREDIT-PASS-RATIO','O-19','O-08','O-13'],formula='最近5年级按年级倒序展示；风险按挂科率降序、覆盖率升序、预警人数降序判断')
    add('major','年级与课程','O-11','6.5','年级未通过率较高课程TOP3',['课程及顺序','失败人次','有效成绩人次','未通过人次率'],kind='ranking',evidence=['O-09','VALID-ATTEMPT-COUNT'])
    add('major','年级与课程','GRADE-COURSE-COUNT','6.6','年级全部课程及数量',['全部课程数','课程集合','失败人次','有效人次','未通过人次率'],kind='collection',evidence=['O-09','O-11','VALID-ATTEMPT-COUNT'],pending='全部课程排序按人次还是人次率，原文仍有讨论。')
    add('major','预警名单','O-13','6.7','当前有效预警学生名单',['学生集合','最高风险','命中规则数','最高风险规则证据'],kind='collection',suffix='alert-list',evidence=['HIGHEST-ALERT-LEVEL','ACTIVE-RULE-COUNT'])
    for key,parts in [('VALID-ATTEMPT-COUNT',[]),('COURSE-MEAN-SCORE',['成绩和','有分数人次']),('O-23',['有最终结果学生数','有GP学生数','缺GP排除人数']),('COURSE-EXCELLENT-RATE',['优秀人次','有分数人次']),('COURSE-EXCELLENT-COUNT',['有分数人次']),('O-22',['最终失败学生数','有最终结果学生数'])]:
        add('course','课程核心指标',key,'7.3',components=parts,pending='最新结果缺GP是否回退待明确。' if key=='O-23' else None,evidence=['COURSE-EXCELLENT-COUNT'] if key=='COURSE-EXCELLENT-RATE' else [])
    add('course','分布与比较','SCORE-DISTRIBUTION','7.4',components=['五档人次','五档占比','有分数人次'],kind='distribution',pending='整数分档的小数与开闭边界待明确。')
    add('course','分布与比较','COURSE-MEAN-SCORE','7.5','课程历年均分及未通过率',['真实学期','平均分','未通过人次率'],kind='series',suffix='history',evidence=['O-11','VALID-ATTEMPT-COUNT'])
    add('course','分布与比较','O-11','7.6','行政班课程结果与顺序',['行政班','有效成绩人次','均分','未通过人次率','任课教师'],kind='collection',evidence=['COURSE-MEAN-SCORE','VALID-ATTEMPT-COUNT'],formula='按行政班汇总记录人次；未通过人次率降序，同率按有效成绩人次降序')
    for section,suffix in [('8.2','organization'),('8.3','course')]:
        add('students','筛选汇总','FILTERED-STUDENT-COUNT',section,components=['完整筛选学生集合'],suffix=suffix+'-count')
        add('students','筛选汇总','O-05',section,'筛选群体平均GPA',['完整筛选有GPA学生','个人筛选期GPA'],suffix=suffix+'-mean',evidence=['STUDENT-PERIOD-GPA'],pending='筛选条件对个人GPA组成的影响待明确。')
    for key in ('STUDENT-PERIOD-GPA','O-09','HIGHEST-ALERT-LEVEL','MANAGEMENT-ATTENTION'):
        add('students','个人学业结果',key,'8.2.3',name='个人未通过记录数' if key=='O-09' else None,evidence=['STUDENT-PERIOD-GPA','O-09','HIGHEST-ALERT-LEVEL'] if key=='MANAGEMENT-ATTENTION' else [])
    add('students','个人课程结果','STUDENT-COURSE-RESULT','8.3.3',components=['选中成绩','同条结果GP','课程','学期'],kind='collection')
    for key in ('O-06','EARNED-CREDITS','UNRESOLVED-COURSE-COUNT','ACTIVE-RULE-COUNT'):
        add('evidence','预警核查摘要',key,'6.8.2',pending='6.8简述需与具体累计/当前/观察期口径挂接。')
    add('evidence','预警核查证据','STUDENT-TERM-GPA','6.8.3','学期GPA及课程证据',['真实学期GPA','未通过课程/成绩/学期','预警历史原因/等级/时间'],kind='series',evidence=['HISTORICAL-FAILED-COURSES','ALERT-HISTORY-COUNT'])
    add('evidence','同类历史轨迹','ALERT-TRAJECTORY','6.8.3',components=['事件数','学生数','解除/关闭占比','有毕业结果人数','按期/延期人数及占比'],kind='distribution',pending='观察窗、解除关闭及毕业分母、状态映射待明确。')
    add('evidence','学生证据','EVIDENCE-RULE-COUNT','9.2',components=['证据观察周期','触发规则与课程集合'],evidence=['HISTORICAL-FAILED-COURSES'])
    for key in ('O-06','UNRESOLVED-COURSE-COUNT','REPEAT-UNRESOLVED-COUNT','ACTIVE-RULE-COUNT'):
        add('evidence','学生证据',key,'9.3',suffix='student-'+key.lower())
    add('evidence','变化与方案进度','STUDENT-TERM-GPA','9.4','逐学期学业变化',['学期GPA','GPA变化','未通过课程数','未通过变化','本学期获得学分'],kind='series',suffix='term-change',evidence=['TERM-FAILED-COURSE-COUNT','TERM-EARNED-CREDITS'],pending='学期失败课程取法、获得学分去重和落期待明确。')
    for key,parts in [('PLAN-MODULE-COMPLETION',['完成模块数','可评价模块数']),('PLAN-RULE-COVERAGE',['可评价模块数','全部方案模块数']),('PLAN-GAP-MODULES',['缺口模块集合','必修失败证据']),('PLAN-CANDIDATE-MODULES',['候选模块集合','逾期未知必修课程'])]:
        add('evidence','变化与方案进度',key,'9.4',components=parts,pending='方案适用关系、结构化规则与替代认定证据待完善。')
    add('evidence','课程与预警证据','HISTORICAL-FAILED-COURSES','9.5',components=['当前未解决','重复未解决','历史已解决','失败次数/学期','通过学期'],kind='collection')
    add('evidence','课程与预警证据','ALERT-CHANGE','9.6','预警变化与规则触发证据',['当前/上次规则及等级','变化类型','GPA及降幅','课程门数','期望/实际/缺口学分','规则版本'],kind='collection',evidence=['ACTIVE-RULE-COUNT','R2-UNRESOLVED-COURSES','O-06'])
    for key,parts in [('O-06',['计入学分','排除门数及原因']),('EARNED-CREDITS',[]),('STUDY-HOURS',[]),('PASSED-COURSE-COUNT',[]),('O-16',['已获学分','方案要求学分']),('HIGHEST-ALERT-LEVEL',['当前有效预警记录数'])]:
        add('profile','档案核心指标',key,'10.3',components=parts,pending='已获学分集合与方案要求待明确，不默认100%封顶。' if key=='O-16' else None,evidence=['CURRENT-ALERT-RECORD-COUNT'] if key=='HIGHEST-ALERT-LEVEL' else [])
    add('profile','趋势与预警','STUDENT-TERM-GPA','10.4','最近6个有GPA学期趋势',['真实学期','学期GPA'],kind='series')
    for key in ('ALERT-HISTORY-COUNT','CURRENT-ALERT-RECORD-COUNT','FOLLOWUP-COUNT','ALERT-CHANGE'):
        add('profile','趋势与预警',key,'10.4')
    add('profile','成长轨迹','GROWTH-EVENT-COUNT','10.5','成长轨迹分类与数量',['学期表现','课程×学期失败','预警','跟进与状态流转','学籍及毕业学位'],kind='collection',evidence=['ALERT-HISTORY-COUNT','FOLLOWUP-COUNT','STATUS-EVENT-COUNT','HISTORICAL-FAILED-COURSES'],pending='各事件集合、挂科门次及同课同学期合并规则需核对。')
    add('profile','成长轨迹','ACTIVE-RULE-COUNT','10.5','预警规则命中依据',['R1 GPA序列及降幅','R2/R2W从未通过课程数','R3期望/实际/缺口学分','R4核心/必修课程数','R6当期GPA与课程数'],kind='collection',evidence=['R2-UNRESOLVED-COURSES','STUDENT-TERM-GPA','REQUIRED-FAILURE-COUNT'],pending='各规则观察窗、R3进度公式、R4/R6输入口径待明确；不新增R5。')
    add('profile','建议事实','REQUIRED-FAILURE-COUNT','10.6','必修失败课程建议',['明确失败课程集合','最多5项及原因'],kind='collection',pending='超过5项的选择顺序待明确。')
    add('profile','建议事实','GPA-ARITHMETIC','10.6','近期GPA变化建议',['最近两个有GP学期','各期记录GP均值','差值'],formula='最近两个有GP学期分别取记录GP算术均值；差≥0.3或≤−0.3形成建议',kind='series')
    add('profile','建议事实','O-11','10.6','历史难课建议',['最近修读学期课程','此前历史人次','失败人次','失败率','最多5项'],formula='此前历史有效人次≥30且未通过率≥15%的最近修读课程，最多5项',kind='collection',pending='历史群体、最近修读学期及截取排序待明确。',evidence=['VALID-ATTEMPT-COUNT','O-09'])
    for key in ('CURRENT-PASSED-COURSE-COUNT','CURRENT-FAILED-COURSE-COUNT','CURRENT-EARNED-CREDITS','GPA-ARITHMETIC','RETAKE-ATTEMPT-COUNT','STATUS-EVENT-COUNT'):
        add('profile','学业成长指标',key,'10.7',suffix='growth-'+mid(key).lower())
    add('profile','困难证据','DIFFICULTY-EVIDENCE','10.7',components=['当前失败门数/程度','重复失败尝试总次数/程度','必修失败门数/程度'],kind='collection',evidence=['CURRENT-FAILED-COURSE-COUNT','REPEAT-FAILURE-ATTEMPTS','REQUIRED-FAILURE-COUNT'])
    for key in ('REQUIRED-FAILURE-COUNT','PLAN-CANDIDATE-COURSES'):
        add('profile','培养方案课程',''+key,'10.8',components=['课程集合','完整总数','推荐学期/代码顺序'],kind='collection',suffix='plan-'+key.lower(),pending='方案绑定、认定及候选课程完整条件待核对。')
    add('profile','历史课程证据','HISTORICAL-FAILED-COURSES','10.9',components=['课程','当前状态','教师/学院','失败次数/学期','通过学期'],kind='collection')
    # 10.10 is a shared evidence set, not another primary KPI.
    for e in entries:
        if e['pageId'] in {'students','evidence','profile'} and any(x in e['metricId'] for x in ('GPA','COURSE','CREDIT','FAIL','RETAKE','O-06','O-09')):
            e['evidenceNotes'] = ['106 §10.10全部成绩尝试见本指标明细SQL；保留同课程多次修读，不能只看最后结果或失败记录。']
    # Correct legacy associations only where the original link was semantically wrong.
    for req in catalog['requirements']:
        if req['section'] == '8.3.3':
            req['metricIds'] = [x for x in req['metricIds'] if x != 'O-23']
        if req['section'] == '9.4' and '学期' in req['title']:
            req['metricIds'] = unique([x for x in req['metricIds'] if x not in {'O-09',mid('EARNED-CREDITS')}]+[mid('TERM-FAILED-COURSE-COUNT'),mid('TERM-EARNED-CREDITS')])
    catalog['indicatorSystem'] = dict(version=VERSION, pages=PAGES, entries=entries,
        sharedEvidence=[dict(id='all-personal-attempts',sourceSection='10.10',name='全部个人成绩尝试',
            fields=['学期','课程代码/名称','成绩','GP','通过标记','修读类别','考试情况'],order='学期降序、成绩升序')])
    catalog['module']['version'] = VERSION
    sync_query_metadata(catalog)
    return catalog


def sync_query_metadata(catalog):
    """Keep embedded lineage current without carrying stale runtime approval."""
    manifest = json.loads(QUERIES.read_text(encoding='utf-8'))
    digest = hashlib.sha256(QUERIES.read_bytes()).hexdigest()
    metric_queries = {m['metricId']: m for m in manifest['metrics']}
    modes = Counter()
    for metric in catalog['metrics']:
        mapping = metric_queries[metric['id']]
        analyses = []
        for layer in mapping['layers']:
            modes[layer['mappingMode']] += 1
            fields = {}
            for query in layer['queries']:
                for table, names in query['requiredColumns'].items():
                    fields.setdefault(table, set()).update(names)
            analyses.append(dict(layer=layer['id'], name=layer['name'], tables=layer['tables'],
                sourceFields=[dict(table=table, fields=sorted(names), evidence='已登记SQL字段依赖；实测与业务验收分别记录。') for table,names in fields.items()],
                grain=layer['grain'], processing=layer['transform'], applicability=layer.get('applicability'),
                mappingMode=layer['mappingMode'], directSource=layer.get('directSource'),
                remainingGaps=layer.get('remainingGaps',[]), closureReason=layer.get('closureReason'),
                queryIds=[q['id'] for q in layer['queries']],
                statusEvidence=dict(registryVersion=manifest['version'], registryStatus=layer['status'],
                    calculationStatus=layer['calculationStatus'], metricResultStatus=layer.get('metricResultStatus'),
                    queryExecutionApprovals=[dict(queryId=q['id'], kind=q['kind'], dialect=q['dialect'],
                        approval=q['executionApproval'], resultRole=q.get('resultRole'),
                        approvalBasis=q.get('approvalBasis'), blockedReason=q.get('blockedReason')) for q in layer['queries']],
                    executionMeaning='旧版本执行结果不沿用；以本次SQL版本与实际执行记录为准。')))
        metric['threeLayerAnalysis'] = analyses
        metric['queryRegistry'] = dict(file='code/metric-verification/queries/teaching-overview.json',metricId=metric['id'],version=manifest['version'],sha256=digest)
        metric['mappingNote'] = '三层数据关系与SQL已登记；应用实际结果映射、候选公式和实际执行状态分别展示。'
        metric['mappingStatus'] = 'needs_confirmation'
    coverage = catalog['module']['coverage']
    coverage.update(metricCount=len(catalog['metrics']),metricAnalysisCount=len(catalog['metrics']),
        internalMetricCount=sum(m['id'].startswith('MV106-') for m in catalog['metrics']),
        indicatorSceneCount=len(catalog['indicatorSystem']['entries']),businessPageCount=len(PAGES),
        layerAnalysis=dict(total=sum(modes.values()),mappingModes=dict(modes),note='事实参考入口不等于应用结果，缺失输入仍需继续追溯。'))
    old_runtime = coverage.pop('runtimeEvidence',None)
    if old_runtime:
        coverage['priorRegistryRuntimeEvidence'] = old_runtime
    catalog['module']['analysisCompletion'].update(metricAnalysis='75项指标定义、113个页面场景及三层SQL已登记；待明确口径保留阻断',businessAcceptance='not_accepted')


def validate(catalog):
    metrics={m['id']:m for m in catalog['metrics']}; reqs={r['id']:r for r in catalog['requirements']}
    entries=catalog['indicatorSystem']['entries']; ids=[e['id'] for e in entries]
    assert len(ids)==len(set(ids)), [k for k,v in Counter(ids).items() if v>1]
    assert len(metrics)==len(catalog['metrics'])
    for e in entries:
        assert e['metricId'] in metrics and e['requirementId'] in reqs
        for key in [e['metricId'],*e.get('evidenceMetricIds',[])]:
            assert key in metrics and key in reqs[e['requirementId']]['metricIds'], (e['id'],key)
        assert e['formula'] and e['sourceSections'] and e['meaning']
    assert len([e for e in entries if e['pageId']=='history'])==8
    assert all(e['sourceSections'] != ['1.1'] for e in entries)
    return {'metrics':len(metrics),'scenarios':len(entries),'pages':dict(Counter(e['pageId'] for e in entries)),'databaseConnections':0}


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    original=json.loads(CATALOG.read_text(encoding='utf-8-sig'))
    result=original if args.check else build(deepcopy(original))
    summary=validate(result)
    if not args.check:
        CATALOG.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))

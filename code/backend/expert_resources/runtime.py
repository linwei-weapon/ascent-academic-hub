"""Registered deterministic methods; business data only comes from the configured RDS.

No free SQL, model-generated formulas, credentials or student identifiers leave here.
"""
from datetime import datetime, timezone
from time import monotonic
from collections import defaultdict
import json
import hashlib
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from backend.api.envelope import ApiError
from backend.metric_verification.config import environment_name
from backend.metric_verification.database import connection, json_value
from .auth import require_use
from . import course_observation

CATALOG = Path(__file__).resolve().parents[2] / 'expert-resources' / 'catalog.json'
HANDLERS = frozenset({'list_analysis_options', 'read_program_structure', 'compare_programs',
    'read_course_performance', 'read_transfer_history', 'read_graduation_progress', 'read_graduation_audit',
    'read_learning_results'})
_LOADED_FINGERPRINT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_BACKEND = Path(__file__).resolve().parents[1]
_SHARED_PATHS = ('expert_resources/auth.py', 'metric_verification/config.py',
                 'metric_verification/database.py', 'metric_verification/auth.py',
                 'api/permission_context.py', 'api/envelope.py')
_LOADED_SHARED_HASHES = {p: hashlib.sha256((_BACKEND / p).read_bytes()).hexdigest() for p in _SHARED_PATHS}
_LOADED_OBSERVATION_MAPPING_HASH = hashlib.sha256((_BACKEND / 'metric_verification' / 'mapping_store.py').read_bytes()).hexdigest()
_LOADED_OBSERVATION_CONTRACT_HASH = hashlib.sha256((_BACKEND / 'metric_verification' / 'mapping_contract.py').read_bytes()).hexdigest()


def fingerprint(scheme=None, task_ids=None):
    """Keep the original file hash for releases without a fingerprint scheme."""
    if scheme in (None, 'runtime-v1'):
        return _LOADED_FINGERPRINT
    if scheme == 'task-v2':
        return task_fingerprint(task_ids)['runtimeFingerprint']
    raise ApiError('不支持的执行指纹方案', status_code=409)


def task_fingerprint(task_ids=None):
    from . import tasks
    selected = sorted(set(task_ids or [t['taskId'] for t in tasks.task_definitions() if t['available']]))
    for task_id in selected:
        tasks.definition(task_id)
    hashes = {**_LOADED_SHARED_HASHES, 'expert_resources/runtime.py': _LOADED_FINGERPRINT,
              'expert_resources/tasks.py': tasks.LOADED_FINGERPRINT}
    if any(tasks.definition(task_id)['handler'] == 'read_course_performance' for task_id in selected):
        hashes['expert_resources/course_observation.py'] = course_observation.LOADED_FINGERPRINT
        # Actual metric registration is part of the observation release gate.
        hashes['metric_verification/mapping_store.py'] = _LOADED_OBSERVATION_MAPPING_HASH
        hashes['metric_verification/mapping_contract.py'] = _LOADED_OBSERVATION_CONTRACT_HASH
    if any(not tasks.definition(task_id)['available'] or tasks.definition(task_id)['handler'] == 'read_learning_results'
           for task_id in selected):
        hashes.update({'expert_resources/' + name: digest for name, digest in tasks._POLICY_HASHES.items()})
    manifest = [{'path': 'code/backend/' + p, 'sha256': digest} for p, digest in sorted(hashes.items())]
    if any(tasks.definition(task_id)['handler'] == 'read_course_performance' for task_id in selected):
        manifest.append({'path': course_observation.REVIEWED_PACKAGE_REF,
                         'sha256': course_observation.LOADED_REFERENCE_SHA256})
        manifest.sort(key=lambda row: row['path'])
    payload = {'fingerprintScheme': 'task-v2', 'taskIds': selected, 'runtimeDependencies': manifest}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**payload, 'runtimeFingerprint': digest}


def now():
    return datetime.now(timezone.utc).isoformat()


def scope_sql(actor, column, selected=None):
    require_use(actor)
    scope = actor['permission_context'].get('detailScope') or {}
    if scope.get('type') == 'all':
        return (f'{column}=%s', [str(selected)]) if selected else ('1=1', [])
    ids = [str(x) for x in scope.get('collegeIds', []) if x is not None]
    if scope.get('type') != 'college' or not ids:
        raise ApiError('此分析需要全校或有效学院范围', code=403, status_code=403)
    if selected and str(selected) not in ids:
        raise ApiError('所选学院不在当前身份范围内', code=403, status_code=403)
    ids = [str(selected)] if selected else ids
    return f"{column} IN ({','.join(['%s'] * len(ids))})", ids


def rows(db, sql, params=()):
    with db.cursor() as cur:
        cur.execute(sql, params)
        return [{k: json_value(v) for k, v in r.items()} for r in cur.fetchall()]


def analysis_options(actor):
    where, params = scope_sql(actor, 'p.organization_id')
    with connection('analytics', consistent=True) as db:
        plans = rows(db, f'''SELECT p.plan_id id,COALESCE(p.plan_name,p.name_zh,p.plan_id) name,
            p.grade,p.organization_id college_id FROM act_curriculum_plan p WHERE {where}
            ORDER BY p.grade DESC,p.plan_id''', params)
        semesters = rows(db, '''SELECT s.semester_id id,COALESCE(s.name_zh,s.semester_id) name
            FROM act_semester s WHERE EXISTS(SELECT 1 FROM agg_course_pass_stat a WHERE a.semester_id=s.semester_id)
            ORDER BY s.start_date DESC,s.semester_id DESC''')
        cw, cp = scope_sql(actor, 'organization_id')
        colleges = rows(db, f'''SELECT organization_id id,name FROM act_organization
            WHERE {cw} AND is_college=1 ORDER BY name''', cp)
    return {'plans': plans, 'semesters': semesters, 'colleges': colleges,
            'environment': environment_name(), 'queriedAt': now(),
            'note': '只显示当前身份范围；培养方案按适用年级排序，学期只列已存在课程统计的项。'}


def authorized_plan(db, actor, plan_id):
    if not plan_id:
        raise ApiError('请选择培养方案', status_code=422)
    where, params = scope_sql(actor, 'p.organization_id')
    found = rows(db, f'''SELECT p.plan_id,p.plan_name,p.grade,p.organization_id,p.version,p.source,p.updated_at
        FROM act_curriculum_plan p WHERE p.plan_id=%s AND {where}''', [str(plan_id), *params])
    if len(found) != 1:
        raise ApiError('培养方案不存在、标识不唯一或超出当前身份范围', code=403, status_code=403)
    return found[0]


def plan_courses(db, plan_id):
    result = rows(db, '''SELECT p.course_id,MAX(c.name) course_name,p.module,p.requirement_type,
        p.compulsory,p.suggested_term,MAX(c.credits) credits,p.credits recorded_plan_credits,p.total_hours,
        MAX(p.updated_at) updated_at,
        COUNT(DISTINCT p.id) source_rows FROM act_curriculum_plan_course p
        LEFT JOIN act_course c ON c.course_id=p.course_id WHERE p.plan_id=%s
        GROUP BY p.course_id,p.module,p.requirement_type,p.compulsory,p.suggested_term,p.credits,p.total_hours
        ORDER BY p.suggested_term,p.course_id''', [str(plan_id)])
    for row in result:
        row['credit_check'] = ('目录学分缺失' if row['credits'] is None else '方案字段缺失' if row['recorded_plan_credits'] is None
            else '字段值不一致' if row['credits'] != row['recorded_plan_credits'] else '字段值相同')
    return result


def table(title, records, labels, note=''):
    return {'title': title, 'rows': records, 'columns': [{'key': k, 'label': v} for k, v in labels.items()], 'note': note}


def source(table_name, records, rule):
    dates = [str(r.get('updated_at') or r.get('calculated_at')) for r in records if r.get('updated_at') or r.get('calculated_at')]
    return {'name': table_name, 'database': 'edu_analytics_v3', 'queriedAt': now(),
            'dataUpdatedAt': max(dates) if dates else None, 'rule': rule,
            'note': '当前库读取结果；查询时间不是源数据更新时间，不承诺历史批次可重建。'}


def _fact(fact_id, label, value, unit='', *, numerator=None, denominator=None, formula=None, refs=(), reason=None):
    return {'factId': fact_id, 'name': label, 'value': value, 'unit': unit,
            'numerator': numerator, 'denominator': denominator, 'formulaRef': formula,
            'sourceRefs': list(refs), 'precision': 2 if unit == '%' else 0, 'reason': reason}


def _percentage(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float((Decimal(numerator) * 100 / Decimal(denominator)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def _evidence(evidence_id, src, records, grain, scope, *, recomputable=True):
    return {'evidenceId': evidence_id, 'sourceRef': src['name'], 'grain': grain,
            'sourceRowCount': len(records), 'retainedRowCount': len(records),
            'fields': sorted({key for row in records for key in row}),
            'queriedAt': src['queriedAt'], 'dataUpdatedAt': src['dataUpdatedAt'],
            'retentionComplete': True, 'records': deepcopy(records),
            'sourceCoverage': 'unknown',
            'recomputableScope': scope if recomputable else None}


def _preview(title, records, labels, limit, note=''):
    return {**table(title, records[:limit], labels, note), 'totalRows': len(records),
            'returnedRows': min(limit, len(records)), 'truncated': len(records) > limit}


def _issue(issue_id, message, affected=()):
    return {'issueId': issue_id, 'originalTurnId': None, 'affectedFacts': list(affected),
            'affectedConditions': [], 'requiredEvidence': message, 'preparationState': 'missing',
            'resolutionState': 'open', 'responsibilityChannel': '数据或业务口径确认', 'sourceRefs': []}


def _legacy_projection(result):
    """The old published schemas forbid new top-level and table fields."""
    keys = ('status', 'summary', 'scope', 'data', 'tables', 'sources', 'limitations', 'missingEvidence')
    projected = {key: deepcopy(result[key]) for key in keys if key in result}
    for item in projected.get('tables', []):
        for key in ('totalRows', 'returnedRows', 'truncated', 'evidenceId'):
            item.pop(key, None)
    return projected


def _comparison(plan, courses, target, target_courses, args):
    """One set implementation serves both the tool and the task processor."""
    limit = args.get('previewLimit', args.get('limit', 50))
    a = {str(c['course_id']) for c in courses if c.get('course_id') and str(c['course_id']).strip()}
    b = {str(c['course_id']) for c in target_courses if c.get('course_id') and str(c['course_id']).strip()}
    common, union = a & b, a | b
    unknown_a = [c for c in courses if not c.get('course_id') or not str(c['course_id']).strip()]
    unknown_b = [c for c in target_courses if not c.get('course_id') or not str(c['course_id']).strip()]
    unknown_modules = sum(not c.get('module') or not str(c['module']).strip() for c in [*courses, *target_courses])
    excluded = [{'side': side, 'recordIndex': i, 'reason': '课程编号缺失，未进入已识别课程分母'}
                for side, records in [('source', courses), ('target', target_courses)]
                for i, c in enumerate(records) if not c.get('course_id') or not str(c['course_id']).strip()]
    src_a = source('act_curriculum_plan_course（来源方案）', courses, '全部模块，按已识别course_id去重；保留全部安排和source_rows重复计数')
    src_b = source('act_curriculum_plan_course（目标方案）', target_courses, '全部模块，按已识别course_id去重；保留全部安排和source_rows重复计数')
    refs = ['program-source-courses', 'program-target-courses']
    data = {'来源方案课程种数': len(a), '目标方案课程种数': len(b), '共同课程种数': len(common),
            '合并去重课程种数': len(union), '来源独有课程种数': len(a-b), '目标独有课程种数': len(b-a),
            '结构重合率(%)': _percentage(len(common), len(union)),
            '目标课程覆盖率(%)': _percentage(len(common), len(b)),
            '来源未知编号安排条数': len(unknown_a), '目标未知编号安排条数': len(unknown_b),
            '模块分类缺失安排条数': unknown_modules}
    facts = [_fact(key, label, value, '种', refs=refs) for key, label, value in [
        ('source-course-count', '来源已识别课程种数', len(a)), ('target-course-count', '目标已识别课程种数', len(b)),
        ('common-course-count', '共同课程种数', len(common)), ('union-course-count', '合并去重课程种数', len(union)),
        ('source-only-course-count', '来源独有课程种数', len(a-b)), ('target-only-course-count', '目标独有课程种数', len(b-a))]]
    facts.extend([
        _fact('structure-overlap', '已识别课程结构重合率', data['结构重合率(%)'], '%', numerator=len(common),
              denominator=len(union), formula='course-id-intersection / course-id-union * 100', refs=refs,
              reason='并集为空，比例未知' if not union else None),
        _fact('target-coverage', '已识别目标课程覆盖率', data['目标课程覆盖率(%)'], '%', numerator=len(common),
              denominator=len(b), formula='course-id-intersection / target-known-course-ids * 100', refs=refs,
              reason='目标已识别集合为空，比例未知' if not b else None)])
    issues = []
    missing = []
    if unknown_a or unknown_b:
        missing.append('存在未知课程编号；比例仅覆盖已识别课程子集，不能称为全方案完整比例。')
        issues.append(_issue('unknown-course-identifiers', missing[-1], ['structure-overlap', 'target-coverage']))
    if unknown_modules:
        issues.append(_issue('unknown-course-classification', '模块分类缺失；本次按全部课程编号比较，不能据此排除公共课或确认专业课比例。'))
    status = 'limited'
    if not a or not b:
        status = 'blocked'
        missing.append('至少一方没有可识别课程集合，不支持方案比例比较。')
        for fact in facts:
            if fact['unit'] == '%':
                fact['value'] = None
                fact['reason'] = missing[-1]
        data['结构重合率(%)'] = data['目标课程覆盖率(%)'] = None
    labels = {'course_id': '课程编号', 'course_name': '课程', '对照状态': '对照状态', 'module': '模块',
              'credits': '课程目录学分', 'recorded_plan_credits': '方案字段原值（待核对）',
              'credit_check': '字段核对', 'suggested_term': '建议学期'}
    def difference(records, exclusive):
        return [dict(c, 对照状态='未知编号' if not c.get('course_id') or not str(c['course_id']).strip()
                     else '共同课程' if str(c['course_id']) in common else exclusive) for c in records]
    tables = [_preview('来源方案课程对照', difference(courses, '来源独有'), labels, limit),
              _preview('目标方案课程对照', difference(target_courses, '目标独有'), labels, limit)]
    for item, ref in zip(tables, refs):
        item['evidenceId'] = ref
    limitations = ['按全部模块的已识别课程编号去重；结构重合率=交集÷并集，目标覆盖率=交集÷目标已识别课程数。',
                  '相同编号不证明教学内容等价；不同编号可能存在等价关系，未确认时不自动匹配。',
                  '课程目录学分只用于结构展示；保留方案字段原值与差异，不用于正式学分认定或个人补修。',
                  '来源课程集合留存完整不代表方案业务来源覆盖已确认；无分类依据不能排除公共课。']
    if plan.get('grade') != target.get('grade'):
        limitations.append('方案适用年级不同，仅作版本结构对照，不作为同年级排名。')
    summary = f'已识别课程中，双方各{len(a)}、{len(b)}种，共同{len(common)}种，来源与目标各独有{len(a-b)}、{len(b-a)}种。'
    return {'status': status, 'summary': summary, 'scope': {**args, 'plan': plan, 'targetPlan': target,
            'environment': environment_name(), 'comparisonMode': 'all_course_ids'}, 'data': data, 'tables': tables,
            'sources': [src_a, src_b], 'limitations': limitations, 'missingEvidence': missing, 'facts': facts,
            'coverage': {'definedPopulation': None, 'observedPopulation': len(courses)+len(target_courses),
                'evaluablePopulation': len(union), 'unknownCount': len(unknown_a)+len(unknown_b), 'exclusions': excluded,
                'grain': '双方方案课程安排；分母为各方及并集已识别课程编号',
                'source': {'observedRows': len(courses), 'identifiedCourseCount': len(a), 'unknownIdentifierRows': len(unknown_a)},
                'target': {'observedRows': len(target_courses), 'identifiedCourseCount': len(b), 'unknownIdentifierRows': len(unknown_b)},
                'inputCompleteness': [
                    {'dimension': 'course_id', 'state': 'partial' if unknown_a or unknown_b else 'complete',
                     'basis': '本次返回安排的编号字段检查；不等同来源业务覆盖确认'},
                    {'dimension': 'classification', 'state': 'partial' if unknown_modules else 'unknown',
                     'basis': 'module仅为原字段，不自动认定为公共课/专业课分类'},
                    {'dimension': 'sourcePopulation', 'state': 'unknown', 'basis': '尚无方案源集合接入对账依据'}]},
            'evidence': [_evidence(refs[0], src_a, courses, '方案×课程编号×模块×要求×学期×学分安排', {'plan_id': plan['plan_id']}),
                         _evidence(refs[1], src_b, target_courses, '方案×课程编号×模块×要求×学期×学分安排', {'plan_id': target['plan_id']})],
            'conditions': [], 'issues': issues}


def _course_performance(records, args, semantic_basis=None):
    limit = args.get('previewLimit', args.get('limit', 50))
    raw_records = deepcopy(records)
    records = deepcopy(records)
    src = source('agg_course_pass_stat → act_course', records, '首修通过率=first_pass÷first_attempts；首修人次与失败次数保持源字段含义')
    counts = defaultdict(int)
    for row in records:
        counts[row.get('course_id')] += 1
    facts, issues = [], []
    bad_ratios = 0
    for index, row in enumerate(records):
        attempts, passed = row.get('first_attempts'), row.get('first_pass')
        duplicate = counts[row.get('course_id')] > 1
        reason = None
        conflict = False
        if not row.get('course_id'):
            reason, conflict = '课程编号缺失，无法确认聚合粒度', True
        elif duplicate:
            reason, conflict = '同课程同学期有多个聚合行，缺少可加粒度或重复处理依据', True
        elif attempts is None or passed is None:
            reason = '首修人次或首修通过人次缺失'
        elif any(isinstance(x, bool) or not isinstance(x, (int, float, Decimal)) or x < 0 or int(x) != x for x in (attempts, passed)):
            reason, conflict = '首修人次字段不是非负整数', True
        elif passed > attempts:
            reason, conflict = '首修通过人次大于首修人次，聚合字段冲突', True
        elif attempts == 0:
            reason = '首修人次为0，比例没有合法分母'
        row['first_pass_pct'] = None if reason else _percentage(passed, attempts)
        row['rate_reason'] = reason
        row['aggregate_state'] = 'conflict' if conflict else 'unknown' if reason else 'known'
        prefix = f'course-row-{index+1}'
        facts.extend([_fact(prefix+'-attempts', '首修人次', attempts, '人次', refs=['course-aggregate']),
                      _fact(prefix+'-passed', '首修通过人次', passed, '人次', refs=['course-aggregate']),
                      _fact(prefix+'-failures', '未通过次数（聚合库原口径）', row.get('failures'), '次', refs=['course-aggregate']),
                      _fact(prefix+'-first-pass-rate', '首修通过率', row['first_pass_pct'], '%', numerator=passed,
                            denominator=attempts, formula='first_pass / first_attempts * 100', refs=['course-aggregate'], reason=reason)])
        for fact in facts[-4:]:
            fact['objectRef'] = {'course_id': row.get('course_id'), 'semester_id': args['semester_id'], 'aggregateRow': index+1}
        if reason:
            bad_ratios += 1
            issues.append(_issue(prefix+'-denominator', reason, [prefix+'-first-pass-rate']))
    labels = {'course_name': '课程', 'course_id': '课程编号', 'first_attempts': '首次修读人次',
              'first_pass': '首次通过人次', 'first_pass_pct': '首次通过率(%)', 'rate_reason': '比例未知或冲突原因',
              'failures': '未通过次数（聚合库原口径）', 'students': '本聚合行学生数', 'rule_version': '聚合规则版本'}
    preview = _preview('课程表现（按未通过次数浏览）', records, labels, limit,
                       '学院是开课院系；失败次数不是去重人数。学生可能跨课程或聚合行重复，不汇总为唯一人数。')
    preview['evidenceId'] = 'course-aggregate'
    conflicts = sum(r['aggregate_state'] == 'conflict' for r in records)
    missing = ['当前筛选范围没有可用聚合记录；空结果不是指标为0。'] if not records else []
    if conflicts:
        missing.append('冲突聚合行的首修比例被阻止，需核对原字段或聚合粒度。')
    result = {'status': 'blocked' if not records or conflicts == len(records) else 'limited',
        'summary': f'本范围读取{len(records)}条课程聚合记录，首修比例未知或冲突{bad_ratios}条；按首修人次展示，不汇总为唯一学生人数。',
        'scope': {**args, 'environment': environment_name(), 'collegeMeaning': '课程开课院系'},
        'data': {'课程统计记录数': len(records), '本次展示条数': min(len(records), limit), '比例未知或冲突条数': bad_ratios,
                 '聚合冲突条数': conflicts, '跨行唯一学生人数': None},
        'tables': [preview], 'sources': [src], 'facts': facts,
        'coverage': {'definedPopulation': None, 'observedPopulation': len(records),
            'evaluablePopulation': len(records)-bad_ratios, 'unknownCount': bad_ratios, 'exclusions': [],
            'grain': '课程×学期聚合行；检测重复后不自动合并', 'uniqueStudentCount': None,
            'inputCompleteness': [
                {'dimension': 'aggregateGrain', 'state': 'conflict' if conflicts else 'complete',
                 'basis': '读取全部聚合行并检查课程×学期唯一性；未确认额外可加维度'},
                {'dimension': 'firstAttemptDenominator', 'state': 'conflict' if conflicts else 'partial' if bad_ratios else 'complete',
                 'basis': 'first_attempts为首修人次，零分母与缺字段分别标记'},
                {'dimension': 'sourcePopulation', 'state': 'unknown', 'basis': '聚合行留存完整不等同全部开课或学生成果覆盖'}]},
        'evidence': [_evidence('course-aggregate', src, records, '课程×学期聚合行（重复与冲突保留）',
                               {k: v for k, v in args.items() if k not in {'previewLimit', 'limit'}})],
        'conditions': [], 'issues': issues, 'missingEvidence': missing,
        'limitations': ['first_attempts与first_pass为首修人次和首修通过人次，分母0或缺失返回未知。',
                         'failures保持失败次数原口径，不能改称首修失败人数或未通过学生人数。',
                         'students只表示本聚合行样本；跨行重叠未确认，不相加为去重学生人数。',
                         '未通过次数排序仅用于浏览和进一步了解，不形成质量排名、教师责任或因果结论。']}
    computed, basis, gate = course_observation.observations(raw_records, args, semantic_basis)
    retained_scope = {k: v for k, v in result['scope'].items() if k not in {'previewLimit', 'limit'}}
    basis['frozenInput']['evidenceId'] = 'course-aggregate-input'
    result['evidence'].append(_evidence('course-aggregate-input', src, raw_records,
        '本次查询返回的原始课程×学期聚合字段；独立复算使用此完整集合', retained_scope))
    result.update({'publishMode': gate['publishMode'], 'publicationGate': gate, 'validationBasis': basis,
        'observationState': computed['populationState'],
        'observationExclusions': computed['excludedRows'], 'observationExclusionCounts': computed['exclusionCounts']})
    if gate['publishMode'] == 'blocked':
        result['status'] = 'blocked'
    if gate['publishMode'] != 'observation':
        result['missingEvidence'].extend(gate['reasons'])
        if (semantic_basis or {}).get('reason'):
            result['missingEvidence'].append(semantic_basis['reason'])
    else:
        observed = computed['observations']
        result['observationBaseline'] = computed['baseline']
        result['observations'] = observed
        result['observationCount'] = len(observed)
        baseline = computed['baseline']
        result['data'].update({'有效课程数': baseline['courseCount'], '有效集合首修人次': baseline['firstAttempts'],
            '有效集合首修通过人次': baseline['firstPass'], '同范围首修通过参照(%)': baseline['ratePct'],
            '首修观察课程数': len(observed)})
        result['summary'] = (f"本范围{baseline['courseCount']}门有效课程，首修人次{baseline['firstAttempts']}、"
            f"通过人次{baseline['firstPass']}，同范围参照{baseline['ratePct']}%；"
            f"有{len(observed)}门课程同时存在首修未通过且通过率低于本范围参照。")
        observation_table = _preview('首修观察课程', observed,
            {'course_name': '课程', 'course_id': '课程编号', 'first_attempts': '首修人次',
             'first_pass': '首修通过人次', 'first_unpassed': '首修未通过人次',
             'first_pass_pct': '首修通过率(%)'}, 5,
            '按首修未通过人次降序、未四舍五入通过率升序、课程编号升序；前5仅为预览，可查看全部依据。')
        observation_table['evidenceId'] = 'course-observations'
        result['tables'].insert(0, observation_table)
        result['evidence'].append(_evidence('course-observations', src, observed,
            '符合已确认条件的课程×学期；前5预览保留全部选入项', retained_scope))
        result['facts'].extend([
            _fact('scope-first-pass-baseline', '同范围首修通过参照', baseline['ratePct'], '%',
                numerator=baseline['firstPass'], denominator=baseline['firstAttempts'],
                formula='AI-C-05: sum(first_pass) / sum(first_attempts) * 100', refs=['course-aggregate']),
            _fact('scope-observation-course-count', '首修观察课程数', len(observed), '门',
                formula='AI-C-06: U>0 AND P*scopeN<scopeP*N', refs=['course-aggregate'])])
        for row in observed:
            fact = _fact('course-' + row['course_id'] + '-first-unpassed', '首修未通过人次',
                row['first_unpassed'], '人次', numerator=row['first_attempts']-row['first_pass'],
                formula='AI-C-04: first_attempts - first_pass', refs=['course-aggregate'])
            fact['objectRef'] = {'course_id': row['course_id'], 'semester_id': args['semester_id']}
            result['facts'].append(fact)
        result['limitations'].extend(gate.get('limitations', []))
        if baseline['courseCount'] == 1:
            result['limitations'].append('本范围只有1门有效课程，参照等于本课程比例，没有相对观察项。')
        if not observed:
            result['limitations'].append('本次没有课程同时满足选入条件；不代表不存在学业困难或所有课程质量已达标。')
    proof = basis['threeLayerCheck']
    if proof.get('factCoursesWithoutAggregate'):
        result['limitations'].append('存在当前事实首修课程尚无应用层聚合；参照仅使用已返回有效聚合集合，未将缺聚合课程算为0。')
    if proof.get('factCourseRows'):
        result['data']['首修结果尚未明确的人次（未计入通过率）'] = proof['unknownFirstPassAttempts']
        result['data']['首修分类尚未明确的人次'] = proof['unknownRetakeClassificationAttempts']
        if proof['unknownFirstPassAttempts']:
            result['limitations'].append(f"本范围有{proof['unknownFirstPassAttempts']}人次首修结果尚未明确，未计入有效首修分母，也未计为首修未通过。")
        check_src = {'name': 'grade → act_grade_attempt → agg_course_pass_stat（当次范围核对）',
                     'queriedAt': proof.get('queriedAt'), 'dataUpdatedAt': None}
        result['evidence'].append(_evidence('course-current-three-layer', check_src,
            proof['factCourseRows'], '课程×学期当前源键、事实有效集合核对；不是历史聚合批次回放', retained_scope))
    result['coverage']['observationExclusions'] = computed['excludedRows']
    result['coverage']['aggregateCoverage'] = proof.get('aggregateCoverage', 'unknown')
    return result


def run_tool(name, args, actor, *, schema_version='1.0'):
    authorize = actor.get('_authorize')
    if authorize is not None:
        actor = authorize()
    require_use(actor)
    if schema_version not in {'1.0', '2.0'}:
        raise ApiError('不支持的工具结果契约', status_code=422)
    if name not in HANDLERS:
        raise ApiError('未登记的只读工具', status_code=422)
    if not isinstance(args, dict):
        raise ApiError('工具输入必须为对象', status_code=422)
    if name == 'list_analysis_options':
        if args:
            raise ApiError('分析对象工具不接受查询参数', status_code=422)
        result = analysis_options(actor)
        return {'status': 'completed', 'summary': '已读取当前身份可用的分析对象', 'scope': {},
                'data': result, 'sources': [], 'limitations': [], 'missingEvidence': []}
    if name == 'read_learning_results':
        from .policy_adapter import read_learning_results
        return read_learning_results(args, actor)
    allow = {'plan_id', 'target_plan_id', 'semester_id', 'college_id', 'limit'}
    if schema_version == '2.0':
        allow |= {'course_id', 'previewLimit', 'comparisonMode'}
    if set(args) - allow:
        raise ApiError('查询包含未登记参数', status_code=422)
    for key in allow - {'limit', 'previewLimit'}:
        if args.get(key) is not None and (not isinstance(args[key], str) or len(args[key]) > 128):
            raise ApiError('分析对象参数格式不正确', status_code=422)
    if args.get('comparisonMode', 'all_course_ids') != 'all_course_ids':
        raise ApiError('尚无已确认分类依据，仅支持全部课程编号比较；请明确可比分类后再分析', status_code=422)
    if 'limit' in args and 'previewLimit' in args:
        raise ApiError('预览条数不能同时传入limit与previewLimit', status_code=422)
    limit = args.get('previewLimit', args.get('limit', 50))
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ApiError('显示条数必须为1至200的整数', status_code=422)
    result = {'status': 'limited', 'summary': '', 'scope': {**args, 'environment': environment_name()},
              'data': {}, 'tables': [], 'sources': [], 'limitations': [], 'missingEvidence': []}
    with connection('analytics', consistent=True) as db:
        # All tools check the active scope, even when no college filter was supplied.
        where, params = scope_sql(actor, 'organization_id', args.get('college_id'))
        if name in {'read_program_structure', 'compare_programs'}:
            plan = authorized_plan(db, actor, args.get('plan_id'))
            courses = plan_courses(db, plan['plan_id'])
            result['scope']['plan'] = plan
            result['sources'] = [source('act_curriculum_plan → act_curriculum_plan_course → act_course', courses,
                '按课程标识比较；同方案完全相同的课程安排去重，跨模块或学期保留。学分展示课程目录act_course.credits；方案字段原值另列，差异不自动认定为已修正。')]
            if not courses and name == 'read_program_structure':
                result['status'] = 'blocked'
                result['missingEvidence'] = ['所选培养方案没有可读取的课程安排']
            elif name == 'read_program_structure':
                modules = defaultdict(lambda: {'安排条数': 0, '课程目录学分合计': 0.0, '目录学分缺失条数': 0, '方案字段差异条数': 0})
                for c in courses:
                    m = modules[c['module'] or '未标注模块']
                    m['安排条数'] += 1
                    m['课程目录学分合计'] += c['credits'] or 0
                    m['目录学分缺失条数'] += c['credits'] is None
                    m['方案字段差异条数'] += c['credit_check'] != '字段值相同'
                summary = [{'模块': k, **v} for k, v in modules.items()]
                for entry in summary:
                    if entry['目录学分缺失条数'] == entry['安排条数']:
                        entry['课程目录学分合计'] = None
                result['data'] = {'课程种数': len({c['course_id'] for c in courses if c['course_id']}), '课程安排条数': len(courses),
                    '学分字段待核对条数': sum(c['credit_check'] != '字段值相同' for c in courses)}
                result['tables'] = [table('模块结构', summary, {k: k for k in summary[0]}), table('课程安排', courses[:limit],
                    {'course_name': '课程', 'course_id': '课程编号', 'module': '模块', 'requirement_type': '修读要求',
                     'suggested_term': '建议学期', 'credits': '课程目录学分', 'recorded_plan_credits': '方案字段原值（待核对）',
                     'credit_check': '字段核对', 'source_rows': '来源条数'}, f'共{len(courses)}条，本次展示前{limit}条')]
                result['summary'] = f"{plan['plan_name']}：读取{len(courses)}条课程安排，可用于结构核对。"
                result['limitations'] = ['当前方案课程学分字段与课程目录存在差异，使用课程目录学分供结构对照；不能据此计算正式方案学分要求。',
                    '模块合计按已知课程目录学分汇总，选修池不能当成毕业最低学分要求；空学分单独计数。',
                    '课程名称、模块和学期来自现有库；无法据此认定培养目标达成、课程先修冲突或建设投入重复。']
            else:
                target = authorized_plan(db, actor, args.get('target_plan_id'))
                if plan['plan_id'] == target['plan_id']:
                    raise ApiError('请选择两个不同的培养方案', status_code=422)
                target_courses = plan_courses(db, target['plan_id'])
                result = _comparison(plan, courses, target, target_courses, args)
        elif name == 'read_course_performance':
            if not args.get('semester_id'):
                raise ApiError('请选择学期', status_code=422)
            semesters = rows(db, 'SELECT semester_id FROM act_semester WHERE semester_id=%s', [args['semester_id']])
            if len(semesters) != 1:
                raise ApiError('学期不存在或标识不唯一', status_code=422)
            cw, cp = scope_sql(actor, 'c.organization_id', args.get('college_id'))
            course_filter = ' AND a.course_id=%s' if args.get('course_id') else ''
            records = rows(db, f'''SELECT a.course_id,a.semester_id,a.course_name,a.first_attempts,a.first_pass,a.failures,a.students,
                a.makeup_attempts,a.makeup_pass,a.retake_attempts,a.retake_pass,a.rule_version,a.calculated_at,a.first_pass_rate,a.source,
                c.organization_id FROM agg_course_pass_stat a JOIN act_course c ON c.course_id=a.course_id
                WHERE a.semester_id=%s AND {cw}{course_filter} ORDER BY a.failures DESC,a.course_id''',
                [args['semester_id'], *cp, *([args['course_id']] if course_filter else [])])
            semantic_basis = course_observation.read_basis(db, cw, cp, args, records)
            result = _course_performance(records, args, semantic_basis)
        elif name == 'read_transfer_history':
            # The ACT projection has no path/date fields in this environment.
            # Read its authoritative Oracle-mirror JSON fields, with explicit provenance.
            source_where, source_params = [], []
            detail = actor['permission_context']['detailScope']
            if detail['type'] != 'all' or args.get('college_id'):
                names = rows(db, f'''SELECT name FROM act_organization WHERE {where}
                    AND name IN (SELECT name FROM act_organization GROUP BY name HAVING COUNT(*)=1)''', params)
                names = [r['name'] for r in names if r['name']]
                if not names:
                    raise ApiError('授权学院缺少唯一名称映射，不能读取贴源异动', status_code=409)
                placeholders = ','.join(['%s'] * len(names))
                source_where += [f'd.old_value IN ({placeholders})', f'd.new_value IN ({placeholders})']
                source_params += names + names
            if args.get('semester_id'):
                semester_rows = rows(db, 'SELECT start_date,end_date FROM act_semester WHERE semester_id=%s', [args['semester_id']])
                if len(semester_rows) != 1 or not all(semester_rows[0].values()):
                    raise ApiError('所选学期缺少有效起止日期，无法归属异动事件', status_code=409)
                source_where += ['a.EFFECTIVE_DATE_TIME >= %s', 'a.EFFECTIVE_DATE_TIME < DATE_ADD(%s,INTERVAL 1 DAY)']
                source_params += [semester_rows[0]['start_date'], semester_rows[0]['end_date']]
            conditions = ' AND '.join(source_where) or '1=1'
            json_table = """JSON_TABLE(CASE WHEN JSON_VALID(a.FIELDS_TEXT) THEN a.FIELDS_TEXT ELSE '[]' END,
                '$[*]' COLUMNS(field_path VARCHAR(100) PATH '$.field',old_value VARCHAR(256) PATH '$.oldValue',
                new_value VARCHAR(256) PATH '$.newValue'))"""
            with connection('source', consistent=True) as source_db:
                records = rows(source_db, f'''SELECT d.old_value before_college,d.new_value after_college,
                    m.old_value before_major_name,m.new_value after_major_name,COUNT(DISTINCT a.ID) event_count,
                    COUNT(DISTINCT a.STUDENT_ID) student_count,MAX(a.EFFECTIVE_DATE_TIME) latest_date,
                    a.STATUS record_status,MAX(a.UPDATED_DATE_TIME) updated_at
                    FROM std_alteration a JOIN b_std_alter_type t ON t.ID=a.STD_ALTER_TYPE_ID
                    JOIN {json_table} d ON d.field_path='student.departmentAssoc'
                    JOIN {json_table} m ON m.field_path='student.majorAssoc'
                    WHERE t.NAME_ZH='转专业' AND {conditions}
                    AND NULLIF(m.old_value,'') IS NOT NULL AND NULLIF(m.new_value,'') IS NOT NULL
                    GROUP BY d.old_value,d.new_value,m.old_value,m.new_value,a.STATUS
                    ORDER BY event_count DESC,before_major_name,after_major_name LIMIT %s''', [*source_params, limit])
            result['data'] = {'本次展示路径与状态分组数': len(records)}
            result['tables'] = [table('贴源异动记录的专业路径', records, {'before_college': '转出学院', 'after_college': '转入学院',
                'before_major_name': '转出专业', 'after_major_name': '转入专业', 'record_status': '源记录状态',
                'event_count': '异动记录数', 'student_count': '分组内去重学生数', 'latest_date': '最近生效日期'}, '按转出/转入学院、专业和记录状态分组；不同分组人数不能直接相加。')]
            result['summary'] = f'从贴源异动字段读取{len(records)}个路径与状态分组，保留原记录状态供核对。'
            src = source('std_alteration → b_std_alter_type（FIELDS_TEXT）', records, '提取student.departmentAssoc与student.majorAssoc的oldValue/newValue；以生效日期归入所选学期')
            src['database'] = 'edu_source'
            result['sources'] = [src]
            result['limitations'] = ['当前事实层缺少异动路径与日期，改从同环境贴源表明确提取，不混用另一个学生异动清单。',
                '学院身份仅查看双端学院名称均精确对应本院的记录，名称无法唯一匹配时拒绝；不表示全校流入流出总量。',
                '保留记录原状态，不把待处理、撤销或其他未确认状态当作已完成转入；没有申请人数分母，不计算成功率。']
        elif name == 'read_graduation_progress':
            plan = authorized_plan(db, actor, args.get('plan_id'))
            student_where, student_params = scope_sql(actor, 's.organization_id')
            student_scope = f'EXISTS (SELECT 1 FROM act_student s WHERE s.student_id=p.student_id AND {student_where})'
            records = rows(db, f'''SELECT COUNT(*) record_count,COUNT(DISTINCT p.student_id) students,
                SUM(CASE WHEN total_credits_required IS NOT NULL AND total_credits_earned IS NOT NULL THEN 1 ELSE 0 END) complete_records,
                SUM(CASE WHEN total_credits_required IS NULL OR total_credits_earned IS NULL THEN NULL
                         WHEN total_credits_required>total_credits_earned THEN 1 ELSE 0 END) remaining_records,
                AVG(credit_completion_pct) avg_completion,MAX(p.updated_at) updated_at
                FROM act_student_plan_progress_summary p WHERE p.plan_id=%s AND {student_scope}''', [plan['plan_id'], *student_params])
            modules = rows(db, f'''SELECT module_name,COUNT(*) records,
                COUNT(remaining_credits) valid_remaining_records,
                SUM(CASE WHEN remaining_credits IS NULL THEN 1 ELSE 0 END) unknown_records,
                SUM(CASE WHEN remaining_credits IS NULL THEN NULL WHEN remaining_credits>0 THEN 1 ELSE 0 END) remaining_records,
                AVG(remaining_credits) avg_remaining,MAX(updated_at) updated_at
                FROM act_student_plan_module_status p WHERE p.plan_id=%s AND {student_scope}
                GROUP BY module_name ORDER BY remaining_records DESC''', [plan['plan_id'], *student_params])
            result['scope']['plan'] = plan
            r = records[0]
            result['data'] = {'学生数': r['students'], '进度记录数': r['record_count'], '学分值完整记录数': r['complete_records'],
                              '学分值缺失记录数': r['record_count'] - (r['complete_records'] or 0), '仍有学分差额记录数': r['remaining_records']}
            result['tables'] = [table('模块进度', modules, {'module_name': '模块', 'records': '记录数',
                'valid_remaining_records': '剩余学分有效记录数', 'unknown_records': '剩余学分缺失记录数',
                'remaining_records': '存在差额记录数（有效记录内）', 'avg_remaining': '平均剩余学分（有效记录内）'}, '缺少剩余学分的记录不能视为没有差额；全部缺值时相关统计留空。')]
            result['summary'] = f"该方案读取{r['record_count']}条学生进度记录，用于定位学分准备情况。"
            result['sources'] = [source('act_student_plan_progress_summary', records, '现有方案进度，不重新推导正式毕业资格'),
                source('act_student_plan_module_status', modules, '模块剩余学分大于0的记录数量')]
            result['limitations'] = ['记录数与人数分开呈现；总学分达标不代表模块、必修课程、学位或非课程条件全部达标。',
                '同时校验方案归属学院和学生当前学院，不输出学生身份信息。']
            if modules and any(m['unknown_records'] for m in modules):
                result['limitations'].append('模块剩余学分存在缺值，只报告已知记录；尚不能据此判断模块缺口已消除。')
        elif name == 'read_graduation_audit':
            where, params = scope_sql(actor, 'g.organization_id', args.get('college_id'))
            sw, sp = scope_sql(actor, 's.organization_id', args.get('college_id'))
            sem = ' AND semester_id=%s' if args.get('semester_id') else ''
            records = rows(db, f'''SELECT audit_batch_id,graduation_status,degree_status,final_result_type,
                is_published,COUNT(*) records,COUNT(DISTINCT student_id) students,MAX(audit_date) audit_date,MAX(updated_at) updated_at
                FROM act_graduation_outcome g WHERE {where}{sem}
                AND EXISTS (SELECT 1 FROM act_student s WHERE s.student_id=g.student_id AND {sw})
                GROUP BY audit_batch_id,graduation_status,degree_status,final_result_type,is_published
                ORDER BY audit_date DESC LIMIT %s''', [*params, *([args['semester_id']] if sem else []), *sp, limit])
            result['data'] = {'本次展示审核分组数': len(records)}
            result['tables'] = [table('已入库的审核结果（保留原状态）', records, {'audit_batch_id': '审核批次', 'graduation_status': '毕业状态原值',
                'degree_status': '学位状态原值', 'final_result_type': '最终结果原值', 'is_published': '源系统公布标记', 'records': '审核记录数', 'students': '批次内学生数', 'audit_date': '审核日期'})]
            result['summary'] = f'读取{len(records)}个审核结果分组；只转述已入库状态，不新增审批结论。'
            result['sources'] = [source('act_graduation_outcome', records, '按批次和原始结果分组，不合并不同批次学生数')]
            result['limitations'] = ['批次字段仅标识当前仍可读取的记录，不能据此重建过去时点全部业务表。', '未公布记录不能等同学校已公布结论，状态编码保留原值。']
        if not result['summary']:
            result['summary'] = '所选范围缺少必要数据，不能完成分析。'
        if result.get('tables') and all(not t['rows'] for t in result['tables']):
            result['status'] = 'blocked'
            result['missingEvidence'].append('当前筛选范围没有分析记录；请核对对象、学期和数据覆盖，空结果不是指标为0。')
        if name == 'read_graduation_progress' and not result['data'].get('进度记录数'):
            result['status'] = 'blocked'
            result['missingEvidence'].append('所选方案未建立学生进度记录')
    return result if schema_version == '2.0' else _legacy_projection(result)


def execute_resource(kind, content, inputs, actor, dependencies):
    require_use(actor)
    start = monotonic()
    inputs = dict(inputs or {})
    inputs.pop('question', None)
    if kind == 'experts':
        skill_id = inputs.pop('skill_id', None)
        skills = dependencies.get('skills', [])
        selected = next((s for s in skills if s['id'] == skill_id), None)
        if selected is None and not skill_id and len(skills) == 1:
            selected = skills[0]
        if selected is None:
            raise ApiError('请选择该专家已绑定的具体分析方法', status_code=422)
        result = execute_resource('skills', selected['content'], inputs, actor, dependencies)
        result['trace'].insert(0, {'step': '选择已登记方法', 'status': 'passed', 'skillId': selected['id'], 'version': selected['version']})
        return result
    if kind == 'mcps':
        tools = content.get('tools', [])
        unknown = [t.get('name') for t in tools if t.get('name') not in HANDLERS]
        if unknown or not tools:
            raise ApiError('MCP工具清单包含未实现方法或为空', status_code=422)
        data = analysis_options(actor)
        return {'status': 'passed', 'summary': f"真实数据连接正常，已登记{len(tools)}个只读工具；业务输出仍需分别测试。",
            'result': {'status': 'completed', 'summary': '已验证数据库连接和工具登记', 'data': {'可选方案数': len(data['plans']), '只读工具数': len(tools)},
            'scope': {'environment': environment_name()}, 'sources': [], 'limitations': ['连接测试不等于全部工具业务验收'], 'missingEvidence': []},
            'trace': [{'step': '只读连接及授权对象查询', 'status': 'passed', 'elapsedMs': round((monotonic()-start)*1000)}], 'missingEvidence': []}
    missing = content.get('missingEvidence') or []
    handler = (content.get('execution') or {}).get('handler')
    if missing or handler == 'unavailable':
        return {'status': 'blocked', 'summary': '需要补齐已确认资料后再测试发布', 'result': None,
                'trace': [{'step': '检查业务资料条件', 'status': 'blocked'}], 'missingEvidence': missing or ['处理方法尚未具备执行条件']}
    inputs.pop('skill_id', None)
    processor = (content.get('execution') or {}).get('processorId')
    if processor:
        from .tasks import execute_processor
        return execute_processor(processor, content, inputs, actor, dependencies)
    # Schema validation rejects accidental coercion and arbitrary parameters.
    from jsonschema import Draft202012Validator
    errors = list(Draft202012Validator(content.get('inputSchema') or {}).iter_errors(inputs))
    if errors:
        field = '.'.join(str(p) for p in errors[0].absolute_path)
        raise ApiError('输入不符合该Skill契约' + ('：' + field if field else '，请补齐必填项'), status_code=422)
    bindings = content.get('toolBindings') or []
    servers = {s['id']: s for s in dependencies.get('mcps', [])}
    def implemented_binding(binding):
        if binding.get('toolName') != handler:
            return False
        server = servers.get(binding.get('serverId'))
        if server:
            return any(t.get('name') == handler for t in server['content'].get('tools', []))
        # Direct deterministic integration checks retain the original registered service.
        return not servers and binding.get('serverId') == 'education-data'
    if handler not in HANDLERS or not any(implemented_binding(b) for b in bindings):
        raise ApiError('Skill处理器与已登记工具依赖不一致', status_code=409)
    result = run_tool(handler, inputs, actor)
    output_errors = list(Draft202012Validator(content.get('outputSchema') or {}).iter_errors(result))
    if output_errors:
        raise ApiError('实际输出不符合该Skill契约，不能发布', status_code=409)
    status = 'blocked' if result['status'] == 'blocked' else 'passed'
    return {'status': status, 'summary': result['summary'], 'result': result,
        'trace': [{'step': '复核当前身份与对象范围', 'status': 'passed'},
                  {'step': '调用只读工具', 'tool': handler, 'status': status, 'elapsedMs': round((monotonic()-start)*1000)},
                  {'step': '校验输出结构', 'status': 'passed'}], 'missingEvidence': result['missingEvidence']}

"""Verified current-input course observations; no model formulas or school writes.

The baseline is the complete valid aggregate set returned for this authorized
scope. Source point joins prove the returned fact keys, never source coverage.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from functools import cmp_to_key
import hashlib
import json
import math
from pathlib import Path
import re

from backend.metric_verification.config import database_config, environment_name
from backend.metric_verification.database import json_value
from backend.metric_verification.mapping_contract import semantic_signatures, query_signature

LOADED_FINGERPRINT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
METRIC_CODES = tuple('AI-C-%02d' % i for i in range(1, 7))
FIRST_COHORT_SQL = 'g.is_retake=0 AND g.is_published=1 AND g.is_void=0 AND g.is_pass IN(0,1)'
REVIEWED_PACKAGE_PATH = Path(__file__).resolve().parents[2] / 'metric-verification' / 'mappings' / 'ai-briefing' / 'package.json'
REVIEWED_PACKAGE_REF = 'code/metric-verification/mappings/ai-briefing/package.json'


def _digest(value):
    return hashlib.sha256(json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str, allow_nan=False).encode()).hexdigest()


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def algorithm_definition(package):
    """The six reviewed business definitions and actual application SQL, excluding provenance prose."""
    metrics = {metric['id']: metric for metric in package['metrics']}
    queries = {query['id']: query for query in package['queries']}
    if package.get('moduleId') != 'ai-briefing' or not set(METRIC_CODES) <= set(metrics):
        raise ValueError('当前映射缺少本C方法已审查的六项AI简报指标')
    signatures = semantic_signatures(package)
    actual_queries = {}
    for code in METRIC_CODES:
        query_id = (metrics[code].get('actualBinding') or {}).get('queryId')
        query = queries.get(query_id)
        if not query or query.get('metricId') != code or query.get('layer') != 'application' or query.get('kind') != 'calculate':
            raise ValueError('指标缺少对应应用层正式计算查询：' + code)
        actual_queries[code] = query_signature(query)
    return {'semanticSignatures': {code: signatures[code] for code in METRIC_CODES},
            'applicationQuerySignatures': actual_queries}


try:
    _REVIEWED_PACKAGE_BYTES = REVIEWED_PACKAGE_PATH.read_bytes()
    LOADED_REFERENCE_SHA256 = hashlib.sha256(_REVIEWED_PACKAGE_BYTES).hexdigest()
    LOADED_REVIEWED_DEFINITION = algorithm_definition(json.loads(_REVIEWED_PACKAGE_BYTES.decode('utf-8')))
    _REFERENCE_ERROR = None
except Exception as error:
    LOADED_REFERENCE_SHA256 = 'unavailable'
    LOADED_REVIEWED_DEFINITION = None
    _REFERENCE_ERROR = type(error).__name__


def algorithm_compatibility(package, reviewed=None):
    """A new registered mapping cannot silently change the fixed C calculation."""
    reviewed = reviewed if reviewed is not None else LOADED_REVIEWED_DEFINITION
    if not reviewed:
        return {'state': 'unconfirmed', 'reason': '本C方法缺少可解析的已审查指标依据',
                'mismatchedMetricIds': [], 'mismatchedApplicationQueryIds': []}
    try:
        current = algorithm_definition(package)
    except Exception as error:
        return {'state': 'unconfirmed', 'reason': '当前指标定义不能匹配本C方法（%s）' % type(error).__name__,
                'mismatchedMetricIds': [], 'mismatchedApplicationQueryIds': []}
    metrics = [code for code in METRIC_CODES if current['semanticSignatures'][code] != reviewed['semanticSignatures'].get(code)]
    queries = [code for code in METRIC_CODES if current['applicationQuerySignatures'][code] != reviewed['applicationQuerySignatures'].get(code)]
    return {'state': 'confirmed' if not metrics and not queries else 'unconfirmed',
        'reason': None if not metrics and not queries else '当前业务定义或应用层SQL与本C方法的审查依据不同，需审查并升级对应方法',
        'mismatchedMetricIds': metrics, 'mismatchedApplicationQueryIds': queries,
        'reviewedReference': {'path': REVIEWED_PACKAGE_REF, 'sha256': LOADED_REFERENCE_SHA256,
                             'semanticSignatures': reviewed['semanticSignatures'],
                             'applicationQuerySignatures': reviewed['applicationQuerySignatures']}}


def _count(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return int(number) if number.is_finite() and number >= 0 and number == number.to_integral_value() else None


def percent(p, n):
    return None if not n else float((Decimal(p) * 100 / Decimal(n)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def _order(a, b):
    if a['first_unpassed'] != b['first_unpassed']:
        return -1 if a['first_unpassed'] > b['first_unpassed'] else 1
    comparison = a['first_pass'] * b['first_attempts'] - b['first_pass'] * a['first_attempts']
    if comparison:
        return -1 if comparison < 0 else 1
    return (str(a['course_id']) > str(b['course_id'])) - (str(a['course_id']) < str(b['course_id']))


def calculate(records, semester_id):
    """Primary method, using integer cross multiplication before display rounding."""
    frozen = deepcopy(records)
    keys = Counter((str(r.get('course_id') or '').strip(), str(r.get('semester_id') or semester_id)) for r in frozen)
    valid, excluded = [], []
    for index, row in enumerate(frozen):
        course_id = str(row.get('course_id') or '').strip()
        term = str(row.get('semester_id') or semester_id)
        n, p = _count(row.get('first_attempts')), _count(row.get('first_pass'))
        reason = None
        if not course_id:
            reason = 'missing_course_id'
        elif not row.get('organization_id'):
            reason = 'missing_opening_organization'
        elif term != str(semester_id):
            reason = 'different_semester'
        elif keys[(course_id, term)] > 1:
            reason = 'duplicate_course_semester'
        elif row.get('first_attempts') is None or row.get('first_pass') is None:
            reason = 'missing_count'
        elif n is None or p is None:
            reason = 'invalid_integer_count'
        elif p > n:
            reason = 'pass_count_exceeds_cohort'
        elif n == 0:
            reason = 'zero_denominator'
        if reason:
            excluded.append({'recordIndex': index, 'course_id': course_id or None,
                             'semester_id': term, 'reason': reason})
            continue
        valid.append({**row, 'course_id': course_id, 'semester_id': term,
            'first_attempts': n, 'first_pass': p, 'first_unpassed': n-p,
            'first_pass_pct': percent(p, n)})
    n_total = sum(r['first_attempts'] for r in valid)
    p_total = sum(r['first_pass'] for r in valid)
    for row in valid:
        row['below_scope_baseline'] = row['first_pass'] * n_total < p_total * row['first_attempts']
        row['observation'] = row['first_unpassed'] > 0 and row['below_scope_baseline']
    selected = sorted([r for r in valid if r['observation']], key=cmp_to_key(_order))
    return {'validRows': valid, 'excludedRows': excluded, 'exclusionCounts': dict(Counter(r['reason'] for r in excluded)),
        'baseline': {'firstAttempts': n_total, 'firstPass': p_total, 'ratePct': percent(p_total, n_total),
                     'courseCount': len(valid), 'population': '当前授权范围已返回且唯一、N/P合法、N>0的课程聚合集合'},
        'observations': selected, 'observationCount': len(selected), 'preview': selected[:5],
        'populationState': 'no_data' if not frozen else 'no_valid_courses' if not valid else
            'one_course' if len(valid) == 1 else 'observations' if selected else 'no_observations',
        'input': frozen, 'inputSha256': _digest(frozen)}


def independent_recompute(frozen_records, semester_id, calculated):
    """An independent Fraction evaluator reads the JSON-frozen input once.

    It shares neither primary normalization, exclusions nor ordering helpers.
    This validates this execution's math, not source/ETL or historical batches.
    """
    snapshot = json.loads(json.dumps(_json_safe(frozen_records), default=str, allow_nan=False))
    frequencies = {}
    for item in snapshot:
        key = (str(item.get('course_id') or '').strip(), str(item.get('semester_id') or semester_id))
        frequencies[key] = frequencies.get(key, 0) + 1
    evaluated = []
    for item in snapshot:
        key = (str(item.get('course_id') or '').strip(), str(item.get('semester_id') or semester_id))
        if not key[0] or key[1] != str(semester_id) or frequencies[key] != 1:
            continue
        if not item.get('organization_id'):
            continue
        values = [item.get('first_attempts'), item.get('first_pass')]
        if any(v is None or isinstance(v, bool) for v in values):
            continue
        try:
            n, p = (Fraction(str(v)) for v in values)
        except (ValueError, ZeroDivisionError):
            continue
        if n.denominator != 1 or p.denominator != 1 or n <= 0 or p < 0 or p > n:
            continue
        evaluated.append((key[0], int(n), int(p)))
    total_n, total_p = sum(r[1] for r in evaluated), sum(r[2] for r in evaluated)
    reference = Fraction(total_p, total_n) if total_n else None
    observed = [r for r in evaluated if r[1]-r[2] > 0 and Fraction(r[2], r[1]) < reference]
    observed.sort(key=lambda r: (-(r[1]-r[2]), Fraction(r[2], r[1]), r[0]))
    def display_rate(passed, attempts):
        if not attempts:
            return None
        cents, remainder = divmod(passed * 10000, attempts)
        return (cents + (remainder * 2 >= attempts)) / 100
    primary = sorted((str(r['course_id']), r['first_attempts'], r['first_pass']) for r in calculated['validRows'])
    checks = {'validSet': sorted(evaluated) == primary,
        'baselineN': total_n == calculated['baseline']['firstAttempts'],
        'baselineP': total_p == calculated['baseline']['firstPass'],
        'baselineRate': display_rate(total_p, total_n) == calculated['baseline']['ratePct'],
        'baselineCourseCount': len(evaluated) == calculated['baseline']['courseCount'],
        'courseRates': all(display_rate(r['first_pass'], r['first_attempts']) == r['first_pass_pct']
                           for r in calculated['validRows']),
        'unpassed': all(r['first_unpassed'] == r['first_attempts']-r['first_pass'] for r in calculated['validRows']),
        'selectionFlags': all(r['below_scope_baseline'] == (Fraction(r['first_pass'], r['first_attempts']) < reference)
            and r['observation'] == (r['first_attempts'] > r['first_pass']
                and Fraction(r['first_pass'], r['first_attempts']) < reference) for r in calculated['validRows']),
        'observationSetAndOrder': [r[0] for r in observed] == [str(r['course_id']) for r in calculated['observations']],
        'observationCount': len(observed) == calculated['observationCount'],
        'preview': [r[0] for r in observed[:5]] == [str(r['course_id']) for r in calculated['preview']],
        'frozenInputHash': _digest(frozen_records) == calculated['inputSha256']}
    return {'state': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
            'inputSha256': _digest(frozen_records), 'evaluator': 'independent-fraction-v1',
            'evaluatedCourseCount': len(evaluated)}


def _read(db, sql, params):
    with db.cursor() as cursor:
        cursor.execute(sql, params)
        return [{key: json_value(value, precise=True) for key, value in row.items()} for row in cursor.fetchall()]


def registration_basis():
    """Read the registered active mapping; a draft or six coincidental codes cannot approve."""
    try:
        from backend.metric_verification import mapping_store
        head = mapping_store.get_head(module_id='ai-briefing')
        if not head.get('revisionId'):
            return {'registered': False, 'metrics': [], 'mappingRef': None,
                    'reason': 'AI简报指标映射尚未正式启用'}
        registration = mapping_store.registration_status(head['revisionId'], module_id='ai-briefing')
        active = mapping_store.get_revision(head['revisionId'], module_id='ai-briefing')
        compatibility = algorithm_compatibility(active['package'])
        registration['algorithmBasis'] = {**compatibility, 'revisionId': head['revisionId']}
        if compatibility['state'] != 'confirmed':
            registration['registered'] = False
            registration['reason'] = compatibility['reason']
        return registration
    except Exception as error:
        return {'registered': False, 'metrics': [], 'mappingRef': None,
                'reason': '无法核实AI简报指标登记（%s）' % type(error).__name__}


def read_basis(db, where, scope_params, args, records):
    """Current consistent RDS snapshot, bounded to authorized course/semester keys."""
    at = datetime.now(timezone.utc).isoformat()
    source_config, fact_config = database_config('source'), database_config('analytics')
    result = {'queriedAt': at, 'state': 'pending', 'sourceCoverage': 'unknown', 'factCourseRows': [],
        'reason': None, 'sourceReference': 'grade.ID → act_grade_attempt.source_row_no',
        'factReference': 'act_grade_attempt', 'applicationReference': 'agg_course_pass_stat',
        'cohortSql': FIRST_COHORT_SQL, 'comparableAt': None,
        'timeComparability': 'unknown', 'fieldMapping': [], 'sqlRefs': []}
    if source_config.engine != 'mysql' or fact_config.engine != 'mysql' or source_config.host != fact_config.host \
            or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', source_config.database):
        result['reason'] = '当前连接无法在同一只读快照按源键核对贴源和事实层'
        return result
    source_schema = '`' + source_config.database + '`'
    query_params = list(scope_params)
    if args.get('course_id'):
        where += ' AND c.course_id=%s'
        query_params.append(args['course_id'])
    # Source PRIMARY point joins avoid a full source grade scan. The returned
    # counts cover fact-linked source keys; all-source missing rows stay unknown.
    sql = f'''SELECT g.course_id,COUNT(*) record_count,
        COALESCE(SUM({FIRST_COHORT_SQL}),0) first_n,
        COALESCE(SUM(g.is_retake=0 AND g.is_published=1 AND g.is_void=0 AND g.is_pass=1),0) first_p,
        COALESCE(SUM(g.is_retake IS NULL AND g.is_published=1 AND g.is_void=0 AND g.is_pass IN(0,1)),0) unknown_retake,
        COALESCE(SUM(g.is_retake=0 AND g.is_published=1 AND g.is_void=0 AND g.is_pass IS NULL),0) unknown_pass,
        COALESCE(SUM({FIRST_COHORT_SQL} AND s.ID IS NULL),0) missing_source,
        COALESCE(SUM({FIRST_COHORT_SQL} AND s.ID IS NOT NULL AND
          (NOT(g.is_pass<=>s.PASSED) OR NOT(g.is_retake<=>s.RETAKE) OR NOT(g.is_published<=>s.PUBLISHED)
           OR NOT(CAST(g.course_id AS DECIMAL(20,0))<=>s.COURSE_ID)
           OR NOT(CAST(g.semester_id AS DECIMAL(20,0))<=>s.SEMESTER_ID))),0) source_field_mismatches,
        COALESCE(SUM(s.RETAKE=0 AND s.PUBLISHED=1 AND s.PASSED IN(0,1) AND g.is_void=0),0) linked_source_n,
        COALESCE(SUM(s.RETAKE=0 AND s.PUBLISHED=1 AND s.PASSED=1 AND g.is_void=0),0) linked_source_p,
        COUNT(DISTINCT CASE WHEN {FIRST_COHORT_SQL} THEN g.source_row_no END) distinct_first_source_keys,
        GROUP_CONCAT(DISTINCT g.batch_id ORDER BY g.batch_id) fact_batches,
        MAX(g.updated_at) fact_updated_at
        FROM act_grade_attempt g JOIN act_course c ON c.course_id=g.course_id
        LEFT JOIN {source_schema}.grade s ON s.ID=CASE WHEN g.source_row_no REGEXP '^[0-9]+$'
            THEN CAST(g.source_row_no AS DECIMAL(20,0)) END
        WHERE g.semester_id=%s AND {where}
        GROUP BY g.course_id ORDER BY g.course_id'''
    organization_sql = f'''SELECT c.course_id,c.organization_id,
        s.DEFAULT_OPEN_DEPART_ID source_open_organization_id,
        (s.ID IS NOT NULL AND c.organization_id IS NOT NULL AND s.DEFAULT_OPEN_DEPART_ID IS NOT NULL
          AND CAST(c.organization_id AS DECIMAL(20,0))=s.DEFAULT_OPEN_DEPART_ID) organization_matches
        FROM act_course c LEFT JOIN {source_schema}.course s ON s.ID=CASE WHEN c.course_id REGEXP '^[0-9]+$'
            THEN CAST(c.course_id AS DECIMAL(20,0)) END
        WHERE {where} AND EXISTS(SELECT 1 FROM agg_course_pass_stat a
            WHERE a.course_id=c.course_id AND a.semester_id=%s) ORDER BY c.course_id'''
    try:
        result['factCourseRows'] = _read(db, sql, [args['semester_id'], *query_params])
        result['fieldMapping'] = _read(db, organization_sql, [*query_params, args['semester_id']])
        result['sqlRefs'] = [{'queryId': 'AI-C-current-source-fact', 'sqlSha256': hashlib.sha256(sql.encode()).hexdigest(),
            'sql': sql, 'parameters': {'semester_id': args['semester_id'], 'authorizedCollegeIds': list(scope_params),
                                     'course_id': args.get('course_id')},
            'recordCount': len(result['factCourseRows']), 'grain': '课程×学期；仅贴源ID与事实键实际关联的记录'},
            {'queryId': 'AI-C-opening-organization', 'sqlSha256': hashlib.sha256(organization_sql.encode()).hexdigest(),
             'sql': organization_sql, 'recordCount': len(result['fieldMapping'])}]
        result['reference'] = 'current-three-layer:' + _digest({k: v for k, v in result.items() if k != 'reference'})
        result['state'] = 'read'
    except Exception as error:
        result['reason'] = '本次三层读取未完成（%s）；只保留已有聚合字段，不批准新观察' % type(error).__name__
        result['state'] = 'pending'
    return result


def validation_basis(records, args, calculated, three_layer, registration=None):
    """Server evidence determines applicability; never accept a client verified flag."""
    registration = registration if registration is not None else registration_basis()
    independent = independent_recompute(records, args['semester_id'], calculated)
    proof = deepcopy(three_layer or {'state': 'pending', 'reason': '尚无当次三层核验依据'})
    facts = {str(r['course_id']): r for r in proof.get('factCourseRows', [])}
    mappings = {str(r['course_id']): r for r in proof.get('fieldMapping', [])}
    relevant = calculated['validRows']
    mismatch, unmatched, unknown, bad_keys, org_missing = [], [], [], [], []
    for row in relevant:
        key = str(row['course_id'])
        raw = facts.get(key)
        if not raw:
            unmatched.append(key)
            continue
        if (_count(raw.get('first_n')), _count(raw.get('first_p'))) != (row['first_attempts'], row['first_pass']):
            mismatch.append(key)
        if _count(raw.get('unknown_retake')) != 0:
            unknown.append(key)
        if (_count(raw.get('missing_source')) != 0 or _count(raw.get('source_field_mismatches')) != 0
            or _count(raw.get('distinct_first_source_keys')) != _count(raw.get('first_n'))
            or (_count(raw.get('linked_source_n')), _count(raw.get('linked_source_p'))) !=
                (_count(raw.get('first_n')), _count(raw.get('first_p')))):
            bad_keys.append(key)
        if not mappings.get(key) or _count(mappings[key].get('organization_matches')) != 1:
            org_missing.append(key)
    all_verified = bool(relevant) and proof.get('state') == 'read' and not any(
        [mismatch, unmatched, unknown, bad_keys, org_missing])
    versions = sorted({str(r['rule_version']) for r in relevant if r.get('rule_version')})
    missing_version = any(not r.get('rule_version') for r in relevant)
    # Current per-course source-key/field and aggregate equality is the common
    # semantic evidence even when labels differ or a rule label is absent.
    semantic = {'state': 'confirmed_current_input' if all_verified else 'unconfirmed',
        'cohort': FIRST_COHORT_SQL, 'sourceCohort': 'grade.RETAKE=0 AND PUBLISHED=1 AND PASSED IN(0,1)',
        'binaryStates': [0, 1], 'passSubset': 'is_pass=1为同一个首修有效集合的子集',
        'sourceKeyGrain': '一个有效事实尝试对应一个源grade.ID，不按学生去重',
        'checkedCourseCount': len(relevant), 'unknownRetakeCourses': unknown, 'sourceKeyIssueCourses': bad_keys,
        'organizationMappingIssueCourses': org_missing, 'aggregateMismatchCourses': mismatch,
        'missingFactCourses': unmatched, 'reference': proof.get('reference')}
    extra = sorted(key for key, row in facts.items() if key not in {str(r.get('course_id')) for r in records}
                   and (_count(row.get('first_n')) or 0) > 0)
    proof.update({'state': 'equal_current' if all_verified else 'pending', 'mismatchedCourses': mismatch,
        'aggregateCoverage': 'partial' if extra else 'unknown', 'factCoursesWithoutAggregate': extra,
        'applicationCourseCount': len(records), 'validApplicationCourseCount': len(relevant),
        'applicationN': calculated['baseline']['firstAttempts'], 'applicationP': calculated['baseline']['firstPass'],
        'factLinkedSourceN': sum(_count(facts[k].get('linked_source_n')) or 0 for k in facts),
        'factLinkedSourceP': sum(_count(facts[k].get('linked_source_p')) or 0 for k in facts),
        'unknownFirstPassAttempts': sum(_count(facts[k].get('unknown_pass')) or 0 for k in facts),
        'unknownRetakeClassificationAttempts': sum(_count(facts[k].get('unknown_retake')) or 0 for k in facts),
        'sourceCoverage': 'unknown', 'timeComparability': 'unknown', 'comparableAt': None})
    return {'schemaVersion': '1.0', 'environment': environment_name(),
        'sourceBasis': {'source': 'grade', 'facts': 'act_grade_attempt', 'application': 'agg_course_pass_stat',
            'sourceCoverage': 'unknown', 'reference': proof.get('reference')},
        'firstAttemptSemantics': semantic, 'ruleVersions': versions,
        'ruleCompatibility': {'state': 'confirmed_current_input' if all_verified else 'unconfirmed',
            'missingVersionLabel': missing_version, 'basis': '当次全部有效课程源键、字段、N/P集合逐课一致性；没有历史批次回放证明'},
        'methodRef': {'taskId': 'C-PERFORMANCE', 'processorId': 'course-performance-v2',
            'helperSha256': LOADED_FINGERPRINT,
            'reviewedMetricReference': {'path': REVIEWED_PACKAGE_REF, 'sha256': LOADED_REFERENCE_SHA256}},
        'metricRegistration': bool(registration.get('registered')),
        'metricAlgorithmBasis': registration.get('algorithmBasis'),
        'metricRefs': registration.get('metrics', []), 'mappingRef': registration.get('mappingRef'),
        'registrationReason': registration.get('reason'),
        'frozenInput': {'sha256': calculated['inputSha256'], 'rowCount': len(records)},
        'independentRecompute': independent, 'threeLayerCheck': proof}


def publication_gate(basis, *, supported_raw_facts=True):
    """One gate for trial, human and automatic formal results; reading uses the saved decision."""
    reasons = []
    if (basis.get('independentRecompute') or {}).get('state') == 'failed':
        return {'publishMode': 'blocked', 'reasons': ['本次冻结输入独立复算失败，停止受影响结果发布']}
    independent = basis.get('independentRecompute') or {}
    if independent.get('state') == 'passed' and (
        not independent.get('checks') or not all(independent['checks'].values())
        or independent.get('inputSha256') != (basis.get('frozenInput') or {}).get('sha256')):
        return {'publishMode': 'blocked', 'reasons': ['独立复算检查项或冻结输入引用不一致，停止受影响结果发布']}
    semantic = basis.get('firstAttemptSemantics') or {}
    if semantic.get('state') != 'confirmed_current_input':
        reasons.append('本次首修有效集合、源键或组织关联尚未得到完整核实')
        details = [('unknownRetakeCourses', '首修或重修分类尚未明确'),
                   ('sourceKeyIssueCourses', '源键或通过等字段未完整对上'),
                   ('organizationMappingIssueCourses', '贴源开课学院关联尚未对上'),
                   ('missingFactCourses', '尚无对应事实层有效集合')]
        reasons.extend(f"{len(semantic[key])}门课程{label}" for key, label in details if semantic.get(key))
        if semantic.get('aggregateMismatchCourses'):
            reasons.append(f"{len(semantic['aggregateMismatchCourses'])}门课程的应用层与当前事实层N/P不同；历史时点尚不可比，差异待核")
    elif (basis.get('ruleCompatibility') or {}).get('state') != 'confirmed_current_input':
        reasons.append('本范围加工规则的首修语义可比性尚未核实')
    if (basis.get('independentRecompute') or {}).get('state') != 'passed':
        reasons.append('尚无本次输入独立复算通过依据')
    registered = {m.get('metricCode') for m in basis.get('metricRefs', []) if m.get('registered')}
    if (not basis.get('metricRegistration') or not set(METRIC_CODES) <= registered or not basis.get('mappingRef')
        or (basis.get('metricAlgorithmBasis') or {}).get('state') != 'confirmed'):
        reasons.append('AI简报六项业务指标及页面绑定尚未正式登记或当前映射不适用')
        if (basis.get('metricAlgorithmBasis') or {}).get('reason'):
            reasons.append(basis['metricAlgorithmBasis']['reason'])
    if reasons:
        return {'publishMode': 'facts_only' if supported_raw_facts else 'blocked', 'reasons': reasons}
    return {'publishMode': 'observation', 'reasons': [], 'applicability': 'limited',
        'limitations': ['覆盖仅为本次已返回的有效课程聚合集合；贴源全集覆盖未知。',
            '当次三层数值和源键一致，不证明聚合时点与当前事实属于同一历史批次。']}


def observations(records, args, three_layer=None, registration=None):
    computed = calculate(records, args['semester_id'])
    basis = validation_basis(records, args, computed, three_layer, registration)
    gate = publication_gate(basis, supported_raw_facts=bool(records))
    return computed, basis, gate

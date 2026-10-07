"""Limited real-database adapter for published graduation conditions.

No client grades or completion flags are accepted. A result-table row is not
proof that the school supplied every attempt: negative conclusions stay unknown.
Only an explicitly approved learning basis may yield positive matched evidence.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib

from backend.api.envelope import ApiError
from backend.metric_verification.database import connection, json_value
from . import policy_tasks, rules, runtime

MAX_OBJECTS = 500
MAX_RESULTS = 100_000


def availability():
    return {'G-CHECK': {
        'codeReady': True, 'algorithmImplemented': True, 'formalReady': False,
        'supportedPopulation': 'plan:<plan_id>：实际主方案分配、学籍program_id及当前组织权限联合读取',
        'verifiedMetadata': ['act_student.program_id/organization_id/grade',
                             'act_student_plan_assignment.student_id/plan_id/is_primary/source',
                             'act_student_course_result.effective_attempt_id/rule_version/is_pass/earned_credits',
                             'act_grade_attempt.attempt_id/student_id/course_id/is_published/is_void/is_pass/credits'],
        'observedBaseline': {'resultRows': 3351558, 'unknownPassRows': 533, 'gradeRuleVersion': 'grade-effective-v1',
                             'studentRows': 45865, 'studentsWithPlanBinding': 0,
                             'verifiedPrimaryAssignments': 30992, 'verifiedSourceProgramMatches': 30992,
                             'assignmentSource': 'real', 'multiplePrimaryAssignments': 0, 'orphanAssignments': 0,
                             'derivedProgressBindings': 30992, 'derivedProgressSource': 'growth-v1',
                             'evidence': '114只读元数据及聚合核对；不等于学校确认或成果覆盖完整'},
        'missingEvidence': ['适用年度、组织及方案的唯一已确认已发布规则',
                            '该规则learningBasis对有效结果来源、规则版本、学分来源的业务确认',
                            '实际成绩/认定来源覆盖依据；当前只能核正向已知成果，缺记录保持未知']},
        'T-RECOGNITION': {'codeReady': False, 'formalReady': False, 'missingEvidence': [
            '已确认目标正式要求及认定/成果分配规则', '真实获授权已选群体引用解析',
            'act_student_course_substitution/credit_recognition的目标方案适用与业务认定依据']},
        'R-CHECK': {'codeReady': False, 'formalReady': False, 'missingEvidence': [
            '已确认当年学校/学院条件与适用关系', '可鉴权的完整实际排名结果引用',
            '纪律及其他非成绩条件可信来源、年度、覆盖和确认依据']}}


def _blocked(task_id, reason, *, unknown=None):
    return {'status': 'blocked', 'summary': reason, 'result': None, 'trace': [],
            'missingEvidence': [reason], 'unknown': unknown or [], 'taskId': task_id}


def _rows(db, sql, parameters):
    with db.cursor() as cursor:
        cursor.execute(sql, parameters)
        return [{key: json_value(value, precise=True) for key, value in row.items()} for row in cursor.fetchall()]


def _metadata(db):
    needed = {
        'act_student': {'student_id', 'organization_id', 'program_id', 'grade'},
        'act_student_plan_assignment': {'student_id', 'plan_id', 'is_primary', 'source'},
        'act_student_course_result': {'id', 'student_id', 'course_id', 'rule_version', 'effective_attempt_id', 'is_pass',
                                      'earned_credits', 'result_basis', 'calculated_at'},
        'act_grade_attempt': {'attempt_id', 'student_id', 'course_id', 'is_published', 'is_void', 'is_pass', 'credits'}}
    data = _rows(db, '''SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (%s,%s,%s,%s)''', list(needed))
    actual = {}
    for row in data:
        actual.setdefault(row['TABLE_NAME'].lower(), set()).add(row['COLUMN_NAME'].lower())
    missing = [table + '.' + column for table, columns in needed.items() for column in columns - actual.get(table, set())]
    if missing:
        raise ApiError('当前事实库缺少所需字段：' + '、'.join(sorted(missing)), status_code=409)


def _basis(rule):
    basis = rule['payload'].get('learningBasis') or {}
    if (basis.get('effectiveResultSource') != 'act_student_course_result'
            or basis.get('attemptSource') != 'act_grade_attempt'
            or basis.get('gradeRuleVersion') != 'grade-effective-v1'
            or basis.get('creditsSource') != 'act_student_course_result.earned_credits'
            or basis.get('selectionConfirmed') is not True or basis.get('creditsConfirmed') is not True):
        raise ApiError('发布规则尚未确认有效成果选择及学分来源learningBasis，不能由表名或同名版本推定', status_code=409)
    return basis


def _object_ref(student_id):
    return 'student-result:' + hashlib.sha256(str(student_id).encode()).hexdigest()


def _achievement(row):
    published, void, passed = row.get('attempt_published'), row.get('attempt_void'), row.get('result_pass')
    valid = published in (1, '1') and void in (0, '0') and row.get('result_pass') == row.get('attempt_pass') and bool(row.get('result_basis'))
    try:
        earned = Decimal(str(row.get('earned_credits')))
        attempt_credits = Decimal(str(row.get('attempt_credits')))
        expected = attempt_credits if passed in (1, '1') else Decimal('0') if passed in (0, '0') else None
        conflict = not earned.is_finite() or not attempt_credits.is_finite() or earned < 0 or expected is None or earned != expected
    except (InvalidOperation, ValueError, TypeError):
        conflict = True
    return {'courseId': str(row['course_id']), 'effective': True, 'valid': valid, 'validityConfirmed': valid,
            'passed': True if passed in (1, '1') else False if passed in (0, '0') else None,
            'credits': row.get('earned_credits'), 'creditsConfirmed': not conflict, 'creditConflict': conflict,
            'evidenceId': 'effective-result:' + hashlib.sha256(str(row['id']).encode()).hexdigest(),
            'sourceRef': 'act_student_course_result/act_grade_attempt:record:' + hashlib.sha256(
                (str(row['id']) + ':' + str(row.get('effective_attempt_id'))).encode()).hexdigest(),
            'ruleVersion': row.get('rule_version'), 'calculatedAt': row.get('calculated_at')}


def _read_learning_results(db, args, actor):
    plan_id = str(args.get('plan_id') or '')
    if not plan_id or args.get('populationRef') != 'plan:' + plan_id:
        raise ApiError('群体引用须为所选方案plan:<plan_id>', status_code=422)
    plan = runtime.authorized_plan(db, actor, plan_id)
    where, params = runtime.scope_sql(actor, 's.organization_id', args.get('college_id'))
    _metadata(db)
    students = _rows(db, f'''SELECT s.student_id,a.plan_id assignment_plan_id,
        a.is_primary assignment_primary,a.source assignment_source
        FROM act_student s LEFT JOIN act_student_plan_assignment a ON a.student_id=s.student_id AND a.is_primary=1
        WHERE s.program_id=%s AND {where} ORDER BY s.student_id LIMIT {MAX_OBJECTS + 1}''', [plan_id, *params])
    if not students:
        raise ApiError('没有可确认的当前主方案群体；零返回不推断该方案无人，不按专业年级或growth-v1进度猜测绑定', status_code=409)
    if len(students) > MAX_OBJECTS:
        raise ApiError(f'所选群体超过{MAX_OBJECTS}对象留存上限，未返回截断集合', status_code=422)
    ids = [str(row['student_id']) for row in students]
    if len(set(ids)) != len(ids):
        raise ApiError('当前学籍对象重复，需确认唯一关系', status_code=409)
    if any(str(row.get('assignment_plan_id')) != plan_id or row.get('assignment_primary') not in (1, '1') or
           row.get('assignment_source') != 'real' for row in students):
        raise ApiError('学籍program_id与实际主方案分配不一致或来源未确认，不能删除冲突对象后计算', status_code=409)
    observed = []
    if ids:
        placeholders = ','.join(['%s'] * len(ids))
        observed = _rows(db, f'''SELECT r.id,r.student_id,r.course_id,r.effective_attempt_id,r.rule_version,
            r.is_pass result_pass,r.earned_credits,r.result_basis,r.calculated_at,
            g.is_published attempt_published,g.is_void attempt_void,g.is_pass attempt_pass,g.credits attempt_credits
            FROM act_student_course_result r LEFT JOIN act_grade_attempt g ON g.attempt_id=r.effective_attempt_id
            AND g.student_id=r.student_id AND g.course_id=r.course_id
            WHERE r.student_id IN ({placeholders}) AND r.rule_version=%s
            ORDER BY r.student_id,r.course_id,r.id LIMIT {MAX_RESULTS + 1}''', [*ids, 'grade-effective-v1'])
    if len(observed) > MAX_RESULTS:
        raise ApiError('成果证据超过当前留存上限，未返回截断集合', status_code=422)
    by_student = {identity: [] for identity in ids}
    for row in observed:
        identity = str(row['student_id'])
        if identity not in by_student:
            raise ApiError('读取成果越出固定授权群体，已停止执行', code=403, status_code=403)
        by_student[identity].append(_achievement(row))
    coverage = {'sourceComplete': False, 'validityConfirmed': False, 'creditsConfirmed': False,
                'returnedEvidenceComplete': True, 'populationComplete': True,
                'reason': '本次查询集合已完整保留，但尚无全部教务尝试或认定的来源覆盖证明'}
    objects = []
    for identity, values in by_student.items():
        for value in values:
            value['attemptChecksPassed'] = value['validityConfirmed']
            value['creditChecksPassed'] = value['creditsConfirmed']
            # Tool checks factual association; school adoption confirmation is separate.
            value['validityConfirmed'] = False
            value['creditsConfirmed'] = False
        objects.append({'objectRef': _object_ref(identity), 'achievements': values, 'coverage': coverage})
    result = {'status': 'limited', 'summary': '真实有效结果及尝试关联，仅作事实证据，不证明完整成果覆盖或学校认定',
              'objects': objects, 'coverage': coverage, 'scope': {'planId': plan_id, 'organization': str(plan['organization_id']),
              'populationRef': args['populationRef'], 'populationCount': len(ids)},
              'sources': [{'name': 'act_student + act_student_plan_assignment', 'grain': '当前授权主方案对象，program_id与真实主分配交叉校验', 'recordCount': len(ids)},
                          {'name': 'act_student_course_result + act_grade_attempt', 'grain': '有效结果与实际尝试关联',
                           'recordCount': len(observed), 'gradeRuleVersion': 'grade-effective-v1',
                           'queriedAt': datetime.now(timezone.utc).isoformat()}],
              'limitations': ['同名grade-effective-v1不自动代表学校确认；无记录不判未修或不满足',
                              '未读取学校纪律、其他毕业/学位要求或转专业正式认定',
                              '群体仅是明确主方案绑定对象，不扩充到缺绑定学生或用专业年级推议']}
    import json
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 5_000_000:
        raise ApiError('证据超过5MB留存上限，未返回截断或正式核验结果', status_code=422)
    return result


def read_learning_results(args, actor):
    if not isinstance(args, dict) or set(args) - {'plan_id', 'populationRef', 'college_id'}:
        raise ApiError('学习成果查询只接受固定方案群体和授权学院筛选', status_code=422)
    runtime.scope_sql(actor, 's.organization_id', args.get('college_id'))
    with connection('analytics', consistent=True) as db:
        return _read_learning_results(db, args, actor)


def execute(task_id, inputs, actor, dependencies=None):
    # Scope is checked before reporting readiness: blocked capability is no bypass.
    if not isinstance(inputs, dict):
        raise ApiError('任务输入结构无效', status_code=422)
    runtime.scope_sql(actor, 's.organization_id', inputs.get('college_id'))
    allowed = {'plan_id', 'populationRef', 'ruleRef', 'conditionIds', 'year', 'college_id'}
    if set(inputs) - allowed:
        raise ApiError('核验不接受客户端成果、成绩、通过状态或未登记字段', status_code=422)
    if task_id != 'G-CHECK':
        item = availability().get(task_id)
        return _blocked(task_id, '；'.join(item['missingEvidence']) if item else '没有已验证的真实输入适配器')
    plan_id = str(inputs.get('plan_id') or '')
    if not plan_id or inputs.get('populationRef') != 'plan:' + plan_id:
        return _blocked(task_id, '请选择明确培养方案群体，populationRef须为plan:<plan_id>，其他群体引用尚未验证')
    if inputs.get('year') is None:
        return _blocked(task_id, '需明确核验适用年度，不使用当前日期或年级猜测政策年度')
    ref = inputs.get('ruleRef')
    if not isinstance(ref, dict) or not ref.get('ruleId') or not ref.get('version'):
        return _blocked(task_id, '请选择已发布规则的固定版本')
    with connection('analytics', consistent=True) as db:
        plan = runtime.authorized_plan(db, actor, plan_id)
        where, params = runtime.scope_sql(actor, 's.organization_id', inputs.get('college_id'))
        context = {'year': inputs['year'], 'organization': str(plan['organization_id']), 'program': plan_id, 'cohort': str(plan['grade'])}
        try:
            rule = rules.select_rule('graduation', context, actor, [ref], purpose='formal')
            _basis(rule)
        except ApiError as error:
            if error.status_code in (401, 403):
                raise
            return _blocked(task_id, error.msg)
        try:
            learning = _read_learning_results(db, inputs, actor)
        except ApiError as error:
            if error.status_code in (409, 422):
                return _blocked(task_id, error.msg)
            raise
        objects = deepcopy(learning['objects'])
        for obj in objects:
            for value in obj['achievements']:
                value['validityConfirmed'] = value['attemptChecksPassed']
                value['creditsConfirmed'] = value['creditChecksPassed']
        requested = inputs.get('conditionIds')
        if requested is not None:
            known = {c['conditionId'] for c in rule['payload']['conditions']}
            if not isinstance(requested, list) or not requested or len(set(requested)) != len(requested) or not set(requested).issubset(known):
                raise ApiError('所选条件不属于固定规则或为空/重复', status_code=422)
        # Calculate using the full policy so hidden overlapping requirements cannot
        # disappear when a user asks to display only one condition.
        data = {'rule': rule, 'objects': objects, 'sources': learning['sources']}
        calculated = policy_tasks.execute_task(task_id, data, trusted_inputs=True)
        if calculated.get('status') != 'passed' or not isinstance(calculated.get('result'), dict):
            return calculated
        if requested is not None:
            states = []
            for obj in calculated['result']['objects']:
                obj['conditions'] = [c for c in obj['conditions'] if c['conditionId'] in requested]
                obj['adopted'] = [a for a in obj['adopted'] if a['conditionId'] in requested]
                obj['counts'] = {state: sum(c['state'] == state for c in obj['conditions']) for state in policy_tasks.STATES}
                selected = [c['state'] for c in obj['conditions']]
                states.append('unsatisfied' if 'unsatisfied' in selected else 'unknown' if 'unknown' in selected or not selected
                              else 'satisfied' if 'satisfied' in selected else 'not_applicable')
            calculated['result']['objectCounts'] = {state: states.count(state) for state in policy_tasks.STATES}
            calculated['result']['affectedObjectRefs'] = [obj['objectRef'] for obj, state in zip(calculated['result']['objects'], states)
                                                         if state in {'unknown', 'unsatisfied'}]
        calculated['result']['learningEvidence'] = learning
        import json
        if len(json.dumps(calculated, ensure_ascii=False).encode('utf-8')) > 5_000_000:
            return _blocked(task_id, '完整条件及学习证据超过5MB留存上限，未输出截断的正式结果')
        return {**calculated, 'summary': '已核对已发布规则的限定条件；未匹配及覆盖不明条件保持未知，不代表毕业或学位资格',
                'trace': [{'step': '方案与群体范围鉴权', 'status': 'passed'}, {'step': '规则唯一适用及学习依据确认', 'status': 'passed'},
                          {'step': '真实成果读取与逐行校验', 'status': 'passed'}]}

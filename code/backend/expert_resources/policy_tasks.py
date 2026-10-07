"""Reusable deterministic task processors for server-validated policy inputs.

This module does not read the database or accept HTTP requests. Adapters own
authorization, authentic sources and fixed applicable rule selection. Fixtures
are visibly nonformal. Every unsupported or missing basis remains unknown.
"""
from copy import deepcopy
from decimal import Decimal

from backend.api.envelope import ApiError
from .matching import STATES, decimal_text, decimal_value, evaluate_group, evaluate_requirements

TASKS = {'G-CHECK', 'T-REQUIREMENTS', 'T-RECOGNITION', 'R-PREPARE', 'R-RANK', 'R-CHECK',
         'R-SCENARIO', 'P-PATH', 'P-CHANGE', 'P-SUPPORT', 'C-SUPPORT',
         'T-POLICY', 'T-POLICY-SCENARIO', 'T-SCHEDULE'}


def _blocked(reason, task_id, purpose):
    return {'taskId': task_id, 'purpose': purpose, 'status': 'blocked', 'summary': reason,
            'missingEvidence': [reason], 'result': None}


def _base(task_id, purpose, result, sources):
    return {'taskId': task_id, 'purpose': purpose, 'status': 'passed', 'result': result,
            'sources': deepcopy(sources), 'missingEvidence': [],
            'limitations': ['开发夹具，不是学校正式核验'] if purpose == 'fixture' else []}


def _rule_ready(rule, purpose):
    if not isinstance(rule, dict):
        return False
    if purpose == 'fixture':
        return True
    if purpose == 'candidate':
        return rule.get('state') == 'confirmed' and bool(rule.get('confirmation', {}).get('accepted'))
    return rule.get('state') == 'published' and bool((rule.get('confirmation') or {}).get('accepted'))


def requirements_compare(source_rule, target_rule):
    source = source_rule.get('payload', source_rule)
    target = target_rule.get('payload', target_rule)
    left = source.get('conditions', [])
    right = target.get('conditions', [])
    def key(item):
        if item.get('type') == 'course_completion':
            return ('course_completion', item.get('courseId'))
        if item.get('type') == 'credit_pool':
            return ('credit_pool', tuple(sorted(item.get('courseIds', []))), str(item.get('minCredits')))
        return ('unsupported', item.get('conditionId'))
    left_keys = {key(item) for item in left}
    right_keys = {key(item) for item in right}
    return {'direction': {'from': source.get('ruleId'), 'to': target.get('ruleId')},
            'targetRequirements': deepcopy(right), 'common': [deepcopy(item) for item in right if key(item) in left_keys],
            'targetAdditional': [deepcopy(item) for item in right if key(item) not in left_keys],
            'sourceOnly': [deepcopy(item) for item in left if key(item) not in right_keys],
            'limitations': ['要求对照具有方向，不代表个人成果认定或录取，池差额不能按所有课程累加']}


def prepare_materials(rule, materials, context):
    payload = rule.get('payload', rule)
    required = payload.get('requiredMaterials', [])
    values = []
    for requirement in required:
        applicable = [m for m in materials if m.get('materialId') == requirement.get('materialId') and
                      m.get('year') == context.get('year') and m.get('organization') == context.get('organization')]
        valid = [m for m in applicable if m.get('confirmed') is True and m.get('sourceRef') and m.get('body')]
        state = 'satisfied' if len(valid) == 1 else 'unknown'
        values.append({'materialId': requirement.get('materialId'), 'state': state,
                       'sourceRef': valid[0]['sourceRef'] if len(valid) == 1 else None,
                       'reason': '当年适用材料已确认' if state == 'satisfied' else '材料缺失、年度不符、未确认或存在多个版本'})
    return {'materials': values, 'ruleRef': {'ruleId': payload.get('ruleId'), 'version': payload.get('version')},
            'conditions': [], 'wholeEligibility': None,
            'preparationComplete': bool(required) and all(v['state'] == 'satisfied' for v in values),
            'limitations': ['仅列年度规则及材料准备，不输出推免资格']}


def rank_objects(rule, objects, coverage):
    """Decimal ordering, explicitly confirmed course scope and competition ties."""
    payload = rule.get('payload', rule)
    rank = payload.get('ranking') or {}
    if rank.get('method') not in {'weighted_mean', 'explicit_score'} or rank.get('tiePolicy') != 'competition':
        raise ApiError('成绩规则或并列规则未明确支持', status_code=422)
    scope = set(rank.get('courseIds') or [])
    rows, excluded = [], []
    seen = set()
    for obj in objects:
        identity = obj.get('objectRef')
        if not identity or identity in seen:
            raise ApiError('排名群体对象标识缺失或重复', status_code=422)
        seen.add(identity)
        try:
            if rank['method'] == 'explicit_score':
                if obj.get('scoreConfirmed') is not True or not obj.get('sourceRef'):
                    raise ValueError('Score unconfirmed')
                score = decimal_value(obj.get('score'))
                evidence = [obj['sourceRef']]
            else:
                achievements = obj.get('achievements', [])
                effective = [a for a in achievements if a.get('courseId') in scope and a.get('effective') is True]
                if not scope or {a.get('courseId') for a in effective} != scope or len(effective) != len(scope):
                    raise ValueError('Incomplete course set')
                total, numerator = Decimal('0'), Decimal('0')
                evidence = []
                for row in effective:
                    if row.get('valid') is not True or row.get('validityConfirmed') is not True or row.get('creditsConfirmed') is not True or not row.get('sourceRef'):
                        raise ValueError('Invalid achievement')
                    credits = decimal_value(row.get('credits'))
                    grade = decimal_value(row.get('score'))
                    if credits <= 0:
                        raise ValueError('Invalid denominator')
                    numerator += credits * grade
                    total += credits
                    evidence.append(row['sourceRef'])
                score = numerator / total
            rows.append({'objectRef': identity, 'exactScore': decimal_text(score), 'displayScore': format(score, '.2f'),
                         'evidence': evidence, '_score': score})
        except ValueError:
            excluded.append({'objectRef': identity, 'state': 'unknown', 'reason': '必要成绩、课程范围或来源确认不完整'})
    rows.sort(key=lambda row: (-row['_score'], row['objectRef']))
    previous, place = None, None
    for position, row in enumerate(rows, 1):
        if row['_score'] != previous:
            place = position
        previous = row['_score']
        row['rank'] = place
        row.pop('_score')
    full = coverage.get('populationComplete') is True and not excluded
    return {'rows': rows, 'excluded': excluded, 'denominator': len(objects), 'populationComplete': full,
            'rankingKind': 'whole_population' if full else 'known_subset', 'wholeEligibility': None,
            'limitations': [] if full else ['必要对象或成绩缺失，仅为已知子集排序，不代表全体正式名次']}


def check_values(rule, objects, thresholds=None):
    payload = rule.get('payload', rule)
    results = []
    ids = [obj.get('objectRef') for obj in objects]
    if any(not identity for identity in ids) or len(set(ids)) != len(ids):
        raise ApiError('核验对象缺失或重复', status_code=422)
    for obj in objects:
        conditions = []
        for requirement in payload.get('conditions', []):
            key = requirement['conditionId']
            entry = {'objectRef': obj['objectRef'], 'conditionId': key, 'state': 'unknown', 'reason': '条件资料或类型未确认',
                     'category': requirement.get('category'), 'matchedEvidence': []}
            value = (obj.get('values') or {}).get(key)
            if requirement.get('applicable') is False:
                entry.update(state='not_applicable', reason='条件明确不适用')
            elif isinstance(value, dict) and value.get('confirmed') is True and value.get('sourceRef'):
                entry['matchedEvidence'] = [value['sourceRef']]
                if requirement.get('type') == 'threshold':
                    try:
                        required = decimal_value((thresholds or {}).get(key, requirement.get('threshold')))
                        observed = decimal_value(value.get('value'))
                        operator = requirement.get('operator', 'gte')
                        if operator not in {'gte', 'lte'}:
                            raise ValueError('Unsupported operator')
                        satisfied = observed >= required if operator == 'gte' else observed <= required
                        entry.update(state='satisfied' if satisfied else 'unsatisfied', required=decimal_text(required),
                                     observed=decimal_text(observed), reason='按确认阈值计算')
                    except ValueError:
                        pass
                elif requirement.get('type') == 'boolean' and isinstance(value.get('value'), bool):
                    satisfied = value['value'] is requirement.get('expected', True)
                    entry.update(state='satisfied' if satisfied else 'unsatisfied', observed=value['value'], reason='按确认条件记录核验')
            conditions.append(entry)
        results.append({'objectRef': obj['objectRef'], 'conditions': conditions})
    counts = {state: sum(any(c['state'] == state for c in obj['conditions']) for obj in results) for state in STATES}
    return {'objects': results, 'denominator': len(objects), 'conditionObjectCounts': counts, 'wholeEligibility': None,
            'limitations': ['只核所列条件，各状态按对象去重且可重叠；不代表完整资格或名额名单']}


def support_mapping(task_id, documents, mappings, targets, context):
    applicable = {}
    unknown = []
    counts = {}
    for doc in documents:
        identity = doc.get('documentId')
        counts[identity] = counts.get(identity, 0) + 1
    for doc in documents:
        valid = counts.get(doc.get('documentId')) == 1 and doc.get('confirmed') is True and doc.get('year') == context.get('year') and doc.get('body') and doc.get('sourceRef') and doc.get('hash')
        if valid:
            applicable[doc.get('documentId')] = doc
        else:
            unknown.append({'documentId': doc.get('documentId'), 'reason': '原文、版本、适用年度或业务确认缺失'})
    rows = []
    required_roles = {'teaching', 'assessment'} if task_id == 'C-SUPPORT' else {'course'}
    for target in targets:
        matched = [m for m in mappings if m.get('targetId') == target and m.get('confirmed') is True and
                   m.get('documentId') in applicable and m.get('sourceLocation')]
        roles = {m.get('role') for m in matched}
        missing = sorted(required_roles - roles)
        rows.append({'targetId': target, 'state': 'satisfied' if not missing else 'unknown', 'mappings': deepcopy(matched),
                     'missingRoles': missing, 'reason': '显式关系具备' if not missing else '缺少已确认对应关系，文本相似不能代替'})
    return {'targets': rows, 'unknownDocuments': unknown, 'attainmentRate': None,
            'limitations': ['只呈现原文和显式对应证据，不证明支撑充分性、达成率或最优资源投入']}


def path_check(courses, constraints, constraints_confirmed):
    records = {}
    for course in courses:
        identity = course.get('courseId')
        if not identity or identity in records:
            raise ApiError('路径课程标识缺失或重复', status_code=422)
        records[identity] = course
    violations, unknown = [], []
    if not constraints_confirmed:
        unknown.append({'reason': '先修和负荷等约束尚未确认'})
    else:
        for constraint in constraints:
            if constraint.get('type') != 'prerequisite':
                unknown.append({'constraint': deepcopy(constraint), 'reason': '当前未支持该约束类型'})
                continue
            before, after = records.get(constraint.get('beforeCourseId')), records.get(constraint.get('afterCourseId'))
            if not before or not after or before.get('semester') is None or after.get('semester') is None:
                unknown.append({'constraint': deepcopy(constraint), 'reason': '课程或计划学期未知'})
            else:
                try:
                    before_semester = decimal_value(before['semester'])
                    after_semester = decimal_value(after['semester'])
                    if before_semester <= 0 or after_semester <= 0 or before_semester != before_semester.to_integral_value() or after_semester != after_semester.to_integral_value():
                        raise ValueError('Invalid semester')
                    if before_semester >= after_semester:
                        violations.append({'constraint': deepcopy(constraint), 'reason': '先修课程未安排在后继课程之前'})
                except ValueError:
                    unknown.append({'constraint': deepcopy(constraint), 'reason': '计划学期格式或依据未知'})
    return {'courses': deepcopy(courses), 'violations': violations, 'unknown': unknown,
            'overallFeasible': None, 'limitations': ['计划学期不代表实际开课，不保证未来安排、容量、成本或师资收益']}


def transfer_policy(rule, objects, changes=None):
    """Same selected objects under fixed baseline or explicitly allowed changes."""
    modified = deepcopy(rule)
    payload = modified.get('payload', modified)
    allowed = set(payload.get('scenarioAllowedConditionIds', []))
    by_id = {condition['conditionId']: condition for condition in payload.get('conditions', [])}
    if changes is not None:
        if not isinstance(changes, list):
            raise ApiError('转入假设changes须为明确变更列表', status_code=422)
        seen = set()
        for change in changes:
            if not isinstance(change, dict):
                raise ApiError('假设条件结构无效', status_code=422)
            key = change.get('conditionId')
            if key not in allowed or key not in by_id or key in seen or set(change) != {'conditionId', 'proposedValue'}:
                raise ApiError('转入假设仅允许已确认可调整条件，每项只能修改一次', status_code=422)
            seen.add(key)
            try:
                value = decimal_value(change.get('proposedValue'))
            except ValueError:
                raise ApiError('假设条件值必须为有限明确数值', status_code=422) from None
            if value < 0:
                raise ApiError('假设条件不能为负数', status_code=422)
            condition = by_id[key]
            if condition.get('type') == 'credit_pool':
                condition['minCredits'] = decimal_text(value)
            elif condition.get('type') == 'threshold':
                condition['threshold'] = decimal_text(value)
            else:
                raise ApiError('该条件类型不能用数值假设修改', status_code=422)
    learning_conditions = [c for c in payload.get('conditions', []) if c.get('type') in {'course_completion', 'credit_pool'}]
    value_conditions = [c for c in payload.get('conditions', []) if c.get('type') not in {'course_completion', 'credit_pool'}]
    learning_rule = {**payload, 'conditions': learning_conditions}
    value_rule = {**payload, 'conditions': value_conditions}
    learning = evaluate_group(learning_rule, objects)
    values = check_values(value_rule, objects)
    for target, additional in zip(learning['objects'], values['objects']):
        target['conditions'].extend(additional['conditions'])
        target['counts'] = {state: sum(c['state'] == state for c in target['conditions']) for state in STATES}
    object_states = []
    for obj in learning['objects']:
        states = [c['state'] for c in obj['conditions']]
        object_states.append('unsatisfied' if 'unsatisfied' in states else 'unknown' if 'unknown' in states or not states
                             else 'satisfied' if 'satisfied' in states else 'not_applicable')
    learning['objectCounts'] = {state: object_states.count(state) for state in STATES}
    learning['affectedObjectRefs'] = [obj['objectRef'] for obj, state in zip(learning['objects'], object_states) if state in {'unsatisfied', 'unknown'}]
    learning.update(assumptions=deepcopy(changes or []), formalBaselineUnchanged=True, capacityConclusion=None,
                    limitations=['仅针对明确群体和所核条件；假设不改学校政策、实际申请、认定结果或开课容量'])
    return learning


def actual_schedule(requirements, offerings, prerequisites, completed_courses, coverage):
    """Check observed opening/time/prerequisite facts, never construct a timetable."""
    from .matching import _cyclic_courses
    edges = [{'fromCourseId': p.get('beforeCourseId'), 'toCourseId': p.get('afterCourseId')} for p in prerequisites]
    cycles = _cyclic_courses(edges)
    results = []
    seen = set()
    for requirement in requirements:
        course = requirement.get('courseId')
        if not course or course in seen:
            raise ApiError('安排核验课程标识缺失或重复', status_code=422)
        seen.add(course)
        entry = {'courseId': course, 'state': 'unknown', 'reason': '实际开课、剩余时间或先修覆盖未知',
                 'matchedEvidence': [], 'capacityState': 'unknown'}
        records = [r for r in offerings if r.get('courseId') == course and r.get('actual') is True and
                   r.get('confirmed') is True and r.get('sourceRef') and r.get('status') in {'published', 'scheduled'}]
        needed = [p for p in prerequisites if p.get('afterCourseId') == course]
        if course in cycles:
            entry['reason'] = '确认先修关系形成循环，不能自动安排'
        elif coverage.get('remainingTimeConfirmed') is not True:
            entry['reason'] = '剩余可用时间未确认，不用方案建议学期代替'
        else:
            try:
                deadline = decimal_value(requirement.get('requiredByTermOrder'))
                if deadline <= 0 or deadline != deadline.to_integral_value():
                    raise ValueError('Invalid term')
                timely = []
                for record in records:
                    term = decimal_value(record.get('termOrder'))
                    if term <= 0 or term != term.to_integral_value():
                        raise ValueError('Invalid offering term')
                    if term <= deadline:
                        timely.append(record)
                entry['matchedEvidence'] = [record['sourceRef'] for record in timely]
                prerequisites_known = coverage.get('prerequisitesConfirmed') is True and all(p.get('confirmed') is True and p.get('sourceRef') for p in needed)
                prerequisite_missing = [p['beforeCourseId'] for p in needed if p.get('beforeCourseId') not in completed_courses]
                if not prerequisites_known:
                    entry['reason'] = '正式先修或成果适用关系未确认'
                elif prerequisite_missing:
                    entry['unmetPrerequisites'] = prerequisite_missing
                    entry['reason'] = '存在尚未确认完成的先修，不推断未来必然无法完成'
                elif timely:
                    entry.update(state='satisfied', reason='已找到所核时间内的实际开课，所核先修满足；名额及实际安排另待确认')
                elif coverage.get('offeringsComplete') is True:
                    entry.update(state='unsatisfied', reason='确认的实际开课范围内没有所核时间内的记录；不保证未来不会新增')
                else:
                    entry['reason'] = '没有所核时间内的记录且实际开课覆盖未知，不能判未来无法开课'
            except ValueError:
                entry['reason'] = '实际开课时间或剩余期限数值不明确'
        results.append(entry)
    return {'courses': results, 'counts': {state: sum(row['state'] == state for row in results) for state in STATES},
            'denominator': len(requirements), 'overallFeasible': None, 'capacityConclusion': None,
            'limitations': ['只检查已确认的实际记录和约束；不自动排课、不保证未来名额、无冲突安排或按时毕业']}


def execute_task(task_id, data, purpose='formal', *, trusted_inputs=False):
    if task_id not in TASKS or purpose not in {'formal', 'candidate', 'fixture', 'scenario'}:
        raise ApiError('任务或用途未登记', status_code=422)
    if purpose != 'fixture' and not trusted_inputs:
        return _blocked('未取得经服务端授权及来源校验的结构化输入', task_id, purpose)
    rule = data.get('rule')
    if task_id.startswith(('G-', 'T-', 'R-')) and task_id != 'T-SCHEDULE' and not _rule_ready(rule, 'formal' if purpose == 'scenario' else purpose):
        return _blocked('缺少唯一适用、已确认并允许执行的规则版本', task_id, purpose)
    if task_id == 'T-SCHEDULE':
        result = actual_schedule(data.get('requirements', []), data.get('offerings', []), data.get('prerequisites', []),
                                 set(data.get('completedCourses', [])), data.get('coverage', {}))
    elif task_id in {'T-POLICY', 'T-POLICY-SCENARIO'}:
        changes = data.get('changes', []) if task_id == 'T-POLICY-SCENARIO' else None
        result = transfer_policy(rule, data.get('objects', []), changes)
        result['populationKind'] = data.get('populationKind', 'selected_unknown_origin')
        if result['populationKind'] not in {'actual_application', 'selected', 'hypothetical', 'selected_unknown_origin'}:
            raise ApiError('群体来源性质无效', status_code=422)
    elif task_id == 'G-CHECK' or task_id == 'T-RECOGNITION':
        result = evaluate_group(rule, data['objects']) if 'objects' in data else evaluate_requirements(rule, data.get('achievements', []), data.get('coverage', {}), data.get('objectRef', ''))
        if task_id == 'T-RECOGNITION':
            result['limitations'].append('认定和补修差额不代表转专业录取或安排承诺')
    elif task_id == 'T-REQUIREMENTS':
        if not _rule_ready(data.get('sourceRule'), purpose):
            return _blocked('缺少适用的原方案要求版本', task_id, purpose)
        result = requirements_compare(data['sourceRule'], rule)
    elif task_id == 'R-PREPARE':
        result = prepare_materials(rule, data.get('materials', []), data.get('context', {}))
    elif task_id == 'R-RANK':
        result = rank_objects(rule, data.get('objects', []), data.get('coverage', {}))
    elif task_id in {'R-CHECK', 'R-SCENARIO'}:
        thresholds = data.get('thresholds') if task_id == 'R-SCENARIO' else None
        if task_id == 'R-SCENARIO':
            payload = rule.get('payload', rule)
            allowed = set(payload.get('scenarioAllowedConditionIds', []))
            if not isinstance(thresholds, dict) or not set(thresholds).issubset(allowed):
                return _blocked('假设阈值不在已确认可调整条件范围内', task_id, purpose)
        result = check_values(rule, data.get('objects', []), thresholds)
        if task_id == 'R-SCENARIO':
            result['assumptions'] = deepcopy(thresholds)
            result['formalBaselineUnchanged'] = True
            result['quotaChange'] = None
    elif task_id in {'P-SUPPORT', 'C-SUPPORT'}:
        result = support_mapping(task_id, data.get('documents', []), data.get('mappings', []), data.get('targets', []), data.get('context', {}))
    elif task_id == 'P-PATH':
        result = path_check(data.get('courses', []), data.get('constraints', []), data.get('constraintsConfirmed') is True)
    else:
        courses = deepcopy(data.get('courses', []))
        baseline = deepcopy(courses)
        for change in data.get('changes', []):
            action = change.get('action')
            identity = change.get('courseId')
            if action not in {'add', 'remove', 'update'}:
                raise ApiError('方案变更类型不支持', status_code=422)
            matches = [row for row in courses if row.get('courseId') == identity]
            if action == 'add':
                if matches:
                    raise ApiError('新增课程已存在', status_code=422)
                if not identity or not set(change.get('values', {})).issubset({'semester', 'credits', 'category'}):
                    raise ApiError('新增课程标识或字段无效', status_code=422)
                courses.append({'courseId': identity, **change.get('values', {})})
            else:
                if len(matches) != 1:
                    raise ApiError('待调整课程不存在或不唯一', status_code=422)
                if action == 'remove':
                    courses.remove(matches[0])
                else:
                    if not set(change.get('values', {})).issubset({'semester', 'credits', 'category'}):
                        raise ApiError('课程变更字段不支持', status_code=422)
                    matches[0].update(change['values'])
        result = path_check(courses, data.get('constraints', []), data.get('constraintsConfirmed') is True)
        result.update(baselineCourses=baseline, assumptions=deepcopy(data.get('changes', [])), formalBaselineUnchanged=True)
        before = {row['courseId']: row for row in baseline}
        after = {row['courseId']: row for row in courses}
        result['courseChanges'] = {'added': sorted(set(after) - set(before)), 'removed': sorted(set(before) - set(after)),
                                   'modified': sorted(key for key in set(before) & set(after) if before[key] != after[key])}
        result['creditChange'] = None
        if data.get('creditsConfirmed') is True:
            try:
                old_values = [decimal_value(row.get('credits')) for row in baseline]
                new_values = [decimal_value(row.get('credits')) for row in courses]
                if any(v < 0 for v in old_values + new_values):
                    raise ValueError('Negative credits')
                old = sum(old_values, Decimal('0'))
                new = sum(new_values, Decimal('0'))
                result['creditChange'] = {'baseline': decimal_text(old), 'scenario': decimal_text(new), 'delta': decimal_text(new - old)}
            except ValueError:
                result['unknown'].append({'reason': '方案学分字段缺失或冲突，未计算学分变化'})
    return _base(task_id, 'scenario' if task_id in {'R-SCENARIO', 'P-CHANGE', 'T-POLICY-SCENARIO'} and purpose != 'fixture' else purpose, result, data.get('sources', []))

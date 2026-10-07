"""Exact, limited learning-result matching; never determines whole eligibility."""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from backend.api.envelope import ApiError

STATES = ('satisfied', 'unsatisfied', 'unknown', 'not_applicable')


def decimal_value(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Missing numeric value')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('Invalid numeric value') from exc
    if not result.is_finite():
        raise ValueError('Non-finite numeric value')
    return result


def decimal_text(value):
    return format(value, 'f')


def _condition_courses(condition):
    if condition.get('type') == 'course_completion':
        return {condition['courseId']} if condition.get('courseId') else set()
    return set(condition.get('courseIds') or [])


def _cyclic_courses(substitutions):
    graph = defaultdict(set)
    for item in substitutions:
        if item.get('fromCourseId') and item.get('toCourseId'):
            graph[item['fromCourseId']].add(item['toCourseId'])
    cycles = set()
    def visit(node, stack):
        if node in stack:
            cycles.update(stack[stack.index(node):])
            return
        if len(stack) > len(graph):
            return
        for neighbor in graph[node]:
            visit(neighbor, stack + [node])
    for node in list(graph):
        visit(node, [])
    return cycles


def evaluate_requirements(rule, achievements, coverage, object_ref=''):
    """Input rows must be obtained/validated by a trusted server-side adapter.

    rule is a payload or RuleVersion projection. Effective attempts are explicit:
    effective=True, valid=True, passed=True plus an evidence/source reference.
    Missing attempts only prove a shortfall when sourceComplete=True.
    """
    payload = rule.get('payload', rule)
    conditions = payload.get('conditions', [])
    if not isinstance(conditions, list) or not isinstance(achievements, list) or not isinstance(coverage, dict):
        raise ApiError('要求、成果或覆盖结构无效', status_code=422)
    result = {'objectRef': object_ref, 'ruleRef': {'ruleId': payload.get('ruleId'), 'version': payload.get('version')},
              'conditions': [], 'coverage': deepcopy(coverage), 'adopted': [], 'excluded': [],
              'limitations': ['仅核对声明条件，不代表完整毕业、学位、录取或推免资格'], 'wholeEligibility': None}
    grouped = defaultdict(list)
    for index, item in enumerate(achievements):
        if not isinstance(item, dict) or not item.get('courseId'):
            result['excluded'].append({'row': index, 'reason': '成果缺少明确课程标识'})
            continue
        grouped[item['courseId']].append({**deepcopy(item), '_index': index})
    selected = {}
    uncertain = set()
    conflicts = {}
    evidence_courses = defaultdict(set)
    for course, rows in grouped.items():
        for row in rows:
            if row.get('effective') is True and row.get('evidenceId'):
                evidence_courses[row['evidenceId']].add(course)
    duplicated_evidence_courses = set().union(*(courses for courses in evidence_courses.values() if len(courses) > 1)) if evidence_courses else set()
    for course, rows in grouped.items():
        if course in duplicated_evidence_courses:
            uncertain.add(course)
            conflicts[course] = '同一有效成果被映射至多个课程，不能重复计入'
            result['excluded'].extend({'evidenceId': row.get('evidenceId'), 'courseId': course, 'reason': conflicts[course]} for row in rows)
            continue
        effective = [row for row in rows if row.get('effective') is True]
        if len(effective) != 1:
            uncertain.add(course)
            conflicts[course] = '有效成果选择未确认或同课程存在多个有效成果'
            for row in rows:
                result['excluded'].append({'evidenceId': row.get('evidenceId'), 'courseId': course, 'reason': conflicts[course]})
            continue
        row = effective[0]
        for other in rows:
            if other['_index'] != row['_index']:
                result['excluded'].append({'evidenceId': other.get('evidenceId'), 'courseId': course, 'reason': '不是已确认有效成果，不重复计入'})
        if row.get('valid') is not True or not (row.get('validityConfirmed') is True or coverage.get('validityConfirmed') is True):
            uncertain.add(course)
            conflicts[course] = '成果有效性尚未确认'
            continue
        if not row.get('evidenceId') or not row.get('sourceRef'):
            uncertain.add(course)
            conflicts[course] = '成果缺少来源定位'
            continue
        if row.get('passed') is True:
            selected[course] = row
        elif row.get('passed') is not False or not coverage.get('sourceComplete'):
            uncertain.add(course)
            conflicts[course] = '成绩状态或其他尝试覆盖未知'
        else:
            result['excluded'].append({'evidenceId': row['evidenceId'], 'courseId': course, 'reason': '确认有效成果未通过'})
    memberships = defaultdict(list)
    for condition in conditions:
        for course in _condition_courses(condition):
            memberships[course].append(condition.get('conditionId'))
    allocations = payload.get('allocations') or {}
    overlaps = {course for course, ids in memberships.items() if len(ids) > 1 and allocations.get(course) not in ids}
    cycles = _cyclic_courses(payload.get('substitutions') or [])
    # Noncyclic substitution chains are also not inferred without explicit recognition.
    substitution_courses = {x.get(k) for x in payload.get('substitutions', []) for k in ('fromCourseId', 'toCourseId')}
    for condition in conditions:
        courses = _condition_courses(condition)
        entry = {'objectRef': object_ref, 'conditionId': condition.get('conditionId'), 'category': condition.get('category'),
                 'ruleRef': result['ruleRef'], 'type': condition.get('type'), 'state': 'unknown',
                 'required': None, 'observed': None, 'gap': None, 'matchedEvidence': [], 'reason': ''}
        if condition.get('applicable') is False:
            entry.update(state='not_applicable', reason='条件明确不适用于此对象')
        elif condition.get('type') not in {'course_completion', 'credit_pool'} or not courses:
            entry['reason'] = '要求类型尚不支持或课程范围不明确'
        elif courses & (overlaps | cycles):
            entry['reason'] = '课程成果分配重叠未确认或替代链循环'
        elif courses & substitution_courses and not condition.get('recognitionConfirmed'):
            entry['reason'] = '课程替代关系需正式认定，不自动沿替代链匹配'
        else:
            allocated_courses = {course for course in courses if course not in allocations or allocations[course] == condition.get('conditionId')}
            matches = [selected[course] for course in sorted(allocated_courses) if course in selected]
            unknown_courses = courses & uncertain
            entry['matchedEvidence'] = [row['evidenceId'] for row in matches]
            if condition['type'] == 'course_completion':
                entry.update(required='完成指定课程', observed=bool(matches))
                if matches:
                    entry.update(state='satisfied', reason='已匹配确认有效且通过的课程成果')
                elif unknown_courses or not coverage.get('sourceComplete'):
                    entry.update(observed=None, reason='未找到可采用成果，来源或有效性覆盖尚不完整')
                else:
                    entry.update(state='unsatisfied', reason='完整成果范围内没有满足要求的有效通过成果')
            else:
                try:
                    threshold = decimal_value(condition.get('minCredits'))
                    if threshold < 0:
                        raise ValueError('Negative threshold')
                    credits = []
                    for row in matches:
                        if not (row.get('creditsConfirmed') is True or coverage.get('creditsConfirmed') is True) or row.get('creditConflict'):
                            raise ValueError('Credit basis unavailable')
                        value = decimal_value(row.get('credits'))
                        if value < 0:
                            raise ValueError('Negative credits')
                        credits.append(value)
                    total = sum(credits, Decimal('0'))
                    entry.update(required=decimal_text(threshold), observed=decimal_text(total), unit='credits')
                    if total >= threshold:
                        entry.update(state='satisfied', gap='0', reason='确认有效成果已达到独立课程池最低学分')
                    elif unknown_courses or not coverage.get('sourceComplete'):
                        entry.update(reason='已知学分不足但来源或有效性未完整，不确定最终差额')
                    else:
                        entry.update(state='unsatisfied', gap=decimal_text(threshold - total), reason='完整成果范围内独立课程池学分不足')
                except ValueError:
                    entry.update(observed=None, reason='学分来源、数值或要求阈值未确认/冲突')
            for row in matches:
                if entry['state'] != 'unknown':
                    result['adopted'].append({'conditionId': entry['conditionId'], 'courseId': row['courseId'],
                                              'evidenceId': row['evidenceId'], 'sourceRef': row['sourceRef']})
        result['conditions'].append(entry)
    result['counts'] = {state: sum(c['state'] == state for c in result['conditions']) for state in STATES}
    return result


def evaluate_group(rule, objects):
    """One stable objectRef per student; duplicate objects rejected rather than doubled."""
    ids = [obj.get('objectRef') for obj in objects]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ApiError('群体对象标识缺失或重复', status_code=422)
    results = [evaluate_requirements(rule, obj.get('achievements', []), obj.get('coverage', {}), obj['objectRef']) for obj in objects]
    object_states = {}
    for value in results:
        states = [condition['state'] for condition in value['conditions']]
        state = 'unsatisfied' if 'unsatisfied' in states else 'unknown' if 'unknown' in states or not states else 'satisfied' if 'satisfied' in states else 'not_applicable'
        object_states[value['objectRef']] = state
    return {'objects': results, 'denominator': len(objects),
            'objectCounts': {state: sum(value == state for value in object_states.values()) for state in STATES},
            'affectedObjectRefs': sorted(key for key, value in object_states.items() if value in {'unsatisfied', 'unknown'}),
            'wholeEligibility': None, 'limitations': ['群体统计仅针对所核条件，未知未剔除，不代表整体资格通过率']}

"""Server-owned, non-formal candidate examples for the fixed matching contract."""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from backend.api.envelope import ApiError
from . import matching, rules, store


def run(rule_id, version, revision, actor):
    rule = rules.get_rule(rule_id, version, actor)
    if rule['revision'] != revision:
        raise ApiError('规则已变化，请刷新', code=409, status_code=409)
    payload = rule['payload']
    cases = []
    # Each independent requirement has a hand-built satisfied/unknown/shortfall
    # oracle. The fixtures test the processor, not the school's policy approval.
    for condition in payload['conditions']:
        kind = condition.get('type')
        if kind not in {'course_completion', 'credit_pool'}:
            raise ApiError('当前匹配器尚未支持此条件，请完善处理器后测试', status_code=409)
        courses = [condition.get('courseId')] if kind == 'course_completion' else condition.get('courseIds', [])
        if not courses or not all(courses):
            raise ApiError('条件课程范围不明确', status_code=422)
        threshold = matching.decimal_value(condition.get('minCredits', 1))
        if threshold < 0:
            raise ApiError('条件最低学分不能为负数', status_code=422)
        sample = {'courseId': courses[0], 'effective': True, 'valid': True, 'passed': True,
                  'credits': str(threshold), 'evidenceId': 'candidate:' + str(uuid4()),
                  'sourceRef': {'name': '独立候选案例', 'locator': condition['conditionId']}}
        one = {**deepcopy(payload), 'conditions': [deepcopy(condition)], 'substitutions': [], 'allocations': {}}
        coverage = {'sourceComplete': True, 'validityConfirmed': True, 'creditsConfirmed': True}
        expected = 'not_applicable' if condition.get('applicable') is False else 'satisfied'
        result = matching.evaluate_requirements(one, [sample], coverage)
        passed = result['conditions'][0]['state'] == expected
        cases.append({'caseId': condition['conditionId'] + ':known', 'expected': expected, 'passed': passed})
        result = matching.evaluate_requirements(one, [], {'sourceComplete': False})
        expected = 'not_applicable' if condition.get('applicable') is False else 'satisfied' if kind == 'credit_pool' and threshold == 0 else 'unknown'
        cases.append({'caseId': condition['conditionId'] + ':unknown', 'expected': expected,
                      'passed': result['conditions'][0]['state'] == expected})
        result = matching.evaluate_requirements(one, [], coverage)
        expected = 'not_applicable' if condition.get('applicable') is False else 'satisfied' if kind == 'credit_pool' and threshold == 0 else 'unsatisfied'
        cases.append({'caseId': condition['conditionId'] + ':complete_empty', 'expected': expected,
                      'passed': result['conditions'][0]['state'] == expected})
    passed = bool(cases) and all(case['passed'] for case in cases)
    run_id = str(uuid4())
    fingerprint = rules.processor_fingerprint()
    owner, identity, scope = store._identity(actor)
    ref = {'ruleId': rule_id, 'version': version, 'revision': revision, 'payloadHash': rule['payloadHash']}
    outcome = {'status': 'passed' if passed else 'failed', 'summary': '固定匹配器候选案例核对完成',
               'result': {'executionPurpose': 'candidate', 'cases': cases,
                          'limitations': ['候选案例只核对计算行为，不能替代学校规则确认或真实成果验证']}}
    with store._db(write=True) as db:
        db.execute('INSERT INTO er_run VALUES (?,?,?,?,?,?,?,?,?,?,?)', (run_id, 'rules', rule_id, revision,
                   owner, identity, scope, store._json({'ruleRef': ref}),
                   store._json({'processorFingerprint': fingerprint}), store._json(outcome), store._now()))
    return rules.record_test(rule_id, version, revision, actor, {'testRunId': run_id,
                             'processorFingerprint': fingerprint, 'caseRefs': [case['caseId'] for case in cases]})

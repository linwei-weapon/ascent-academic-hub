"""Policy versions and append-only business issues, separate from conversation turns.

The actor is supplied by the existing trusted identity dependency. Confirmation
permissions never follow from system.manage. Database creation is explicit.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4
from pathlib import Path

from backend.api.envelope import ApiError
from backend.api.permission_context import has_action


def _store():
    from . import store
    return store


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def payload_hash(payload):
    return 'sha256:' + hashlib.sha256(_json(payload).encode()).hexdigest()


def processor_fingerprint():
    digest = hashlib.sha256()
    for name in ('matching.py', 'policy_tasks.py'):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return 'sha256:' + digest.hexdigest()


def initialize():
    with _store()._db(write=True) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS er_rule_version (
            rule_id TEXT NOT NULL, version TEXT NOT NULL, revision INTEGER NOT NULL,
            domain TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
            payload_hash TEXT NOT NULL, confirmation TEXT, test_record TEXT,
            history TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(rule_id,version))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS er_issue_event (
            id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES er_research(id),
            issue_id TEXT NOT NULL, ordinal INTEGER NOT NULL, event_type TEXT NOT NULL,
            payload TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(research_id,issue_id,ordinal))''')


def _permission(actor, action):
    _store()._identity(actor)
    if not has_action(actor, action):
        raise ApiError('当前身份没有规则操作权限：' + action, code=403, status_code=403)


def _confirmation_scope(actor, payload):
    context = actor.get('permission_context') or {}
    scope = context.get('policyConfirmationScope') or context.get('detailScope') or {}
    if scope.get('type') == 'all':
        return
    organizations = payload.get('applicability', {}).get('organizations')
    allowed = {str(value) for value in scope.get('collegeIds', [])}
    if scope.get('type') != 'college' or not organizations or not {str(value) for value in organizations}.issubset(allowed):
        raise ApiError('规则适用组织不在当前业务确认授权范围内', code=403, status_code=403)


def validate_payload(payload):
    if not isinstance(payload, dict) or len(_json(payload).encode()) > 150_000:
        raise ApiError('规则结构无效或超过150KB', status_code=422)
    for key in ('ruleId', 'version', 'domain', 'applicability', 'conditions', 'sources'):
        if key not in payload:
            raise ApiError('规则缺少字段：' + key, status_code=422)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(payload['ruleId'])):
        raise ApiError('规则标识格式无效', status_code=422)
    if not re.fullmatch(r'\d+\.\d+\.\d+', str(payload['version'])):
        raise ApiError('规则版本格式应为1.0.0', status_code=422)
    if not isinstance(payload['domain'], str) or not payload['domain']:
        raise ApiError('规则domain不能为空', status_code=422)
    scope = payload['applicability']
    if not isinstance(scope, dict) or not scope or any(not isinstance(v, list) or not v for v in scope.values()):
        raise ApiError('适用年度、组织、方案须提供明确非空列表', status_code=422)
    if not set(scope).issubset({'years', 'organizations', 'programs', 'cohorts'}):
        raise ApiError('规则适用字段不支持', status_code=422)
    if not isinstance(payload['conditions'], list) or not payload['conditions']:
        raise ApiError('规则条件不能为空', status_code=422)
    ids = []
    for condition in payload['conditions']:
        if not isinstance(condition, dict) or not condition.get('conditionId') or not condition.get('type'):
            raise ApiError('条件须有conditionId和type', status_code=422)
        ids.append(condition['conditionId'])
        if condition.get('category') not in {'graduation', 'degree', 'transfer', 'recommendation', 'support'}:
            raise ApiError('条件category无效', status_code=422)
    if len(ids) != len(set(ids)):
        raise ApiError('规则条件标识重复', status_code=422)
    if not isinstance(payload['sources'], list):
        raise ApiError('sources须为来源定位列表', status_code=422)
    skills = payload.get('skillIds', [])
    if not isinstance(skills, list) or any(not isinstance(value, str) or not value for value in skills) or len(set(skills)) != len(skills):
        raise ApiError('规则关联技能须为不重复标识列表', status_code=422)
    return deepcopy(payload)


def _skill_refs(conn, payload):
    for skill_id in payload.get('skillIds', []):
        _store()._row(conn, 'skills', skill_id)


def _row(conn, rule_id, version, revision=None):
    row = conn.execute('SELECT * FROM er_rule_version WHERE rule_id=? AND version=?', (rule_id, version)).fetchone()
    if not row:
        raise ApiError('规则版本不存在', code=404, status_code=404)
    if revision is not None and row['revision'] != revision:
        raise ApiError('规则已变化，请重新读取', code=409, status_code=409)
    return row


def _view(row):
    return {'ruleId': row['rule_id'], 'version': row['version'], 'revision': row['revision'],
            'domain': row['domain'], 'state': row['state'], 'payload': json.loads(row['payload']),
            'payloadHash': row['payload_hash'], 'confirmation': json.loads(row['confirmation']) if row['confirmation'] else None,
            'test': json.loads(row['test_record']) if row['test_record'] else None,
            'history': json.loads(row['history']), 'createdAt': row['created_at'], 'updatedAt': row['updated_at']}


def create_rule(payload, actor):
    _permission(actor, 'system.manage')
    payload = validate_payload(payload)
    with _store()._db(write=True) as conn:
        _skill_refs(conn, payload)
        if conn.execute('SELECT 1 FROM er_rule_version WHERE rule_id=? AND version=?', (payload['ruleId'], payload['version'])).fetchone():
            raise ApiError('规则版本已存在', code=409, status_code=409)
        now = _now()
        conn.execute('INSERT INTO er_rule_version VALUES (?,?,1,?,?,?,?,NULL,NULL,?,?,?,?)',
                     (payload['ruleId'], payload['version'], payload['domain'], 'draft', _json(payload), payload_hash(payload),
                      _json([{'event': 'created', 'actor': actor['username'], 'at': now}]), actor['username'], now, now))
        return _view(_row(conn, payload['ruleId'], payload['version']))


def get_rule(rule_id, version, actor=None):
    if actor is not None:
        from .auth import require_use
        require_use(actor)
    with _store()._db() as conn:
        return _view(_row(conn, rule_id, version))


def list_rules(actor=None):
    if actor is not None:
        from .auth import require_use
        require_use(actor)
    with _store()._db() as conn:
        return {'items': [_view(row) for row in conn.execute('SELECT * FROM er_rule_version ORDER BY rule_id,version')]}


def _change(conn, row, actor, event, state, **values):
    history = json.loads(row['history'])
    history.append({'event': event, 'actor': actor['username'], 'at': _now(), 'revision': row['revision'],
                    'payloadHash': row['payload_hash'], 'confirmation': json.loads(row['confirmation']) if row['confirmation'] else None,
                    'test': json.loads(row['test_record']) if row['test_record'] else None,
                    'reason': values.pop('reason', '')})
    updates = {'state': state, 'history': _json(history), 'updated_at': _now(), **values}
    allowed = {'state', 'history', 'updated_at', 'payload', 'payload_hash', 'revision', 'confirmation', 'test_record'}
    if not set(updates).issubset(allowed):
        raise ValueError('Unsupported rule update')
    conn.execute('UPDATE er_rule_version SET ' + ','.join(key + '=?' for key in updates) + ' WHERE rule_id=? AND version=?',
                 (*updates.values(), row['rule_id'], row['version']))
    return _view(_row(conn, row['rule_id'], row['version']))


def update_rule(rule_id, version, revision, payload, actor):
    _permission(actor, 'system.manage')
    payload = validate_payload(payload)
    if (payload['ruleId'], payload['version']) != (rule_id, version):
        raise ApiError('规则标识和版本不可修改', status_code=422)
    with _store()._db(write=True) as conn:
        row = _row(conn, rule_id, version, revision)
        _skill_refs(conn, payload)
        if row['state'] in {'published', 'withdrawn'}:
            raise ApiError('发布后的规则内容不可覆盖，请新建版本', code=409, status_code=409)
        if payload['domain'] != row['domain']:
            raise ApiError('规则domain不可在同版本修改', status_code=422)
        return _change(conn, row, actor, 'edited', 'draft', payload=_json(payload), payload_hash=payload_hash(payload),
                       revision=revision + 1, confirmation=None, test_record=None)


def confirm_rule(rule_id, version, revision, actor, confirmation, accepted=True):
    if not isinstance(confirmation, dict):
        raise ApiError('业务确认记录结构无效', status_code=422)
    external = confirmation.get('mode') == 'external'
    _permission(actor, 'policy.confirm.import' if external else 'policy.confirm')
    if not isinstance(confirmation, dict) or not confirmation.get('note'):
        raise ApiError('请填写业务确认意见', status_code=422)
    if external and not all(confirmation.get(key) for key in ('businessConfirmer', 'sourceRef', 'confirmedAt')):
        raise ApiError('外部确认须有实际确认人、来源定位和确认时间', status_code=422)
    with _store()._db(write=True) as conn:
        row = _row(conn, rule_id, version, revision)
        if row['state'] in {'published', 'withdrawn'}:
            raise ApiError('已发布规则不可重新确认', code=409, status_code=409)
        payload = json.loads(row['payload'])
        _confirmation_scope(actor, payload)
        if not payload['sources']:
            raise ApiError('缺少原文来源定位，不能确认学校规则', status_code=422)
        record = {**deepcopy(confirmation), 'accepted': bool(accepted), 'revision': revision, 'payloadHash': row['payload_hash'],
                  'applicability': payload['applicability'], 'importedBy' if external else 'confirmedBy': actor['username'],
                  'recordedAt': _now()}
        return _change(conn, row, actor, 'confirmed' if accepted else 'rejected', 'confirmed' if accepted else 'draft',
                       confirmation=_json(record), test_record=None, reason=confirmation['note'])


def record_test(rule_id, version, revision, actor, test_record):
    """Trusted candidate runner supplies record; do not expose arbitrary passed flags."""
    _permission(actor, 'system.manage')
    if not isinstance(test_record, dict) or not all(test_record.get(k) for k in ('testRunId', 'processorFingerprint', 'caseRefs')):
        raise ApiError('候选测试须有运行引用、处理器指纹和独立案例', status_code=422)
    with _store()._db(write=True) as conn:
        row = _row(conn, rule_id, version, revision)
        if row['state'] in {'published', 'withdrawn'}:
            raise ApiError('已发布版本不允许改测试记录', code=409, status_code=409)
        run = conn.execute('SELECT * FROM er_run WHERE id=?', (test_record['testRunId'],)).fetchone()
        if not run or not _store()._owns(run, actor):
            raise ApiError('候选测试运行不存在或当前身份无权读取', code=409, status_code=409)
        run_input = json.loads(run['input'])
        ref = run_input.get('ruleRef') or {}
        expected = {'ruleId': rule_id, 'version': version, 'revision': revision, 'payloadHash': row['payload_hash']}
        if run['kind'] != 'rules' or run['resource_id'] != rule_id or run['revision'] != revision or ref != expected:
            raise ApiError('测试运行不对应当前规则及固定内容', code=409, status_code=409)
        dependencies = json.loads(run['dependencies'])
        if dependencies.get('processorFingerprint') != test_record['processorFingerprint']:
            raise ApiError('处理器指纹与实际测试不一致', code=409, status_code=409)
        outcome = json.loads(run['outcome'])
        record = {**deepcopy(test_record), 'passed': outcome.get('status') == 'passed',
                  'revision': revision, 'payloadHash': row['payload_hash'], 'recordedAt': _now()}
        return _change(conn, row, actor, 'tested', row['state'], test_record=_json(record))


def publish_rule(rule_id, version, revision, actor):
    _permission(actor, 'system.manage')
    with _store()._db(write=True) as conn:
        row = _row(conn, rule_id, version, revision)
        confirmation = json.loads(row['confirmation']) if row['confirmation'] else {}
        test = json.loads(row['test_record']) if row['test_record'] else {}
        if row['state'] != 'confirmed' or not confirmation.get('accepted') or not test.get('passed'):
            raise ApiError('规则须业务确认并通过当前候选测试后发布', code=409, status_code=409)
        if any(r.get('revision') != revision or r.get('payloadHash') != row['payload_hash'] for r in (confirmation, test)):
            raise ApiError('确认或测试不对应当前规则', code=409, status_code=409)
        if test.get('processorFingerprint') != processor_fingerprint():
            raise ApiError('规则处理器已变化，请重新执行候选测试', code=409, status_code=409)
        return _change(conn, row, actor, 'published', 'published')


def withdraw_rule(rule_id, version, revision, actor, reason):
    _permission(actor, 'system.manage')
    if not reason or not reason.strip():
        raise ApiError('请填写撤回原因', status_code=422)
    with _store()._db(write=True) as conn:
        row = _row(conn, rule_id, version, revision)
        if row['state'] != 'published':
            raise ApiError('只有已发布规则可以撤回', code=409, status_code=409)
        return _change(conn, row, actor, 'withdrawn', 'withdrawn', reason=reason)


def select_rule(domain, context, actor=None, rule_refs=None, purpose='formal'):
    if purpose not in {'formal', 'candidate', 'fixture'}:
        raise ApiError('规则使用用途无效', status_code=422)
    candidates = list_rules(actor)['items']
    keys = {'years': 'year', 'organizations': 'organization', 'programs': 'program', 'cohorts': 'cohort'}
    matching = []
    for rule in candidates:
        if rule_refs is not None and not any(ref.get('ruleId') == rule['ruleId'] and ref.get('version') == rule['version'] for ref in rule_refs):
            continue
        if rule['domain'] != domain or (purpose == 'formal' and rule['state'] != 'published'):
            continue
        if rule['state'] == 'withdrawn':
            continue
        scope = rule['payload']['applicability']
        if all(context.get(keys[k]) is not None and str(context[keys[k]]) in {str(value) for value in values} for k, values in scope.items()):
            matching.append(rule)
    if len(matching) != 1:
        raise ApiError('没有唯一适用规则，需确认年度、组织及方案关系', code=409, status_code=409)
    return matching[0]


def append_issue_event(research_id, issue_id, event, actor, *, trusted_recheck=False):
    _store()._identity(actor)
    types = {'opened', 'submitted', 'rejected', 'confirmed', 'rule_published', 'rechecked', 'reopened', 'deferred', 'scope_corrected'}
    kind = event.get('type')
    if kind not in types or not issue_id or len(_json(event).encode()) > 50_000:
        raise ApiError('事项事件无效', status_code=422)
    if kind == 'rechecked' and (not trusted_recheck or not event.get('resultRef') or not event.get('originalTurnId')):
        raise ApiError('事项须由受控重核结果引用原问题后解决', code=409, status_code=409)
    with _store()._db(write=True) as conn:
        _store()._research_row(conn, research_id, actor)
        previous = conn.execute('SELECT * FROM er_issue_event WHERE research_id=? AND issue_id=? ORDER BY ordinal DESC LIMIT 1',
                                (research_id, issue_id)).fetchone()
        if not previous and kind != 'opened':
            raise ApiError('事项不存在，先登记原问题', code=404, status_code=404)
        if previous and kind == 'opened':
            raise ApiError('事项已存在', code=409, status_code=409)
        if 'revision' in event and (not previous or event['revision'] != previous['ordinal']):
            raise ApiError('事项已有新记录，请刷新', code=409, status_code=409)
        if kind in {'deferred', 'scope_corrected', 'reopened'} and not event.get('reason', '').strip():
            raise ApiError('请填写本次处理说明', status_code=422)
        if kind == 'submitted' and not isinstance(event.get('sourceRef'), dict):
            raise ApiError('补充依据须有来源定位', status_code=422)
        if kind == 'opened':
            turn_id = event.get('originalTurnId')
            if not turn_id or not conn.execute('SELECT 1 FROM er_turn WHERE id=? AND research_id=?', (turn_id, research_id)).fetchone():
                raise ApiError('事项须引用本研究的实际原问题轮次', code=409, status_code=409)
        if kind == 'rechecked':
            original = conn.execute('SELECT payload FROM er_issue_event WHERE research_id=? AND issue_id=? AND ordinal=1',
                                    (research_id, issue_id)).fetchone()
            if event.get('originalTurnId') != json.loads(original['payload']).get('originalTurnId'):
                raise ApiError('重核必须引用该事项的原问题', code=409, status_code=409)
        ordinal = previous['ordinal'] + 1 if previous else 1
        conn.execute('INSERT INTO er_issue_event VALUES (?,?,?,?,?,?,?,?)', (str(uuid4()), research_id, issue_id, ordinal,
                     kind, _json(event), actor['username'], _now()))
    return next(issue for issue in list_issues(research_id, actor)['items'] if issue['issueId'] == issue_id)


def list_issues(research_id, actor):
    with _store()._db() as conn:
        _store()._research_row(conn, research_id, actor)
        events = conn.execute('SELECT * FROM er_issue_event WHERE research_id=? ORDER BY issue_id,ordinal', (research_id,)).fetchall()
        issues = {}
        turn_context = {}
        for row in events:
            event = json.loads(row['payload'])
            issue = issues.setdefault(row['issue_id'], {'issueId': row['issue_id'], 'preparationState': 'missing',
                                                       'resolutionState': 'open', 'events': []})
            issue['revision'] = row['ordinal']
            if row['event_type'] == 'opened':
                issue.update({key: event.get(key) for key in ('originalTurnId', 'title', 'summary', 'reason', 'neededEvidence')})
                issue['title'] = issue['title'] or event.get('requiredEvidence') or '待明确的数据依据'
                issue['neededEvidence'] = issue['neededEvidence'] or event.get('requiredEvidence')
                turn_id = event.get('originalTurnId')
                if turn_id and turn_id not in turn_context:
                    saved = conn.execute('SELECT outcome FROM er_turn WHERE id=? AND research_id=?', (turn_id, research_id)).fetchone()
                    result = (json.loads(saved['outcome']).get('result') or {}) if saved else {}
                    facts = {fact.get('factId'): fact for fact in result.get('facts', [])}
                    courses = {str(record.get('course_id')): record.get('course_name') for evidence in result.get('evidence', [])
                               for record in evidence.get('records', []) if record.get('course_id')}
                    turn_context[turn_id] = (facts, courses)
                facts, courses = turn_context.get(turn_id, ({}, {}))
                course_ids = {str((facts.get(ref, {}).get('objectRef') or {}).get('course_id'))
                              for ref in event.get('affectedFacts', [])
                              if (facts.get(ref, {}).get('objectRef') or {}).get('course_id')}
                if len(course_ids) == 1:
                    course_id = next(iter(course_ids))
                    issue['title'] = f"课程{courses.get(course_id) or course_id}：{issue['title']}"
            issue['events'].append({**event, 'eventId': row['id'], 'ordinal': row['ordinal'], 'at': row['created_at']})
            if row['event_type'] in {'submitted', 'confirmed', 'rule_published', 'rejected'}:
                issue['preparationState'] = {'submitted': 'submitted', 'confirmed': 'confirmed', 'rule_published': 'published', 'rejected': 'rejected'}[row['event_type']]
            if row['event_type'] == 'rechecked':
                issue['resolutionState'] = 'resolved' if event.get('resolved') is True and event.get('requiredEvidenceComplete') is True else 'open'
                issue['lastRecheck'] = event
            if row['event_type'] == 'reopened':
                issue['resolutionState'] = 'open'
            if row['event_type'] == 'deferred':
                issue['preparationState'] = 'deferred'
        return {'items': list(issues.values())}

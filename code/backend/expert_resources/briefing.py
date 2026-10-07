"""Expert preset tasks and organization publications over the existing results.

Presets are configuration, executions own immutable facts, publications control
shared consumption. Reading a publication never runs a task or reconstructs a
historical database batch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy
import hashlib
import json
import math
import re
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo

from backend.api.envelope import ApiError
from . import store, processing
from .auth import require_use

FIELDS = {'id', 'name', 'question', 'expertId', 'taskId', 'input', 'scope', 'collegeMeaning',
          'serviceId', 'schedule', 'activeWindow', 'grantId', 'expectedRevision'}


def initialize():
    with store._db(write=True) as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS er_brief_preset (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, content TEXT NOT NULL,
            signature TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
            trial_execution_id TEXT, deleted_at TEXT, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS er_brief_publication (
            id TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE, revision INTEGER NOT NULL,
            preset_id TEXT NOT NULL REFERENCES er_brief_preset(id), preset_revision INTEGER NOT NULL,
            analysis_signature TEXT NOT NULL, result_id TEXT NOT NULL UNIQUE REFERENCES er_execution(id),
            semester_id TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL,
            reason TEXT, withdrawn_by TEXT, withdrawn_at TEXT, published_at TEXT NOT NULL,
            replaces_id TEXT, explanations TEXT NOT NULL DEFAULT '[]');
          CREATE TABLE IF NOT EXISTS er_brief_operation (
            id TEXT PRIMARY KEY, object_id TEXT NOT NULL, request_id TEXT NOT NULL,
            owner TEXT NOT NULL, identity_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
            execution_id TEXT, created_at TEXT NOT NULL,
            UNIQUE(object_id,owner,identity_id,request_id));
          CREATE TABLE IF NOT EXISTS er_brief_trigger (
            preset_id TEXT NOT NULL, preset_revision INTEGER NOT NULL,
            trigger_key TEXT NOT NULL, state TEXT NOT NULL, execution_id TEXT,
            period TEXT NOT NULL, queued_at TEXT NOT NULL,
            PRIMARY KEY(preset_id,trigger_key));
          CREATE INDEX IF NOT EXISTS er_brief_publication_scope ON er_brief_publication(preset_id,semester_id,sequence);
        ''')


def _row(db, pid):
    row = db.execute('SELECT * FROM er_brief_preset WHERE id=? AND deleted_at IS NULL', (pid,)).fetchone()
    if not row:
        raise ApiError('预设任务不存在或已删除', code=404, status_code=404)
    return row


def _authorize_content(content, actor, manager=False):
    (processing.publication_manager if manager else require_use)(actor)
    return processing.normalize_scope(content['scope'], actor)


def _dependency(db, content):
    expert = store._version(db, 'experts', content['expertId'])
    store._live_dependencies(db, expert['id'], expert['version'], expert['dependencies'])
    from .tasks import resolve_task
    resolve_task(content['taskId'], expert['content'], expert['dependencies'])
    return expert


def analysis_signature(content, expert):
    # Scheduling, names and display limits do not change the calculation cohort.
    payload = {'taskId': content['taskId'], 'expertId': content['expertId'],
               'expertVersion': expert['version'], 'dependencies': expert['dependencies'],
               'input': {k: v for k, v in content['input'].items() if k not in {'previewLimit', 'limit'}},
               'scope': content['scope'], 'collegeMeaning': content['collegeMeaning'],
               'metricMapping': mapping_condition(),
               'environment': processing.effective()['environment']}
    return hashlib.sha256(store._json(payload).encode()).hexdigest()


def mapping_condition():
    from backend.metric_verification.mapping_store import get_head
    try:
        head = get_head(module_id='ai-briefing')
        return {'moduleId': 'ai-briefing', 'revisionId': head.get('revisionId')}
    except Exception:
        return {'moduleId': 'ai-briefing', 'revisionId': None, 'availability': 'unknown'}


def _content(body, actor, previous=None):
    if set(body) - FIELDS:
        raise ApiError('预设任务包含未支持字段', status_code=422)
    value = {**(previous or {}), **{k: v for k, v in body.items() if k not in {'id', 'expectedRevision'}}}
    value.pop('_pauseReason', None)
    for key in ('name', 'question', 'expertId', 'taskId', 'input'):
        if not value.get(key):
            raise ApiError('请填写业务名称、问题、专家、任务及实际范围', status_code=422)
    if len(str(value['name'])) > 200 or len(str(value['question'])) > 4000:
        raise ApiError('名称或问题过长', status_code=422)
    if value['taskId'] != 'C-PERFORMANCE' or value.get('serviceId', processing.SERVICE_ID) != processing.SERVICE_ID:
        raise ApiError('首期预设简报只支持课程首修表现', status_code=422)
    inputs = deepcopy(value['input'])
    if not isinstance(inputs, dict) or not inputs.get('semester_id') or inputs.get('course_id'):
        raise ApiError('请选择真实学期；简报须按完整授权范围计算，不能限定单门课程', status_code=422)
    from .tasks import definition
    from jsonschema import Draft202012Validator
    schema = definition('C-PERFORMANCE')['inputSchema']
    cleaned = {k: v for k, v in inputs.items() if k != 'taskId' and v not in (None, '')}
    if list(Draft202012Validator(schema).iter_errors(cleaned)):
        raise ApiError('任务输入未符合课程分析契约', status_code=422)
    cid = str(inputs.get('college_id') or '')
    derived = {'type': 'college', 'collegeIds': [cid]} if cid else {'type': 'all', 'collegeIds': []}
    scope = processing.normalize_scope(value.get('scope', derived), actor)
    if scope != derived:
        raise ApiError('发布范围须与开课学院查询范围一致', status_code=422)
    if value.get('collegeMeaning', 'course_opening') != 'course_opening':
        raise ApiError('当前任务的学院含义为开课学院', status_code=422)
    value.update(input=cleaned, scope=scope, collegeMeaning='course_opening', serviceId=processing.SERVICE_ID)
    value.setdefault('schedule', None)
    value.setdefault('activeWindow', None)
    value.setdefault('grantId', None)
    return value


def _view(db, row, actor=None):
    content = json.loads(row['content'])
    latest = db.execute('SELECT * FROM er_execution WHERE preset_id=? ORDER BY created_at DESC LIMIT 1', (row['id'],)).fetchone()
    if latest and latest['purpose'] == 'briefing_trial' and actor and (latest['owner'], latest['identity_id'], latest['scope_fingerprint']) != store._identity(actor):
        latest = None
    if latest and actor:
        try:
            processing.normalize_scope(json.loads(latest['request'])['_scope'], actor)
        except ApiError:
            latest = None
    from .execution import _view as execution_view
    signature = row['signature']
    valid = False
    try:
        signature = analysis_signature(content, _dependency(db, content))
        trial = db.execute('SELECT * FROM er_execution WHERE id=?', (row['trial_execution_id'],)).fetchone()
        valid = bool(trial and trial['state'] in {'completed', 'partial'} and
                     json.loads(trial['request']).get('_analysisSignature') == signature)
    except ApiError:
        pass
    publications = db.execute("SELECT * FROM er_brief_publication WHERE preset_id=? AND status='published' ORDER BY sequence DESC", (row['id'],)).fetchall()
    current = next((p for p in publications if p['analysis_signature'] == signature), None)
    return {**content, 'id': row['id'], 'presetId': row['id'], 'revision': row['revision'],
            'automaticPauseReason': content.get('_pauseReason'),
            'enabled': bool(row['enabled']), 'analysisSignature': signature, 'trialExecutionId': row['trial_execution_id'],
            'trialValid': valid, 'currentPublicationId': current['id'] if current else None,
            'latestExecution': execution_view(db, latest) if latest else None,
            'canDelete': not bool(latest or publications), 'updatedAt': row['updated_at']}


def presets(actor, expert_id=None):
    processing.publication_manager(actor)
    with store._db() as db:
        rows = db.execute('SELECT * FROM er_brief_preset WHERE deleted_at IS NULL ORDER BY updated_at DESC').fetchall()
        items = []
        for row in rows:
            content = json.loads(row['content'])
            if expert_id and content['expertId'] != expert_id:
                continue
            try:
                _authorize_content(content, actor)
                items.append(_view(db, row, actor))
            except ApiError:
                continue
    return {'items': items, 'total': len(items)}


def save(body, actor, pid=None):
    processing.publication_manager(actor)
    with store._db(write=True) as db:
        previous = _row(db, pid) if pid else None
        if previous:
            processing._revision(previous, body.get('expectedRevision'))
            _authorize_content(json.loads(previous['content']), actor)
        content = _content(body, actor, json.loads(previous['content']) if previous else None)
        expert = _dependency(db, content)
        signature = analysis_signature(content, expert)
        pid = pid or body.get('id') or str(uuid4())
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', pid):
            raise ApiError('预设任务编号格式无效', status_code=422)
        if previous:
            keep_enabled = bool(previous['enabled'] and signature == previous['signature'])
            if previous['enabled'] and not keep_enabled:
                content['_pauseReason'] = '分析条件已改变，暂停自动执行；请完成当前条件试跑后重新启用'
            if keep_enabled:
                old_content = json.loads(previous['content'])
                if any(old_content.get(k) != content.get(k) for k in ('schedule', 'activeWindow', 'grantId')):
                    try:
                        _auto_ready(content, datetime.now(timezone.utc))
                    except ApiError as exc:
                        keep_enabled = False
                        content['_pauseReason'] = '运行条件未通过重新检查：' + exc.msg
            db.execute('UPDATE er_brief_preset SET content=?,signature=?,revision=revision+1,enabled=?,updated_by=?,updated_at=? WHERE id=?',
                       (store._json(content), signature, int(keep_enabled), actor['username'], store._now(), pid))
        else:
            if db.execute('SELECT 1 FROM er_brief_preset WHERE id=?', (pid,)).fetchone():
                raise ApiError('预设任务编号已存在', code=409, status_code=409)
            db.execute('INSERT INTO er_brief_preset VALUES (?,1,?,?,0,NULL,NULL,?,?)',
                       (pid, store._json(content), signature, actor['username'], store._now()))
        processing.audit(db, pid, 'preset_save', actor, {'analysisSignature': signature})
        return _view(db, _row(db, pid), actor)


def remove(pid, expected, actor):
    processing.publication_manager(actor)
    with store._db(write=True) as db:
        row = _row(db, pid)
        processing._revision(row, expected)
        _authorize_content(json.loads(row['content']), actor)
        if db.execute('SELECT 1 FROM er_execution WHERE preset_id=?', (pid,)).fetchone():
            raise ApiError('已运行任务保留历史，请停用自动执行', code=409, status_code=409)
        db.execute('UPDATE er_brief_preset SET deleted_at=?,enabled=0,revision=revision+1 WHERE id=?', (store._now(), pid))
        processing.audit(db, pid, 'preset_delete', actor, {})
    return {'deleted': True, 'id': pid}


def _uuid(value):
    try:
        UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ApiError('请求编号须为UUID', status_code=422) from None


def _active(db, pid):
    return db.execute("SELECT 1 FROM er_execution WHERE preset_id=? AND (state IN ('queued','running') OR worker_finished=0)", (pid,)).fetchone()


def _submit(db, row, actor, operation, request_id, replace=None, trigger=None):
    from . import execution
    processing.ensure_ready()
    content = json.loads(row['content'])
    expert = _dependency(db, content)
    signature = analysis_signature(content, expert)
    if operation != 'trial':
        trial = db.execute('SELECT * FROM er_execution WHERE id=?', (row['trial_execution_id'],)).fetchone()
        if not trial or trial['state'] not in {'completed', 'partial'} or json.loads(trial['request']).get('_analysisSignature') != signature:
            raise ApiError('请先按当前分析条件完成真实试跑', code=409, status_code=409)
        outcome = json.loads(db.execute('SELECT outcome FROM er_turn WHERE id=?', (trial['turn_id'],)).fetchone()['outcome'])
        if (outcome.get('result') or {}).get('publishMode') == 'blocked':
            raise ApiError('试跑存在确定计算冲突，不能生成正式简报', code=409, status_code=409)
    if _active(db, row['id']):
        raise ApiError('该预设任务仍占用执行名额，请等待事实及解释工作结束', code=409, status_code=409)
    if replace:
        original = db.execute('SELECT * FROM er_brief_publication WHERE id=?', (replace,)).fetchone()
        if not original or original['preset_id'] != row['id'] or original['semester_id'] != str(content['input']['semester_id']) or json.loads(original['scope']) != content['scope']:
            raise ApiError('修正须关联同任务、学期及学院的已有发布', code=409, status_code=409)
    cfg = processing.effective()
    request = {'clientRequestId': request_id, 'expertId': content['expertId'], 'mode': 'selected_task',
               'expectedTurn': 0, 'question': content['question'], 'input': {**content['input'], 'taskId': content['taskId']},
               '_purpose': 'briefing_trial' if operation == 'trial' else 'briefing',
               '_presetId': row['id'], '_presetRevision': row['revision'], '_analysisSignature': signature,
               '_scope': content['scope'], '_principalKind': actor.get('principalKind', 'verified_user'),
               '_grantId': actor.get('grantId'), '_serviceConfigRevision': cfg['revision'],
               '_timeoutSeconds': cfg['timeoutSeconds'], '_retryLimit': cfg['retryLimit'],
               '_trigger': trigger or 'manual', '_replacesPublicationId': replace}
    if actor.get('principalKind') == 'registered_service':
        request['_activeWindow'] = deepcopy(content.get('activeWindow'))
    view = execution.submit(request, actor, start=False, internal=True, db_override=db)
    if operation == 'trial':
        db.execute('UPDATE er_brief_preset SET trial_execution_id=? WHERE id=?', (view['executionId'], row['id']))
    return view


def execute(pid, body, actor, authorization='', identity='', operation='trial'):
    processing.publication_manager(actor)
    processing.ensure_ready()
    _uuid(body.get('clientRequestId'))
    request_hash = hashlib.sha256(store._json([operation, body]).encode()).hexdigest()
    owner, iid, _ = store._identity(actor)
    from . import execution
    with store._db(write=True) as db:
        row = _row(db, pid)
        _authorize_content(json.loads(row['content']), actor)
        previous = db.execute('SELECT * FROM er_brief_operation WHERE object_id=? AND owner=? AND identity_id=? AND request_id=?',
                              (pid, owner, iid, body['clientRequestId'])).fetchone()
        if previous:
            if previous['payload_hash'] != request_hash:
                raise ApiError('相同请求编号不能改变动作或内容', code=409, status_code=409)
            return execution._view(db, execution._row(db, previous['execution_id']))
        processing._revision(row, body.get('expectedRevision'))
        view = _submit(db, row, actor, operation, body['clientRequestId'], body.get('replacesPublicationId'))
        db.execute('INSERT INTO er_brief_operation VALUES (?,?,?,?,?,?,?,?)', (str(uuid4()), pid, body['clientRequestId'], owner, iid, request_hash, view['executionId'], store._now()))
        processing.audit(db, pid, operation, actor, {'executionId': view['executionId']})
    execution.start_execution(view['executionId'], actor, authorization, identity)
    return view


def schedule_due(content, now):
    schedule = content.get('schedule') or {}
    try:
        zone = ZoneInfo('Asia/Shanghai')
    except __import__('zoneinfo').ZoneInfoNotFoundError:
        # The approved single-zone schedules use current China standard time;
        # Windows installations need not install another timezone runtime.
        zone = timezone(timedelta(hours=8), 'Asia/Shanghai')
    local = now.astimezone(zone)
    if schedule.get('kind') == 'test_interval':
        return 'test:' + str(int(now.timestamp() // 300)), str(content['input']['semester_id'])
    weekday = schedule.get('weekday')
    clock = schedule.get('time', '')
    if type(weekday) is not int or weekday not in range(7) or not re.fullmatch(r'\d{2}:\d{2}', clock):
        raise ApiError('请选择每周日期及有效时间', status_code=422)
    hour, minute = map(int, clock.split(':'))
    if hour > 23 or minute > 59:
        raise ApiError('每周时间无效', status_code=422)
    start = local.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(days=(local.weekday() - weekday) % 7)
    if start > local:
        start -= timedelta(days=7)
    return 'weekly:' + start.isoformat(), str(content['input']['semester_id'])


def _auto_ready(content, now):
    cfg = processing.effective()
    if not cfg['automaticEnabled']:
        raise ApiError('后台处理服务尚未开启自动执行', code=409, status_code=409)
    schedule = content.get('schedule') or {}
    if schedule.get('timezone', 'Asia/Shanghai') != 'Asia/Shanghai' or schedule.get('kind') not in {'weekly', 'test_interval'}:
        raise ApiError('请配置每周周期及上海时区', status_code=422)
    if schedule.get('kind') == 'test_interval' and (schedule.get('intervalMinutes') != 5 or cfg['environment'] != 'test-114'):
        raise ApiError('临时验证周期仅允许测试环境5分钟', status_code=422)
    try:
        window = content['activeWindow']
        start, end = (datetime.fromisoformat(window[k].replace('Z', '+00:00')) for k in ('start', 'end'))
        if start.tzinfo is None or end.tzinfo is None or not start <= now < end:
            raise ValueError()
        if schedule['kind'] == 'test_interval' and (end - start).total_seconds() > 3600:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ApiError('请配置当前生效窗口；临时验证窗口最多1小时', code=409, status_code=409) from None
    schedule_due(content, now)
    return processing.service_actor(content.get('grantId'), content['taskId'], content['scope'])


def validate_start_window(request, now):
    """Check the frozen window when queued service work claims its slot."""
    try:
        window = request['_activeWindow']
        start, end = (datetime.fromisoformat(window[k].replace('Z', '+00:00')) for k in ('start', 'end'))
        if start.tzinfo is None or end.tzinfo is None or not start <= now < end:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ApiError('该自动任务的生效窗口已结束，未启动执行', code=409, status_code=409) from None


def enable(pid, body, actor):
    processing.publication_manager(actor)
    processing.ensure_ready()
    _uuid(body.get('clientRequestId'))
    from . import execution
    now = datetime.now(timezone.utc)
    # Slow connectivity checks precede the short local write transaction.
    with store._db() as db:
        preview = _row(db, pid)
        _authorize_content(json.loads(preview['content']), actor)
        processing._revision(preview, body.get('expectedRevision'))
        _auto_ready(json.loads(preview['content']), now)
    processing.check_connections()
    with store._db(write=True) as db:
        row = _row(db, pid)
        _authorize_content(json.loads(row['content']), actor)
        key = 'initial:' + str(row['revision'])
        old = db.execute('SELECT * FROM er_brief_trigger WHERE preset_id=? AND trigger_key=?', (pid, key)).fetchone()
        processing._revision(row, body.get('expectedRevision'))
        content = json.loads(row['content'])
        service = _auto_ready(content, now)
        if old:
            db.execute('UPDATE er_brief_preset SET enabled=1 WHERE id=?', (pid,))
            processing.audit(db, pid, 'resume_automatic', actor, {'initialExecutionId': old['execution_id']})
            return execution._view(db, execution._row(db, old['execution_id']))
        rid = str(uuid5(NAMESPACE_URL, 'expert-initial:' + pid + ':' + str(row['revision'])))
        view = _submit(db, row, service, 'run', rid, trigger=key)
        db.execute('INSERT INTO er_brief_trigger VALUES (?,?,?, ?,?,?,?)',
                   (pid, row['revision'], key, 'submitted', view['executionId'], str(content['input']['semester_id']), store._now()))
        db.execute('UPDATE er_brief_preset SET enabled=1 WHERE id=?', (pid,))
        anchor, period = schedule_due(content, now)
        db.execute("INSERT OR IGNORE INTO er_brief_trigger VALUES (?,?,?,'initial_anchor',?,?,?)", (pid, row['revision'], anchor, view['executionId'], period, store._now()))
        processing.audit(db, pid, 'enable', actor, {'executionId': view['executionId']})
    execution.start_execution(view['executionId'], service)
    return view


def pause(pid, expected, actor):
    processing.publication_manager(actor)
    with store._db(write=True) as db:
        row = _row(db, pid)
        processing._revision(row, expected)
        _authorize_content(json.loads(row['content']), actor)
        db.execute('UPDATE er_brief_preset SET enabled=0 WHERE id=?', (pid,))
        db.execute("UPDATE er_brief_trigger SET state='cancelled' WHERE preset_id=? AND state='pending'", (pid,))
        processing.audit(db, pid, 'pause', actor, {})
        return _view(db, _row(db, pid), actor)


def due():
    processing.ensure_ready()
    if not processing.effective()['automaticEnabled']:
        return
    from . import execution
    now = datetime.now(timezone.utc)
    with store._db() as db:
        ids = [r['id'] for r in db.execute('SELECT id FROM er_brief_preset WHERE enabled=1 AND deleted_at IS NULL')]
    for pid in ids:
        try:
            with store._db(write=True) as db:
                row = _row(db, pid)
                content = json.loads(row['content'])
                service = _auto_ready(content, now)
                key, period = schedule_due(content, now)
                start = datetime.fromisoformat(content['activeWindow']['start'].replace('Z', '+00:00'))
                # Weekly schedule doesn't backfill events preceding the active window.
                if key.startswith('weekly:') and datetime.fromisoformat(key[7:]) < start:
                    continue
                trigger = db.execute('SELECT * FROM er_brief_trigger WHERE preset_id=? AND trigger_key=?', (pid, key)).fetchone()
                if trigger and trigger['state'] != 'pending':
                    continue
                if _active(db, pid):
                    # Collapse missed due events to one current pending trigger.
                    db.execute("DELETE FROM er_brief_trigger WHERE preset_id=? AND state='pending' AND trigger_key<>?", (pid, key))
                    db.execute("INSERT OR IGNORE INTO er_brief_trigger VALUES (?,?,?,'pending',NULL,?,?)", (pid, row['revision'], key, period, store._now()))
                    continue
                rid = str(uuid5(NAMESPACE_URL, 'expert-due:' + pid + ':' + key))
                view = _submit(db, row, service, 'run', rid, trigger=key)
                db.execute("INSERT INTO er_brief_trigger VALUES (?,?,?,'submitted',?,?,?) ON CONFLICT(preset_id,trigger_key) DO UPDATE SET state='submitted',execution_id=excluded.execution_id", (pid, row['revision'], key, view['executionId'], period, store._now()))
            execution.start_execution(view['executionId'], service)
        except ApiError as exc:
            with store._db(write=True) as db:
                processing.audit(db, pid, 'due_blocked', {'username': 'service'}, {'reason': exc.msg})
                if exc.status_code in {403, 409}:
                    current = _row(db, pid)
                    value = json.loads(current['content'])
                    value['_pauseReason'] = '自动执行条件不再有效：' + exc.msg
                    db.execute('UPDATE er_brief_preset SET enabled=0,content=? WHERE id=?', (store._json(value), pid))


def recover_registered():
    """Retry current interrupted service work once, never restore human tokens."""
    if not processing.effective()['automaticEnabled']:
        return
    from . import execution
    now = datetime.now(timezone.utc)
    with store._db() as db:
        interrupted = db.execute("SELECT * FROM er_execution WHERE principal_kind='registered_service' AND failure_code='interrupted_auth_lost' AND purpose='briefing' ORDER BY created_at DESC").fetchall()
    for old in interrupted:
        try:
            with store._db(write=True) as db:
                request = json.loads(old['request'])
                if str(request.get('_trigger', '')).startswith('recovery:'):
                    continue
                preset = _row(db, old['preset_id'])
                if not preset['enabled'] or preset['revision'] != request.get('_presetRevision'):
                    continue
                content = json.loads(preset['content'])
                service = _auto_ready(content, now)
                start = datetime.fromisoformat(content['activeWindow']['start'].replace('Z', '+00:00'))
                if datetime.fromisoformat(old['created_at']) < start:
                    continue
                current_key, period = schedule_due(content, now)
                if request['_trigger'] != current_key and not request['_trigger'].startswith('initial:'):
                    continue
                key = 'recovery:' + old['id']
                if db.execute('SELECT 1 FROM er_brief_trigger WHERE preset_id=? AND trigger_key=?', (preset['id'], key)).fetchone():
                    continue
                rid = str(uuid5(NAMESPACE_URL, 'expert-recovery:' + old['id']))
                run = _submit(db, preset, service, 'run', rid, trigger=key)
                db.execute("INSERT INTO er_brief_trigger VALUES (?,?,?,'submitted',?,?,?)", (preset['id'], preset['revision'], key, run['id'], period, store._now()))
                processing.audit(db, preset['id'], 'recover_current_once', service, {'originalExecutionId': old['id'], 'executionId': run['id']})
            execution.start_execution(run['id'], service)
        except ApiError:
            # Expired windows, lost permissions or incompatible versions are
            # preserved as interrupted history; they are not replayed.
            continue


def publish_in_transaction(db, row, saved, actor):
    request = json.loads(row['request'])
    if request.get('_purpose') != 'briefing' or row['state'] not in {'queued', 'running'}:
        return None
    content = json.loads(_row(db, request['_presetId'])['content'])
    if actor.get('principalKind') == 'registered_service':
        processing.service_actor(request['_grantId'], row['task_id'], request['_scope'])
    else:
        processing.publication_manager(actor)
        processing.normalize_scope(request['_scope'], actor)
    result = saved.get('result') or {}
    mode = result.get('publishMode')
    basis = result.get('validationBasis') or {}
    if mode not in {'observation', 'facts_only'}:
        raise ApiError('本次结果未通过正式发布准入，请查看试跑核验依据', code=409, status_code=409)
    from .course_observation import publication_gate
    decision = publication_gate(basis, supported_raw_facts=bool(result.get('evidence') or result.get('facts')))
    if mode == 'observation' and decision['publishMode'] != 'observation':
        raise ApiError('观察指标缺少本次复算或已登记口径依据', code=409, status_code=409)
    if decision['publishMode'] == 'blocked':
        raise ApiError('本次核验依据存在确定冲突，停止正式发布', code=409, status_code=409)
    pid = str(uuid4())
    sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 n FROM er_brief_publication').fetchone()['n']
    now = store._now()
    db.execute('INSERT INTO er_brief_publication (id,sequence,revision,preset_id,preset_revision,analysis_signature,result_id,semester_id,scope,status,published_at,replaces_id) VALUES (?,?,1,?,?,?,?,?,?,\'published\',?,?)',
               (pid, sequence, request['_presetId'], request['_presetRevision'], request['_analysisSignature'], row['id'],
                str((request['input'])['semester_id']), store._json(request['_scope']), now, request.get('_replacesPublicationId')))
    saved['publicationId'] = pid
    result['publicationId'] = pid
    result['publicationSequence'] = sequence
    processing.audit(db, pid, 'publish', actor, {'executionId': row['id'], 'publishMode': mode})
    return pid


def _publication(db, publication_id, actor, valid=False):
    require_use(actor)
    row = db.execute('SELECT * FROM er_brief_publication WHERE id=?', (publication_id,)).fetchone()
    if not row:
        raise ApiError('简报不存在', code=404, status_code=404)
    processing.normalize_scope(json.loads(row['scope']), actor)
    if valid and row['status'] != 'published':
        raise ApiError('该简报已撤回或失效，不能作为有效分析依据', code=409, status_code=409)
    return row


def _publication_view(db, row, actor):
    from . import execution
    er = execution._row(db, row['result_id'])
    saved = json.loads(db.execute('SELECT outcome FROM er_turn WHERE id=?', (er['turn_id'],)).fetchone()['outcome'])
    preset = db.execute('SELECT * FROM er_brief_preset WHERE id=?', (row['preset_id'],)).fetchone()
    signature = preset['signature'] if preset else ''
    explanations = json.loads(row['explanations'])
    applicable = row['status'] == 'published'
    try:
        signature = analysis_signature(json.loads(preset['content']), _dependency(db, json.loads(preset['content'])))
    except (ApiError, TypeError):
        signature = None
    return {'id': row['id'], 'publicationId': row['id'], 'publicationSequence': row['sequence'], 'revision': row['revision'],
            'presetId': row['preset_id'], 'presetRevision': row['preset_revision'], 'analysisSignature': row['analysis_signature'],
            'name': json.loads(preset['content'])['name'] if preset else '历史简报', 'resultId': row['result_id'],
            'semesterId': row['semester_id'], 'scope': json.loads(row['scope']), 'status': row['status'], 'state': row['status'],
            'applicable': applicable, 'currentAnalysisConditions': row['analysis_signature'] == signature,
            'withdrawReason': row['reason'], 'withdrawnAt': row['withdrawn_at'], 'publishedAt': row['published_at'],
            'replacesPublicationId': row['replaces_id'], 'outcome': execution._public_outcome(saved),
            'run': execution._view(db, er),
            'explanationState': er['explanation_state'], 'explanationVersion': len(explanations), 'explanations': explanations,
            'workerFinished': bool(er['worker_finished'])}


def publications(actor, semester_id=None, college_id=None, history=False, offset=0, limit=20):
    require_use(actor)
    with store._db() as db:
        rows = db.execute('SELECT * FROM er_brief_publication ORDER BY sequence DESC').fetchall()
        items, seen = [], set()
        for row in rows:
            if semester_id and row['semester_id'] != semester_id:
                continue
            scope = json.loads(row['scope'])
            if college_id and (scope['type'] != 'college' or scope['collegeIds'] != [college_id]):
                continue
            try:
                processing.normalize_scope(scope, actor)
            except ApiError:
                continue
            if not history:
                key = (row['preset_id'], row['semester_id'], row['scope'])
                if row['status'] != 'published' or key in seen:
                    continue
                view = _publication_view(db, row, actor)
                if not view['currentAnalysisConditions']:
                    continue
                seen.add(key)
            items.append(row)
        return {'items': [_publication_view(db, r, actor) for r in items[offset:offset + limit]],
                'total': len(items), 'offset': offset, 'limit': limit,
                'publicationSequence': max((r['sequence'] for r in rows), default=0)}


def publication(publication_id, actor):
    with store._db() as db:
        return _publication_view(db, _publication(db, publication_id, actor), actor)


def withdraw(publication_id, body, actor):
    processing.publication_manager(actor)
    _uuid(body.get('clientRequestId'))
    reason = str(body.get('reason') or '').strip()
    if not reason or len(reason) > 4000:
        raise ApiError('请填写撤回原因', status_code=422)
    digest = hashlib.sha256(store._json(body).encode()).hexdigest()
    owner, identity, _ = store._identity(actor)
    with store._db(write=True) as db:
        row = _publication(db, publication_id, actor)
        old = db.execute('SELECT * FROM er_brief_operation WHERE object_id=? AND request_id=? AND owner=? AND identity_id=?', (publication_id, body['clientRequestId'], owner, identity)).fetchone()
        if old:
            if old['payload_hash'] != digest:
                raise ApiError('相同请求编号不能改变撤回内容', code=409, status_code=409)
            return _publication_view(db, row, actor)
        processing._revision(row, body.get('expectedRevision'))
        if row['status'] != 'published':
            raise ApiError('该简报已经撤回或失效', code=409, status_code=409)
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 n FROM er_brief_publication').fetchone()['n']
        db.execute("UPDATE er_brief_publication SET status='withdrawn',revision=revision+1,sequence=?,reason=?,withdrawn_by=?,withdrawn_at=? WHERE id=?", (sequence, reason, owner, store._now(), publication_id))
        db.execute('INSERT INTO er_brief_operation VALUES (?,?,?,?,?,?,NULL,?)', (str(uuid4()), publication_id, body['clientRequestId'], owner, identity, digest, store._now()))
        processing.audit(db, publication_id, 'withdraw', actor, {'reason': reason})
        return _publication_view(db, _publication(db, publication_id, actor), actor)


def evidence(publication_id, evidence_id, actor, offset=0, limit=20):
    with store._db() as db:
        row = _publication(db, publication_id, actor)
        er = db.execute('SELECT * FROM er_execution WHERE id=?', (row['result_id'],)).fetchone()
        outcome = json.loads(db.execute('SELECT outcome FROM er_turn WHERE id=?', (er['turn_id'],)).fetchone()['outcome'])
    selected = next((e for e in (outcome.get('result') or {}).get('evidence', []) if e.get('evidenceId') == evidence_id), None)
    if selected is None:
        raise ApiError('该简报未留存此证据', code=404, status_code=404)
    records = selected.get('records') or []
    return {**{k: v for k, v in selected.items() if k != 'records'}, 'publicationStatus': row['status'],
            'totalRows': len(records), 'returnedRows': len(records[offset:offset + limit]), 'offset': offset,
            'rows': records[offset:offset + limit]}


def executions(pid, actor, offset=0, limit=20):
    processing.publication_manager(actor)
    from . import execution
    with store._db() as db:
        preset = _row(db, pid)
        _authorize_content(json.loads(preset['content']), actor)
        rows = db.execute('SELECT * FROM er_execution WHERE preset_id=? ORDER BY created_at DESC', (pid,)).fetchall()
        owner, identity, fingerprint = store._identity(actor)
        allowed = []
        for r in rows:
            try:
                processing.normalize_scope(json.loads(r['request'])['_scope'], actor)
            except ApiError:
                continue
            if r['purpose'] == 'briefing' or (r['owner'], r['identity_id'], r['scope_fingerprint']) == (owner, identity, fingerprint):
                allowed.append(r)
        rows = allowed
        return {'items': [execution._view(db, r) for r in rows[offset:offset + limit]], 'total': len(rows), 'offset': offset, 'limit': limit}


def candidate_evidence(pid, execution_id, evidence_id, actor, offset=0, limit=20):
    processing.publication_manager(actor)
    from . import execution
    with store._db() as db:
        preset = _row(db, pid)
        _authorize_content(json.loads(preset['content']), actor)
        row = execution._row(db, execution_id)
        if row['preset_id'] != pid or row['purpose'] != 'briefing_trial' or (row['owner'], row['identity_id'], row['scope_fingerprint']) != store._identity(actor):
            raise ApiError('该候选结果不属于当前维护身份', code=404, status_code=404)
        if row['state'] not in {'completed', 'partial'}:
            raise ApiError('候选结果尚未保存', code=404, status_code=404)
        saved = json.loads(db.execute('SELECT outcome FROM er_turn WHERE id=?', (row['turn_id'],)).fetchone()['outcome'])
    selected = next((e for e in (saved.get('result') or {}).get('evidence', []) if e.get('evidenceId') == evidence_id), None)
    if selected is None:
        raise ApiError('未留存此证据', code=404, status_code=404)
    records = selected.get('records') or []
    return {**{k: v for k, v in selected.items() if k != 'records'}, 'totalRows': len(records),
            'returnedRows': len(records[offset:offset + limit]), 'rows': records[offset:offset + limit], 'offset': offset}


def service_executions(actor, offset=0, limit=20):
    processing.publication_manager(actor)
    from . import execution
    owner = store._identity(actor)
    with store._db() as db:
        rows = db.execute("SELECT * FROM er_execution WHERE purpose IN ('briefing','briefing_trial') ORDER BY created_at DESC").fetchall()
        permitted = []
        for row in rows:
            try:
                processing.normalize_scope(json.loads(row['request'])['_scope'], actor)
            except ApiError:
                continue
            if row['purpose'] == 'briefing_trial' and (row['owner'], row['identity_id'], row['scope_fingerprint']) != owner:
                continue
            permitted.append(row)
        return {'items': [execution._view(db, row) for row in permitted[offset:offset + limit]],
                'total': len(permitted), 'offset': offset, 'limit': limit}


def resolve_reference(request, actor):
    """Server-owned saved facts; caller cannot supply payloads or replace scope."""
    from . import execution
    with store._db() as db:
        if request.get('publicationId'):
            publication = _publication(db, request['publicationId'], actor, valid=True)
            rid = publication['result_id']
            if request.get('sourceResultId') and request['sourceResultId'] != rid:
                raise ApiError('结果不属于该简报', code=409, status_code=409)
            er = execution._row(db, rid)
            saved = json.loads(db.execute('SELECT outcome FROM er_turn WHERE id=?', (er['turn_id'],)).fetchone()['outcome'])
        elif request.get('sourceResultId'):
            saved = execution._saved(db, request['sourceResultId'], actor)
        else:
            raise ApiError('保存读取须指定已保存结果', status_code=422)
        publication_ref = _reference_publication(db, request, actor)
        if publication_ref:
            saved['sourcePublicationRef'] = publication_ref
            if saved.get('result'):
                saved['result']['sourcePublicationRef'] = publication_ref
    result = saved.get('result') or {}
    object_id = request.get('objectId')
    if object_id:
        source = [e for e in result.get('evidence', []) if e.get('records')]
        if not any(str(r.get('course_id')) == object_id for e in source for r in e['records']):
            raise ApiError('课程不属于该结果留存集合', code=404, status_code=404)
        selected = next(((index, row) for index, row in enumerate(result.get('observations') or [])
                         if str(row.get('course_id')) == object_id), None)
        baseline = result.get('observationBaseline') or {}
        if selected and result.get('publishMode') == 'observation':
            index, row = selected
            text = (f"{row.get('course_name') or object_id}在该次保存结果中，首修人次N={row['first_attempts']}，"
                    f"首修通过人次P={row['first_pass']}，首修未通过人次U={row['first_unpassed']}；"
                    f"首修通过率显示为{row['first_pass_pct']}%，同范围参照显示为{baseline.get('ratePct')}%。"
                    '该次计算按原始比例比较，确认U>0且课程通过率低于同范围参照，因此进入观察集合。'
                    f"它是已保存观察集合的第{index+1}条，共{len(result['observations'])}条；"
                    '按首修未通过人次降序、原始通过率升序及课程编码排序。'
                    '显示百分比经过舍入，选入和排序使用原始比例。')
            evidence_id = 'course-observations'
        else:
            text = f'课程{object_id}在该次留存数据中，但没有可用的已保存观察选入依据，不能据此认定它进入观察集合。'
            evidence_id = 'course-aggregate-input'
        text += '本说明只解释该次已保存结果；未重新查询数据库，不代表当前状态、课程质量或原因结论。'
        if baseline.get('population'):
            text += '参照范围：' + baseline['population'] + '。'
        if result.get('limitations'):
            text += '适用边界：' + '；'.join(str(item) for item in result['limitations']) + '。'
        result['interpretation'] = {'mode': 'saved_observation', 'text': text,
                                   'objectRef': {'course_id': object_id}, 'evidenceId': evidence_id,
                                   'sourceResultId': result.get('resultId'),
                                   'publicationId': (saved.get('sourcePublicationRef') or {}).get('publicationId')}
    return deepcopy(saved)


def _reference_publication(db, request, actor):
    """Follow persisted server requests; a personal copy cannot clear ancestry."""
    from . import execution
    seen = set()
    while request.get('publicationId') or request.get('sourceResultId'):
        if request.get('publicationId'):
            publication = _publication(db, request['publicationId'], actor, valid=True)
            if request.get('sourceResultId') and request['sourceResultId'] != publication['result_id']:
                raise ApiError('结果不属于该简报', code=409, status_code=409)
            return {'publicationId': publication['id'], 'resultId': publication['result_id']}
        rid = request['sourceResultId']
        if rid in seen or len(seen) >= 50:
            raise ApiError('保存结果的来源关联无法验证', code=409, status_code=409)
        seen.add(rid)
        saved = execution._saved(db, rid, actor)
        ref = saved.get('sourcePublicationRef') or (saved.get('result') or {}).get('sourcePublicationRef')
        if ref:
            publication = _publication(db, ref.get('publicationId'), actor, valid=True)
            if ref.get('resultId') != publication['result_id']:
                raise ApiError('保存结果的简报来源不一致', code=409, status_code=409)
            return {'publicationId': publication['id'], 'resultId': publication['result_id']}
        if rid.startswith('legacy:'):
            row = db.execute('SELECT input FROM er_turn WHERE id=?', (rid[7:],)).fetchone()
            request = json.loads(row['input']) if row else {}
        else:
            request = json.loads(execution._row(db, rid, actor)['request'])
    return None


def append_explanation(db, er, outcome, lease):
    request = json.loads(er['request'])
    pub = db.execute('SELECT * FROM er_brief_publication WHERE result_id=?', (er['id'],)).fetchone()
    explanation = (outcome.get('result') or {}).get('explanation')
    if pub and pub['status'] != 'published':
        return False
    if er['lease'] != lease or er['explanation_state'] in {'completed', 'failed', 'interrupted', 'not_configured', 'budget_exhausted'}:
        return False
    turn = db.execute('SELECT outcome FROM er_turn WHERE id=?', (er['turn_id'],)).fetchone()
    saved = json.loads(turn['outcome'])
    if explanation:
        saved['result']['explanation'] = explanation
        db.execute('UPDATE er_turn SET outcome=? WHERE id=?', (store._json(saved), er['turn_id']))
    state = 'completed' if explanation and explanation.get('mode') == 'validated_references' else 'failed'
    db.execute('UPDATE er_execution SET explanation_state=?,revision=revision+1 WHERE id=? AND lease=?', (state, er['id'], lease))
    if pub:
        versions = json.loads(pub['explanations'])
        versions.append({'version': len(versions) + 1, 'state': state, 'explanation': explanation, 'createdAt': store._now()})
        db.execute('UPDATE er_brief_publication SET explanations=?,revision=revision+1 WHERE id=? AND revision=? AND status=\'published\'', (store._json(versions), pub['id'], pub['revision']))
    return True

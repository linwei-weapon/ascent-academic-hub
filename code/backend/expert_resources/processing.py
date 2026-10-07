"""One local processing service, bounded recovery and explicit delegated scope.

The service grant is a local read-only delegation. It is not a school login and
never stores or restores a browser bearer. Business tables remain read-only.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import threading
import time
from uuid import uuid4

from backend.api.envelope import ApiError
from backend.api.permission_context import has_action
from backend.metric_verification.database import connection
from backend.metric_verification.config import environment_name
from . import store
from .auth import require_manage, require_use

SERVICE_ID = 'expert-resources'
INSTANCE = str(uuid4())
_lock_file = None
_stop = threading.Event()
_thread = None
_recovery_lock = threading.RLock()
_state = {'ready': False, 'recoveryState': 'starting', 'blockedWorkers': [], 'heartbeat': None}
DEFAULT = {'serviceId': SERVICE_ID, 'name': '专家分析处理服务', 'environment': 'test-114',
           'dataConfigRef': 'metric-verification', 'modelConfigRef': 'expert-resources',
           'automaticEnabled': False, 'timeoutSeconds': 180, 'retryLimit': 0}


def environment_id():
    return os.getenv('MV_MAPPING_ENVIRONMENT', 'test-114')


def initialize():
    with store._db(write=True) as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS er_processing_config (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, draft TEXT NOT NULL,
            effective TEXT NOT NULL, effective_revision INTEGER NOT NULL,
            check_result TEXT, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS er_service_grant (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, status TEXT NOT NULL,
            scope TEXT NOT NULL, task_ids TEXT NOT NULL, valid_until TEXT NOT NULL,
            granted_by TEXT NOT NULL, granted_identity TEXT NOT NULL, created_at TEXT NOT NULL,
            revoked_at TEXT);
          CREATE TABLE IF NOT EXISTS er_processing_event (
            id TEXT PRIMARY KEY, object_id TEXT NOT NULL, action TEXT NOT NULL,
            actor TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
        db.execute('INSERT OR IGNORE INTO er_processing_config VALUES (?,1,?,?,1,NULL,?,?)',
                   (SERVICE_ID, store._json(DEFAULT), store._json(DEFAULT), 'initial-migration', store._now()))


def audit(db, object_id, action, actor, payload):
    db.execute('INSERT INTO er_processing_event VALUES (?,?,?,?,?,?)',
               (str(uuid4()), object_id, action, actor.get('username', 'service'), store._json(payload), store._now()))


def publication_manager(actor):
    require_manage(actor)
    require_use(actor)
    if not has_action(actor, 'ai.analyze'):
        raise ApiError('当前身份须同时具备管理与AI分析权限', code=403, status_code=403)
    return actor


def normalize_scope(scope, actor):
    context = actor.get('permission_context') or {}
    available = context.get('detailScope') or {}
    if not isinstance(scope, dict) or scope.get('type') not in {'all', 'college'}:
        raise ApiError('请明确全校或开课学院范围', status_code=422)
    ids = sorted(set(str(x) for x in scope.get('collegeIds', []) if str(x)))
    if scope['type'] == 'all':
        if available.get('type') != 'all' or ids:
            raise ApiError('当前身份不能授予或读取全校范围', code=403, status_code=403)
        return {'type': 'all', 'collegeIds': []}
    if not ids or len(ids) > 1:
        raise ApiError('首期请选择一个开课学院', status_code=422)
    allowed = set(str(x) for x in available.get('collegeIds', []))
    if available.get('type') != 'all' and (available.get('type') != 'college' or not set(ids).issubset(allowed)):
        raise ApiError('学院超出当前有效数据范围', code=403, status_code=403)
    return {'type': 'college', 'collegeIds': ids}


def scope_contains(container, requested):
    return container.get('type') == 'all' or (requested.get('type') == 'college' and
           set(requested.get('collegeIds', [])).issubset(set(container.get('collegeIds', []))))


def config_row(db):
    return db.execute('SELECT * FROM er_processing_config WHERE id=?', (SERVICE_ID,)).fetchone()


def effective():
    with store._db() as db:
        row = config_row(db)
        return {**__import__('json').loads(row['effective']), 'revision': row['effective_revision']}


def status():
    return {**_state, 'serviceInstance': INSTANCE, 'pid': os.getpid(),
            'schedulerAlive': bool(_thread and _thread.is_alive() and not _stop.is_set()),
            'hostMustRemainRunning': True, 'deployment': 'local-prototype',
            'interactiveSlots': 2, 'automaticSlots': 1}


def ensure_ready():
    if _stop.is_set() or not _state['ready']:
        raise ApiError('处理服务恢复未完成；请在后台处理服务查看诊断并重新检查', code=503, status_code=503)


def view(actor):
    require_manage(actor)
    import json
    with store._db() as db:
        row = config_row(db)
        grants = [grant_view(r) for r in db.execute('SELECT * FROM er_service_grant ORDER BY created_at DESC')]
    from .model_adapter import available_models
    return {'serviceId': SERVICE_ID, 'revision': row['revision'], 'draft': json.loads(row['draft']),
            'effective': {**json.loads(row['effective']), 'revision': row['effective_revision']},
            'check': json.loads(row['check_result']) if row['check_result'] else None,
            'status': status(), 'grants': grants, 'models': available_models(),
            'dataConfigRefs': [{'id': 'metric-verification', 'environment': environment_name(), 'access': 'read-only'}],
            'modelConfigRefs': [{'id': 'expert-resources', 'available': available_models()['available']}],
            'updatedAt': row['updated_at']}


def _revision(row, expected):
    if row['revision'] != expected:
        raise ApiError('配置已改变，请刷新后再操作', code=409, status_code=409)


def save(body, actor):
    require_manage(actor)
    allowed = set(DEFAULT) | {'expectedRevision'}
    if set(body) - allowed:
        raise ApiError('配置包含未支持字段', status_code=422)
    with store._db(write=True) as db:
        row = config_row(db)
        _revision(row, body.get('expectedRevision'))
        import json
        draft = {**json.loads(row['draft']), **{k: v for k, v in body.items() if k != 'expectedRevision'}}
        if (draft['serviceId'] != SERVICE_ID or draft['environment'] != environment_id()
                or draft['dataConfigRef'] != 'metric-verification' or draft['modelConfigRef'] != 'expert-resources'):
            raise ApiError('只能使用本服务已登记的测试数据及模型配置引用', status_code=422)
        if not isinstance(draft['automaticEnabled'], bool) or not isinstance(draft['name'], str) or not draft['name'].strip():
            raise ApiError('名称及自动执行开关无效', status_code=422)
        if type(draft['timeoutSeconds']) is not int or not 20 <= draft['timeoutSeconds'] <= 300 or type(draft['retryLimit']) is not int or draft['retryLimit'] not in {0, 1}:
            raise ApiError('超时须为20至300秒，瞬时重试为0或1次', status_code=422)
        db.execute('UPDATE er_processing_config SET draft=?,revision=revision+1,check_result=NULL,updated_by=?,updated_at=? WHERE id=?',
                   (store._json(draft), actor['username'], store._now(), SERVICE_ID))
        audit(db, SERVICE_ID, 'save_draft', actor, {'revision': row['revision'] + 1})
    return view(actor)


def check(expected, actor):
    require_manage(actor)
    with store._db() as db:
        row = config_row(db)
        _revision(row, expected)
    checks = []
    for layer in ('source', 'analytics'):
        try:
            with connection(layer, consistent=True) as db, db.cursor() as cursor:
                cursor.execute('SELECT RETAKE,PUBLISHED,PASSED FROM grade LIMIT 0' if layer == 'source' else
                               'SELECT first_attempts,first_pass,course_id,semester_id FROM agg_course_pass_stat LIMIT 0')
                cursor.fetchall()
            checks.append({'source': layer, 'state': 'passed', 'access': 'read-only'})
        except Exception:
            checks.append({'source': layer, 'state': 'failed', 'reason': '连接或只读访问未通过'})
    try:
        with store._db() as db:
            expert = store._version(db, 'experts', 'course')
            store._live_dependencies(db, 'course', expert['version'], expert['dependencies'])
        checks.append({'source': 'C-PERFORMANCE', 'state': 'passed', 'reason': '当前课程专家及冻结依赖可运行'})
    except ApiError:
        checks.append({'source': 'C-PERFORMANCE', 'state': 'failed', 'reason': '课程专家或运行依赖尚未发布／已变化'})
    result = {'revision': expected, 'state': 'passed' if all(c['state'] == 'passed' for c in checks) else 'failed',
              'checks': checks, 'checkedAt': store._now(), 'serviceReady': _state['ready']}
    with store._db(write=True) as db:
        _revision(config_row(db), expected)
        db.execute('UPDATE er_processing_config SET check_result=? WHERE id=?', (store._json(result), SERVICE_ID))
    return result


def check_connections():
    try:
        for layer in ('source', 'analytics'):
            with connection(layer) as db, db.cursor() as cursor:
                cursor.execute('SELECT RETAKE,PUBLISHED,PASSED FROM grade LIMIT 0' if layer == 'source' else
                               'SELECT first_attempts,first_pass,course_id,semester_id FROM agg_course_pass_stat LIMIT 0')
                cursor.fetchall()
    except Exception:
        raise ApiError('启用前真实数据库只读检查未通过，自动任务尚未启用', code=503, status_code=503) from None


def apply(expected, actor):
    require_manage(actor)
    import json
    with store._db(write=True) as db:
        row = config_row(db)
        _revision(row, expected)
        checked = json.loads(row['check_result']) if row['check_result'] else {}
        if checked.get('revision') != expected or checked.get('state') != 'passed':
            raise ApiError('请先完成当前草稿的真实连接检查', code=409, status_code=409)
        if (datetime.now(timezone.utc) - datetime.fromisoformat(checked['checkedAt'])).total_seconds() > 600:
            raise ApiError('连接检查已过期，请重新检查', code=409, status_code=409)
        db.execute('UPDATE er_processing_config SET effective=draft,effective_revision=revision,updated_by=?,updated_at=? WHERE id=?',
                   (actor['username'], store._now(), SERVICE_ID))
        audit(db, SERVICE_ID, 'apply', actor, {'effectiveRevision': expected})
    return view(actor)


def grant_view(row):
    import json
    expired = datetime.now(timezone.utc) >= datetime.fromisoformat(row['valid_until'])
    return {'id': row['id'], 'grantId': row['id'], 'revision': row['revision'],
            'status': 'expired' if expired and row['status'] == 'active' else row['status'],
            'scope': json.loads(row['scope']), 'taskIds': json.loads(row['task_ids']),
            'validUntil': row['valid_until'], 'grantedBy': row['granted_by'], 'createdAt': row['created_at']}


def grant(body, actor):
    publication_manager(actor)
    if set(body) - {'scope', 'taskIds', 'validUntil'} or body.get('taskIds') != ['C-PERFORMANCE']:
        raise ApiError('首期只允许课程首修表现任务', status_code=422)
    scope = normalize_scope(body.get('scope'), actor)
    # Validate the actual selected organization rather than merely an ID string.
    if scope['type'] == 'college':
        with connection('analytics') as db, db.cursor() as cursor:
            cursor.execute('SELECT organization_id FROM act_organization WHERE organization_id=%s AND is_college=1',
                           (scope['collegeIds'][0],))
            if not cursor.fetchone():
                raise ApiError('所选学院不在测试数据库中', status_code=422)
    try:
        until = datetime.fromisoformat(body['validUntil'].replace('Z', '+00:00'))
        if until.tzinfo is None or not 0 < (until - datetime.now(timezone.utc)).total_seconds() <= 90 * 86400:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ApiError('授权有效期须在未来90天内并包含时区', status_code=422) from None
    gid = str(uuid4())
    with store._db(write=True) as db:
        db.execute('INSERT INTO er_service_grant VALUES (?,1,?,?,?,?,?,?,?,NULL)',
                   (gid, 'active', store._json(scope), store._json(body['taskIds']), until.isoformat(),
                    actor['username'], store._identity(actor)[1], store._now()))
        audit(db, gid, 'grant', actor, {'scope': scope, 'validUntil': until.isoformat()})
    return view(actor)


def revoke(gid, expected, actor):
    publication_manager(actor)
    with store._db(write=True) as db:
        row = db.execute('SELECT * FROM er_service_grant WHERE id=?', (gid,)).fetchone()
        if not row:
            raise ApiError('授权不存在', code=404, status_code=404)
        _revision(row, expected)
        normalize_scope(__import__('json').loads(row['scope']), actor)
        db.execute("UPDATE er_service_grant SET status='revoked',revision=revision+1,revoked_at=? WHERE id=?", (store._now(), gid))
        audit(db, gid, 'revoke', actor, {'revision': expected + 1})
    return view(actor)


def renew(gid, expected, valid_until, actor):
    publication_manager(actor)
    try:
        until = datetime.fromisoformat(valid_until.replace('Z', '+00:00'))
        if until.tzinfo is None or not 0 < (until - datetime.now(timezone.utc)).total_seconds() <= 90 * 86400:
            raise ValueError()
    except (TypeError, ValueError):
        raise ApiError('授权有效期须在未来90天内并包含时区', status_code=422) from None
    with store._db(write=True) as db:
        row = db.execute('SELECT * FROM er_service_grant WHERE id=?', (gid,)).fetchone()
        if not row:
            raise ApiError('授权不存在', code=404, status_code=404)
        _revision(row, expected)
        if row['status'] != 'active':
            raise ApiError('撤销的授权不能恢复，请重新登记授权', code=409, status_code=409)
        normalize_scope(__import__('json').loads(row['scope']), actor)
        db.execute('UPDATE er_service_grant SET valid_until=?,revision=revision+1 WHERE id=?', (until.isoformat(), gid))
        audit(db, gid, 'renew', actor, {'validUntil': until.isoformat()})
    return view(actor)


def service_actor(gid, task_id, requested):
    import json
    with store._db() as db:
        row = db.execute('SELECT * FROM er_service_grant WHERE id=?', (gid,)).fetchone()
    if not row or row['status'] != 'active' or datetime.now(timezone.utc) >= datetime.fromisoformat(row['valid_until']):
        raise ApiError('服务授权已过期或撤销', code=403, status_code=403)
    scope = json.loads(row['scope'])
    if task_id not in json.loads(row['task_ids']) or not scope_contains(scope, requested):
        raise ApiError('任务或范围超出登记服务授权', code=403, status_code=403)
    # No system.manage action or administrator role is assigned to this subject.
    identity = 'service-grant:' + gid
    # Extending validity doesn't change the authority of an in-flight task.
    # Status and expiry are still checked on every authorization boundary.
    fingerprint = hashlib.sha256(store._json([gid, scope, sorted(json.loads(row['task_ids']))]).encode()).hexdigest()
    return {'principalKind': 'registered_service', 'username': 'service:' + SERVICE_ID,
            'identity_id': identity, 'grantId': gid, 'permission_context': {'authorized': True,
            'activeIdentityId': identity, 'scopeFingerprint': fingerprint,
            'actionPermissions': ['ai.analyze'], 'detailScope': scope}, 'menus': []}


def process_identity(pid):
    """Creation token for a PID; prevents recycling an unrelated PID as our worker."""
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
            kernel.GetProcessTimes.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return 'uninspectable' if ctypes.get_last_error() == 5 else None
            times = [wintypes.FILETIME() for _ in range(4)]
            try:
                if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                    return 'uninspectable'
                return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
            finally:
                kernel.CloseHandle(handle)
        return Path('/proc', str(pid), 'stat').read_text().split(') ', 1)[1].split()[19]
    except (OSError, ValueError):
        return None


def terminate_owned(pid, created):
    if not created or created == 'uninspectable' or process_identity(pid) != created:
        return False
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x0001, False, int(pid))
            if not handle:
                return False
            try:
                if process_identity(pid) != created:
                    return False
                return bool(kernel.TerminateProcess(handle, 1))
            finally:
                kernel.CloseHandle(handle)
        import signal
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def acquire():
    global _lock_file
    target = store.path().with_suffix('.service.lock')
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = target.open('a+b')
    handle.seek(0)
    if target.stat().st_size == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError('Another expert processing instance owns the control store') from None
    _lock_file = handle


def recover(cleanup=False):
    with _recovery_lock:
        return _recover(cleanup)


def _recover(cleanup=False):
    from . import execution
    if _stop.is_set():
        _state.update(ready=False, recoveryState='stopping')
        return status()
    with store._db() as db:
        rows = db.execute('SELECT id,lease,phase,worker_pid,worker_created,service_instance FROM er_execution WHERE worker_finished=0 AND worker_pid IS NOT NULL').fetchall()
    blocked = []
    for row in rows:
        if row['service_instance'] == INSTANCE:
            with execution._supervisor_lock:
                held = execution._supervisor_active.get(row['id']) == row['lease']
            if held and row['phase'] != 'recovery_blocked':
                continue
        current = process_identity(row['worker_pid'])
        if cleanup and current == row['worker_created'] and current != 'uninspectable':
            terminate_owned(row['worker_pid'], row['worker_created'])
            current = process_identity(row['worker_pid'])
        if current and (current == 'uninspectable' or not row['worker_created'] or current == row['worker_created']):
            blocked.append({'executionId': row['id'], 'pid': row['worker_pid'],
                            'reason': '旧工作进程仍在运行，待现有服务诊断确认退出'})
        elif current is None or current != row['worker_created']:
            with store._db(write=True) as db:
                db.execute("UPDATE er_execution SET worker_finished=1,phase=?,explanation_state=CASE WHEN explanation_state='running' THEN 'interrupted' ELSE explanation_state END WHERE id=?", ('interrupted', row['id']))
            execution._terminal(row['id'], 'failed', '执行进程已退出，请按原条件重新执行', 'interrupted_auth_lost')
    became_ready = not blocked and not _state['ready']
    _state.update(ready=not blocked, recoveryState='blocked' if blocked else 'ready', blockedWorkers=blocked)
    if not blocked:
        execution.recover_interrupted(exclude_instance=INSTANCE)
        if became_ready:
            from .briefing import recover_registered
            recover_registered()
    return status()


def recheck(actor):
    require_manage(actor)
    return recover()


def start():
    global _thread
    _stop.clear()
    deadline = time.monotonic() + 30
    while True:
        state = recover(cleanup=True)
        if state['ready'] or time.monotonic() >= deadline:
            break
        time.sleep(.25)
    def tick():
        from . import briefing
        while not _stop.wait(1):
            _state['heartbeat'] = store._now()
            if int(time.monotonic()) % 30 != 0 or not _state['ready']:
                continue
            try:
                briefing.due()
            except Exception:
                # No credentials or provider errors in health diagnostics.
                _state['lastSchedulerError'] = '周期检查失败，下一周期重查'
    _thread = threading.Thread(target=tick, name='expert-due-checker', daemon=True)
    _thread.start()


def stop():
    global _lock_file
    from . import execution
    with _recovery_lock:
        _stop.set()
        _state.update(ready=False, recoveryState='stopping')
    if _thread:
        _thread.join(2)
    with _recovery_lock, execution._supervisor_lock:
        if (_thread and _thread.is_alive()) or execution._supervisor_active:
            # Preserve exclusive ownership while old work may still finish.
            # The OS releases the handle when this process actually exits.
            return
        if _lock_file:
            _lock_file.close()
            _lock_file = None

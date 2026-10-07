"""Durable, identity-bound analysis with supervised processes and retained evidence.

The browser bearer lives only in the parent process. SQLite holds request/state
and a turn reference; the immutable turn outcome is the only result payload.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import multiprocessing
import os
import threading
import time
from uuid import uuid4
from contextlib import nullcontext

from backend.api.envelope import ApiError
from . import store
from .auth import normalize_actor, require_use
from backend.metric_verification.auth import remote_identity_payload

ACTIVE = {"queued", "running"}
FINAL = {"needs_input", "completed", "partial", "blocked", "failed", "cancelled"}
MAX_BYTES = 5 * 1024 * 1024
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="expert-supervisor")
_automatic_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="expert-automatic")
_credentials: dict[str, tuple[str, str, tuple, float]] = {}
_credentials_lock = threading.Lock()
_init_lock = threading.Lock()
_supervisor_active: dict[str, str] = {}
_supervisor_lock = threading.Lock()


def initialize():
    with _init_lock, store._db(write=True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS er_execution (
          id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES er_research(id),
          turn_id TEXT NOT NULL UNIQUE REFERENCES er_turn(id), owner TEXT NOT NULL,
          identity_id TEXT NOT NULL, scope_fingerprint TEXT NOT NULL,
          client_request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
          state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          task_id TEXT, request TEXT NOT NULL, dependencies TEXT NOT NULL,
          expert_version TEXT NOT NULL, deadline TEXT NOT NULL, lease TEXT,
          failure_code TEXT, summary TEXT NOT NULL, created_at TEXT NOT NULL,
          started_at TEXT, completed_at TEXT,
          UNIQUE(owner,identity_id,client_request_id))""")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS er_execution_active
          ON er_execution(research_id) WHERE state IN ('queued','running')""")
        db.execute("CREATE INDEX IF NOT EXISTS er_execution_owner ON er_execution(owner,identity_id,scope_fingerprint)")
        columns = {r[1] for r in db.execute('PRAGMA table_info(er_execution)')}
        additions = {'purpose': "TEXT NOT NULL DEFAULT 'personal'", 'preset_id': 'TEXT',
                     'principal_kind': "TEXT NOT NULL DEFAULT 'verified_user'",
                     'phase': "TEXT NOT NULL DEFAULT 'queued'", 'worker_finished': 'INTEGER NOT NULL DEFAULT 1',
                     'worker_pid': 'INTEGER', 'worker_created': 'TEXT', 'service_instance': 'TEXT',
                     'explanation_state': "TEXT NOT NULL DEFAULT 'not_requested'"}
        for name, declaration in additions.items():
            if name not in columns:
                db.execute(f'ALTER TABLE er_execution ADD COLUMN {name} {declaration}')
        db.execute('CREATE INDEX IF NOT EXISTS er_execution_preset ON er_execution(preset_id,state,worker_finished)')


def _row(db, execution_id, actor=None):
    row = db.execute("SELECT * FROM er_execution WHERE id=?", (execution_id,)).fetchone()
    if not row or (actor is not None and not store._owns(row, actor)):
        raise ApiError("执行不存在或当前身份无权访问", code=404, status_code=404)
    return row


def _public_outcome(outcome):
    result = deepcopy(outcome)
    for evidence in (result.get("result") or {}).get("evidence", []):
        evidence.pop("records", None)
    return result


def _view(db, row):
    turn = db.execute("SELECT outcome FROM er_turn WHERE id=?", (row["turn_id"],)).fetchone()
    saved = json.loads(turn["outcome"]) if turn else {}
    result_id = (saved.get("result") or {}).get("resultId")
    view = {"id": row["id"], "executionId": row["id"], "researchId": row["research_id"],
            "turnId": row["turn_id"], "taskId": row["task_id"], "state": row["state"],
            "revision": row["revision"], "summary": row["summary"], "failureCode": row["failure_code"],
            "createdAt": row["created_at"], "startedAt": row["started_at"], "completedAt": row["completed_at"],
            "resultId": result_id, "expertId": json.loads(row["request"]).get("expertId"), "expertVersion": row["expert_version"],
            'purpose': row['purpose'], 'presetId': row['preset_id'], 'phase': row['phase'],
            'workerFinished': bool(row['worker_finished']), 'factsState': row['state'],
            'explanationState': row['explanation_state']}
    if row["state"] in FINAL:
        view["outcome"] = _public_outcome(saved)
        if saved.get("clarification"):
            view["clarification"] = saved["clarification"]
    request = json.loads(row['request'])
    public_fields = {'clientRequestId', 'expertId', 'researchId', 'expectedTurn', 'mode', 'question', 'input',
                     'context', 'originalTurnId', 'clarificationId', 'answer', 'retryOfExecutionId', 'expertSelection',
                     'upgradeToVersion', 'readMode', 'publicationId', 'sourceResultId', 'objectId'}
    view['submittedRequest'] = {k: v for k, v in request.items() if k in public_fields}
    view['trigger'] = request.get('_trigger', 'interactive')
    view['principalKind'] = row['principal_kind']
    view['serviceConfigRevision'] = request.get('_serviceConfigRevision')
    return view


def get(execution_id, actor):
    require_use(actor)
    initialize()
    with store._db() as db:
        return _view(db, _row(db, execution_id, actor))


def find(client_request_id, actor, missing_ok=False):
    require_use(actor)
    initialize()
    owner, identity, _ = store._identity(actor)
    with store._db() as db:
        row = db.execute("SELECT * FROM er_execution WHERE owner=? AND identity_id=? AND client_request_id=?",
                         (owner, identity, client_request_id)).fetchone()
        if not row or not store._owns(row, actor):
            if missing_ok:
                return {'found': False}
            raise ApiError("未找到当前身份的请求", code=404, status_code=404)
        view = _view(db, row)
        return {'found': True, 'execution': view} if missing_ok else view


def _frozen(db, request, actor):
    research_id = request.get('researchId')
    expert_id = request.get('expertId')
    version = None
    if research_id:
        research = store._research_row(db,research_id,actor)
        expert_id = expert_id or research['expert_id']
        if request.get('expertSelection','legacy') != 'per_turn':
            if expert_id != research['expert_id']:
                raise ApiError('旧入口的专家不能变更，请使用专家问策',code=409,status_code=409)
            version = research['expert_version']
        else:
            last = db.execute("SELECT e.* FROM er_execution e JOIN er_turn t ON t.id=e.turn_id WHERE e.research_id=? ORDER BY t.ordinal DESC LIMIT 1",(research_id,)).fetchone()
            if last and json.loads(last['request']).get('expertId') == expert_id:
                version = last['expert_version']
            elif not last and expert_id == research['expert_id']:
                version = research['expert_version']
        if request.get('originalTurnId') or request.get('retryOfExecutionId'):
            original = (db.execute('SELECT * FROM er_execution WHERE turn_id=? AND research_id=?',
                        (request['originalTurnId'],research_id)).fetchone() if request.get('originalTurnId')
                        else _row(db,request['retryOfExecutionId'],actor))
            if original:
                original_id=json.loads(original['request']).get('expertId') or research['expert_id']
                if expert_id!=original_id:
                    raise ApiError('原问题须使用当时专家，请先确认原专家',code=409,status_code=409)
                version=original['expert_version']
    if not expert_id:
        raise ApiError('请选择专家',status_code=422)
    if (request.get('retryOfExecutionId') or request.get('mode') == 'clarification_answer') and request.get('upgradeToVersion') not in (None, version):
        raise ApiError('失败重试或澄清须保留原方法版本；请新建分析以使用新版本',code=409,status_code=409)
    version=request.get('upgradeToVersion') or version
    expert=store._version(db,'experts',expert_id,version)
    dependencies=expert['dependencies']
    store._live_dependencies(db,expert_id,expert['version'],dependencies)
    return expert,deepcopy(dependencies)


def submit(request, actor, authorization="", identity="", *, start=True, internal=False, db_override=None):
    require_use(actor)
    if start:
        from .processing import ensure_ready
        ensure_ready()
    if db_override is None:
        initialize()
    request = deepcopy(request)
    if not internal and any(k.startswith('_') for k in request):
        raise ApiError('个人执行不接受服务主体、用途或授权注入', status_code=422)
    saved_reference = None
    if request.get('publicationId') or request.get('sourceResultId') or request.get('readMode') == 'saved':
        from .briefing import resolve_reference
        saved_reference = resolve_reference(request, actor)
    request_hash = hashlib.sha256(store._json(request).encode("utf-8")).hexdigest()
    owner, identity_id, fingerprint = store._identity(actor)
    with (nullcontext(db_override) if db_override is not None else store._db(write=True)) as db:
        previous = db.execute("SELECT * FROM er_execution WHERE owner=? AND identity_id=? AND client_request_id=?",
                              (owner, identity_id, request["clientRequestId"])).fetchone()
        if previous:
            if (previous['owner'], previous['identity_id'], previous['scope_fingerprint']) != store._identity(actor):
                raise ApiError("当前数据范围已变化，不能恢复旧请求", code=403, status_code=403)
            if previous["request_hash"] != request_hash:
                raise ApiError("相同请求编号不能提交不同内容", code=409, status_code=409)
            return _view(db, previous)
        if request.get("retryOfExecutionId"):
            original = _row(db, request["retryOfExecutionId"], actor)
            if request.get('researchId') and request['researchId'] != original['research_id']:
                raise ApiError('重试须保留原会话', code=409, status_code=409)
            if original["state"] not in FINAL or original["state"] in {"completed", "partial", "needs_input"}:
                raise ApiError("原任务尚未失败，不能另建重试", code=409, status_code=409)
            original_request = json.loads(original["request"])
            for key in ("expertId", "input", "mode", "question"):
                if key in request and request[key] != original_request.get(key):
                    raise ApiError("重试范围不能改变；请新建分析", code=409, status_code=409)
                request.setdefault(key, original_request.get(key))
            request.setdefault("researchId", original["research_id"])
        expert, dependencies = _frozen(db, request, actor)
        mode = request.get("mode", "selected_task")
        if mode in {"question", "clarification_answer"}:
            from .model_adapter import available_models
            if not available_models()["available"]:
                raise ApiError("尚未配置真实模型，请选择业务任务及范围", code=409, status_code=409)
        elif mode == "selected_task":
            from .tasks import resolve_task
            if request.get('readMode') == 'saved':
                result = (saved_reference or {}).get('result') or {}
                request['input'] = {**result.get('scope', {}), 'taskId': result.get('taskId')}
            else:
                resolve_task((request.get("input") or {}).get("taskId"), expert["content"], dependencies)
        else:
            raise ApiError("执行入口无效", status_code=422)
        research_id = request.get("researchId") or str(uuid4())
        now = store._now()
        question = request.get("question", "").strip() or "按已选范围执行"
        if request.get("researchId"):
            ordinal = db.execute("SELECT COUNT(*) n FROM er_turn WHERE research_id=?", (research_id,)).fetchone()["n"]
            if ordinal != request.get("expectedTurn", 0):
                raise ApiError("研究已有新轮次，请刷新", code=409, status_code=409)
            if db.execute("SELECT 1 FROM er_execution WHERE research_id=? AND (state IN ('queued','running') OR worker_finished=0)", (research_id,)).fetchone():
                raise ApiError("本研究仍有任务执行中", code=409, status_code=409)
        else:
            if request.get("expectedTurn", 0) != 0:
                raise ApiError("新研究轮次应为0", status_code=422)
            ordinal = 0
        if db.execute("SELECT COUNT(*) n FROM er_execution WHERE state IN ('queued','running')").fetchone()["n"] >= 64:
            raise ApiError("执行队列已满，请稍后重试", code=429, status_code=429)
        if mode == "clarification_answer":
            origin = db.execute("SELECT * FROM er_turn WHERE id=? AND research_id=?", (request.get("originalTurnId"), research_id)).fetchone()
            current = db.execute("SELECT id FROM er_turn WHERE research_id=? ORDER BY ordinal DESC LIMIT 1", (research_id,)).fetchone()
            saved = json.loads(origin["outcome"]) if origin else {}
            if (not current or not origin or current["id"] != origin["id"] or
                    saved.get("clarification", {}).get("clarificationId") != request.get("clarificationId")):
                raise ApiError("澄清已过期或不属于本问题", code=409, status_code=409)
            request["question"] = origin["question"]
            question = origin["question"]
            request["context"] = {**json.loads(origin["input"]).get("context", {}),
                                  "clarification": saved["clarification"], "answer": request.get("answer")}
        elif request.get('originalTurnId'):
            origin = db.execute('SELECT outcome FROM er_turn WHERE id=? AND research_id=?',
                                (request['originalTurnId'], research_id)).fetchone()
            if not origin or not (json.loads(origin['outcome']).get('result') or {}).get('resultId'):
                raise ApiError('重新核验须引用本研究已保存的分析轮次', code=409, status_code=409)
        task_id = (request.get("input") or {}).get("taskId")
        execution_id, turn_id = str(uuid4()), str(uuid4())
        budget = min(300, max(20, int(request.get('_timeoutSeconds') or os.environ.get("EXPERT_EXECUTION_TIMEOUT", "180"))))
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=budget)).isoformat()
        if not request.get("researchId"):
            db.execute("INSERT INTO er_research (id,owner,identity_id,scope_fingerprint,title,expert_id,expert_version,dependencies,input,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                research_id, owner, identity_id, fingerprint, question[:100], expert["id"], expert["version"],
                store._json(dependencies), store._json(request.get("input") or {}), now, now))
        elif request.get("upgradeToVersion") and request.get('expertSelection', 'legacy') == 'legacy':
            db.execute("UPDATE er_research SET expert_version=?,dependencies=? WHERE id=?", (expert["version"], store._json(dependencies), research_id))
        placeholder = {"kind": "pending", "status": "running", "summary": "任务已登记", "executionId": execution_id}
        db.execute("INSERT INTO er_turn (id,research_id,ordinal,question,input,outcome,created_at) VALUES (?,?,?,?,?,?,?)", (turn_id, research_id, ordinal + 1, question,
                   store._json(request), store._json(placeholder), now))
        db.execute("""INSERT INTO er_execution
          (id,research_id,turn_id,owner,identity_id,scope_fingerprint,client_request_id,request_hash,
          state,task_id,request,dependencies,expert_version,deadline,summary,created_at)
          VALUES (?,?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?)""", (
            execution_id, research_id, turn_id, owner, identity_id, fingerprint, request["clientRequestId"],
            request_hash, task_id, store._json(request), store._json(dependencies), expert["version"], deadline, "任务已登记，等待执行", now))
        purpose = request.get('_purpose', 'personal')
        db.execute('UPDATE er_execution SET purpose=?,preset_id=?,principal_kind=? WHERE id=?',
                   (purpose, request.get('_presetId'), request.get('_principalKind', 'verified_user'), execution_id))
        from .processing import INSTANCE
        db.execute('UPDATE er_execution SET service_instance=? WHERE id=?', (INSTANCE, execution_id))
        db.execute('UPDATE er_research SET purpose=? WHERE id=?', (purpose, research_id))
        db.execute("UPDATE er_research SET input=?,updated_at=? WHERE id=?", (store._json(request.get("input") or {}), now, research_id))
        view = _view(db, _row(db, execution_id))
    if start:
        from .processing import ensure_ready
        ensure_ready()
        start_execution(execution_id, actor, authorization, identity)
    return view


def start_execution(execution_id, actor, authorization='', identity=''):
    with store._db() as db:
        row = _row(db, execution_id)
        request = json.loads(row['request'])
    budget = min(300, max(20, int(request.get('_timeoutSeconds') or os.environ.get('EXPERT_EXECUTION_TIMEOUT', '180'))))
    service = row['principal_kind'] == 'registered_service'
    if not service and not authorization:
        _terminal(execution_id, 'failed', '授权句柄不可用，请重新登录', 'auth_handle_missing')
        return
    with _credentials_lock:
        _credentials[execution_id] = (authorization, identity or store._identity(actor)[1], store._identity(actor), time.monotonic() + budget + (300 if service else 0))
    (_automatic_pool if service else _pool).submit(_supervise, execution_id)


def _authenticate(execution_id):
    with store._db() as db:
        row = _row(db, execution_id)
        request = json.loads(row['request'])
    if row['principal_kind'] == 'registered_service':
        from .processing import service_actor
        if row['state'] == 'queued':
            from .briefing import validate_start_window
            validate_start_window(request, datetime.now(timezone.utc))
        actor = service_actor(request.get('_grantId'), row['task_id'], request['_scope'])
        if store._identity(actor) != (row['owner'], row['identity_id'], row['scope_fingerprint']):
            raise ApiError('执行期间服务授权已改变', code=403, status_code=403)
        return actor
    with _credentials_lock:
        secret = _credentials.get(execution_id)
    if not secret:
        raise ApiError("执行授权已失效，请重新登录后开始新执行", code=401, status_code=401)
    if time.monotonic() >= secret[3]:
        raise ApiError('执行超过时间预算，请缩小范围后重试', code=408, status_code=408)
    actor = normalize_actor(remote_identity_payload(secret[0], secret[1]))
    require_use(actor)
    if store._identity(actor) != secret[2]:
        raise ApiError("执行期间授权或范围已变化", code=403, status_code=403)
    return actor


def _recheck_issues(db, row, outcome):
    """Resolve only cited facts for the same original task and business scope.

    Saved inputs and server-generated facts are the evidence. A document event,
    a changed scope, or a client assertion never closes an issue.
    """
    request = json.loads(row['request'])
    original_id = request.get('originalTurnId')
    result = outcome.get('result') or {}
    if not original_id or request.get('mode') != 'selected_task' or not result.get('resultId'):
        return set()
    original = db.execute('SELECT input,outcome FROM er_turn WHERE id=? AND research_id=?',
                          (original_id, row['research_id'])).fetchone()
    if not original:
        return set()
    previous = json.loads(original['outcome']).get('result') or {}
    old_input = json.loads(original['input'])
    old_input = old_input.get('input', old_input)
    def scope(value):
        return {key: val for key, val in value.items()
                if key not in {'previewLimit', 'limit', 'taskId', 'skill_id'} and val not in (None, '')}
    if previous.get('taskId') != result.get('taskId') or scope(old_input) != scope(request.get('input') or {}):
        return set()
    old_facts = {fact.get('factId'): fact for fact in previous.get('facts', [])}
    def signature(fact):
        subject = {key: val for key, val in (fact.get('objectRef') or {}).items() if key != 'aggregateRow'}
        return store._json([fact.get('name'), fact.get('unit'), fact.get('formula'), subject])
    candidates = {}
    new_facts = {fact.get('factId'): fact for fact in result.get('facts', [])}
    for fact in result.get('facts', []):
        candidates.setdefault(signature(fact), []).append(fact)
    still_affected = {signature(new_facts[ref]) for issue in result.get('issues', [])
                      for ref in issue.get('affectedFacts', []) if ref in new_facts}
    unresolved_signatures = set()
    opened = db.execute("SELECT issue_id,payload FROM er_issue_event WHERE research_id=? AND event_type='opened'",
                        (row['research_id'],)).fetchall()
    for event in opened:
        issue = json.loads(event['payload'])
        if issue.get('originalTurnId') != original_id:
            continue
        refs = issue.get('affectedFacts') or []
        keys = [signature(old_facts[ref]) for ref in refs if ref in old_facts]
        if not refs or len(keys) != len(refs):
            continue
        resolved = all(key not in still_affected and len(candidates.get(key, [])) == 1 and candidates[key][0].get('value') is not None
                       and not candidates[key][0].get('reason') for key in keys)
        if not resolved:
            unresolved_signatures.add(tuple(sorted(keys)))
        ordinal = db.execute('SELECT MAX(ordinal) n FROM er_issue_event WHERE research_id=? AND issue_id=?',
                             (row['research_id'], event['issue_id'])).fetchone()['n'] + 1
        payload = {'type': 'rechecked', 'originalTurnId': original_id,
                   'resultRef': {'resultId': row['id']}, 'resolved': resolved, 'requiredEvidenceComplete': resolved,
                   'reason': '同任务、同范围重新读取并核对原事实依据' if resolved else '原事实依据仍有缺项或冲突'}
        db.execute('INSERT INTO er_issue_event VALUES (?,?,?,?,?,?,?,?)',
                   (str(uuid4()), row['research_id'], event['issue_id'], ordinal, 'rechecked', store._json(payload),
                    row['owner'], store._now()))
    # Repeated unknown facts remain attached to the original issue. New problems
    # receive a separate event rather than duplicating the unresolved list.
    return {issue['issueId'] for issue in result.get('issues', [])
            if issue.get('affectedFacts') and tuple(sorted(signature(new_facts[ref])
               for ref in issue['affectedFacts'] if ref in new_facts)) in unresolved_signatures}


def _terminal(execution_id, state, summary, failure_code=None, outcome=None, lease=None, validated_actor=None):
    if state not in FINAL:
        raise ValueError("Invalid terminal state")
    with store._db(write=True) as db:
        row = _row(db, execution_id)
        if row["state"] not in ACTIVE or (lease and row["lease"] not in (None, lease)):
            return False
        if state in {"completed", "partial", "needs_input"} and datetime.now(timezone.utc) >= datetime.fromisoformat(row['deadline']):
            state, summary, failure_code, outcome = 'failed', '执行超过时间预算，请缩小范围后重试', 'deadline_exceeded', None
        if state in {"completed", "partial"}:
            if not outcome or not isinstance(outcome.get("result"), dict):
                raise ApiError("执行结果不符合契约", status_code=503)
            research = db.execute('SELECT * FROM er_research WHERE id=?', (row['research_id'],)).fetchone()
            store._live_dependencies(db, json.loads(row["request"]).get("expertId") or research["expert_id"], row["expert_version"], json.loads(row["dependencies"]))
            def check_rules(value):
                if isinstance(value, dict):
                    ref = value.get('ruleRef')
                    if isinstance(ref, dict) and ref.get('ruleId') and ref.get('version'):
                        from .rules import get_rule
                        rule = get_rule(ref['ruleId'], ref['version'])
                        if rule['state'] != 'published':
                            raise ApiError('所用规则已撤回，不能保存正式核验结果', code=409, status_code=409)
                    for key, child in value.items():
                        if key not in {'records', 'learningEvidence'}:
                            check_rules(child)
                elif isinstance(value, list):
                    for child in value:
                        check_rules(child)
            check_rules(outcome.get('result'))
        saved = deepcopy(outcome) if outcome else {"status": "failed" if state in {"failed", "cancelled"} else "blocked",
            "summary": summary, "result": None, "trace": [], "missingEvidence": []}
        source_request = json.loads(row['request'])
        if state in {'completed', 'partial'} and (source_request.get('publicationId') or source_request.get('sourceResultId')):
            if validated_actor is None:
                raise ApiError('保存引用结果须重新验证当前身份与来源', code=403, status_code=403)
            from .briefing import _reference_publication
            reference = _reference_publication(db, source_request, validated_actor)
            if reference:
                saved['sourcePublicationRef'] = reference
                saved['result']['sourcePublicationRef'] = reference
        frozen_expert_id = json.loads(row['request']).get('expertId')
        frozen_version = store._version(db,'experts',frozen_expert_id,row['expert_version'],include_deleted=True)
        saved['expert'] = {'id':frozen_expert_id,'name':frozen_version['name'],'version':row['expert_version']}
        saved["kind"] = "analysis" if state in {"completed", "partial"} else "clarification" if state == "needs_input" else "diagnostic"
        meta = {"id": execution_id, "executionId": execution_id, "researchId": row["research_id"], "turnId": row["turn_id"],
                "taskId": row["task_id"], "state": state, "startedAt": row["started_at"], "completedAt": store._now(), "failureCode": failure_code}
        saved["execution"] = meta
        if saved.get("result"):
            saved["result"]["execution"] = meta
            saved["result"]["executionPurpose"] = row['purpose']
            if state in {"completed", "partial"}:
                saved["result"]["resultId"] = execution_id
            else:
                saved["result"].pop("resultId", None)
            pinned = json.loads(row['dependencies'])
            saved["result"]["dependencies"] = {key: pinned[key] for key in
                 ('snapshot', 'fingerprintScheme', 'runtimeFingerprint', 'runtimeDependencies', 'taskIds') if key in pinned}
            for issue in saved["result"].get("issues", []):
                issue["originalTurnId"] = row["turn_id"]
                issue["issueId"] = f"{row['turn_id']}:{issue.get('issueId') or uuid4()}"
        for issue in saved.get("issues", []):
            issue["originalTurnId"] = row["turn_id"]
            issue["issueId"] = f"{row['turn_id']}:{issue.get('issueId') or uuid4()}"
        issues = saved.get('issues', []) + (saved.get('result') or {}).get('issues', [])
        if not issues and saved.get('missingEvidence'):
            issues = [{'issueId': str(uuid4()), 'originalTurnId': row['turn_id'], 'title': item,
                       'neededEvidence': item} for item in saved['missingEvidence'][:30]]
            saved['issues'] = issues
        if row['purpose'] == 'briefing' and state in {'completed', 'partial'}:
            if validated_actor is None:
                raise ApiError('正式简报保存须重新验证当前执行主体', code=403, status_code=403)
            from .briefing import publish_in_transaction
            publish_in_transaction(db, row, saved, validated_actor)
        serialized = store._json(saved)
        if len(serialized.encode("utf-8")) > MAX_BYTES:
            raise ApiError("完整证据超过留存上限，请缩小范围", code=413, status_code=413)
        db.execute("UPDATE er_turn SET outcome=? WHERE id=?", (serialized, row["turn_id"]))
        db.execute("UPDATE er_execution SET state=?,phase=?,revision=revision+1,failure_code=?,summary=?,completed_at=? WHERE id=?",
                   (state, 'facts_saved' if state in {'completed','partial'} else 'finished', failure_code, summary, meta["completedAt"], execution_id))
        db.execute("UPDATE er_research SET updated_at=? WHERE id=?", (meta["completedAt"], row["research_id"]))
        repeated = _recheck_issues(db, row, saved) if state in {'completed', 'partial'} else set()
        for issue in issues:
            if issue['issueId'] in repeated:
                continue
            if not db.execute('SELECT 1 FROM er_issue_event WHERE research_id=? AND issue_id=?',
                              (row['research_id'], issue['issueId'])).fetchone():
                event = {**issue, 'type': 'opened', 'originalTurnId': row['turn_id']}
                db.execute('INSERT INTO er_issue_event VALUES (?,?,?,?,?,?,?,?)',
                           (str(uuid4()), row['research_id'], issue['issueId'], 1, 'opened', store._json(event), row['owner'], meta['completedAt']))
        return True


def cancel(execution_id, actor):
    initialize()
    require_use(actor)
    with store._db() as db:
        _row(db, execution_id, actor)
    _terminal(execution_id, "cancelled", "本次执行已取消", "cancelled")
    with _credentials_lock:
        _credentials.pop(execution_id, None)
    return get(execution_id, actor)


def recover_interrupted(exclude_instance=None):
    initialize()
    with store._db() as db:
        ids = [r["id"] for r in db.execute("SELECT id FROM er_execution WHERE state IN ('queued','running') AND (? IS NULL OR service_instance IS NULL OR service_instance<>?)", (exclude_instance, exclude_instance))]
    for execution_id in ids:
        _terminal(execution_id, "failed", "服务重启后执行授权已丢失，请重新登录后开始新执行", "interrupted_auth_lost")
    with store._db(write=True) as db:
        db.execute("UPDATE er_execution SET phase='interrupted',worker_finished=1,explanation_state=CASE WHEN explanation_state='running' THEN 'interrupted' ELSE explanation_state END WHERE service_instance IS NOT NULL AND worker_finished=0 AND (? IS NULL OR service_instance<>?)", (exclude_instance, exclude_instance))
    return len(ids)


def _worker(pipe, payload):
    # Child has database/model service configuration, never the browser bearer.
    from .tasks import run_task
    def authorize():
        pipe.send({"kind": "authorize"})
        response = pipe.recv()
        if response.get("error"):
            raise ApiError(response["error"], code=403, status_code=403)
        actor = response["actor"]
        actor["_authorize"] = authorize
        return actor
    try:
        actor = authorize()
        request = payload["request"]
        request['_deadlineMonotonic'] = time.monotonic() + max(0, (datetime.fromisoformat(payload['deadline']) - datetime.now(timezone.utc)).total_seconds())
        inputs = request.get("input") or {}
        task_id = inputs.get("taskId")
        if request["mode"] in {"question", "clarification_answer"}:
            from .model_adapter import route
            routing = route(payload["expert"], payload["dependencies"], request, payload.get("history", []))
            if routing.get("clarification"):
                pipe.send({"kind": "outcome", "outcome": {"status": "blocked", "summary": routing["clarification"]["question"],
                    "clarification": routing["clarification"], "result": None, "trace": [], "missingEvidence": []}})
                return
            task_id, inputs = routing["taskId"], routing["input"]
        pipe.send({"kind": "task", "taskId": task_id, 'input': inputs})
        if request.get('readMode') == 'saved':
            outcome = payload['savedReference']
            outcome['sourceResultId'] = (outcome.get('result') or {}).get('resultId')
            outcome.pop('execution', None)
            outcome['summary'] = '按已保存结果查看；未重新查询当前数据库'
            if outcome.get('result'):
                outcome['result']['readMode'] = 'saved'
        else:
            tries = 0
            while True:
                try:
                    outcome = run_task(task_id, inputs, actor, {**payload["dependencies"], 'expertContent': payload['expert']['content']})
                    break
                except ApiError as exc:
                    if exc.status_code != 503 or tries >= request.get('_retryLimit', 0) or time.monotonic() >= request['_deadlineMonotonic'] - 3:
                        raise
                    tries += 1
                    authorize()
        pipe.send({"kind": "facts", "outcome": outcome})
        response = pipe.recv()
        if not response.get('saved') or not response.get('explain'):
            return
        authorize()
        request['_deadlineMonotonic'] = min(request['_deadlineMonotonic'], time.monotonic() + response['explanationBudget'])
        from .model_adapter import explain
        outcome = explain(payload['expert'], payload['dependencies'], request, outcome)
        pipe.send({'kind': 'explanation', 'outcome': outcome})
    except ApiError as exc:
        pipe.send({"kind": "error", "status": exc.status_code, "message": exc.msg})
    except Exception:
        pipe.send({"kind": "error", "status": 503, "message": "分析工具或数据暂不可用，请重试"})
    finally:
        pipe.close()


def _history_entry(db, turn, actor):
    saved = json.loads(turn['outcome'])
    result = saved.get('result') or {}
    entry = {'turnId': turn['id'], 'question': turn['question'], 'resultId': result.get('resultId'),
             'facts': result.get('facts', []), 'scope': result.get('scope', {}),
             'versions': result.get('dependencies', {}), 'queriedAt': result.get('execution', {}).get('completedAt')}
    source = json.loads(turn['input'])
    ref = saved.get('sourcePublicationRef') or result.get('sourcePublicationRef')
    if ref and not (source.get('publicationId') or source.get('sourceResultId')):
        source = {'publicationId': ref.get('publicationId'), 'sourceResultId': ref.get('resultId')}
    if source.get('publicationId') or source.get('sourceResultId'):
        from .briefing import _reference_publication
        try:
            _reference_publication(db, source, actor)
        except ApiError:
            entry.update(facts=[], scope={}, versions={}, referenceState='invalid',
                         referenceReason='原保存依据已撤回、失效或不在当前授权范围，不提供其事实作为本轮分析依据')
    return entry


def _supervise(execution_id):
    from . import processing
    process = parent = child = None
    lease = str(uuid4())
    facts_saved = False
    try:
        processing.ensure_ready()
        actor = _authenticate(execution_id)
        with processing._recovery_lock, store._db(write=True) as db:
            processing.ensure_ready()
            row = _row(db, execution_id)
            if (row['owner'], row['identity_id'], row['scope_fingerprint']) != store._identity(actor):
                raise ApiError('执行主体或范围已改变', code=403, status_code=403)
            if row['state'] != 'queued':
                return
            request, dependencies = json.loads(row['request']), json.loads(row['dependencies'])
            if row['principal_kind'] == 'registered_service':
                from .briefing import validate_start_window
                validate_start_window(request, datetime.now(timezone.utc))
            research = db.execute('SELECT * FROM er_research WHERE id=?', (row['research_id'],)).fetchone()
            expert = store._live_dependencies(db, request.get('expertId') or research['expert_id'], row['expert_version'], dependencies)
            history = []
            for t in db.execute('SELECT id,question,input,outcome FROM er_turn WHERE research_id=? AND ordinal<(SELECT ordinal FROM er_turn WHERE id=?) ORDER BY ordinal DESC LIMIT 4', (row['research_id'], row['turn_id'])):
                history.append(_history_entry(db, t, actor))
            budget = min(300, max(20, int(request.get('_timeoutSeconds') or os.environ.get('EXPERT_EXECUTION_TIMEOUT', '180'))))
            # Automatic queueing does not spend the execution budget. Human auth
            # remains short lived and is checked before this allocation.
            deadline = (datetime.now(timezone.utc) + timedelta(seconds=budget)).isoformat()
            db.execute("UPDATE er_execution SET state='running',phase='querying',worker_finished=0,revision=revision+1,lease=?,started_at=?,deadline=?,service_instance=?,summary=? WHERE id=?",
                       (lease, store._now(), deadline, processing.INSTANCE, '正在核对范围、依赖和数据', execution_id))
            with _supervisor_lock:
                _supervisor_active[execution_id] = lease
        saved_reference = None
        if request.get('readMode') == 'saved':
            from .briefing import resolve_reference
            saved_reference = resolve_reference(request, actor)
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        process = context.Process(target=_worker, args=(child, {'request': request, 'dependencies': dependencies,
                'expert': expert, 'history': history, 'deadline': deadline, 'savedReference': saved_reference}), daemon=True)
        process.start()
        child.close()
        with store._db(write=True) as db:
            db.execute('UPDATE er_execution SET worker_pid=?,worker_created=? WHERE id=? AND lease=?',
                       (process.pid, processing.process_identity(process.pid), execution_id, lease))
        explanation_deadline = None
        while True:
            with store._db() as db:
                current = _row(db, execution_id)
                if current['lease'] != lease or (not facts_saved and current['state'] not in ACTIVE):
                    break
                expired = datetime.now(timezone.utc) >= datetime.fromisoformat(current['deadline'])
            if expired or (explanation_deadline is not None and time.monotonic() >= explanation_deadline):
                if facts_saved:
                    _finish_explanation(execution_id, lease, 'budget_exhausted')
                else:
                    _terminal(execution_id, 'failed', '执行超过时间预算，请缩小范围后重试', 'deadline_exceeded', lease=lease)
                break
            if not parent.poll(.1):
                if not process.is_alive():
                    if not facts_saved:
                        _terminal(execution_id, 'failed', '执行进程已中断，请重试', 'worker_interrupted', lease=lease)
                    elif current['explanation_state'] == 'running':
                        _finish_explanation(execution_id, lease, 'interrupted')
                    break
                continue
            try:
                message = parent.recv()
            except EOFError:
                if not facts_saved:
                    _terminal(execution_id, 'failed', '执行进程已中断，请重试', 'worker_interrupted', lease=lease)
                break
            kind = message.get('kind')
            if kind == 'authorize':
                parent.send({'actor': _authenticate(execution_id)})
            elif kind == 'task':
                with store._db(write=True) as db:
                    db.execute("UPDATE er_execution SET task_id=? WHERE id=? AND lease=? AND state='running'", (message['taskId'], execution_id, lease))
                    db.execute("UPDATE er_turn SET input=? WHERE id=? AND (SELECT state FROM er_execution WHERE id=?)='running'",
                               (store._json({**request, 'input': message['input']}), row['turn_id'], execution_id))
            elif kind == 'error':
                if facts_saved:
                    _finish_explanation(execution_id, lease, 'failed')
                else:
                    state = 'blocked' if message['status'] in {409, 422} else 'failed'
                    _terminal(execution_id, state, message['message'], 'tool_error', lease=lease)
                break
            elif kind in {'facts', 'outcome'}:
                if facts_saved:
                    parent.send({'saved': True, 'explain': False})
                    continue
                verified = _authenticate(execution_id)
                if request.get('publicationId') or request.get('sourceResultId'):
                    from .briefing import resolve_reference
                    resolve_reference(request, verified)
                outcome = message['outcome']
                state = 'needs_input' if outcome.get('clarification') else 'blocked' if outcome.get('status') == 'blocked' else 'failed' if outcome.get('status') == 'failed' else 'partial' if (outcome.get('result') or {}).get('status') == 'limited' else 'completed'
                saved_ok = _terminal(execution_id, state, outcome.get('summary', '执行完成'), outcome=outcome, lease=lease, validated_actor=verified)
                facts_saved = bool(saved_ok and state in {'completed', 'partial'})
                if kind == 'outcome' or not facts_saved:
                    break
                from .model_adapter import available_models
                wants_explain = expert['content'].get('executionMode') == 'llm' or request.get('_purpose') == 'briefing'
                remaining = (datetime.fromisoformat(deadline) - datetime.now(timezone.utc)).total_seconds()
                explain = wants_explain and available_models()['available'] and remaining > 1
                explanation_state = 'running' if explain else 'budget_exhausted' if remaining <= 1 else 'not_configured' if wants_explain else 'not_requested'
                with store._db(write=True) as db:
                    db.execute('UPDATE er_execution SET phase=?,explanation_state=?,revision=revision+1 WHERE id=? AND lease=?',
                               ('explaining' if explain else 'facts_saved', explanation_state, execution_id, lease))
                explanation_budget = min(25, remaining)
                explanation_deadline = time.monotonic() + explanation_budget if explain else None
                parent.send({'saved': True, 'explain': explain, 'explanationBudget': explanation_budget})
            elif kind == 'explanation':
                _authenticate(execution_id)
                if request.get('publicationId') or request.get('sourceResultId'):
                    from .briefing import resolve_reference
                    resolve_reference(request, _authenticate(execution_id))
                from .briefing import append_explanation
                with store._db(write=True) as db:
                    applied = append_explanation(db, _row(db, execution_id), message['outcome'], lease)
                if not applied:
                    _finish_explanation(execution_id, lease, 'reference_invalid')
                break
    except ApiError as exc:
        if facts_saved:
            _finish_explanation(execution_id, lease, 'failed')
        else:
            code = 'deadline_exceeded' if exc.status_code == 408 else 'authorization_changed' if exc.status_code in {401, 403} else 'evidence_save_failed' if exc.status_code == 413 else 'dependency_unavailable'
            _terminal(execution_id, 'failed', exc.msg, code, lease=lease)
    except Exception:
        if facts_saved:
            _finish_explanation(execution_id, lease, 'failed')
        else:
            _terminal(execution_id, 'failed', '执行或证据保存失败，原请求已保留', 'execution_failed', lease=lease)
    finally:
        ended = True
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=3)
            ended = not process.is_alive()
        with store._db(write=True) as db:
            db.execute('UPDATE er_execution SET worker_finished=?,phase=?,revision=revision+1 WHERE id=? AND lease=?',
                       (int(ended), 'finished' if ended else 'recovery_blocked', execution_id, lease))
        if not ended:
            processing._state.update(ready=False, recoveryState='blocked')
        with _supervisor_lock:
            _supervisor_active.pop(execution_id, None)
        for endpoint in (parent, child):
            if endpoint is not None:
                endpoint.close()
        if ended:
            with _credentials_lock:
                _credentials.pop(execution_id, None)


def _finish_explanation(execution_id, lease, state):
    with store._db(write=True) as db:
        db.execute("UPDATE er_execution SET explanation_state=?,revision=revision+1 WHERE id=? AND lease=? AND explanation_state='running'", (state, execution_id, lease))


def _saved(db, result_id, actor):
    if result_id.startswith("legacy:"):
        row = db.execute("SELECT * FROM er_turn WHERE id=?", (result_id[7:],)).fetchone()
        if not row:
            raise ApiError("结果不存在", code=404, status_code=404)
        store._research_row(db, row["research_id"], actor)
        outcome = json.loads(row["outcome"])
        if outcome.get("kind") == "pending":
            raise ApiError("结果尚未保存", code=404, status_code=404)
        outcome["legacy"] = True
        return outcome
    execution = _row(db, result_id, actor)
    if execution["state"] not in {"completed", "partial"}:
        raise ApiError("本任务没有可引用的已保存结果", code=404, status_code=404)
    turn = db.execute("SELECT outcome FROM er_turn WHERE id=?", (execution["turn_id"],)).fetchone()
    return json.loads(turn["outcome"])


def get_result(result_id, actor):
    require_use(actor)
    initialize()
    with store._db() as db:
        return _public_outcome(_saved(db, result_id, actor))


def evidence(result_id, evidence_id, actor, offset=0, limit=20):
    require_use(actor)
    initialize()
    with store._db() as db:
        saved = _saved(db, result_id, actor)
    selected = next((e for e in (saved.get("result") or {}).get("evidence", []) if e.get("evidenceId") == evidence_id), None)
    if selected is None:
        raise ApiError("该结果未保留此证据", code=404, status_code=404)
    records = selected.get("records") or []
    return {**{k: v for k, v in selected.items() if k != "records"}, "totalRows": len(records),
            "returnedRows": len(records[offset:offset + limit]), "rows": records[offset:offset + limit], "offset": offset}


def tasks(actor):
    require_use(actor)
    from .tasks import task_definitions, resolve_task
    items = []
    with store._db() as db:
        for definition in task_definitions():
            item = deepcopy(definition)
            try:
                expert = store._version(db, "experts", item["expertId"])
                store._live_dependencies(db, expert["id"], expert["version"], expert["dependencies"])
                resolve_task(item["taskId"], expert["content"], expert["dependencies"])
                item["available"] = True
            except ApiError as exc:
                item["available"] = False
                required = item.get('requiredDependencies') or []
                item["reason"] = '；'.join([*required, exc.msg])
            items.append(item)
    return {"items": items}

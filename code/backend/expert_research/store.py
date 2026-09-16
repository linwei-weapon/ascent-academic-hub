"""Transactional research store; business scope authorization belongs to service/router."""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from ..api.envelope import ApiError
from ..expert_team.storage import owner

ACTIVE = ('queued', 'running', 'cancel_requested')
TERMINAL = ('completed', 'partial', 'needs_input', 'failed', 'cancelled')
DEFAULTS = dict(global_running=2, user_active=2, queue_capacity=20, queue_seconds=60.0,
                run_seconds=180.0, lease_seconds=30.0, heartbeat_seconds=10.0, poll_seconds=0.2)
DDL = """
CREATE TABLE IF NOT EXISTS er_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS er_research(
 id TEXT PRIMARY KEY,username TEXT NOT NULL,identity_id TEXT NOT NULL,scope_key TEXT NOT NULL,
 title TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',scope_json TEXT NOT NULL,
 context_epoch INTEGER NOT NULL DEFAULT 1,metadata_revision INTEGER NOT NULL DEFAULT 1,
 participants_revision INTEGER NOT NULL DEFAULT 1,current_result_id TEXT,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS er_owner ON er_research(username,identity_id,scope_key,updated_at,id);
CREATE TABLE IF NOT EXISTS er_participant(
 research_id TEXT NOT NULL REFERENCES er_research(id),expert_id TEXT NOT NULL,
 status TEXT NOT NULL,origin TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(research_id,expert_id));
CREATE TABLE IF NOT EXISTS er_text(
 owner_key TEXT NOT NULL,research_id TEXT NOT NULL,kind TEXT NOT NULL,
 text TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0,saved_at TEXT,
 PRIMARY KEY(owner_key,research_id,kind));
CREATE TABLE IF NOT EXISTS er_text_version(
 owner_key TEXT NOT NULL,research_id TEXT NOT NULL,kind TEXT NOT NULL,revision INTEGER NOT NULL,
 text TEXT NOT NULL,source_refs_json TEXT NOT NULL,saved_at TEXT NOT NULL,
 PRIMARY KEY(owner_key,research_id,kind,revision));
CREATE TABLE IF NOT EXISTS er_turn(
 id TEXT PRIMARY KEY,research_id TEXT NOT NULL REFERENCES er_research(id),seq INTEGER NOT NULL,
 message TEXT NOT NULL,kind TEXT NOT NULL,scope_json TEXT NOT NULL,context_epoch INTEGER NOT NULL,
 created_at TEXT NOT NULL,UNIQUE(research_id,seq));
CREATE TABLE IF NOT EXISTS er_run(
 id TEXT PRIMARY KEY,research_id TEXT NOT NULL REFERENCES er_research(id),
 turn_id TEXT NOT NULL REFERENCES er_turn(id),status TEXT NOT NULL,payload_json TEXT NOT NULL,
 lease_generation INTEGER NOT NULL DEFAULT 0,lease_until REAL,heartbeat REAL,
 worker_id TEXT,created_epoch REAL NOT NULL,deadline REAL,queue_deadline REAL NOT NULL,
 created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,error TEXT,
 retry_of TEXT,attempt INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS er_one_active ON er_run(research_id)
 WHERE status IN ('queued','running','cancel_requested');
CREATE INDEX IF NOT EXISTS er_run_queue ON er_run(status,created_epoch,id);
CREATE TABLE IF NOT EXISTS er_source_bundle(
 id TEXT PRIMARY KEY,research_id TEXT NOT NULL REFERENCES er_research(id),run_id TEXT NOT NULL,
 content_json TEXT NOT NULL,content_hash TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS er_result(
 id TEXT PRIMARY KEY,research_id TEXT NOT NULL REFERENCES er_research(id),run_id TEXT NOT NULL UNIQUE,
 turn_id TEXT NOT NULL,source_bundle_id TEXT REFERENCES er_source_bundle(id),result_json TEXT NOT NULL,
 scope_json TEXT NOT NULL,context_epoch INTEGER NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS er_progress(
 id TEXT PRIMARY KEY,research_id TEXT NOT NULL REFERENCES er_research(id),result_id TEXT NOT NULL,
 version INTEGER NOT NULL,content_json TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(research_id,version));
CREATE TABLE IF NOT EXISTS er_question(
 id TEXT PRIMARY KEY,research_id TEXT NOT NULL REFERENCES er_research(id),revision INTEGER NOT NULL,
 status TEXT NOT NULL,content_json TEXT NOT NULL,history_json TEXT NOT NULL,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS er_material(
 id TEXT PRIMARY KEY,research_id TEXT NOT NULL REFERENCES er_research(id),snapshot_json TEXT NOT NULL,
 content_hash TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS er_event(
 id INTEGER PRIMARY KEY AUTOINCREMENT,research_id TEXT NOT NULL REFERENCES er_research(id),
 run_id TEXT,event_type TEXT NOT NULL,content_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS er_event_research ON er_event(research_id,id);
CREATE TABLE IF NOT EXISTS er_idempotency(
 owner_key TEXT NOT NULL,operation TEXT NOT NULL,request_id TEXT NOT NULL,
 content_hash TEXT NOT NULL,response_json TEXT NOT NULL,
 PRIMARY KEY(owner_key,operation,request_id));
CREATE TABLE IF NOT EXISTS er_legacy_archive(
 id TEXT PRIMARY KEY,namespace TEXT NOT NULL,legacy_id TEXT NOT NULL,
 username TEXT NOT NULL,identity_id TEXT NOT NULL,scope_key TEXT NOT NULL,
 source_revision INTEGER NOT NULL,archive_json TEXT NOT NULL,content_hash TEXT NOT NULL,
 archived_at TEXT NOT NULL,UNIQUE(namespace,legacy_id));
"""

def is_read_only():
    return os.getenv('EXPERT_RESEARCH_READ_ONLY', '0') == '1'

def _writable():
    if is_read_only():
        error('研究工作区目前为只读，已保存历史仍可查看', 503)

def path():
    # Dedicated UI-validation instances may share read-only school inputs,
    # but must never mix their discussions with the leadership workspace.
    if os.getenv('EXPERT_RESEARCH_DB_PATH'):
        return Path(os.environ['EXPERT_RESEARCH_DB_PATH']).resolve()
    from ..expert_team.storage import path as legacy_path
    return legacy_path().with_name('expert_research.sqlite')

def connect(path=None):
    target = Path(path) if path is not None else globals()['path']()
    if not target.is_file():
        error('研究工作区尚未初始化，请先执行独立迁移', 503)
    # FastAPI may enter/use/close one request's dependency on different worker
    # threads. Connections stay request-owned; this is not a shared global pool.
    conn = sqlite3.connect(target.resolve().as_uri() + '?mode=rw', uri=True, timeout=2, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=2000')
    try:
        version = conn.execute("SELECT value FROM er_meta WHERE key='schema_version'").fetchone()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'er_research', 'er_turn', 'er_run', 'er_text', 'er_text_version', 'er_result',
                    'er_source_bundle', 'er_material', 'er_event', 'er_question', 'er_legacy_archive',
                    'er_idempotency', 'er_participant', 'er_progress'}
        if not version or version[0] != '1' or not required.issubset(tables):
            raise sqlite3.DatabaseError('incomplete_research_schema')
    except sqlite3.DatabaseError:
        conn.close()
        error('研究工作区迁移尚未完成', 503)
    return conn

def migrate(conn):
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(DDL)
    conn.execute("INSERT OR REPLACE INTO er_meta VALUES('schema_version','1')")
    conn.commit()

def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def fingerprint(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()

def uid():
    return str(uuid.uuid4())

def error(message, status=409):
    raise ApiError(message, code=status, status_code=status)

@contextmanager
def transaction(conn):
    if conn.in_transaction:
        raise RuntimeError('research operations require an independent transaction')
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise

def _key(user):
    return encode(owner(user))

def _research(conn, user, research_id):
    row = conn.execute('SELECT * FROM er_research WHERE id=? AND username=? AND identity_id=? AND scope_key=?',
                       (research_id, *owner(user))).fetchone()
    if row is None or conn.execute('SELECT 1 FROM er_meta WHERE key=?', ('qa:research:' + research_id,)).fetchone():
        error('研究不存在或当前工作身份无权查看', 404)
    return dict(row)

def _event(conn, research_id, kind, run_id=None, content=None):
    conn.execute('INSERT INTO er_event(research_id,run_id,event_type,content_json,created_at) VALUES(?,?,?,?,?)',
                 (research_id, run_id, kind, encode(content or {}), now()))

def _existing(conn, user, operation, request_id, content):
    if not request_id or len(request_id) > 160:
        error('缺少有效的请求标识', 422)
    row = conn.execute('SELECT * FROM er_idempotency WHERE owner_key=? AND operation=? AND request_id=?',
                       (_key(user), operation, request_id)).fetchone()
    if row:
        if row['content_hash'] != fingerprint(content):
            error('request_conflict：同一请求标识对应的内容不同')
        return json.loads(row['response_json'])
    return None

def _remember(conn, user, operation, request_id, content, response):
    conn.execute('INSERT INTO er_idempotency VALUES(?,?,?,?,?)',
                 (_key(user), operation, request_id, fingerprint(content), encode(response)))

def _capacity(conn, user, config):
    if conn.execute("SELECT COUNT(*) FROM er_run WHERE status='queued'").fetchone()[0] >= config['queue_capacity']:
        error('queue_full：分析等待队列已满，请保留输入稍后再试', 429)
    count = conn.execute("""SELECT COUNT(*) FROM er_run x JOIN er_research r ON r.id=x.research_id
        WHERE r.username=? AND x.status IN ('queued','running','cancel_requested')""", (owner(user)[0],)).fetchone()[0]
    if count >= config['user_active']:
        error('user_active_limit：已有研究正在处理，请稍后再发送', 429)

def _insert_turn(conn, user, research, message, scope, expert_id, kind, config, retry_of=None):
    stamp, current_time = now(), time.time()
    turn_id, run_id = uid(), uid()
    seq = conn.execute('SELECT COALESCE(MAX(seq),0)+1 FROM er_turn WHERE research_id=?', (research['id'],)).fetchone()[0]
    username, identity_id, scope_key = owner(user)
    payload = dict(user=dict(username=username, identity_id=identity_id, scope_key=scope_key),
                   research_id=research['id'], turn_id=turn_id, run_id=run_id, scope=scope,
                   message=message, expert_id=expert_id, kind=kind, context_epoch=research['context_epoch'])
    conn.execute('INSERT INTO er_turn VALUES(?,?,?,?,?,?,?,?)', (turn_id, research['id'], seq, message, kind,
                 encode(scope), research['context_epoch'], stamp))
    conn.execute("""INSERT INTO er_run(id,research_id,turn_id,status,payload_json,created_epoch,queue_deadline,
        created_at,retry_of) VALUES(?,?,?,'queued',?,?,?,?,?)""", (run_id, research['id'], turn_id, encode(payload),
                 current_time, current_time + config['queue_seconds'], stamp, retry_of))
    _event(conn, research['id'], 'queued', run_id)
    conn.execute('UPDATE er_research SET updated_at=? WHERE id=?', (stamp, research['id']))
    return dict(research_id=research['id'], turn_id=turn_id, run_id=run_id)

def create_research(conn, user, message, scope, client_request_id, expert_id=None, config=None):
    _writable()
    config = {**DEFAULTS, **(config or {})}
    message = str(message).strip()
    if not message or len(message) > 12000 or not isinstance(scope, dict):
        error('请填写有效研究问题与范围', 422)
    content = dict(message=message, scope=scope, expert_id=expert_id)
    with transaction(conn):
        response = _existing(conn, user, 'create', client_request_id, content)
        if response is None:
            _capacity(conn, user, config)
            research_id, stamp = uid(), now()
            conn.execute('''INSERT INTO er_research(id,username,identity_id,scope_key,title,scope_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)''', (research_id, *owner(user), message[:28]+('…' if len(message)>28 else ''), encode(scope), stamp, stamp))
            response = _insert_turn(conn, user, _research(conn, user, research_id), message, scope, expert_id, 'analysis', config)
            _remember(conn, user, 'create', client_request_id, content, response)
    return detail(conn, user, response['research_id'])

def add_turn(conn, user, research_id, message, scope, request_id, expected_epoch, expert_id=None,
             kind='analysis', config=None):
    _writable()
    config = {**DEFAULTS, **(config or {})}
    message = str(message).strip()
    if not message or len(message) > 12000 or not isinstance(scope, dict):
        error('请填写有效研究问题与范围', 422)
    content = dict(message=message, scope=scope, expert_id=expert_id, kind=kind, epoch=expected_epoch)
    with transaction(conn):
        research = _research(conn, user, research_id)
        previous = _existing(conn, user, 'turn:' + research_id, request_id, content)
        if previous is None:
            if research['status'] != 'active':
                error('请先恢复已归档研究')
            if research['context_epoch'] != expected_epoch:
                error('context_conflict：研究范围已变化，请重新确认')
            if conn.execute("SELECT 1 FROM er_run WHERE research_id=? AND status IN ('queued','running','cancel_requested')", (research_id,)).fetchone():
                error('research_busy：本项研究正在分析，请保留下轮草稿')
            _capacity(conn, user, config)
            if encode(scope) != research['scope_json']:
                research['context_epoch'] += 1
                conn.execute('UPDATE er_research SET scope_json=?,context_epoch=?,current_result_id=NULL WHERE id=?',
                             (encode(scope), research['context_epoch'], research_id))
            response = _insert_turn(conn, user, research, message, scope, expert_id, kind, config)
            _remember(conn, user, 'turn:' + research_id, request_id, content, response)
    return detail(conn, user, research_id)

def update_metadata(conn, user, research_id, revision, title=None, status=None, scope=None, expected_epoch=None):
    _writable()
    with transaction(conn):
        row = _research(conn, user, research_id)
        if row['metadata_revision'] != revision:
            error('metadata_conflict：研究信息已在其他窗口更新')
        if status is not None and status not in ('active', 'archived'):
            error('无效研究状态', 422)
        if title is not None and not title.strip():
            error('研究名称不能为空', 422)
        if scope is not None and encode(scope) != row['scope_json']:
            if expected_epoch != row['context_epoch']:
                error('context_conflict：研究范围已变化')
            row['context_epoch'] += 1
            row['scope_json'], row['current_result_id'] = encode(scope), None
        conn.execute('''UPDATE er_research SET title=?,status=?,scope_json=?,context_epoch=?,current_result_id=?,
            metadata_revision=metadata_revision+1,updated_at=? WHERE id=?''',
            ((title.strip()[:100] if title is not None else row['title']), status or row['status'], row['scope_json'],
             row['context_epoch'], row['current_result_id'], now(), research_id))
        _event(conn, research_id, 'research_updated')
    return detail(conn, user, research_id)

def update_participants(conn, user, research_id, revision, expert_id, action='add'):
    _writable()
    if action not in ('add', 'exclude') or not expert_id:
        error('无效专家操作', 422)
    with transaction(conn):
        row = _research(conn, user, research_id)
        if row['participants_revision'] != revision:
            error('participants_conflict：参与专家已更新')
        conn.execute('''INSERT INTO er_participant VALUES(?,?,?,?,?)
            ON CONFLICT(research_id,expert_id) DO UPDATE SET status=excluded.status,origin=excluded.origin''',
            (research_id, expert_id, 'active' if action == 'add' else 'excluded', 'manual', now()))
        conn.execute('UPDATE er_research SET participants_revision=participants_revision+1 WHERE id=?', (research_id,))
        _event(conn, research_id, 'participants_updated', content={'effective': 'next_claim'})
    return detail(conn, user, research_id)

def _text_auth(conn, user, research_id, kind):
    if kind not in ('draft', 'opinion') or (research_id == 'new' and kind != 'draft'):
        error('无效文字类型', 422)
    owner(user)
    if research_id != 'new':
        _research(conn, user, research_id)

def get_text(conn, user, research_id, kind):
    _text_auth(conn, user, research_id, kind)
    row = conn.execute('SELECT text,revision,saved_at FROM er_text WHERE owner_key=? AND research_id=? AND kind=?',
                       (_key(user), research_id, kind)).fetchone()
    return dict(row) if row else dict(text='', revision=0, saved_at=None)

def save_text(conn, user, research_id, kind, text, revision, request_id, source_refs=None):
    _writable()
    if not isinstance(text, str) or len(text) > 100000:
        error('文字长度超出限制', 422)
    content = dict(text=text, revision=revision, source_refs=source_refs or [])
    operation = f'text:{research_id}:{kind}'
    with transaction(conn):
        current = get_text(conn, user, research_id, kind)
        response = _existing(conn, user, operation, request_id, content)
        if response is None:
            if current['revision'] != revision:
                error('text_conflict：文字已在其他窗口保存，请保留当前内容并比较版本')
            response = dict(text=text, revision=revision + 1, saved_at=now())
            conn.execute('''INSERT INTO er_text VALUES(?,?,?,?,?,?) ON CONFLICT(owner_key,research_id,kind)
                DO UPDATE SET text=excluded.text,revision=excluded.revision,saved_at=excluded.saved_at''',
                (_key(user), research_id, kind, text, response['revision'], response['saved_at']))
            conn.execute('INSERT INTO er_text_version VALUES(?,?,?,?,?,?,?)',
                (_key(user), research_id, kind, response['revision'], text, encode(source_refs or []), response['saved_at']))
            _remember(conn, user, operation, request_id, content, response)
            if research_id != 'new':
                _event(conn, research_id, kind + '_saved', content={'revision': response['revision']})
    return response

def text_versions(conn, user, research_id, kind='opinion', before=None, limit=30):
    _text_auth(conn, user, research_id, kind)
    rows = conn.execute('''SELECT revision,text,source_refs_json,saved_at FROM er_text_version
        WHERE owner_key=? AND research_id=? AND kind=? AND revision<? ORDER BY revision DESC LIMIT ?''',
        (_key(user), research_id, kind, before or 2147483647, min(max(int(limit), 1), 100))).fetchall()
    return [dict(revision=r['revision'], text=r['text'], source_refs=json.loads(r['source_refs_json']), saved_at=r['saved_at']) for r in rows]

def _run_public(row):
    if row is None:
        return None
    return {key: row[key] for key in ('id', 'research_id', 'turn_id', 'status', 'error', 'lease_generation',
                                      'created_at', 'started_at', 'finished_at', 'retry_of')}

def get_run(conn, user, run_id):
    row = conn.execute('SELECT * FROM er_run WHERE id=?', (run_id,)).fetchone()
    if row is None:
        error('运行不存在或无权访问', 404)
    _research(conn, user, row['research_id'])
    return _run_public(row)

def _result(row):
    if row is None:
        return None
    return {**json.loads(row['result_json']), 'id': row['id'], 'source_bundle_id': row['source_bundle_id'],
            'created_at': row['created_at'], 'scope': json.loads(row['scope_json']), 'context_epoch': row['context_epoch']}

def get_result(conn, user, result_id):
    row = conn.execute('SELECT * FROM er_result WHERE id=?', (result_id,)).fetchone()
    if row is None:
        error('分析结果不存在或无权访问', 404)
    _research(conn, user, row['research_id'])
    return _result(row)

def _result_method_experts(conn, research_id, result, bundle=None, seen=None):
    from .service import method_experts
    seen = set() if seen is None else seen
    bundle_id = result.get('source_bundle_id')
    if bundle is None and bundle_id:
        source = conn.execute('SELECT content_json FROM er_source_bundle WHERE id=? AND research_id=?',
                              (bundle_id, research_id)).fetchone()
        bundle = json.loads(source[0]) if source else None
    methods = method_experts(result, bundle)
    previous = result.get('based_on_result_id')
    if previous and previous not in seen:
        seen.add(previous)
        row = conn.execute('SELECT * FROM er_result WHERE id=? AND research_id=?', (previous, research_id)).fetchone()
        if row is None:
            error('派生结果引用的来源不存在或不属于本项研究', 409)
        methods.update(_result_method_experts(conn, research_id, _result(row), seen=seen))
    return methods

def result_method_experts(conn, user, result):
    row = conn.execute('SELECT research_id FROM er_result WHERE id=?', (result.get('id'),)).fetchone()
    if row is None:
        error('分析结果不存在或无权访问', 404)
    _research(conn, user, row['research_id'])
    return _result_method_experts(conn, row['research_id'], result)

def detail(conn, user, research_id, before=None, limit=30):
    # All parts must reflect one SQLite snapshot. A worker can otherwise publish
    # between reading current_result_id and reading the corresponding turns.
    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute('BEGIN')
    try:
        row = _research(conn, user, research_id)
        result = {k: v for k, v in row.items() if k not in ('username', 'identity_id', 'scope_key', 'scope_json')}
        result['scope'] = json.loads(row['scope_json'])
        result['participants'] = [dict(x) for x in conn.execute('SELECT expert_id,status,origin FROM er_participant WHERE research_id=? ORDER BY created_at,expert_id', (research_id,))]
        result['draft'], result['opinion'] = get_text(conn, user, research_id, 'draft'), get_text(conn, user, research_id, 'opinion')
        turns = conn.execute('SELECT * FROM er_turn WHERE research_id=? AND seq<? ORDER BY seq DESC LIMIT ?',
                             (research_id, before or 2147483647, min(max(int(limit), 1), 100))).fetchall()
        result['turns'] = []
        for item in reversed(turns):
            turn = {k: item[k] for k in ('id', 'seq', 'message', 'kind', 'created_at', 'context_epoch')}
            turn['scope'] = json.loads(item['scope_json'])
            turn['run'] = _run_public(conn.execute('SELECT * FROM er_run WHERE turn_id=? ORDER BY attempt DESC LIMIT 1', (item['id'],)).fetchone())
            turn['result'] = _result(conn.execute('SELECT * FROM er_result WHERE turn_id=? ORDER BY created_at DESC LIMIT 1', (item['id'],)).fetchone())
            result['turns'].append(turn)
        result['next_before'] = turns[-1]['seq'] if turns and turns[-1]['seq'] > 1 else None
        result['active_run'] = _run_public(conn.execute("SELECT * FROM er_run WHERE research_id=? AND status IN ('queued','running','cancel_requested')", (research_id,)).fetchone())
        result['current_result'] = _result(conn.execute('SELECT * FROM er_result WHERE id=?', (row['current_result_id'],)).fetchone())
        result['questions'] = list_questions(conn, user, research_id)
        return result
    finally:
        if own_transaction:
            conn.rollback()

def list_researches(conn, user, q='', before=None, limit=30, status='active'):
    limit = min(max(int(limit), 1), 100)
    conditions, params = ['r.username=?', 'r.identity_id=?', 'r.scope_key=?'], list(owner(user))
    conditions.append("NOT EXISTS(SELECT 1 FROM er_meta m WHERE m.key='qa:research:'||r.id)")
    if status is not None:
        conditions.append('r.status=?'); params.append(status)
    if q:
        conditions.append("""(r.title LIKE ? OR EXISTS(SELECT 1 FROM er_turn t WHERE t.research_id=r.id AND t.message LIKE ?)
            OR EXISTS(SELECT 1 FROM er_result x WHERE x.research_id=r.id AND x.result_json LIKE ?)
            OR EXISTS(SELECT 1 FROM er_text v WHERE v.research_id=r.id AND v.kind='opinion' AND v.text LIKE ?))""")
        params.extend(['%' + q + '%'] * 4)
    if before:
        try:
            stamp, item_id = json.loads(before)
        except (ValueError, TypeError):
            error('无效分页位置', 422)
        conditions.append('(r.updated_at<? OR (r.updated_at=? AND r.id<?))'); params.extend([stamp, stamp, item_id])
    rows = conn.execute('SELECT r.id,r.title,r.status,r.updated_at,r.context_epoch FROM er_research r WHERE ' +
        ' AND '.join(conditions) + ' ORDER BY r.updated_at DESC,r.id DESC LIMIT ?', (*params, min(max(int(limit), 1), 100) + 1)).fetchall()
    items = [dict(r) for r in rows[:limit]]
    if q:
        for item in items:
            matched = conn.execute('''SELECT t.id FROM er_turn t WHERE t.research_id=? AND
                (t.message LIKE ? OR EXISTS(SELECT 1 FROM er_result x WHERE x.turn_id=t.id AND x.result_json LIKE ?))
                ORDER BY t.seq DESC LIMIT 1''', (item['id'], '%' + q + '%', '%' + q + '%')).fetchone()
            item['matched_turn_id'] = matched['id'] if matched else None
    return dict(items=items, next_cursor=encode([items[-1]['updated_at'], items[-1]['id']]) if len(rows) > limit and items else None)

def list_events(conn, user, research_id, after=0, limit=100):
    _research(conn, user, research_id)
    return [dict(id=r['id'], event_id=r['id'], research_id=research_id, run_id=r['run_id'],
                 type=r['event_type'], content=json.loads(r['content_json']), created_at=r['created_at'])
            for r in conn.execute('SELECT * FROM er_event WHERE research_id=? AND id>? ORDER BY id LIMIT ?',
                                  (research_id, int(after), min(max(int(limit), 1), 200)))]

def _question(row):
    return {**json.loads(row['content_json']), 'id': row['id'], 'revision': row['revision'],
            'status': row['status'], 'created_at': row['created_at'], 'updated_at': row['updated_at'],
            'history': json.loads(row['history_json'])}

def list_questions(conn, user, research_id):
    _research(conn, user, research_id)
    return [_question(r) for r in conn.execute('SELECT * FROM er_question WHERE research_id=? ORDER BY created_at,id', (research_id,))]

def _insert_question(conn, research_id, content, result_id=None):
    question_id, stamp = uid(), now()
    content = {**content, 'created_from_result_id': result_id}
    conn.execute('INSERT INTO er_question VALUES(?,?,1,?,?,?,?,?)', (question_id, research_id, 'open',
                 encode(content), encode([dict(status='open', at=stamp)]), stamp, stamp))
    return question_id

def add_question(conn, user, research_id, content):
    _writable()
    if not isinstance(content, dict) or not str(content.get('text', '')).strip():
        error('请说明待明确事项', 422)
    with transaction(conn):
        _research(conn, user, research_id)
        question_id = _insert_question(conn, research_id, content)
        _event(conn, research_id, 'question_added', content={'question_id': question_id})
    return _question(conn.execute('SELECT * FROM er_question WHERE id=?', (question_id,)).fetchone())

def update_question(conn, user, research_id, question_id, revision, status, note='', text=None):
    _writable()
    # Only managerial disposition is directly editable. Data-resolution needs a
    # published source and a new validated result; clients cannot assert closure.
    if status not in ('open', 'deferred'):
        error('资料问题须由已发布来源和新的有效分析确认，不能手工标为已解决', 422)
    with transaction(conn):
        _research(conn, user, research_id)
        row = conn.execute('SELECT * FROM er_question WHERE id=? AND research_id=?', (question_id, research_id)).fetchone()
        if row is None:
            error('待明确事项不存在', 404)
        if row['revision'] != revision:
            error('question_conflict：待明确事项已更新')
        content = json.loads(row['content_json'])
        if text is not None:
            if not isinstance(text, str) or not text.strip() or len(text) > 5000:
                error('请填写有效事项说明', 422)
            content['text'] = text.strip()
        history = json.loads(row['history_json']) + [dict(status=status, note=note, text=content.get('text'), at=now())]
        conn.execute('UPDATE er_question SET status=?,revision=revision+1,content_json=?,history_json=?,updated_at=? WHERE id=?',
                     (status, encode(content), encode(history), now(), question_id))
        _event(conn, research_id, 'question_updated', content={'question_id': question_id})
    return _question(conn.execute('SELECT * FROM er_question WHERE id=?', (question_id,)).fetchone())

def get_source_bundle(conn, user, source_bundle_id):
    row = conn.execute('SELECT * FROM er_source_bundle WHERE id=?', (source_bundle_id,)).fetchone()
    if row is None:
        error('来源包不存在或无权访问', 404)
    _research(conn, user, row['research_id'])
    return {**json.loads(row['content_json']), 'id': row['id'], 'research_id': row['research_id'],
            'created_at': row['created_at'], 'content_hash': row['content_hash']}

def create_material(conn, user, research_id, result_id, opinion_revision, question_revisions,
                    include_opinion=True, request_id=None):
    _writable()
    content = dict(result_id=result_id, opinion_revision=opinion_revision,
                   question_revisions=question_revisions, include_opinion=include_opinion)
    with transaction(conn):
        research = _research(conn, user, research_id)
        previous = _existing(conn, user, 'material:' + research_id, request_id, content) if request_id else None
        if previous:
            material_id = previous['id']
        else:
            row = conn.execute('SELECT * FROM er_result WHERE id=? AND research_id=?', (result_id, research_id)).fetchone()
            if row is None:
                error('所选分析结果不存在', 404)
            state = conn.execute('SELECT status FROM er_run WHERE id=?', (row['run_id'],)).fetchone()[0]
            if state not in ('completed', 'partial') or json.loads(row['result_json']).get('status') == 'reference':
                error('说明、澄清或未完成分析不能作为正式材料结果，请选择有效分析结果', 422)
            if result_id != research['current_result_id']:
                error('result_conflict：研究范围或当前结果已变化，请从当前有效结果重新整理材料')
            from .service import require_methods_available
            require_methods_available(_result_method_experts(conn, research_id, _result(row)))
            opinion = get_text(conn, user, research_id, 'opinion')
            if include_opinion and opinion['revision'] != opinion_revision:
                error('opinion_conflict：意见已更新，请重新预览后整理')
            questions = list_questions(conn, user, research_id)
            actual = {x['id']: x['revision'] for x in questions}
            if actual != question_revisions:
                error('questions_conflict：待明确事项已更新，请重新预览')
            question = conn.execute('SELECT message FROM er_turn WHERE id=? AND research_id=?', (row['turn_id'], research_id)).fetchone()
            first_question = conn.execute('SELECT message FROM er_turn WHERE research_id=? ORDER BY seq LIMIT 1', (research_id,)).fetchone()
            frozen_plans = []
            if row['source_bundle_id']:
                bundle = get_source_bundle(conn, user, row['source_bundle_id'])
                frozen_plans = [item['plan'] for item in bundle.get('plans', []) if item.get('plan')]
            snapshot = dict(title=research['title'], question=question['message'] if question else '',
                            research_question=first_question['message'] if first_question else '', frozen_plans=frozen_plans,
                            result=_result(row), opinion=opinion if include_opinion else None,
                            questions=questions, template_version='research-material-v3/2',
                            result_id=result_id, opinion_revision=opinion_revision if include_opinion else None,
                            question_revisions=actual, include_opinion=bool(include_opinion), created_at=now())
            from .memo import build
            snapshot['discussion_memo'] = build(snapshot)
            material_id = uid()
            conn.execute('INSERT INTO er_material VALUES(?,?,?,?,?)',
                         (material_id, research_id, encode(snapshot), fingerprint(snapshot), now()))
            _event(conn, research_id, 'material_created', content={'material_id': material_id})
            if request_id:
                _remember(conn, user, 'material:' + research_id, request_id, content, {'id': material_id})
    return get_material(conn, user, material_id)

def get_material(conn, user, material_id):
    row = conn.execute('SELECT * FROM er_material WHERE id=?', (material_id,)).fetchone()
    if row is None:
        error('材料不存在或无权访问', 404)
    _research(conn, user, row['research_id'])
    return dict(id=row['id'], research_id=row['research_id'], snapshot=json.loads(row['snapshot_json']),
                content_hash=row['content_hash'], created_at=row['created_at'])

def list_materials(conn, user, research_id):
    _research(conn, user, research_id)
    return [dict(r) for r in conn.execute('SELECT id,created_at,content_hash FROM er_material WHERE research_id=? ORDER BY created_at DESC,id DESC', (research_id,))]

def list_legacy(conn, user, before=None, limit=30):
    rows = conn.execute('''SELECT id,legacy_id,source_revision,archived_at FROM er_legacy_archive
        WHERE username=? AND identity_id=? AND scope_key=? AND id>? ORDER BY id LIMIT ?''',
        (*owner(user), before or '', min(max(int(limit), 1), 100) + 1)).fetchall()
    items = [dict(r) for r in rows[:limit]]
    return dict(items=items, next_cursor=items[-1]['id'] if len(rows) > limit and items else None)

def read_legacy(conn, user, archive_id):
    row = conn.execute('''SELECT * FROM er_legacy_archive WHERE id=?
        AND username=? AND identity_id=? AND scope_key=?''', (archive_id, *owner(user))).fetchone()
    if row is None:
        error('旧讨论档案不存在或当前身份无权查看', 404)
    return dict(id=row['id'], legacy_id=row['legacy_id'], source_revision=row['source_revision'],
                archive=json.loads(row['archive_json']), content_hash=row['content_hash'],
                read_only=True, historical_completeness='existing_record_only', archived_at=row['archived_at'])

def import_legacy(conn, legacy_conn, namespace):
    """Administrative migration only: never changes legacy_conn or existing archives."""
    counts = dict(imported=0, unchanged=0, conflicts=[])
    legacy_conn.row_factory = sqlite3.Row
    with transaction(conn):
        for row in legacy_conn.execute('SELECT * FROM team_session ORDER BY id'):
            record = dict(row)
            content_hash = fingerprint(record)
            old = conn.execute('SELECT content_hash FROM er_legacy_archive WHERE namespace=? AND legacy_id=?',
                               (namespace, record['id'])).fetchone()
            if old:
                if old['content_hash'] == content_hash:
                    counts['unchanged'] += 1
                else:
                    counts['conflicts'].append(record['id'])
                continue
            if not all(record.get(k) for k in ('username', 'identity_id', 'scope_key')):
                counts['conflicts'].append(record['id'])
                continue
            conn.execute('INSERT INTO er_legacy_archive VALUES(?,?,?,?,?,?,?,?,?,?)',
                (uid(), namespace, record['id'], record['username'], record['identity_id'], record['scope_key'],
                 record['revision'], encode(record), content_hash, now()))
            counts['imported'] += 1
    return counts

def cancel_run(conn, user, run_id):
    with transaction(conn):
        get_run(conn, user, run_id)
        row = conn.execute('SELECT * FROM er_run WHERE id=?', (run_id,)).fetchone()
        if row['status'] == 'queued':
            conn.execute("UPDATE er_run SET status='cancelled',lease_generation=lease_generation+1,finished_at=? WHERE id=?", (now(), run_id))
            _event(conn, row['research_id'], 'cancelled', run_id)
        elif row['status'] == 'running':
            # Fencing takes effect at acceptance, before process reclamation.
            conn.execute("UPDATE er_run SET status='cancel_requested',lease_generation=lease_generation+1 WHERE id=?", (run_id,))
            _event(conn, row['research_id'], 'cancel_requested', run_id)
    return get_run(conn, user, run_id)

def claim_next(conn, worker_id, config=None, clock=None):
    """Trusted supervisor only. Atomic global capacity and generation ownership."""
    if is_read_only():
        return None
    cfg, current_time = {**DEFAULTS, **(config or {})}, time.time() if clock is None else clock
    with transaction(conn):
        if conn.execute("SELECT COUNT(*) FROM er_run WHERE status IN ('running','cancel_requested')").fetchone()[0] >= cfg['global_running']:
            return None
        row = conn.execute("SELECT * FROM er_run WHERE status='queued' AND queue_deadline>? ORDER BY created_epoch,id LIMIT 1", (current_time,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row['payload_json'])
        participants = conn.execute('SELECT expert_id,status FROM er_participant WHERE research_id=?', (row['research_id'],)).fetchall()
        payload['chosen'] = [p['expert_id'] for p in participants if p['status'] == 'active']
        payload['excluded'] = [p['expert_id'] for p in participants if p['status'] == 'excluded']
        payload['deadline'] = current_time + cfg['run_seconds']
        payload['lease_generation'] = row['lease_generation'] + 1
        conn.execute("""UPDATE er_run SET status='running',payload_json=?,lease_generation=lease_generation+1,
            worker_id=?,deadline=?,lease_until=?,heartbeat=?,started_at=? WHERE id=? AND status='queued'""",
            (encode(payload), worker_id, payload['deadline'], current_time + cfg['lease_seconds'], current_time, now(), row['id']))
        _event(conn, row['research_id'], 'running', row['id'])
        return dict(id=row['id'], lease_generation=payload['lease_generation'], payload=payload,
                    deadline=payload['deadline'], worker_id=worker_id)

def heartbeat(conn, run_id, generation, worker_id, lease_seconds=30, clock=None):
    stamp = time.time() if clock is None else clock
    with transaction(conn):
        return bool(conn.execute("""UPDATE er_run SET heartbeat=?,lease_until=MIN(?,deadline) WHERE id=? AND status='running'
            AND lease_generation=? AND worker_id=? AND lease_until>? AND deadline>?""",
            (stamp, stamp + lease_seconds, run_id, generation, worker_id, stamp, stamp)).rowcount)

def finish_failure(conn, run_id, generation, reason, status='failed'):
    if status not in ('failed', 'cancelled'):
        raise ValueError('invalid failure state')
    with transaction(conn):
        row = conn.execute('SELECT * FROM er_run WHERE id=?', (run_id,)).fetchone()
        if row is None or row['status'] not in ACTIVE or row['lease_generation'] != generation:
            return False
        conn.execute('UPDATE er_run SET status=?,error=?,finished_at=?,lease_generation=lease_generation+1 WHERE id=?',
                     (status, reason, now(), run_id))
        _event(conn, row['research_id'], status, run_id, {'reason': reason})
        return True

def finish_cancel(conn, run_id, worker_id=None):
    with transaction(conn):
        row = conn.execute('SELECT * FROM er_run WHERE id=?', (run_id,)).fetchone()
        if row is None or row['status'] != 'cancel_requested' or (worker_id and row['worker_id'] != worker_id):
            return False
        conn.execute("UPDATE er_run SET status='cancelled',finished_at=? WHERE id=?", (now(), run_id))
        _event(conn, row['research_id'], 'cancelled', run_id)
        return True

def reap_expired(conn, clock=None, excluded_run_ids=None):
    """Expired attempts cannot be safely replayed without fixed sources: terminate.

    A user may submit a new explicitly scoped analysis. This avoids guessing that
    a process crash is a recoverable network failure or inventing old slices.
    """
    stamp = time.time() if clock is None else clock
    with transaction(conn):
        rows = conn.execute("""SELECT * FROM er_run WHERE (status='queued' AND queue_deadline<=?) OR
            (status IN ('running','cancel_requested') AND (lease_until<=? OR deadline<=?))""", (stamp, stamp, stamp)).fetchall()
        excluded = set(excluded_run_ids or ())
        rows = [row for row in rows if row['id'] not in excluded]
        for row in rows:
            reason = 'queue_timeout' if row['status'] == 'queued' else ('run_timeout' if row['deadline'] <= stamp else 'lease_expired')
            state = 'cancelled' if row['status'] == 'cancel_requested' else 'failed'
            conn.execute('UPDATE er_run SET status=?,error=?,finished_at=?,lease_generation=lease_generation+1 WHERE id=?',
                         (state, reason, now(), row['id']))
            _event(conn, row['research_id'], state, row['id'], {'reason': reason})
        return len(rows)

def publish(conn, run_id, generation, worker_id, output, clock=None):
    """Fenced result publication, called only after fresh service authorization."""
    if is_read_only():
        return False
    stamp = time.time() if clock is None else clock
    if not isinstance(output, dict):
        raise ValueError('execution must return a dictionary')
    status = output.get('status', 'completed')
    if status not in ('completed', 'partial', 'needs_input'):
        raise ValueError('invalid successful execution status')
    result = output.get('result', output)
    if not isinstance(result, dict):
        raise ValueError('invalid analysis result')
    with transaction(conn):
        row = conn.execute('SELECT * FROM er_run WHERE id=?', (run_id,)).fetchone()
        if (row is None or row['status'] != 'running' or row['lease_generation'] != generation
                or row['worker_id'] != worker_id or row['lease_until'] <= stamp or row['deadline'] <= stamp):
            return False
        payload, created = json.loads(row['payload_json']), now()
        bundle_id = None
        bundle = output.get('source_bundle')
        from .catalog import disabled_versions
        methods = _result_method_experts(conn, row['research_id'], result, bundle)
        methods.update(expert for expert in output.get('actual_experts', []) if isinstance(expert, str))
        unavailable = methods & disabled_versions()
        reference_only = result.get('status') == 'reference' and output.get('publish_current') is False
        if unavailable and not reference_only:
            conn.execute("UPDATE er_run SET status='failed',error='method_unavailable',finished_at=?,lease_generation=lease_generation+1 WHERE id=?",
                         (created, run_id))
            _event(conn, row['research_id'], 'failed', run_id, {'reason': 'method_unavailable'})
            return False
        result = {**result, 'method_experts': sorted(methods)}
        if bundle is not None:
            if not isinstance(bundle, dict):
                raise ValueError('invalid source bundle')
            bundle_id = uid()
            conn.execute('INSERT INTO er_source_bundle VALUES(?,?,?,?,?,?)',
                         (bundle_id, row['research_id'], run_id, encode(bundle), fingerprint(bundle), created))
        result_id = uid()
        effective_scope = result.get('scope', payload['scope'])
        if not isinstance(effective_scope, dict):
            raise ValueError('invalid_effective_scope')
        current = conn.execute('SELECT scope_json,context_epoch FROM er_research WHERE id=?', (row['research_id'],)).fetchone()
        can_promote = (status in ('completed', 'partial') and output.get('publish_current', True)
                       and current['context_epoch'] == payload['context_epoch']
                       and current['scope_json'] == encode(payload['scope']))
        semantic = lambda value: {k: v for k, v in value.items() if k not in ('expert_id', 'scenario')}
        result_epoch = payload['context_epoch'] + int(can_promote and semantic(effective_scope) != semantic(payload['scope']))
        result = {**result, 'submitted_context_epoch': payload['context_epoch']}
        conn.execute('INSERT INTO er_result VALUES(?,?,?,?,?,?,?,?,?)',
            (result_id, row['research_id'], run_id, row['turn_id'], bundle_id, encode(result),
             encode(effective_scope), result_epoch, created))
        for question in output.get('questions', []):
            if not isinstance(question, dict) or not question.get('text'):
                continue
            # Repeated missing-data explanations should not create duplicate work.
            exists = any(json.loads(q[0]).get('text') == question['text'] for q in conn.execute(
                "SELECT content_json FROM er_question WHERE research_id=? AND status='open'", (row['research_id'],)))
            if not exists:
                _insert_question(conn, row['research_id'], question, result_id)
        actual = output.get('actual_experts', result.get('actual_experts', []))
        changed = False
        for expert in actual:
            if not isinstance(expert, str):
                continue
            # An in-flight manual exclusion must not be undone by publication.
            changed = bool(conn.execute('INSERT OR IGNORE INTO er_participant VALUES(?,?,?,?,?)',
                (row['research_id'], expert, 'active', 'automatic', created)).rowcount) or changed
        if changed:
            conn.execute('UPDATE er_research SET participants_revision=participants_revision+1 WHERE id=?', (row['research_id'],))
        if can_promote:
            updated = conn.execute('''UPDATE er_research SET current_result_id=?,updated_at=?,scope_json=?,context_epoch=? WHERE id=?
                AND context_epoch=? AND scope_json=?''',
                (result_id, created, encode(effective_scope), result_epoch, row['research_id'], payload['context_epoch'], encode(payload['scope']))).rowcount
            if updated:
                version = conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM er_progress WHERE research_id=?', (row['research_id'],)).fetchone()[0]
                summary = dict(result_id=result_id, body=result.get('management_note') or result.get('body', ''), status=status)
                conn.execute('INSERT INTO er_progress VALUES(?,?,?,?,?,?)', (uid(), row['research_id'], result_id, version, encode(summary), created))
        conn.execute('UPDATE er_run SET status=?,finished_at=? WHERE id=?', (status, created, run_id))
        _event(conn, row['research_id'], status, run_id, {'result_id': result_id})
        return True

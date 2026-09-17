"""Separate derived-data/session store. Legacy analytical databases stay intact."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..api.envelope import ApiError

DDL = """
CREATE TABLE IF NOT EXISTS team_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS team_plan_course(
 plan_id TEXT NOT NULL,source_row INTEGER NOT NULL,course_id TEXT NOT NULL,
 course_name TEXT, module TEXT,nature TEXT,credits REAL,hours REAL,assessment TEXT,
 term TEXT,source_file TEXT,source_hash TEXT,PRIMARY KEY(plan_id,source_row));
CREATE INDEX IF NOT EXISTS team_course_plan ON team_plan_course(plan_id,course_id);
CREATE TABLE IF NOT EXISTS team_document(
 plan_id TEXT PRIMARY KEY,file_name TEXT NOT NULL,file_hash TEXT,content TEXT NOT NULL,
 sections_json TEXT NOT NULL,status TEXT NOT NULL,issues_json TEXT NOT NULL,imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS team_session(
 id TEXT PRIMARY KEY,username TEXT NOT NULL,identity_id TEXT NOT NULL,scope_key TEXT NOT NULL,
 expert_id TEXT NOT NULL,title TEXT NOT NULL,request_json TEXT NOT NULL,result_json TEXT NOT NULL,
 messages_json TEXT NOT NULL DEFAULT '[]',draft TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS team_session_owner ON team_session(username,identity_id,scope_key,updated_at);
CREATE TABLE IF NOT EXISTS team_graduation_snapshot(
 id TEXT PRIMARY KEY,username TEXT NOT NULL,identity_id TEXT NOT NULL,scope_key TEXT NOT NULL,
 plan_id TEXT NOT NULL,source_hash TEXT NOT NULL,snapshot_version TEXT NOT NULL,
 snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(username,identity_id,scope_key,plan_id,source_hash,snapshot_version));
CREATE INDEX IF NOT EXISTS team_snapshot_owner ON team_graduation_snapshot(username,identity_id,scope_key,plan_id,created_at);
"""


def path():
    from ..api.settings import DB_PATH
    return Path(DB_PATH).with_name("expert_team.sqlite")


def migrate(conn):
    for sql in DDL.split(";"):
        if sql.strip():
            conn.execute(sql)


def connect():
    if not path().is_file():
        raise ApiError("专家团尚未初始化，请联系管理员完成独立数据准备", code=503, status_code=503)
    conn = sqlite3.connect(path().resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def owner(user):
    context = user.get("permission_context") or {}
    values = (user.get("username"), context.get("activeIdentityId"), context.get("scopeFingerprint"))
    if not context.get("authorized") or not all(values):
        raise ApiError("当前身份或数据范围无效", code=403, status_code=403)
    return values


def unpack(row):
    result = dict(row)
    for key in ("request", "result", "messages"):
        result[key] = json.loads(result.pop(key + "_json"))
    for key in ("username", "identity_id", "scope_key"):
        result.pop(key, None)
    return result


def get_session(conn, user, session_id):
    row = conn.execute("SELECT * FROM team_session WHERE id=? AND username=? AND identity_id=? AND scope_key=?",
                       (session_id, *owner(user))).fetchone()
    if not row:
        raise ApiError("讨论不存在或当前工作身份无权查看", code=404, status_code=404)
    return unpack(row)


def list_sessions(conn, user):
    return [dict(r) for r in conn.execute(
        "SELECT id,expert_id,title,updated_at FROM team_session WHERE username=? AND identity_id=? AND scope_key=? ORDER BY updated_at DESC,id LIMIT 50",
        owner(user))]


def get_snapshot(conn,user,snapshot_id):
    row=conn.execute('SELECT id,plan_id,snapshot_json,created_at FROM team_graduation_snapshot WHERE id=? AND username=? AND identity_id=? AND scope_key=?',
                     (snapshot_id,*owner(user))).fetchone()
    if not row: raise ApiError('阶段记录不存在或当前工作身份无权查看',code=404,status_code=404)
    value=dict(row);value['snapshot']=json.loads(value.pop('snapshot_json'))
    return value


def list_snapshots(conn,user,plan_id):
    return [dict(row) for row in conn.execute('SELECT id,created_at FROM team_graduation_snapshot WHERE username=? AND identity_id=? AND scope_key=? AND plan_id=? ORDER BY created_at DESC,id DESC LIMIT 30',
                                            (*owner(user),plan_id))]


def latest_snapshot(conn,user,plan_id):
    available=list_snapshots(conn,user,plan_id)
    return get_snapshot(conn,user,available[0]['id']) if available else None


def save_snapshot(conn,user,snapshot):
    # Aggregates and fingerprints only. No student identifiers/names are stored.
    conn.execute('''INSERT OR IGNORE INTO team_graduation_snapshot
        (id,username,identity_id,scope_key,plan_id,source_hash,snapshot_version,snapshot_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)''',(str(uuid.uuid4()),*owner(user),snapshot['plan_id'],snapshot['source_hash'],
                                     snapshot['snapshot_version'],json.dumps(snapshot,ensure_ascii=False),now()))
    row=conn.execute('SELECT id FROM team_graduation_snapshot WHERE username=? AND identity_id=? AND scope_key=? AND plan_id=? AND source_hash=? AND snapshot_version=?',
                     (*owner(user),snapshot['plan_id'],snapshot['source_hash'],snapshot['snapshot_version'])).fetchone()
    return get_snapshot(conn,user,row['id'])


def create_session(conn, user, request, result):
    session_id, stamp = str(uuid.uuid4()), now()
    conn.execute("""INSERT INTO team_session(id,username,identity_id,scope_key,expert_id,title,
        request_json,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (session_id, *owner(user), request["expert_id"], result["title"][:100],
         json.dumps(request, ensure_ascii=False), json.dumps(result, ensure_ascii=False), stamp, stamp))
    conn.commit()
    return get_session(conn, user, session_id)


def update_session(conn, user, session_id, revision, *, draft=None, note=None, messages=None, request=None, result=None):
    get_session(conn, user, session_id)
    fields, params = [], []
    for key, value in (("draft", draft), ("note", note), ("messages_json", messages),
                       ("request_json", request), ("result_json", result),
                       ("title", result["title"][:100] if result else None)):
        if value is not None:
            fields.append(key + "=?")
            params.append(json.dumps(value, ensure_ascii=False) if key.endswith("_json") else value)
    if not fields:
        return get_session(conn, user, session_id)
    changed = conn.execute("UPDATE team_session SET " + ",".join(fields) +
        ",revision=revision+1,updated_at=? WHERE id=? AND revision=? AND username=? AND identity_id=? AND scope_key=?",
        (*params, now(), session_id, revision, *owner(user))).rowcount
    if not changed:
        raise ApiError("讨论已在其他窗口更新，请重新打开后再保存", code=409, status_code=409)
    conn.commit()
    return get_session(conn, user, session_id)

"""Versioned resource configuration and identity-bound execution records.

This SQLite store contains configuration and explicit result snapshots only.
Business data remains in the configured school database, read by runtime.py.
Call initialize() explicitly at service startup; migrations never replace edits.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
import sqlite3
from typing import Callable
from uuid import uuid4

from backend.api.envelope import ApiError

KINDS = ("experts", "skills", "mcps")
CODE = Path(__file__).resolve().parents[2]


def path() -> Path:
    return Path(os.environ.get("EXPERT_RESOURCES_DB_PATH", str(CODE / "backend/db/expert_resources.sqlite")))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _kind(kind: str) -> str:
    kind = {"expert": "experts", "skill": "skills", "mcp": "mcps"}.get(kind, kind)
    if kind not in KINDS:
        raise ApiError("资源类型不存在", code=404, status_code=404)
    return kind


@contextmanager
def _db(write=False):
    if not path().is_file():
        raise ApiError("专家资源库尚未初始化", status_code=503)
    conn = sqlite3.connect(str(path()), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        if write:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(seed_path: str | Path | None = None) -> None:
    """Idempotent, additive schema + seed installation; never auto-publish."""
    seed = Path(seed_path) if seed_path else CODE / "expert-resources/catalog.json"
    payload = json.loads(seed.read_text(encoding="utf-8"))
    path().parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path()), timeout=10)) as conn, conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS er_resource (
              kind TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
              draft_version TEXT NOT NULL, content TEXT NOT NULL,
              published_version TEXT, enabled INTEGER NOT NULL DEFAULT 1,
              run_id TEXT, review TEXT, updated_at TEXT NOT NULL,
              PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS er_version (
              kind TEXT NOT NULL, resource_id TEXT NOT NULL, version TEXT NOT NULL,
              content TEXT NOT NULL, dependencies TEXT NOT NULL,
              published_at TEXT NOT NULL, published_by TEXT NOT NULL,
              run_id TEXT NOT NULL, review TEXT,
              PRIMARY KEY(kind,resource_id,version));
            CREATE TABLE IF NOT EXISTS er_run (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, resource_id TEXT NOT NULL,
              revision INTEGER NOT NULL, owner TEXT NOT NULL, identity_id TEXT NOT NULL,
              scope_fingerprint TEXT NOT NULL, input TEXT NOT NULL,
              dependencies TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS er_research (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, identity_id TEXT NOT NULL,
              scope_fingerprint TEXT NOT NULL, title TEXT NOT NULL,
              expert_id TEXT NOT NULL, expert_version TEXT NOT NULL,
              dependencies TEXT NOT NULL, input TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS er_turn (
              id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES er_research(id),
              ordinal INTEGER NOT NULL, question TEXT NOT NULL, input TEXT NOT NULL,
              outcome TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(research_id,ordinal));
            CREATE INDEX IF NOT EXISTS er_research_owner ON er_research(owner,identity_id,scope_fingerprint);
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(er_resource)")}
        if "deleted_at" not in columns:
            conn.execute("ALTER TABLE er_resource ADD COLUMN deleted_at TEXT")
        research_columns = {row[1] for row in conn.execute('PRAGMA table_info(er_research)')}
        if 'purpose' not in research_columns:
            conn.execute("ALTER TABLE er_research ADD COLUMN purpose TEXT NOT NULL DEFAULT 'personal'")
        for kind in KINDS:
            for item in payload.get(kind, []):
                # Seeds may carry envelope metadata, but editable definitions live in content.
                content = item.get("content", item)
                if not item.get("id") or not isinstance(content, dict):
                    raise ValueError("Invalid expert-resource seed")
                conn.execute("""INSERT OR IGNORE INTO er_resource
                    (kind,id,revision,draft_version,content,enabled,updated_at)
                    VALUES (?,?,1,?,?,?,?)""", (kind, item["id"], str(item.get("version", "1.0.0")),
                    _json(content), int(item.get("enabled", True)), _now()))


def _identity(actor: dict) -> tuple[str, str, str]:
    context = actor.get("permission_context") or actor.get("permissionContext") or {}
    owner = actor.get("username")
    identity = actor.get("identity_id") or context.get("activeIdentityId")
    fingerprint = context.get("scopeFingerprint")
    if (not owner or not identity or not fingerprint or context.get("authorized") is not True
            or context.get("activeIdentityId") != identity):
        raise ApiError("当前工作身份或数据范围无效", code=403, status_code=403)
    return str(owner), str(identity), str(fingerprint)


def _owns(row, actor: dict) -> bool:
    if 'purpose' in row.keys() and row['purpose'] != 'personal' and actor.get('principalKind') != 'registered_service':
        return False
    return (row["owner"], row["identity_id"], row["scope_fingerprint"]) == _identity(actor)


def _row(conn, kind, resource_id, include_deleted=False):
    row = conn.execute("SELECT * FROM er_resource WHERE kind=? AND id=?", (_kind(kind), resource_id)).fetchone()
    if not row or (row["deleted_at"] and not include_deleted):
        raise ApiError("资源不存在或已删除", code=404, status_code=404)
    return row


def _revision(row, revision):
    if row["revision"] != revision:
        raise ApiError("资源已被修改，请刷新后再操作", code=409, status_code=409)


def _version(conn, kind, resource_id, version=None, include_deleted=False):
    row = _row(conn, kind, resource_id, include_deleted)
    selected = version or row["published_version"]
    record = conn.execute("SELECT * FROM er_version WHERE kind=? AND resource_id=? AND version=?",
                          (_kind(kind), resource_id, selected)).fetchone()
    if not record:
        raise ApiError(f"依赖 {resource_id} 尚未发布", code=409, status_code=409)
    return {"id": resource_id, "kind": _kind(kind), "name": json.loads(record["content"]).get("name", resource_id),
            "version": selected, "content": json.loads(record["content"]),
            "dependencies": json.loads(record["dependencies"]), "enabled": bool(row["enabled"]),
            "publishedAt": record["published_at"]}


def _runtime_fingerprint():
    from .runtime import fingerprint
    return fingerprint()


def _require_runtime_version(resource, current=None):
    dependencies = resource["dependencies"]
    if dependencies.get("fingerprintScheme") == "task-v2":
        from .runtime import task_fingerprint
        expected = task_fingerprint(dependencies.get("taskIds"))
        valid = all(dependencies.get(key) == expected[key] for key in
                    ("runtimeFingerprint", "runtimeDependencies", "taskIds"))
    else:
        # A historical release with no scheme retains its strict original hash.
        valid = dependencies.get("runtimeFingerprint") == (current or _runtime_fingerprint())
    if not valid:
        raise ApiError(f"{resource['name']} 的执行处理器已变化，请创建新草稿、重新测试并发布；历史结果仍可查看", code=409, status_code=409)


def _dependencies(conn, kind: str, content: dict) -> dict:
    result = {"skills": [], "mcps": [], "snapshot": [], "runtimeFingerprint": _runtime_fingerprint()}
    if content.get("fingerprintScheme") == "task-v2":
        from .tasks import task_definitions
        from .runtime import task_fingerprint
        ids = content.get("skillIds", []) if kind == "experts" else [content.get("id")] if kind == "skills" else None
        task_ids = [t["taskId"] for t in task_definitions() if t["available"] and (ids is None or t["skillId"] in ids)]
        result.update(task_fingerprint(task_ids))
    seen = set()

    def add(dep):
        key = (dep["kind"], dep["id"], dep["version"])
        if key in seen:
            return
        if not dep["enabled"]:
            raise ApiError(f"依赖 {dep['name']} 已停用", code=409, status_code=409)
        seen.add(key)
        result[dep["kind"]].append({key: dep[key] for key in ("id", "name", "version", "content")})
        result["snapshot"].append({"kind": dep["kind"], "id": dep["id"], "version": dep["version"], "enabled": True})

    if kind == "experts":
        for skill_id in content.get("skillIds", []):
            skill = _version(conn, "skills", skill_id)
            _require_runtime_version(skill)
            add(skill)
            for pinned in skill["dependencies"].get("mcps", []):
                add(_version(conn, "mcps", pinned["id"], pinned["version"]))
    elif kind == "skills":
        for binding in content.get("toolBindings", []):
            server_id = binding.get("serverId")
            tool_name = binding.get("toolName")
            server = _version(conn, "mcps", server_id)
            tools = server["content"].get("tools", [])
            names = {tool if isinstance(tool, str) else tool.get("name") for tool in tools}
            if tool_name not in names:
                raise ApiError(f"MCP {server_id} 未声明工具 {tool_name}", code=409, status_code=409)
            add(server)
    result["snapshot"].sort(key=lambda item: (item["kind"], item["id"], item["version"]))
    return result


def _validate_content(kind, content):
    from .runtime import HANDLERS
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    if len(_json(content).encode("utf-8")) > 200_000:
        raise ApiError("资源定义过大", status_code=422)
    if not isinstance(content.get("name"), str) or not content["name"].strip():
        raise ApiError("请填写资源名称", status_code=422)
    if kind == "experts":
        if content.get("expertCode", content.get("id")) != content.get("id"):
            raise ApiError("专家编码必须与稳定标识一致，创建后不可修改", status_code=422)
        if content.get("executionMode", "deterministic") not in {"deterministic", "llm"}:
            raise ApiError("专家执行方式无效", status_code=422)
        if content.get("executionMode") == "llm" and not content.get("modelId"):
            raise ApiError("请选择大模型", status_code=422)
        if content.get("expertType", "single") not in {"single", "orchestrator"}:
            raise ApiError("专家类型无效", status_code=422)
        limit = content.get("maxIters")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000):
            raise ApiError("迭代上限应为1至1000的整数", status_code=422)
        if "sandboxEnabled" in content and not isinstance(content["sandboxEnabled"], bool):
            raise ApiError("沙箱开关必须为布尔值", status_code=422)
        children = content.get("childExpertIds", [])
        if not isinstance(children, list) or any(not isinstance(x, str) for x in children) or len(set(children)) != len(children):
            raise ApiError("子专家列表格式无效或重复", status_code=422)
        if content.get("id") in children:
            raise ApiError("专家不能编排自身", status_code=422)
        if content.get("expertType") == "orchestrator" and not children:
            raise ApiError("编排专家至少选择一个子专家", status_code=422)
        ids = content.get("skillIds", [])
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
            raise ApiError("Skill 绑定格式无效或重复", status_code=422)
    if kind == "skills":
        tools = content.get("toolBindings", [])
        if not isinstance(tools, list) or any(not isinstance(b, dict) or not b.get("serverId") or not b.get("toolName") for b in tools):
            raise ApiError("工具绑定格式无效", status_code=422)
        execution = content.get("execution") or {}
        handler, processor = execution.get("handler"), execution.get("processorId")
        if processor:
            from .tasks import PROCESSORS
            if handler or processor not in PROCESSORS:
                raise ApiError("只能选择一个已登记的业务处理器", status_code=422)
            if not tools:
                raise ApiError("业务处理器必须声明使用的只读工具", status_code=422)
        else:
            if handler not in HANDLERS | {"unavailable"}:
                raise ApiError("只能选择已登记的执行方法", status_code=422)
            if handler != "unavailable" and not any(t["toolName"] == handler for t in tools):
                raise ApiError("执行方法必须绑定到已登记工具", status_code=422)
    if kind == "mcps" and content.get("accessType", "internal") != "internal":
        from urllib.parse import urlparse
        if content.get("accessType") not in {"native", "http"}:
            raise ApiError("MCP接入类型无效", status_code=422)
        url = urlparse(content.get("serviceUrl", ""))
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ApiError("请填写不含账号密码的HTTP或HTTPS服务地址", status_code=422)
        if content.get("transport") not in {"sse", "streamable-http", "http"}:
            raise ApiError("连接方式无效", status_code=422)
        headers = content.get("requestHeaders", [])
        if not isinstance(headers, list) or len(headers) > 30:
            raise ApiError("请求头格式无效", status_code=422)
        names = []
        for header in headers:
            if not isinstance(header, dict) or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", header.get("name", "")):
                raise ApiError("请填写合法请求头名称", status_code=422)
            value = header.get("value", "")
            if not isinstance(value, str) or not value or '\r' in value or '\n' in value:
                raise ApiError("请求头值不能为空或包含换行", status_code=422)
            names.append(header["name"].lower())
        if len(set(names)) != len(names):
            raise ApiError("请求头名称不能重复", status_code=422)
    if kind == "mcps" and content.get("accessType", "internal") == "internal":
        tools = content.get("tools", [])
        if not isinstance(tools, list) or any(not isinstance(t, dict) or t.get("name") not in HANDLERS for t in tools):
            raise ApiError("MCP 只能声明已实现的只读工具", status_code=422)
        if (content.get("transport", "internal") != "internal"
                or content.get("endpoint", "/api/admin/expert-resources/mcp") not in {
                    "/api/admin/expert-resources/mcp",
                    "/api/admin/expert-resources/mcp?server_id=" + str(content.get("id", ""))}):
            raise ApiError("当前只支持已接通的内置 MCP 地址与传输配置", status_code=422)
        registry = json.loads((CODE / "expert-resources/catalog.json").read_text(encoding="utf-8"))
        registered = {tool["name"]: tool for server in registry["mcps"] for tool in server["tools"]}
        for tool in tools:
            contract = registered.get(tool["name"], {})
            for schema in ("inputSchema", "outputSchema"):
                if tool.get(schema) != contract.get(schema):
                    raise ApiError("MCP 工具契约须与已实现处理器一致；调整契约需要同步开发和验证", status_code=422)
    def local_references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (not isinstance(item, str) or not item.startswith("#")):
                    raise ApiError("Schema 只允许本地引用", status_code=422)
                local_references(item)
        elif isinstance(value, list):
            for item in value:
                local_references(item)
    for holder in [content, *(content.get("tools", []) if kind == "mcps" else [])]:
        for field in ("inputSchema", "outputSchema"):
            if field in holder:
                try:
                    local_references(holder[field])
                    Draft202012Validator.check_schema(holder[field])
                except SchemaError:
                    raise ApiError(f"{field} 不是有效的 JSON Schema", status_code=422) from None


def _validate_references(conn, kind, content):
    if kind == "experts":
        for expert_id in content.get('childExpertIds', []):
            _row(conn, 'experts', expert_id)
        visited = set()
        def visit(expert_id):
            if expert_id == content.get('id'):
                raise ApiError('子专家关系不能形成循环', status_code=422)
            if expert_id in visited:
                return
            visited.add(expert_id)
            child = json.loads(_row(conn, 'experts', expert_id)['content'])
            for nested in child.get('childExpertIds', []):
                visit(nested)
        for expert_id in content.get('childExpertIds', []):
            visit(expert_id)
        for skill_id in content.get("skillIds", []) + content.get("plannedSkillIds", []):
            _row(conn, "skills", skill_id)
    if kind == "skills":
        for binding in content.get("toolBindings", []):
            target = _row(conn, "mcps", binding["serverId"])
            declared = {t.get("name") for t in json.loads(target["content"]).get("tools", []) if isinstance(t, dict)}
            if binding["toolName"] not in declared:
                raise ApiError("所选 MCP 没有声明该工具", status_code=422)


def _next_version(version):
    parts = version.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{int(parts[1]) + 1}.0"
    return version + ".1"


def _run_view(conn, row, actor, dependencies):
    if not row["run_id"]:
        return None
    run = conn.execute("SELECT * FROM er_run WHERE id=?", (row["run_id"],)).fetchone()
    if not run:
        return None
    outcome = json.loads(run["outcome"])
    executed_dependencies = json.loads(run["dependencies"])
    valid = (run["revision"] == row["revision"] and dependencies is not None
             and executed_dependencies.get("snapshot") == dependencies.get("snapshot")
             and executed_dependencies.get("runtimeFingerprint") == dependencies.get("runtimeFingerprint"))
    view = {**outcome, "runId": run["id"], "revision": run["revision"], "createdAt": run["created_at"],
            "valid": valid, "input": json.loads(run["input"]),
            "dependencySnapshot": executed_dependencies.get("snapshot", []),
            "runtimeFingerprint": executed_dependencies.get("runtimeFingerprint")}
    if actor is None or not _owns(run, actor):
        # Catalog metadata is shared, but execution data must not cross identities/scopes.
        view = {key: view[key] for key in ("runId", "revision", "createdAt", "valid", "status")}
        view.update({"redacted": True, "summary": "测试记录属于其他工作身份或数据范围"})
    return view


def _capability_block(kind, content):
    if kind == 'mcps' and content.get('accessType', 'internal') != 'internal':
        return '外部MCP配置已保存，协议连接与工具发现执行器尚未接入，不能测试或发布'
    if kind == 'experts' and content.get('executionMode') == 'llm':
        from .model_adapter import available_models
        if not any(m['id'] == content.get('modelId') for m in available_models()['items']):
            return '尚未配置与此专家一致的真实大模型，不能测试或发布'
    if kind == 'experts' and content.get('sandboxEnabled'):
        return '尚未接入通用沙箱，不能以已启用沙箱的配置测试或发布'
    if kind == 'experts' and content.get('expertType') == 'orchestrator':
        return '编排配置已保存，多专家执行器尚未接入，不能测试或发布'
    return None


def _redact_content(content):
    result = deepcopy(content)
    for header in result.get('requestHeaders', []):
        header['hasValue'] = bool(header.get('value'))
        header['value'] = ''
    return result


def _present(conn, row, actor=None):
    content = json.loads(row["content"])
    reasons = []
    capability = _capability_block(row["kind"], content)
    if capability:
        reasons.append(capability)
    deps = None
    try:
        deps = _dependencies(conn, row["kind"], content)
    except ApiError as exc:
        reasons.append(exc.msg)
    test = _run_view(conn, row, actor, deps)
    review = json.loads(row["review"]) if row["review"] else None
    if row["deleted_at"]:
        reasons.append("资源已删除")
    if not row["enabled"]:
        reasons.append("资源已停用")
    missing = content.get("missingEvidence") or []
    if missing:
        reasons.append("资源仍缺少必要业务材料或规则")
    if (content.get("execution") or {}).get("handler") == "unavailable":
        reasons.append("执行方法尚不可用")
    if row["kind"] == "experts" and not content.get("skillIds"):
        reasons.append("请至少绑定一个 Skill")
    if not test or test.get("status") != "passed" or not test.get("valid"):
        reasons.append("当前草稿尚未通过有效的真实测试")
        if row["published_version"] == row["draft_version"]:
            reasons.append("已发布版本不能覆盖，请先新建版本草稿，再重新测试与发布")
    if test and test.get("redacted"):
        reasons.append("请在当前身份与数据范围重新测试")
    if row["kind"] != "mcps" and (not review or not review.get("accepted") or not test or review.get("runId") != test["runId"]):
        reasons.append("尚未完成当前测试结果的业务复核")
    draft = {"version": row["draft_version"], "revision": row["revision"], "content": _redact_content(content)}
    if test:
        draft["test"] = test
    if review:
        # Reviewer note may contain an interpretation of scoped results.
        draft["review"] = review if test and not test.get("redacted") else {"accepted": review.get("accepted"), "redacted": True}
    published = None
    if row["published_version"]:
        v = _version(conn, row["kind"], row["id"], row["published_version"], include_deleted=True)
        published = {key: v[key] for key in ("version", "content", "publishedAt", "dependencies")}
        published["content"] = _redact_content(published["content"])
    run_reasons = []
    if row['kind'] == 'experts':
        if row['deleted_at']:
            run_reasons.append('资源已删除')
        elif not row['enabled']:
            run_reasons.append('专家已停用')
        if not published:
            run_reasons.append('专家尚未发布')
        else:
            try:
                _live_dependencies(conn, row['id'], published['version'], published['dependencies'])
            except ApiError as exc:
                run_reasons.append(exc.msg)
    from .metadata import policy_domains
    return {"id": row["id"], "kind": row["kind"], "policyDomains": policy_domains(row['id']) if row['kind'] == 'skills' else [], "name": content.get("name", row["id"]),
            "summary": content.get("summary", ""), "category": content.get("category", ""),
            "draft": draft, "published": published, "enabled": bool(row["enabled"]),
            "deletedAt": row["deleted_at"], "updatedAt": row['updated_at'], "references": _references(conn, row["kind"], row["id"]),
            "dependencies": deps or {"skills": [], "mcps": [], "snapshot": []},
            "readiness": {"canPublish": not reasons, "reasons": reasons,
                          "canRun": row['kind'] == 'experts' and not run_reasons,
                          "runReasons": run_reasons}}


def catalog(actor=None):
    with _db() as conn:
        result = {kind: [] for kind in KINDS}
        for row in conn.execute("SELECT * FROM er_resource WHERE deleted_at IS NULL ORDER BY rowid"):
            result[row["kind"]].append(_present(conn, row, actor))
        return result


def get_resource(kind, resource_id, actor=None):
    with _db() as conn:
        return _present(conn, _row(conn, kind, resource_id), actor)



def _references(conn, kind, resource_id):
    """Reverse links of editable drafts and live published definitions, never research contents."""
    kind = _kind(kind)
    items = []
    def uses(content, deps=None):
        if kind == 'experts':
            return resource_id in content.get('childExpertIds', [])
        if kind == "skills":
            return resource_id in content.get("skillIds", []) + content.get("plannedSkillIds", [])
        if kind == "mcps":
            return (any(b.get("serverId") == resource_id for b in content.get("toolBindings", []))
                    or any(d.get("id") == resource_id for d in (deps or {}).get("mcps", [])))
        return False
    for row in conn.execute("SELECT * FROM er_resource WHERE deleted_at IS NULL"):
        if row["kind"] == kind and row["id"] == resource_id:
            continue
        content = json.loads(row["content"])
        base = {"kind": row["kind"], "id": row["id"], "name": content.get("name", row["id"])}
        if uses(content):
            items.append({**base, "relation": "draft", "version": row["draft_version"]})
        if row["published_version"]:
            version = conn.execute("SELECT * FROM er_version WHERE kind=? AND resource_id=? AND version=?",
                                   (row["kind"], row["id"], row["published_version"])).fetchone()
            if version and uses(json.loads(version["content"]), json.loads(version["dependencies"])):
                items.append({**base, "relation": "published", "version": row["published_version"]})
    history_count = conn.execute("SELECT count(*) FROM er_version WHERE kind=? AND resource_id=?", (kind, resource_id)).fetchone()[0]
    for row in conn.execute("SELECT expert_id,dependencies FROM er_research"):
        deps = json.loads(row["dependencies"])
        if (kind == "experts" and row["expert_id"] == resource_id) or any(d.get("id") == resource_id for d in deps.get(kind, [])):
            history_count += 1
    return {"items": items, "historyCount": history_count, "canDelete": not items}


def references(kind, resource_id):
    with _db() as conn:
        _row(conn, kind, resource_id, include_deleted=True)
        return _references(conn, kind, resource_id)


def _new_id(kind, resource_id):
    value = resource_id or f"{kind[:-1]}-{uuid4().hex[:12]}"
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,99}", value):
        raise ApiError("标识须以小写字母开头，仅含小写字母、数字、短横线或下划线，最长100字符", status_code=422)
    return value


def _insert_resource(conn, kind, resource_id, content, actor):
    if kind == "mcps":
        content["endpoint"] = "/api/admin/expert-resources/mcp?server_id=" + resource_id
    _validate_content(kind, content)
    _validate_references(conn, kind, content)
    if conn.execute("SELECT 1 FROM er_resource WHERE kind=? AND id=?", (kind, resource_id)).fetchone():
        raise ApiError("资源标识已存在（含已删除资源），请使用其他标识", code=409, status_code=409)
    conn.execute("""INSERT INTO er_resource(kind,id,revision,draft_version,content,enabled,updated_at)
                    VALUES (?,?,1,'1.0.0',?,1,?)""", (kind, resource_id, _json(content), _now()))
    return _present(conn, _row(conn, kind, resource_id), actor)


def create_resource(kind, name, actor, resource_id=None, template_id=None, category="", summary="", extra_content=None):
    _identity(actor)
    kind = _kind(kind)
    resource_id = _new_id(kind, resource_id)
    with _db(write=True) as conn:
        if template_id:
            content = deepcopy(json.loads(_row(conn, kind, template_id)["content"]))
        elif kind == "experts":
            content = {"skillIds": [], "responsibilities": [], "boundaries": []}
        elif kind == "skills":
            content = {"execution": {"handler": "unavailable"}, "toolBindings": [],
                       "missingEvidence": ["尚未接入可执行处理方法，需要开发实现并验证"],
                       "inputSchema": {"type": "object", "additionalProperties": False},
                       "outputSchema": {"type": "object"}, "steps": []}
        else:
            content = {"tools": [], "accessType": "native", "transport": "sse"}
        content.update(extra_content or {})
        content.update({"id": resource_id, "name": name, "category": category, "summary": summary})
        if kind == "experts":
            content["expertCode"] = resource_id
        return _insert_resource(conn, kind, resource_id, content, actor)


def copy_resource(kind, resource_id, revision, name, actor, new_id=None):
    _identity(actor)
    kind = _kind(kind)
    with _db(write=True) as conn:
        row = _row(conn, kind, resource_id)
        _revision(row, revision)
        content = deepcopy(json.loads(row["content"]))
        target_id = _new_id(kind, new_id)
        content.update({"id": target_id, "name": name})
        if kind == 'experts':
            content['expertCode'] = target_id
        return _insert_resource(conn, kind, target_id, content, actor)


def delete_resource(kind, resource_id, revision, actor):
    _identity(actor)
    with _db(write=True) as conn:
        row = _row(conn, kind, resource_id)
        _revision(row, revision)
        refs = _references(conn, kind, resource_id)
        if refs["items"]:
            names = sorted({item["name"] for item in refs["items"]})
            raise ApiError("资源仍被引用，请先处理关联资源：" + "、".join(names), code=409, status_code=409)
        conn.execute("""UPDATE er_resource SET deleted_at=?,enabled=0,revision=revision+1,
                        run_id=NULL,review=NULL,updated_at=? WHERE kind=? AND id=?""",
                     (_now(), _now(), _kind(kind), resource_id))
        return _present(conn, _row(conn, kind, resource_id, include_deleted=True), actor)


def restore_resource(kind, resource_id, revision, actor):
    _identity(actor)
    with _db(write=True) as conn:
        row = _row(conn, kind, resource_id, include_deleted=True)
        _revision(row, revision)
        if not row["deleted_at"]:
            raise ApiError("资源未删除，无需恢复", code=409, status_code=409)
        _validate_references(conn, _kind(kind), json.loads(row["content"]))
        conn.execute("""UPDATE er_resource SET deleted_at=NULL,enabled=0,revision=revision+1,
                        run_id=NULL,review=NULL,updated_at=? WHERE kind=? AND id=?""", (_now(), _kind(kind), resource_id))
        return _present(conn, _row(conn, kind, resource_id), actor)


def archived(kind=None, actor=None):
    with _db() as conn:
        query = "SELECT * FROM er_resource WHERE deleted_at IS NOT NULL"
        params = ()
        if kind:
            query += " AND kind=?"
            params = (_kind(kind),)
        return {"items": [_present(conn, row, actor) for row in conn.execute(query + " ORDER BY updated_at DESC", params)]}

def save_resource(kind, resource_id, revision, content, actor=None):
    kind = _kind(kind)
    with _db(write=True) as conn:
        row = _row(conn, kind, resource_id)
        _revision(row, revision)
        existing_content = json.loads(row["content"])
        content = deepcopy(content)
        if kind == "mcps":
            previous = {h["name"].lower(): h.get("value", "") for h in existing_content.get("requestHeaders", [])}
            for h in content.get("requestHeaders", []):
                if h.get("hasValue") and not h.get("value"):
                    h["value"] = previous.get(h.get("name", "").lower(), "")
                h.pop("hasValue", None)
        _validate_content(kind, content)
        if content.get("id", resource_id) != resource_id or ("id" in existing_content and content.get("id") != existing_content["id"]):
            raise ApiError("资源标识不能修改", status_code=422)
        _validate_references(conn, kind, content)
        version = _next_version(row["draft_version"]) if row["published_version"] == row["draft_version"] else row["draft_version"]
        conn.execute("""UPDATE er_resource SET revision=revision+1,draft_version=?,content=?,run_id=NULL,
            review=NULL,updated_at=? WHERE kind=? AND id=?""", (version, _json(content), _now(), kind, resource_id))
        return _present(conn, _row(conn, kind, resource_id), actor)


def install_package(package, actor, resource_id=None, revision=None, display_name='', category=''):
    _identity(actor)
    metadata = package['frontMatter']
    target = resource_id or metadata['name']
    if resource_id and target != metadata['name']:
        raise ApiError('更新包的name必须与技能标识一致', status_code=422)
    with _db(write=True) as conn:
        existing = conn.execute('SELECT * FROM er_resource WHERE kind=? AND id=?', ('skills', target)).fetchone()
        if existing:
            row = _row(conn, 'skills', target)
            if revision is None:
                raise ApiError('技能标识已存在，更新需提供revision', code=409, status_code=409)
            _revision(row, revision)
            if conn.execute('SELECT 1 FROM er_version WHERE kind=? AND resource_id=? AND version=?', ('skills', target, metadata['version'])).fetchone():
                raise ApiError('该技能版本已发布，不能覆盖', code=409, status_code=409)
            content = json.loads(row['content'])
        else:
            if resource_id:
                raise ApiError('待更新技能不存在', status_code=404)
            content = {'id': target, 'execution': {'handler': 'unavailable'}, 'toolBindings': [],
                       'inputSchema': {'type': 'object'}, 'outputSchema': {'type': 'object'}, 'steps': [],
                       'missingEvidence': ['技能包已解析，执行器尚未接入；上传脚本不会自动运行']}
        content.update({'name': display_name or metadata['name'], 'summary': metadata['description'],
                        'category': category, 'package': package, 'skillType': package['skillType']})
        content['execution'] = {'handler': 'unavailable'}
        content['missingEvidence'] = ['技能包已解析，执行器尚未接入；上传脚本不会自动运行']
        _validate_content('skills', content)
        if existing:
            conn.execute('UPDATE er_resource SET content=?,draft_version=?,revision=revision+1,run_id=NULL,review=NULL,updated_at=? WHERE kind=? AND id=?',
                         (_json(content), metadata['version'], _now(), 'skills', target))
        else:
            _insert_resource(conn, 'skills', target, content, actor)
            conn.execute('UPDATE er_resource SET draft_version=? WHERE kind=? AND id=?', (metadata['version'], 'skills', target))
        return _present(conn, _row(conn, 'skills', target), actor)


def _execute(kind, content, inputs, actor, dependencies, executor: Callable | None = None):
    from .runtime import execute_resource
    if executor is None:
        executor = execute_resource
    block = _capability_block(kind, content)
    if block:
        return {"status": "blocked", "summary": block, "result": None, "trace": [], "missingEvidence": [block]}
    if executor is execute_resource and kind == 'experts' and content.get('executionMode') == 'llm':
        from .model_adapter import route, explain
        from .tasks import run_task
        expert = {'id': content['id'], 'version': content.get('version', 'candidate'), 'content': content}
        request = {'question': inputs.get('question', ''), 'input': {k: v for k, v in inputs.items() if k != 'question'}}
        routing = route(expert, dependencies, request)
        if routing.get('clarification'):
            return {'status': 'blocked', 'summary': routing['clarification']['question'], 'result': None,
                    'clarification': routing['clarification'], 'missingEvidence': [], 'trace': []}
        return explain(expert, dependencies, request, run_task(routing['taskId'], routing['input'], actor, dependencies))
    result = executor(kind, content, inputs, actor, dependencies)
    if not isinstance(result, dict) or result.get("status") not in {"passed", "blocked", "failed"}:
        raise ApiError("执行器没有返回有效结果，未记录为成功", status_code=503)
    return result


def test_resource(kind, resource_id, revision, inputs, actor, executor=None):
    kind = _kind(kind)
    owner, identity, fingerprint = _identity(actor)
    run_id = str(uuid4())
    with _db(write=True) as conn:
        row = _row(conn, kind, resource_id)
        _revision(row, revision)
        content = json.loads(row["content"])
        try:
            dependencies = _dependencies(conn, kind, content)
            dependency_error = None
        except ApiError as exc:
            dependencies = {"skills": [], "mcps": [], "snapshot": [], "runtimeFingerprint": _runtime_fingerprint()}
            dependency_error = exc.msg
        if not row["enabled"]:
            dependency_error = "资源已停用，请先启用后测试"
        # Reserving the run clears prior acceptance before any fallible I/O.
        # A slower earlier request cannot overwrite a newer test's result.
        conn.execute("UPDATE er_resource SET run_id=?,review=NULL,updated_at=? WHERE kind=? AND id=?",
                     (run_id, _now(), kind, resource_id))
    if dependency_error:
        outcome = {"status": "blocked", "summary": dependency_error, "result": None, "trace": [],
                   "missingEvidence": [dependency_error]}
    else:
        try:
            outcome = _execute(kind, content, inputs, actor, dependencies, executor)
        except ApiError as exc:
            if exc.status_code in {401, 403}:
                raise
            outcome = {"status": "blocked" if exc.status_code == 422 else "failed", "summary": exc.msg,
                       "result": None, "trace": [{"step": "执行测试", "status": "failed"}], "missingEvidence": []}
        except Exception as exc:
            logging.getLogger(__name__).error("Resource test failed (%s)", type(exc).__name__)
            outcome = {"status": "failed", "summary": "执行测试失败，请检查数据连接或服务配置后重试",
                       "result": None, "trace": [{"step": "执行测试", "status": "failed"}], "missingEvidence": []}
    if kind == "experts":
        selected = inputs.get("skill_id")
        if not selected and len(dependencies["skills"]) == 1:
            selected = dependencies["skills"][0]["id"]
        outcome["coverage"] = {"testedSkillIds": [selected] if selected else [],
                               "publishedSkillIds": [s["id"] for s in dependencies["skills"]],
                               "note": "本次专家测试只覆盖所选方法；其余绑定方法使用各自已经测试并复核的发布版本。"}
    with _db(write=True) as conn:
        current = _row(conn, kind, resource_id)
        _revision(current, revision)
        if current["run_id"] != run_id:
            raise ApiError("已有更新的测试，请以最新测试结果为准", code=409, status_code=409)
        conn.execute("INSERT INTO er_run VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            run_id, kind, resource_id, revision, owner, identity, fingerprint, _json(inputs),
            _json(dependencies), _json(outcome), _now()))
        conn.execute("UPDATE er_resource SET run_id=?,review=NULL,updated_at=? WHERE kind=? AND id=?",
                     (run_id, _now(), kind, resource_id))
        return _present(conn, _row(conn, kind, resource_id), actor)


def review_resource(kind, resource_id, revision, run_id, accepted, note, actor):
    _identity(actor)
    with _db(write=True) as conn:
        row = _row(conn, kind, resource_id)
        _revision(row, revision)
        view = _present(conn, row, actor)
        test = view["draft"].get("test")
        if not test or test["runId"] != run_id or not test["valid"] or test.get("redacted"):
            raise ApiError("测试已变化或无权读取，请在当前范围重新测试", code=409, status_code=409)
        if accepted and test["status"] != "passed":
            raise ApiError("技术测试未通过，不能确认业务结果", code=409, status_code=409)
        if not note.strip():
            raise ApiError("请填写复核意见", status_code=422)
        review = {"runId": run_id, "accepted": accepted, "note": note.strip(),
                  "reviewer": actor.get("name") or actor["username"], "reviewedAt": _now()}
        conn.execute("UPDATE er_resource SET review=?,updated_at=? WHERE kind=? AND id=?",
                     (_json(review), _now(), _kind(kind), resource_id))
        return _present(conn, _row(conn, kind, resource_id), actor)


def publish_resource(kind, resource_id, revision, actor):
    owner, _, _ = _identity(actor)
    with _db(write=True) as conn:
        row = _row(conn, kind, resource_id)
        _revision(row, revision)
        view = _present(conn, row, actor)
        if row["published_version"] == row["draft_version"]:
            return view
        if not view["readiness"]["canPublish"]:
            raise ApiError("；".join(view["readiness"]["reasons"]), code=409, status_code=409)
        conn.execute("INSERT INTO er_version VALUES (?,?,?,?,?,?,?,?,?)", (
            _kind(kind), resource_id, row["draft_version"], row["content"], _json(view["dependencies"]),
            _now(), owner, row["run_id"], row["review"]))
        conn.execute("UPDATE er_resource SET published_version=draft_version,updated_at=? WHERE kind=? AND id=?",
                     (_now(), _kind(kind), resource_id))
        return _present(conn, _row(conn, kind, resource_id), actor)


def set_enabled(kind, resource_id, enabled, actor=None):
    with _db(write=True) as conn:
        _row(conn, kind, resource_id)
        conn.execute("UPDATE er_resource SET enabled=?,updated_at=? WHERE kind=? AND id=?",
                     (int(enabled), _now(), _kind(kind), resource_id))
        return _present(conn, _row(conn, kind, resource_id), actor)


def _live_dependencies(conn, expert_id, expert_version, dependencies):
    expert = _version(conn, "experts", expert_id, expert_version)
    current_runtime = _runtime_fingerprint()
    _require_runtime_version(expert, current_runtime)
    if not expert["enabled"]:
        raise ApiError("该专家已停用，历史可读，不能继续调用", code=409, status_code=409)
    for kind in ("skills", "mcps"):
        for dep in dependencies.get(kind, []):
            live = _version(conn, kind, dep["id"], dep["version"])
            if kind == "skills":
                _require_runtime_version(live, current_runtime)
            if not live["enabled"]:
                raise ApiError(f"依赖 {live['name']} 已停用，不能继续调用", code=409, status_code=409)
    return expert


def _research_row(conn, research_id, actor):
    row = conn.execute("SELECT * FROM er_research WHERE id=?", (research_id,)).fetchone()
    if not row or not _owns(row, actor):
        raise ApiError("研究不存在或当前身份无权访问", code=404, status_code=404)
    return row


def _research_view(conn, row):
    turns = []
    for item in conn.execute("SELECT * FROM er_turn WHERE research_id=? ORDER BY ordinal", (row["id"],)):
        outcome = json.loads(item["outcome"])
        result = outcome.get('result')
        if isinstance(result, dict):
            for evidence in result.get('evidence', []):
                evidence.pop('records', None)
            if not outcome.get('execution'):
                result['resultId'] = 'legacy:' + item['id']
                outcome['legacy'] = True
        raw = json.loads(item['input'])
        execution_id = outcome.get('executionId') or outcome.get('execution', {}).get('executionId')
        execution = outcome.get('execution')
        if execution_id and not execution:
            ex = conn.execute('SELECT state,summary FROM er_execution WHERE id=?', (execution_id,)).fetchone()
            if ex:
                execution = {'id': execution_id, 'state': ex['state']}
                outcome['summary'] = ex['summary']
        identity = outcome.get('expert') or {}
        if not identity:
            expert_id = raw.get('expertId') or row['expert_id']
            version = row['expert_version'] if expert_id == row['expert_id'] else None
            frozen = conn.execute('SELECT content FROM er_version WHERE kind=\'experts\' AND resource_id=? AND version=?', (expert_id, version)).fetchone() if version else None
            identity = {'id': expert_id, 'name': json.loads(frozen['content']).get('name') if frozen else None,
                        'version': version, 'legacy': True}
        turns.append({"id": item["id"], "question": item["question"], "expertId": identity.get('id'),
                      "expertName": identity.get('name'), "expertVersion": identity.get('version'), "expert": identity,
                      "input": raw.get('input', raw),
                      **outcome, "execution": execution, "createdAt": item["created_at"]})
    return {"id": row["id"], "title": row["title"], "expertId": row["expert_id"],
            "expertVersion": row["expert_version"], "dependencies": json.loads(row["dependencies"]),
            "input": json.loads(row["input"]), "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            "turns": turns}


def get_research(research_id, actor):
    with _db() as conn:
        view = _research_view(conn, _research_row(conn, research_id, actor))
        # Current validity is read metadata; keep the saved facts immutable.
        from .execution import _history_entry
        turns = {turn['id']: turn for turn in view['turns']}
        for row in conn.execute('SELECT * FROM er_turn WHERE research_id=? ORDER BY ordinal', (research_id,)):
            context = _history_entry(conn, row, actor)
            for key in ('referenceState', 'referenceReason'):
                if key in context:
                    turns[row['id']][key] = context[key]
        return view


def list_research(actor, search='', offset=0, limit=50):
    owner, identity, fingerprint = _identity(actor)
    where = "r.owner=? AND r.identity_id=? AND r.scope_fingerprint=? AND r.purpose='personal'"
    params = [owner, identity, fingerprint]
    if search.strip():
        where += " AND r.title LIKE ? ESCAPE '\\'"
        params.append('%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    with _db() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM er_research r WHERE {where}',params).fetchone()[0]
        items = conn.execute(f"""SELECT r.*, (SELECT count(*) FROM er_turn t WHERE t.research_id=r.id) AS turn_count,
            (SELECT outcome FROM er_turn t WHERE t.research_id=r.id ORDER BY ordinal DESC LIMIT 1) AS last_outcome
            FROM er_research r WHERE {where} ORDER BY updated_at DESC,r.id DESC LIMIT ? OFFSET ?""",
            [*params,limit,offset]).fetchall()
        result=[]
        for row in items:
            last=json.loads(row['last_outcome'] or '{}'); expert=last.get('expert') or {}
            result.append({'id':row['id'],'title':row['title'],'expertId':expert.get('id',row['expert_id']),
                'expertName':expert.get('name'),'expertVersion':expert.get('version',row['expert_version']),
                'createdAt':row['created_at'],'updatedAt':row['updated_at'],
                'status':last.get('status','blocked'),'turnCount':row['turn_count']})
        return {'items':result,'total':total,'offset':offset,'limit':limit}


def create_research(expert_id, inputs, question, actor, executor=None):
    owner, identity, fingerprint = _identity(actor)
    with _db() as conn:
        expert = _version(conn, "experts", expert_id)
        if expert['content'].get('executionMode') == 'llm':
            raise ApiError('模型分析请使用任务执行接口，保留可取消与授权核验流程', code=409, status_code=409)
        dependencies = expert["dependencies"]
        _live_dependencies(conn, expert_id, expert["version"], dependencies)
    execution_input = {**inputs, "question": question}
    outcome = _execute("experts", expert["content"], execution_input, actor, dependencies, executor)
    research_id, turn_id, now = str(uuid4()), str(uuid4()), _now()
    with _db(write=True) as conn:
        _live_dependencies(conn, expert_id, expert["version"], dependencies)
        conn.execute("INSERT INTO er_research (id,owner,identity_id,scope_fingerprint,title,expert_id,expert_version,dependencies,input,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            research_id, owner, identity, fingerprint, question.strip()[:100], expert_id, expert["version"],
            _json(dependencies), _json(inputs), now, now))
        conn.execute("INSERT INTO er_turn (id,research_id,ordinal,question,input,outcome,created_at) VALUES (?,?,?,?,?,?,?)", (turn_id, research_id, 1, question,
                     _json(inputs), _json(outcome), now))
        return _research_view(conn, _research_row(conn, research_id, actor))


def add_turn(research_id, inputs, question, actor, executor=None):
    with _db() as conn:
        row = _research_row(conn, research_id, actor)
        dependencies = json.loads(row["dependencies"])
        expert = _live_dependencies(conn, row["expert_id"], row["expert_version"], dependencies)
        if expert['content'].get('executionMode') == 'llm':
            raise ApiError('模型分析请使用任务执行接口', code=409, status_code=409)
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='er_execution'").fetchone():
            if conn.execute("SELECT 1 FROM er_execution WHERE research_id=? AND state IN ('queued','running')", (research_id,)).fetchone():
                raise ApiError('本研究仍有任务执行中，请先等待或取消', code=409, status_code=409)
        ordinal = conn.execute("SELECT count(*) FROM er_turn WHERE research_id=?", (research_id,)).fetchone()[0] + 1
        # The form submits the complete scope for each turn. Clearing a filter
        # or choosing a different method must not resurrect the previous scope.
        merged = dict(inputs)
    outcome = _execute("experts", expert["content"], {**merged, "question": question}, actor, dependencies, executor)
    with _db(write=True) as conn:
        row = _research_row(conn, research_id, actor)
        _live_dependencies(conn, row["expert_id"], row["expert_version"], dependencies)
        actual = conn.execute("SELECT count(*) FROM er_turn WHERE research_id=?", (research_id,)).fetchone()[0] + 1
        if ordinal != actual:
            raise ApiError("研究已有新回复，请刷新后继续", code=409, status_code=409)
        now = _now()
        conn.execute("INSERT INTO er_turn (id,research_id,ordinal,question,input,outcome,created_at) VALUES (?,?,?,?,?,?,?)", (str(uuid4()), research_id, ordinal,
                     question, _json(merged), _json(outcome), now))
        conn.execute("UPDATE er_research SET input=?,updated_at=? WHERE id=?", (_json(merged), now, research_id))
        return _research_view(conn, _research_row(conn, research_id, actor))

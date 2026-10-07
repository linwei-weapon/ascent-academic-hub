"""版本化需求与SQL登记；定义由需求资产驱动，不读取原业务计算接口。"""
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path

from backend.api.envelope import ApiError
from .config import ASSETS, database_config
from .database import validate_sql

_UNSET = object()
_revision = ContextVar("metric_mapping_revision", default=_UNSET)
_revision_scope = ContextVar("metric_mapping_revision_scope", default=None)


def _active_revision():
    from . import mapping_store
    value = _revision.get()
    if value is not _UNSET and _revision_scope.get() == mapping_store.scope():
        return value
    head = mapping_store.get_head()
    return mapping_store.get_revision(head["revisionId"]) if head["revisionId"] else None


@contextmanager
def revision_scope(revision_id: str | None = None, *, draft_allowed: bool = False):
    """Pin every registry lookup in one request; stale ordinary requests fail before any write."""
    from . import mapping_store
    head = mapping_store.get_head()
    active_id = head["revisionId"]
    if revision_id and revision_id != active_id and not draft_allowed:
        raise ApiError("映射版本已变化，请刷新后确认；已填写的人工内容可保留", status_code=409)
    selected = revision_id or active_id
    revision = mapping_store.get_revision(selected) if selected else None
    token = _revision.set(revision)
    scope_token = _revision_scope.set(mapping_store.scope())
    try:
        yield revision
    finally:
        _revision_scope.reset(scope_token)
        _revision.reset(token)


def current_revision_id() -> str | None:
    revision = _active_revision()
    return revision["revisionId"] if revision else None


def current_package() -> dict | None:
    revision = _active_revision()
    return deepcopy(revision["package"]) if revision else None


def current_revision() -> dict | None:
    return deepcopy(_active_revision())


def read_json(path: Path) -> dict:
    if not path.is_file():
        raise ApiError("核验登记数据尚未准备完成", status_code=503)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def catalog() -> dict:
    revision = _active_revision()
    if revision:
        from .mapping_adapter import catalog as adapt_catalog
        return adapt_catalog(revision)
    from .mapping_store import scope, MODULES
    module_id = scope()[1]
    if module_id != "teaching-overview":
        return {"schemaVersion": "3.1.0", "module": {"id": module_id, "name": MODULES[module_id]},
                "requirements": [], "metrics": [], "conflicts": [],
                "indicatorSystem": {"entries": [], "pages": [], "groups": []},
                "mappingRevisionId": None, "mappingQuestions": [],
                "mappingSummary": {"state": "not_registered", "metricCount": 0}}
    return read_json(ASSETS / "catalog" / "teaching-overview.json")


def requirements() -> dict:
    return {r["id"]: r for r in catalog()["requirements"]}


def requirement(requirement_id: str) -> dict:
    result = requirements().get(requirement_id)
    if not result:
        raise ApiError("未找到需求条目", code=404, status_code=404)
    return result


def scenario(scenario_id: str, requirement_id: str | None = None, metric_id: str | None = None,
             *, allow_evidence: bool = False) -> dict:
    entry = next((item for item in catalog().get("indicatorSystem", {}).get("entries", [])
                  if item["id"] == scenario_id), None)
    if not entry:
        raise ApiError("指标使用场景已变化，请重新加载目录", status_code=409)
    allowed = {entry["metricId"]}
    if allow_evidence:
        allowed.update(entry.get("evidenceMetricIds", []))
    if (requirement_id and entry["requirementId"] != requirement_id) or (metric_id and metric_id not in allowed):
        raise ApiError("指标、需求与使用场景不匹配", code=403, status_code=403)
    return entry


def scenario_checksum(scenario_id: str) -> str:
    document = catalog()
    entry = next((item for item in document.get("indicatorSystem", {}).get("entries", [])
                  if item["id"] == scenario_id), None)
    if not entry:
        raise ApiError("指标使用场景已变化，请重新加载目录", status_code=409)
    ids = {entry["metricId"], *entry.get("evidenceMetricIds", [])}
    if document.get("mappingRevisionId"):
        snapshot = {"scenarioId": entry["id"], "metricId": entry["metricId"], "requirementId": entry["requirementId"],
                    "comparisonKind": entry.get("comparisonKind"),
                    "signatures": {m["id"]: m["semanticSignature"] for m in document["metrics"] if m["id"] in ids}}
    else:
        snapshot = {"entry": entry, "metrics": [m for m in document["metrics"] if m["id"] in ids]}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def queries_document() -> dict:
    revision = _active_revision()
    if revision:
        from .mapping_adapter import queries_document as adapt_queries
        return adapt_queries(revision)
    from .mapping_store import scope
    if scope()[1] != "teaching-overview":
        return {"schemaVersion": "3.1.0", "mappingRevisionId": None, "metrics": []}
    return read_json(ASSETS / "queries" / "teaching-overview.json")


def load_sql(query: dict) -> dict:
    result = deepcopy(query)
    if result.get("sqlFile"):
        path = (ASSETS / result["sqlFile"]).resolve()
        if not path.is_relative_to((ASSETS / "sql").resolve()) or not path.is_file():
            raise ApiError("SQL登记文件路径无效", status_code=422)
        content = path.read_text(encoding="utf-8-sig")
        if result.get("sql") and content.strip() != result["sql"].strip():
            raise ApiError("SQL文件与登记文本不一致", status_code=409)
        result["sql"] = content
    if result.get("sql") is None and result.get("mappingRevisionId"):
        return {**result, "executable": False, "executionApproval": "blocked", "blockedReason": result.get("blockedReason") or "SQL尚未建立"}
    validate_sql(result.get("sql", ""))
    result["checksum"] = hashlib.sha256(result["sql"].encode()).hexdigest()
    return result


def metric_queries(metric_id: str, *, allow_execute: bool = False) -> dict:
    metrics = queries_document()["metrics"]
    found = next((m for m in metrics if m["metricId"] == metric_id), None)
    if not found:
        if any(m["id"] == metric_id for m in catalog()["metrics"]):
            return {"metricId": metric_id, "layers": [{
                "id": layer, "name": name, "tables": [], "grain": "待登记", "transform": [],
                "issues": ["该指标尚未建立数据库查询映射"], "status": "blocked", "queries": [],
            } for layer, name in (("source", "贴源层"), ("fact", "事实层"), ("application", "应用层"))]}
        raise ApiError("未找到指标", code=404, status_code=404)
    result = deepcopy(found)
    for layer in result["layers"]:
        config = database_config(layer["id"])
        raw = layer.get("queries", [])
        # The database dialect decides which documented variant can be selected.
        selected = [q for q in raw if q.get("dialect") == config.engine]
        layer["queries"] = []
        for item in selected:
            q = load_sql(item)
            reasons = []
            if q.get("executionApproval") != "documented":
                reasons.append(q.get("blockedReason") or "该计算口径尚未具备执行条件")
            if not config.configured:
                reasons.append("执行服务尚未配置可访问的测试数据库连接")
            if not allow_execute:
                reasons.append("当前身份没有全校数据库核验权限")
            q["executable"] = not reasons
            q["blockedReason"] = "；".join(reasons)
            layer["queries"].append(q)
        if not selected:
            layer.setdefault("issues", []).append("当前数据库方言没有已登记查询")
    return result


def find_query(query_id: str) -> dict:
    for metric in queries_document()["metrics"]:
        for layer in metric["layers"]:
            for q in layer.get("queries", []):
                if q["id"] == query_id:
                    return {**load_sql(q), "metricId": metric["metricId"], "layer": layer["id"],
                            **{key: layer.get(key, "") for key in ("mappingMode", "directSource", "metricResultStatus", "metricResultReason")}}
    raise ApiError("未找到SQL模板", code=404, status_code=404)


def requirement_checksum(requirement_id: str) -> str:
    """定义或关联指标口径变化后，旧结果不能作为新版本符合的依据。"""
    document = catalog()
    req = requirement(requirement_id)
    if document.get("mappingRevisionId"):
        snapshot = {"requirementId": req["id"], "signatures": {m["id"]: m["semanticSignature"] for m in document["metrics"] if m["id"] in req["metricIds"]}}
    else:
        snapshot = {"requirement": req, "metrics": [m for m in document["metrics"] if m["id"] in req["metricIds"]]}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

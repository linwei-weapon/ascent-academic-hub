"""指标核验原型服务：可在本机或能访问测试库的应用服务器运行。

启动位置 code/：python -m uvicorn backend.metric_verification.app:app --host 127.0.0.1 --port 8010
"""
from copy import deepcopy
import logging
import time
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ConfigDict

from backend.api.envelope import ApiError, ok, fail
from . import registry, store, evidence, mapping_store
from .auth import (current_actor, can_execute, require_execution, menu_for_actor,
                   can_manage_mapping, require_mapping_management, can_record, require_record)
from .config import load_environment, database_config, environment_name
from .database import connection, bind_parameters, execute_read
from .options import parameter_options
from .comparison import ComparisonInput, prepare as prepare_comparison
from .evidence_import import expected_draft
from .mapping_router import router as mapping_router

load_environment()
app = FastAPI(title="指标核验原型", version="3.1.0", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(mapping_router)
log = logging.getLogger("metric_verification")
PREFIX = "/api/admin/metric-verification"


@app.middleware("http")
async def mapping_snapshot(request: Request, call_next):
    path = request.url.path
    if not path.startswith(PREFIX):
        return await call_next(request)
    try:
        with mapping_store.module_scope(request.query_params.get("moduleId")):
            if (path.startswith(PREFIX + "/mapping/") or path == PREFIX + "/access"
                    or "/executions/" in path
                    or not request.headers.get("authorization", "").lower().startswith("bearer ")):
                return await call_next(request)
            body = await request.json() if request.method in {"POST", "PUT"} else {}
            if not isinstance(body, dict):
                body = {}
            revision = body.get("mappingRevisionId") or request.query_params.get("mappingRevisionId")
            draft = path.endswith("/execute") and body.get("executionUse") == "definition_validation"
            with registry.revision_scope(revision, draft_allowed=draft):
                return await call_next(request)
    except ApiError as exc:
        return JSONResponse(status_code=exc.status_code, content=fail(exc.msg, exc.code))
    except ValueError:
        return JSONResponse(status_code=422, content=fail("请求内容格式无效", 422))
    except Exception as exc:
        log.error("mapping_read_failure error_type=%s", type(exc).__name__)
        return JSONResponse(status_code=503, content=fail("指标映射版本暂不可用，请检查核验服务与数据库", 503))


@app.exception_handler(ApiError)
async def api_error(_request: Request, error: ApiError):
    return JSONResponse(status_code=error.status_code, content=fail(error.msg, error.code))


@app.exception_handler(Exception)
async def unexpected_error(_request: Request, error: Exception):
    # Driver exceptions can include credentials or host names: expose neither.
    log.error("verification_failure error_type=%s", type(error).__name__)
    return JSONResponse(status_code=503, content=fail("核验服务暂不可用，请检查数据库网络、配置及专用表迁移", 503))


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _error: RequestValidationError):
    return JSONResponse(status_code=422, content=fail("请求参数不符合核验接口要求", 422))


class ExecuteInput(BaseModel):
    requirementId: str = Field(min_length=1, max_length=120)
    scenarioId: str | None = Field(default=None, max_length=160)
    parameters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=50, ge=1, le=100)
    sqlVersion: str | None = None
    mappingRevisionId: str | None = None
    executionUse: Literal["verification", "definition_validation"] = "verification"
    validationCaseId: str | None = None


class RecordInput(BaseModel):
    requirementId: str = Field(min_length=1, max_length=120)
    metricId: str | None = Field(default=None, max_length=120)
    judgment: Literal["符合", "有差异", "条件不足"]
    comment: str = Field(min_length=1, max_length=5000)
    evidenceIds: list[str] = Field(default_factory=list, max_length=30)
    scenarioId: str | None = Field(default=None, max_length=160)
    comparison: ComparisonInput | None = None
    mappingRevisionId: str | None = None


class ImportInput(BaseModel):
    requirementId: str = Field(min_length=1, max_length=120)
    scenarioId: str = Field(min_length=1, max_length=160)
    executionId: str = Field(min_length=1, max_length=100)
    mappingRevisionId: str | None = None


class ExpectationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str = Field(min_length=1, max_length=200)
    basisRef: str | None = Field(default=None, max_length=1000)
    derivation: str = Field(min_length=1, max_length=10000)
    rows: list[dict[str, Any]] = Field(max_length=50)
    inputContentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resultKnownBeforeCalculation: bool


def capabilities(actor: dict) -> dict:
    permitted = can_execute(actor)
    source = database_config("source").configured
    analytics = database_config("application").configured
    limitations = []
    if not source:
        limitations.append("贴源库未配置可访问连接；原型可改为由数据库所在网络的应用服务执行SQL。")
    if not analytics:
        limitations.append("事实／应用库未配置可访问连接。")
    if not permitted:
        limitations.append("当前身份可查阅定义并记录人工核对；数据库执行限系统管理且拥有全校范围的身份。")
    records = can_record(actor) and analytics and store.table_ready()
    if not records:
        limitations.append("核验意见存储未就绪；需要可写业务连接及本模块专用表。")
    return {"execute": permitted and (source or analytics), "records": records, "mappingManage": can_manage_mapping(actor),
            "environment": environment_name(), "limitations": limitations,
            "connections": {"sourceConfigured": source, "analyticsConfigured": analytics}}


@app.get("/health")
def health():
    return ok({"status": "up", "module": "metric-verification"})


@app.get(PREFIX + "/access")
def access(actor: dict = Depends(current_actor)):
    return ok(menu_for_actor(actor))


@app.get(PREFIX + "/catalog")
def get_catalog(actor: dict = Depends(current_actor)):
    result = deepcopy(registry.catalog())
    result["capabilities"] = capabilities(actor)
    return ok(result)


@app.get(PREFIX + "/metrics/{metric_id}/queries")
def get_queries(metric_id: str, actor: dict = Depends(current_actor)):
    return ok(registry.metric_queries(metric_id, allow_execute=can_execute(actor)))


@app.get(PREFIX + "/schema/{layer}")
def get_schema(layer: Literal["source", "fact", "application"], actor: dict = Depends(current_actor)):
    require_execution(actor)
    config = database_config(layer)
    with connection(layer) as conn, conn.cursor() as cursor:
        if config.engine == "mysql":
            cursor.execute("SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,ORDINAL_POSITION")
            rows = cursor.fetchall()
        else:
            cursor.execute("SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,NULLABLE FROM USER_TAB_COLUMNS ORDER BY TABLE_NAME,COLUMN_ID")
            rows = [dict(zip(("TABLE_NAME", "COLUMN_NAME", "DATA_TYPE", "IS_NULLABLE"), row)) for row in cursor.fetchall()]
    return ok({"layer": layer, "dialect": config.engine, "columns": rows, "checkedAt": store.now()})


@app.post(PREFIX + "/queries/{query_id}/execute")
def execute_query(query_id: str, body: ExecuteInput, actor: dict = Depends(current_actor)):
    require_execution(actor)
    if body.executionUse == "definition_validation":
        require_mapping_management(actor)
    if body.validationCaseId and body.executionUse != "definition_validation":
        raise ApiError("独立核算用例必须使用定义验证用途", status_code=422)
    req = registry.requirement(body.requirementId)
    query = registry.find_query(query_id)
    if query["metricId"] not in req["metricIds"]:
        raise ApiError("该SQL的指标不属于当前需求", code=403, status_code=403)
    if body.sqlVersion and body.sqlVersion != query["version"]:
        raise ApiError("SQL版本已变化，请重新加载", status_code=409)
    if body.scenarioId:
        registry.scenario(body.scenarioId, body.requirementId, query["metricId"], allow_evidence=True)
    if query.get("executionApproval") != "documented" and not (
            body.executionUse == "definition_validation" and query.get("schemaOnlyBlocked") is True):
        raise ApiError(query.get("blockedReason") or "该SQL口径尚未确认", status_code=409)
    config = database_config(query["layer"])
    if query["dialect"] != config.engine:
        raise ApiError("SQL方言与数据源不一致", status_code=409)
    params = bind_parameters(query, body.parameters)
    result = {"id": str(uuid4()), "queryId": query_id, "requirementId": body.requirementId,
              "moduleId": mapping_store.scope()[1],
              "metricId": query["metricId"], "layer": query["layer"], "queryKind": query["kind"],
              "requirementChecksum": registry.requirement_checksum(body.requirementId),
              "executedAt": store.now(), "sqlVersion": query["version"], "parameters": params,
              "recordCount": None, "columns": [], "rows": [], "metrics": {}, "truncated": False}
    result.update(mappingRevisionId=registry.current_revision_id(), executionUse=body.executionUse)
    if body.scenarioId:
        result.update(scenarioId=body.scenarioId, scenarioChecksum=registry.scenario_checksum(body.scenarioId))
    result.update({key: query.get(key, "") for key in ("mappingMode", "directSource", "metricResultStatus", "metricResultReason")})
    started = time.perf_counter()
    retained = None
    try:
        if body.validationCaseId:
            retained = evidence.capture_case(query, params, body.validationCaseId, result, limit=body.limit)
            result.update(retainedEvidence=True, resultDisclosure="withheld", returnedRows=0,
                          message="输入与SQL结果已同时采集；提交独立预期后查看被测结果。")
        else:
            with connection(query["layer"]) as conn:
                if query.get("purpose") == "application_actual":
                    result.update(execute_read(conn, query, params, config.engine, body.limit, precise=True))
                else:
                    result.update(execute_read(conn, query, params, config.engine, body.limit))
            if query.get("purpose") == "application_actual":
                retained = evidence.capture_application(query, params, result, result)
                result.update(retainedEvidence=True, resultDisclosure="not_applicable")
        result["status"] = "success"
        if query["kind"] == "detail":
            # Same metric, layer and dialect; count is not the length of the
            # returned detail page. Both queries use the same read transaction
            # in a future snapshot request; this response does not fake a total.
            result["message"] = "明细按上限返回；完整记录数请执行同条件的记录数SQL。"
    except ApiError as exc:
        result.update(status="error", message=exc.msg)
    except Exception as exc:
        log.warning("query_failed query_id=%s error_type=%s", query_id, type(exc).__name__)
        result.update(status="error", message="数据库查询失败或超时；请检查网络、字段及数据源配置。未产生核验结论。")
    result["durationMs"] = round((time.perf_counter() - started) * 1000)
    try:
        if retained is not None:
            store.execution_save(result, actor, body.requirementId, query["checksum"], retained_evidence=retained)
            evidence.get_evidence(result["id"], actor)
            result["evidenceRef"] = result["id"]
        else:
            store.execution_save(result, actor, body.requirementId, query["checksum"])
        result["evidenceSaved"] = True
    except Exception as exc:
        errno = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
        log.warning("evidence_save_failed error_type=%s errno=%s", type(exc).__name__, errno)
        result["evidenceSaved"] = False
        if retained is not None:
            result.update(status="error", retainedEvidence=False, evidenceRef=None)
        result["message"] = (result.get("message", "") + " 查询元信息未保存，不能引用为已存核验证据。 ").strip()
    return ok(result)


@app.get(PREFIX + "/executions/{execution_id}/evidence")
def get_retained_evidence(execution_id: str, actor: dict = Depends(current_actor)):
    require_execution(actor)
    return ok(evidence.get_evidence(execution_id, actor))


@app.post(PREFIX + "/executions/{execution_id}/independent-expectation")
def save_independent_expectation(execution_id: str, body: ExpectationInput, actor: dict = Depends(current_actor)):
    require_execution(actor)
    require_mapping_management(actor)
    return ok(evidence.save_expectation(execution_id, body.model_dump(), actor))


@app.get(PREFIX + "/queries/{query_id}/options")
def get_parameter_options(query_id: str, requirementId: str, actor: dict = Depends(current_actor)):
    require_execution(actor)
    req = registry.requirement(requirementId)
    query = registry.find_query(query_id)
    if query["metricId"] not in req["metricIds"]:
        raise ApiError("该SQL的指标不属于当前需求", code=403, status_code=403)
    if query["dialect"] != database_config(query["layer"]).engine:
        raise ApiError("SQL方言与数据源不一致", status_code=409)
    return ok(parameter_options(query))


@app.get(PREFIX + "/requirements/{requirement_id}/executions")
def get_executions(requirement_id: str, actor: dict = Depends(current_actor)):
    require_execution(actor)
    registry.requirement(requirement_id)
    return ok(store.execution_list(requirement_id, actor))


@app.get(PREFIX + "/requirements/{requirement_id}/records")
def get_records(requirement_id: str, actor: dict = Depends(current_actor)):
    require_record(actor)
    registry.requirement(requirement_id)
    return ok(store.record_list(requirement_id, actor))


@app.post(PREFIX + "/comparisons/preview")
def preview_comparison(body: ComparisonInput, actor: dict = Depends(current_actor)):
    require_record(actor)
    return ok(prepare_comparison(body.model_dump(), "有差异"))


@app.post(PREFIX + "/comparisons/from-execution")
def import_comparison(body: ImportInput, actor: dict = Depends(current_actor)):
    require_execution(actor)
    return ok(expected_draft(body.requirementId, body.scenarioId, body.executionId, actor))


@app.get(PREFIX + "/records/recent")
def get_recent_records(actor: dict = Depends(current_actor)):
    require_record(actor)
    return ok(store.record_recent(actor))


@app.post(PREFIX + "/records")
def save_record(body: RecordInput, actor: dict = Depends(current_actor)):
    require_record(actor)
    req = registry.requirement(body.requirementId)
    if body.metricId and body.metricId not in req["metricIds"]:
        raise ApiError("指标与需求关联不一致", status_code=422)
    if not body.comment.strip():
        raise ApiError("请填写核对依据、差异或条件不足原因", status_code=422)
    if body.scenarioId:
        if not body.metricId:
            raise ApiError("请选择本次核对指标", status_code=422)
        registry.scenario(body.scenarioId, body.requirementId, body.metricId)
    if body.judgment == "符合" and (not body.scenarioId or body.comparison is None):
        raise ApiError("请从指标场景填写真实结果对照；旧版单条查询不能直接证明符合", status_code=422)
    data = body.model_dump()
    data["mappingRevisionId"] = registry.current_revision_id()
    data["moduleId"] = mapping_store.scope()[1]
    data["comparison"] = prepare_comparison(data["comparison"], body.judgment)
    return ok(store.record_save(data, actor))

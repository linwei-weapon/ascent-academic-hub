"""核验记录只写专用SYS表；不修改业务表或源数据。"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from backend.api.envelope import ApiError
from .database import connection
from . import registry, mapping_store
from .comparison import prepare as prepare_comparison
from .evidence_import import validate_binding

TABLES = ("sys_metric_verification_execution", "sys_metric_verification_record")


def table_ready() -> bool:
    try:
        with connection("application") as conn, conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (%s,%s)", TABLES)
            return int(cursor.fetchone()["n"]) == len(TABLES)
    except Exception:
        return False


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def execution_save(result: dict, actor: dict, requirement_id: str, checksum: str, *, retained_evidence: dict | None = None) -> None:
    # Store the aggregate evidence and a digest of detail rows; do not copy the
    # entire source/student detail set into the governance log.
    snapshot = {key: result.get(key) for key in (
        "status", "recordCount", "metrics", "columns", "returnedRows", "truncated", "message", "queryKind",
        "mappingMode", "directSource", "metricResultStatus", "metricResultReason")}
    snapshot["requirementChecksum"] = result.get("requirementChecksum") or registry.requirement_checksum(requirement_id)
    snapshot["scenarioId"] = result.get("scenarioId")
    snapshot["scenarioChecksum"] = result.get("scenarioChecksum")
    snapshot.update({k: result.get(k) for k in ("mappingRevisionId", "executionUse", "retainedEvidence", "resultDisclosure")})
    snapshot["moduleId"] = result.get("moduleId") or mapping_store.scope()[1]
    snapshot["detailDigest"] = hashlib.sha256(json.dumps(result.get("rows", []), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    with connection("application", write=True) as conn, conn.cursor() as cursor:
        extra_columns, extra_values, extra_params = "", "", ()
        if result.get("mappingRevisionId") or retained_evidence is not None:
            extra_columns, extra_values = ",mapping_revision_id,evidence_json", ",%s,%s"
            extra_params = (result.get("mappingRevisionId"), json.dumps(retained_evidence, ensure_ascii=False, allow_nan=False) if retained_evidence is not None else None)
        cursor.execute("""INSERT INTO sys_metric_verification_execution
            (execution_id,requirement_id,metric_id,query_id,query_version,query_checksum,layer_name,
             actor,identity_id,parameters_json,result_json,executed_at,duration_ms""" + extra_columns + ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s" + extra_values + ")", (
                result["id"], requirement_id, result["metricId"], result["queryId"], result["sqlVersion"], checksum,
                result["layer"], actor["username"], actor["identity_id"],
                json.dumps(result["parameters"], ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False),
                result["executedAt"], result["durationMs"],
            ) + extra_params)


def record_payload(raw: str) -> dict:
    value = json.loads(raw)
    # Existing records stored a bare array of execution IDs. Keep them readable.
    return {"evidenceIds": value, "schemaVersion": 1} if isinstance(value, list) else value


def record_current(payload: dict, requirement_id: str, metric_id: str | None, cache: dict) -> bool:
    if not payload.get("scenarioId") or not payload.get("comparison"):
        return False
    try:
        scene = payload["scenarioId"]
        key = (scene, requirement_id, metric_id)
        if key not in cache:
            registry.scenario(scene, requirement_id, metric_id)
            cache[key] = (registry.requirement_checksum(requirement_id), registry.scenario_checksum(scene))
        req_hash, scene_hash = cache[key]
        if payload.get("requirementChecksum") != req_hash or payload.get("scenarioChecksum") != scene_hash:
            return False
        for evidence in payload.get("evidenceDefinitions", []):
            query_key = ("query", evidence["queryId"])
            if query_key not in cache:
                cache[query_key] = registry.find_query(evidence["queryId"])
            query = cache[query_key]
            if query.get("version") != evidence["version"] or query.get("checksum") != evidence["checksum"]:
                return False
            if query.get("executionApproval") != "documented":
                return False
        return True
    except (ApiError, KeyError, TypeError):
        return False


def records_from_rows(rows: list[dict]) -> dict:
    cache, items = {}, []
    for row in rows:
        payload = record_payload(row["evidence_json"])
        if payload.get("moduleId", "teaching-overview") != mapping_store.scope()[1]:
            continue
        items.append({"id": row["record_id"], "requirementId": row["requirement_id"], "metricId": row["metric_id"],
                      "judgment": row["judgment"], "comment": row["comment_text"],
                      "evidenceIds": payload.get("evidenceIds", []), "createdAt": row["created_at"],
                      "createdBy": row["created_by"], "scenarioId": payload.get("scenarioId"),
                      "comparison": payload.get("comparison"), "mappingRevisionId": payload.get("mappingRevisionId"),
                      "current": record_current(payload, row["requirement_id"], row["metric_id"], cache)})
    return {"items": items}


def record_list(requirement_id: str, actor: dict) -> dict:
    with connection("application") as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT record_id,requirement_id,metric_id,judgment,comment_text,evidence_json,
            created_at,created_by FROM sys_metric_verification_record
            WHERE requirement_id=%s AND created_by=%s AND identity_id=%s ORDER BY created_at DESC,record_id DESC LIMIT 100""",
                       (requirement_id, actor["username"], actor["identity_id"]))
        rows = cursor.fetchall()
    return records_from_rows(rows)


def record_recent(actor: dict) -> dict:
    with connection("application") as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT record_id,requirement_id,metric_id,judgment,comment_text,evidence_json,
            created_at,created_by FROM sys_metric_verification_record
            WHERE created_by=%s AND identity_id=%s ORDER BY created_at DESC,record_id DESC LIMIT 100""",
                       (actor["username"], actor["identity_id"]))
        rows = cursor.fetchall()
    return records_from_rows(rows)


def execution_list(requirement_id: str, actor: dict) -> dict:
    """Recent evidence plus every reference in the visible 100 record history."""
    records = record_list(requirement_id, actor)["items"]
    references = {identifier for record in records for identifier in record["evidenceIds"]}
    scope = (requirement_id, actor["username"], actor["identity_id"])
    base = """SELECT execution_id,requirement_id,metric_id,query_id,query_version,query_checksum,
        layer_name,parameters_json,result_json,executed_at,duration_ms
        FROM sys_metric_verification_execution
        WHERE requirement_id=%s AND actor=%s AND identity_id=%s"""
    with connection("application") as conn, conn.cursor() as cursor:
        cursor.execute(base + " ORDER BY executed_at DESC,execution_id DESC LIMIT 100", scope)
        rows = list(cursor.fetchall())
        missing = references - {row["execution_id"] for row in rows}
        if missing:
            cursor.execute(base + " AND execution_id IN (" + ",".join(["%s"] * len(missing)) + ")", scope + tuple(sorted(missing)))
            rows.extend(cursor.fetchall())
    requirement_hash = registry.requirement_checksum(requirement_id)
    metric_ids = set(registry.requirement(requirement_id)["metricIds"])
    current_queries = {}
    items = []
    for row in rows:
        snapshot = json.loads(row["result_json"])
        if snapshot.get("moduleId", "teaching-overview") != mapping_store.scope()[1]:
            continue
        identifier = row["query_id"]
        if identifier not in current_queries:
            try:
                current_queries[identifier] = registry.find_query(identifier)
            except ApiError:
                current_queries[identifier] = {}
        query = current_queries[identifier]
        current = bool(query and query.get("executionApproval") == "documented"
                       and query.get("version") == row["query_version"]
                       and query.get("checksum") == row["query_checksum"]
                       and snapshot.get("requirementChecksum") == requirement_hash
                       and row["metric_id"] in metric_ids)
        if snapshot.get("scenarioId"):
            try:
                registry.scenario(snapshot["scenarioId"], requirement_id, row["metric_id"], allow_evidence=True)
                current = current and snapshot.get("scenarioChecksum") == registry.scenario_checksum(snapshot["scenarioId"])
            except ApiError:
                current = False
        items.append({"id": row["execution_id"], "requirementId": row["requirement_id"],
                      "scenarioId": snapshot.get("scenarioId"),
                      "metricId": row["metric_id"], "queryId": identifier,
                      "queryKind": snapshot.get("queryKind") or query.get("kind", "detail"),
                      "layer": row["layer_name"], "sqlVersion": row["query_version"],
                      "queryChecksum": row["query_checksum"], "current": current,
                      "mappingRevisionId": snapshot.get("mappingRevisionId"),
                      "retainedEvidence": bool(snapshot.get("retainedEvidence")), "resultDisclosure": snapshot.get("resultDisclosure"),
                      "executionUse": snapshot.get("executionUse"),
                      "parameters": json.loads(row["parameters_json"]), "executedAt": row["executed_at"],
                      "durationMs": row["duration_ms"], **{key: snapshot.get(key) for key in (
                          "status", "recordCount", "metrics", "columns", "returnedRows", "truncated", "message",
                          "mappingMode", "directSource", "metricResultStatus", "metricResultReason")}})
    return {"items": items}


def record_save(body: dict, actor: dict) -> dict:
    body = {**body, "evidenceIds": list(dict.fromkeys(body.get("evidenceIds", [])))}
    if (body.get("comparison") or {}).get("expectedExecutionId"):
        if not body.get("scenarioId"):
            raise ApiError("带入查询结果必须关联指标场景", status_code=422)
        imported_id = validate_binding(body["comparison"], body["requirementId"], body["scenarioId"], actor)
        if imported_id not in body["evidenceIds"]:
            body["evidenceIds"].append(imported_id)
    rid, metric_id, evidence = body["requirementId"], body.get("metricId"), body.get("evidenceIds", [])
    record = {**body, "moduleId": mapping_store.scope()[1], "id": str(uuid4()), "createdAt": now(), "createdBy": actor["username"]}
    scene_id = body.get("scenarioId")
    allowed_metrics = {metric_id} if metric_id else set()
    payload = None
    if scene_id:
        scene = registry.scenario(scene_id, rid, metric_id)
        allowed_metrics.update(scene.get("evidenceMetricIds", []))
        record["comparison"] = prepare_comparison(body.get("comparison"), body["judgment"])
        if body["judgment"] == "符合" and not record["comparison"]:
            raise ApiError("符合判断必须保留真实结果对照", status_code=422)
        if (body["judgment"] == "符合" and scene.get("status") == "pending"
                and record["comparison"]["coverage"] != "display"):
            raise ApiError("本场景计算口径仍待明确，可核对页面显示或记录条件不足，暂不能判计算链路符合", status_code=422)
        payload = {"schemaVersion": 2, "evidenceIds": list(dict.fromkeys(evidence)), "scenarioId": scene_id,
                   "comparison": record["comparison"], "requirementChecksum": registry.requirement_checksum(rid),
                   "scenarioChecksum": registry.scenario_checksum(scene_id), "evidenceDefinitions": [],
                   "mappingRevisionId": body.get("mappingRevisionId"), "moduleId": mapping_store.scope()[1]}
    covered_metrics = set()
    evidence_scope = {}
    with connection("application", write=True) as conn, conn.cursor() as cursor:
        for evidence_id in evidence:
            cursor.execute("""SELECT metric_id,result_json,query_id,query_version,query_checksum,parameters_json FROM sys_metric_verification_execution
                WHERE execution_id=%s AND requirement_id=%s AND actor=%s AND identity_id=%s""",
                           (evidence_id, rid, actor["username"], actor["identity_id"]))
            result = cursor.fetchone()
            if not result or (metric_id and result["metric_id"] not in allowed_metrics):
                raise ApiError("查询证据不属于当前需求、指标或工作身份", code=403, status_code=403)
            covered_metrics.add(result["metric_id"])
            snapshot = json.loads(result["result_json"])
            if snapshot.get("moduleId", "teaching-overview") != mapping_store.scope()[1]:
                raise ApiError("查询证据不属于当前指标模块", status_code=403)
            if scene_id and snapshot.get("scenarioId") != scene_id:
                raise ApiError("查询证据属于其他使用场景，请在当前指标场景重新查询", status_code=422)
            if payload is not None:
                payload["evidenceDefinitions"].append({"queryId": result["query_id"],
                    "version": result["query_version"], "checksum": result["query_checksum"]})
            if body["judgment"] == "符合":
                parameters = json.loads(result.get("parameters_json") or "{}")
                scope_keys = {"semester_id", "previous_semester_id", "term_id", "organization_id", "college_id", "student_id", "course_id", "major_id", "grade"}
                scope_keys.update(key for key in parameters if "batch" in key or "version" in key)
                for key in scope_keys:
                    if key in parameters:
                        if key in evidence_scope and evidence_scope[key] != parameters[key]:
                            raise ApiError("所选证据的学期、业务对象范围不同或同类批次/版本不一致，请选择同一范围的证据", status_code=422)
                        evidence_scope[key] = parameters[key]
                if snapshot.get("executionUse") == "definition_validation":
                    raise ApiError("定义验证证据仅说明该次限定核算；业务符合请使用当前生效版本取得同范围应用对照", status_code=409)
                if snapshot.get("status") != "success":
                    raise ApiError("执行失败的查询不能作为符合的依据", status_code=422)
                current = registry.find_query(result["query_id"])
                req_checksum = registry.requirement_checksum(rid)
                if (current.get("executionApproval") != "documented"
                        or current["version"] != result["query_version"] or current["checksum"] != result["query_checksum"]
                        or snapshot.get("requirementChecksum") != req_checksum):
                    raise ApiError("需求或SQL已经调整，请重新查询后再判断符合", status_code=409)
                if scene_id and snapshot.get("scenarioChecksum") != payload["scenarioChecksum"]:
                    raise ApiError("使用场景口径已调整，请重新查询后再判断符合", status_code=409)
        if body["judgment"] == "符合" and not metric_id:
            required_metrics = set(registry.requirement(rid)["metricIds"])
            if not required_metrics.issubset(covered_metrics):
                raise ApiError("整条需求判为符合须覆盖所有关联指标；也可选择单个指标分别核对", status_code=422)
        extra_column = ",mapping_revision_id" if body.get("mappingRevisionId") else ""
        extra_value = ",%s" if body.get("mappingRevisionId") else ""
        extra_param = (body["mappingRevisionId"],) if body.get("mappingRevisionId") else ()
        cursor.execute("""INSERT INTO sys_metric_verification_record
            (record_id,requirement_id,metric_id,judgment,comment_text,evidence_json,created_at,created_by,identity_id""" + extra_column + ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s" + extra_value + ")", (
                record["id"], rid, metric_id, body["judgment"], body["comment"],
                json.dumps(payload if payload is not None else {"schemaVersion": 2, "moduleId": mapping_store.scope()[1], "evidenceIds": evidence}, ensure_ascii=False), record["createdAt"], actor["username"], actor["identity_id"],
            ) + extra_param)
    record["current"] = record_current(payload, rid, metric_id, {}) if payload else False
    return record

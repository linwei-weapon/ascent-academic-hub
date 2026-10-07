"""Bounded, owned calculation evidence. Business tables are only read."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json

from backend.api.envelope import ApiError
from . import registry, mapping_store
from .config import database_config
from .database import connection, bind_parameters, execute_read, schema_mapping

MAX_BYTES = 1024 * 1024
MAX_ROWS = 50


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(evidence):
    body = {k: v for k, v in evidence.items() if k != "integrity"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def columns_for(query, result):
    declared = {c["key"]: c for c in (query.get("resultContract") or {}).get("columns", [])}
    return [{"key": name, "label": declared.get(name, {}).get("label", name),
             "dataType": declared.get(name, {}).get("dataType", "string"),
             "unit": declared.get(name, {}).get("unit", ""),
             "semanticRole": declared.get(name, {}).get("semanticRole", "supporting"),
             **{k: declared[name][k] for k in ("decimalScale", "rounding") if k in declared.get(name, {})}}
            for name in result["columns"]]


def query_result(query, parameters, result):
    return {"queryId": query["id"], "sql": query["sql"], "sqlChecksum": query["checksum"],
            "parameters": parameters, "columns": columns_for(query, result), "rows": result["rows"],
            "returnedRecordCount": result["returnedRows"], "complete": not result["truncated"],
            "truncated": result["truncated"]}


def _approved(query, *, definition_validation=False):
    if query.get("executionApproval") != "documented" and not (
            definition_validation and query.get("schemaOnlyBlocked") is True):
        raise ApiError(query.get("blockedReason") or "该查询仍缺计算口径或来源条件", status_code=409)


def assert_snapshot_tables(conn, queries, engine):
    if engine != "mysql":
        raise ApiError("首版留存核算只支持已核实的MySQL一致性读取；其他方言可作普通技术查询", status_code=409)
    required = {name.lower() for q in queries for name in q.get("requiredColumns", {})}
    if not required:
        raise ApiError("缺少一致性读取的对象登记", status_code=409)
    with conn.cursor() as cursor:
        cursor.execute("SELECT TABLE_NAME,ENGINE,TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()")
        objects = {r["TABLE_NAME"].lower(): r for r in cursor.fetchall()}
    unsupported = [name for name in required if name not in objects
                   or (objects[name].get("ENGINE") or "").lower() != "innodb"
                   or objects[name].get("TABLE_TYPE") != "BASE TABLE"]
    if unsupported:
        raise ApiError("无法证明这些对象支持同次一致性读取：" + "、".join(sorted(unsupported)), status_code=409)
    for q in queries:
        schema_mapping(conn, q, engine)


def capture_case(query, parameters, case_id, execution, *, limit=50):
    """Acquire both sides once; do not keep a transaction open for a person."""
    from .store import now
    package = registry.current_package()
    if not package:
        raise ApiError("请先登记映射版本和核算用例", status_code=409)
    case = next((c for c in package.get("validationCases", []) if c["id"] == case_id), None)
    if not case or case.get("metricId") != query["metricId"] or (case.get("execution") or {}).get("queryId") != query["id"]:
        raise ApiError("核算用例与指标SQL不匹配", status_code=422)
    plans = (case.get("samplePlan") or {}).get("inputDatasets") or []
    if not plans or len(plans) > 10:
        raise ApiError("核算用例必须登记完整的原始输入及对应count", status_code=409)
    cap = min(MAX_ROWS, limit)
    budget = min(MAX_BYTES, int((((package.get("inputManifest") or {}).get("checks") or {})
                               .get("evidenceCapture") or {}).get("maxBytes", MAX_BYTES)))
    datasets, prepared = [], []
    config = database_config(query["layer"])
    _approved(query, definition_validation=True)
    for spec in plans:
        detail = registry.find_query(spec["queryId"])
        count = registry.find_query(spec["countQueryId"])
        if detail["kind"] != "detail" or count["kind"] != "count":
            raise ApiError("样本登记必须分别引用明细和记录数SQL", status_code=422)
        if (detail.get("resultContract") or {}).get("completeness", {}).get("totalCountQueryId") != count["id"]:
            raise ApiError("原始输入与记录数没有明确配对", status_code=422)
        for q in (detail, count):
            _approved(q, definition_validation=True)
            if (q["metricId"] != query["metricId"] or q["dialect"] != query["dialect"]
                    or database_config(q["layer"]) != config):
                raise ApiError("首版样本取证限同指标、同数据库连接和方言", status_code=409)
        names = {p["name"] for p in detail.get("parameters", [])}
        if names != {p["name"] for p in count.get("parameters", [])}:
            raise ApiError("原始明细与count参数范围不一致", status_code=422)
        if not names.issubset(parameters):
            raise ApiError("样本参数未包含于被测SQL的限定范围", status_code=422)
        params = bind_parameters(detail, {k: parameters[k] for k in names})
        count_params = bind_parameters(count, params)
        prepared.append((spec, detail, count, params, count_params))
    evidence = {"schemaVersion": "3.1.0", "id": execution["id"], "executionId": execution["id"],
                "mappingRevisionId": registry.current_revision_id(), "metricId": query["metricId"],
                "caseId": case_id, "environmentId": package["environmentId"], "moduleId": package.get("moduleId") or mapping_store.scope()[1],
                "capture": {"connectionRef": query.get("connectionRef", query["layer"]),
                            "method": "single_connection_consistent_read", "startedAt": now(),
                            "endedAt": None, "consistency": "verified",
                            "consistencyBasis": "MySQL REPEATABLE READ / READ ONLY；依赖对象为InnoDB基础表；同一连接读取。不能据此证明ETL批次对齐。"},
                "scope": {"parameters": parameters, "coverage": "bounded_sample",
                          "description": (case.get("samplePlan") or {}).get("scopeReason") or "登记SQL所限定的完整小范围"}}
    metric = next(m for m in package["metrics"] if m["id"] == query["metricId"])
    evidence["comparisonPolicy"] = deepcopy(metric["definition"].get("precision", {}).get("comparison"))
    evidence["resultRowKey"] = (query.get("resultContract") or {}).get("rowKey", [])
    with connection(query["layer"], consistent=True) as conn:
        assert_snapshot_tables(conn, [query] + [q for _, d, c, _, _ in prepared for q in (d, c)], config.engine)
        for spec, detail, count, params, count_params in prepared:
            total = execute_read(conn, count, count_params, config.engine, 1, precise=True)
            n = total["recordCount"]
            if total["truncated"] or n is None or n < 0 or n > cap:
                raise ApiError("完整原始样本超过上限或记录数无效，请缩小有业务意义的查询范围", status_code=409)
            data = execute_read(conn, detail, params, config.engine, cap, precise=True)
            if data["truncated"] or data["returnedRows"] != n:
                raise ApiError("原始样本被截断或与登记记录数不一致，不能验证计算", status_code=409)
            dataset = query_result(detail, params, data)
            dataset.update(countQueryId=count["id"], countSql=count["sql"], countSqlChecksum=count["checksum"],
                           matchedRecordCount=n, role=spec.get("role", "raw_input"))
            datasets.append(dataset)
            if len(canonical(datasets).encode("utf-8")) > budget:
                raise ApiError("原始样本证据超过体积上限，请缩小范围", status_code=409)
        calculated = execute_read(conn, query, parameters, config.engine, cap, precise=True)
        if calculated["truncated"]:
            raise ApiError("被测结果不完整，本次不能形成独立核算证据", status_code=409)
    evidence["capture"]["endedAt"] = now()
    evidence.update(datasets=datasets, testedResult=query_result(query, parameters, calculated))
    size = len(canonical(evidence).encode("utf-8"))
    if size > budget:
        raise ApiError("整份核算证据超过体积上限，请缩小范围", status_code=409)
    evidence["integrity"] = {"contentHash": content_hash(evidence), "byteCount": size,
                             "persistedAt": now(), "readbackVerified": True}
    return evidence


def capture_application(query, parameters, result, execution):
    from .store import now
    if query.get("purpose") != "application_actual":
        raise ApiError("此查询不属于独立应用实际结果", status_code=422)
    evidence = {"schemaVersion": "3.1.0", "id": execution["id"], "executionId": execution["id"],
                "mappingRevisionId": registry.current_revision_id(), "metricId": query["metricId"],
                "caseId": None, "environmentId": (registry.current_package() or {}).get("environmentId"), "moduleId": mapping_store.scope()[1],
                "capture": {"connectionRef": query.get("connectionRef", query["layer"]),
                            "method": "application_result", "startedAt": execution["executedAt"],
                            "endedAt": now(), "consistency": "single_query",
                            "consistencyBasis": "单次应用结果读取；跨来源业务时点仍需核对"},
                "scope": {"parameters": parameters, "coverage": "sample" if result["truncated"] else "complete_result"},
                "datasets": [], "testedResult": query_result(query, parameters, result)}
    size = len(canonical(evidence).encode("utf-8"))
    if size > MAX_BYTES:
        raise ApiError("应用结果证据超过体积上限", status_code=409)
    evidence["integrity"] = {"contentHash": content_hash(evidence), "byteCount": size,
                             "persistedAt": now(), "readbackVerified": True}
    return evidence


def _owned_row(execution_id, actor, *, cursor=None, lock=False):
    sql = """SELECT evidence_json,independent_expectation_json,result_json FROM sys_metric_verification_execution
        WHERE execution_id=%s AND actor=%s AND identity_id=%s""" + (" FOR UPDATE" if lock else "")
    params = (execution_id, actor["username"], actor["identity_id"])
    if cursor is None:
        with connection("application") as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    else:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    if not row:
        raise ApiError("证据不存在或不属于当前工作身份", code=404, status_code=404)
    if not row.get("evidence_json"):
        raise ApiError("该历史执行只有摘要，没有留存原始核算证据", status_code=409)
    evidence = json.loads(row["evidence_json"])
    if evidence.get("moduleId", "teaching-overview") != mapping_store.scope()[1]:
        raise ApiError("证据不存在或不属于当前指标模块", code=404, status_code=404)
    if content_hash(evidence) != evidence.get("integrity", {}).get("contentHash"):
        raise ApiError("证据内容校验失败，不能用于复核", status_code=409)
    return row, evidence


def compare_expected(evidence, expected):
    if not expected:
        return {"status": "pending", "differences": []}
    if expected.get("resultKnownBeforeCalculation"):
        return {"status": "inconclusive", "differences": [], "reason": "核算前已知结果，本次属于普通复核"}
    tested = evidence["testedResult"]
    if not tested["complete"]:
        return {"status": "inconclusive", "differences": [], "reason": "被测结果不完整"}
    actual, wanted, differences = tested["rows"], expected["rows"], []
    if len(actual) != len(wanted):
        differences.append({"field": "rowCount", "expected": len(wanted), "actual": len(actual)})
    numeric = {c["key"] for c in tested["columns"] if c.get("dataType") in {"number", "integer", "decimal", "float"}}
    policy = evidence.get("comparisonPolicy") or {}
    tolerant = {c["key"] for c in tested["columns"] if c.get("semanticRole") in {"metric_value", "share"}
                and c.get("dataType") in {"number", "decimal", "float"} and c.get("unit") == policy.get("unit")
                and c["key"] not in evidence.get("resultRowKey", [])}
    for i, (a, b) in enumerate(zip(actual, wanted)):
        for key in sorted(set(a) | set(b)):
            av, bv = a.get(key), b.get(key)
            same = av == bv
            if key in numeric and av is not None and bv is not None:
                try:
                    da, db = Decimal(str(av)), Decimal(str(bv))
                    same = da.is_finite() and db.is_finite() and da == db
                    if not same and key in tolerant and policy.get("mode") == "absolute":
                        tolerance = Decimal(str(policy.get("tolerance")))
                        same = da.is_finite() and db.is_finite() and tolerance.is_finite() and tolerance >= 0 and abs(da - db) <= tolerance
                except (InvalidOperation, ValueError):
                    same = False
            if not same:
                differences.append({"row": i + 1, "field": key, "expected": bv, "actual": av})
    return {"status": "different" if differences else "match", "differences": differences,
            "scope": "本次限定样本；不代表应用或全量业务符合"}


def public_evidence(evidence, expected=None):
    result = deepcopy(evidence)
    result["integrity"]["readbackVerified"] = True
    result["expected"] = expected
    withheld = bool(evidence.get("caseId") and expected is None)
    result["resultDisclosure"] = "withheld" if withheld else ("revealed" if evidence.get("caseId") else "not_applicable")
    result["validation"] = compare_expected(evidence, expected) if evidence.get("caseId") else {
        "status": "inconclusive", "differences": [], "reason": "应用实值仍需同条件需求复算与人工判断"}
    if withheld:
        result["testedResult"] = None
    return result


def get_evidence(execution_id, actor):
    row, evidence = _owned_row(execution_id, actor)
    expected = json.loads(row["independent_expectation_json"]) if row.get("independent_expectation_json") else None
    return public_evidence(evidence, expected)


def save_expectation(execution_id, body, actor):
    from .store import now
    with connection("application", write=True) as conn, conn.cursor() as cursor:
        row, evidence = _owned_row(execution_id, actor, cursor=cursor, lock=True)
        if not evidence.get("caseId"):
            raise ApiError("应用实值记录不使用独立预期提交流程", status_code=422)
        if body["inputContentHash"] != evidence["integrity"]["contentHash"]:
            raise ApiError("输入证据已经变化，请重新读取", status_code=409)
        keys = {c["key"] for c in evidence["testedResult"]["columns"]}
        for item in body["rows"]:
            if set(item) != keys or any(isinstance(v, (dict, list)) or len(str(v)) > 500 for v in item.values()):
                raise ApiError("独立预期应填写全部登记结果列，数值和空值须明确", status_code=422)
        if len(canonical(body).encode("utf-8")) > MAX_BYTES:
            raise ApiError("独立预期超过体积上限", status_code=422)
        existing = json.loads(row["independent_expectation_json"]) if row.get("independent_expectation_json") else None
        if existing:
            if any(existing.get(k) != v for k, v in body.items()):
                raise ApiError("已揭示结果的独立预期不能覆盖；请另建复核记录说明更正", status_code=409)
            expected = existing
        else:
            expected = {**body, "inputEvidenceRef": execution_id, "determinedAt": now(),
                        "determinedByRef": actor["username"], "submittedBeforeResultDisclosure": True}
            summary = json.loads(row["result_json"])
            tested = evidence["testedResult"]
            summary.update(resultDisclosure="revealed", returnedRows=len(tested["rows"]),
                           columns=[c["key"] for c in tested["columns"]], truncated=tested["truncated"],
                           metrics=tested["rows"][0] if len(tested["rows"]) == 1 else {},
                           message="限定样本的独立核算已提交；不能直接作为当前全量应用符合的依据。")
            cursor.execute("""UPDATE sys_metric_verification_execution SET independent_expectation_json=%s,result_json=%s
                WHERE execution_id=%s AND actor=%s AND identity_id=%s AND independent_expectation_json IS NULL""",
                           (canonical(expected), canonical(summary), execution_id, actor["username"], actor["identity_id"]))
    return public_evidence(evidence, expected)

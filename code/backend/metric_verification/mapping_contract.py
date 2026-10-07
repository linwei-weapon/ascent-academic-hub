"""Deterministic mapping contracts. No SQL is executed and no approval is inferred from AI status."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path

from backend.api.envelope import ApiError
from .database import validate_sql
from .config import ASSETS

VERSION = "3.1.0"
ROOT_FIELDS = {"schemaVersion", "template", "packageId", "analysisId", "projectId", "moduleId",
               "moduleName", "environmentId", "baseRevisionId", "inputManifest", "sourceManifest",
               "coverage", "metrics", "queries", "questions", "pendingAnswers", "decisions",
               "validationCases", "validations", "analysisSummary", "checkpoint", "changeSet", "sharedRules"}
LAYERS = {"source", "fact", "application"}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z_0-9$]*$")
SEMANTIC_IGNORED = {"name", "title", "businessPurpose", "evidenceRefs", "questionIds", "note", "description",
                    "version", "status", "observed", "checkRef", "locator", "excerpt", "capturedAt", "checkedAt"}


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_document(value, kind: str) -> list[dict]:
    """Validate the checked-in schema subset without introducing a new runtime dependency."""
    if kind not in {"input", "output", "question", "validation-case", "receipt"}:
        raise ValueError("未知映射文档类型")
    errors = []
    directory = ASSETS / "contracts"

    def visit(item, schema, path):
        if "$ref" in schema:
            name = schema["$ref"]
            if Path(name).name != name or not name.endswith(".schema.json"):
                raise ValueError("schema引用必须是同目录文件")
            visit(item, json.loads((directory / name).read_text(encoding="utf-8")), path)
            return
        types = schema.get("type")
        types = [types] if isinstance(types, str) else types
        checks = {"object": lambda: isinstance(item, dict), "array": lambda: isinstance(item, list),
                  "string": lambda: isinstance(item, str), "null": lambda: item is None,
                  "boolean": lambda: isinstance(item, bool), "integer": lambda: isinstance(item, int) and not isinstance(item, bool),
                  "number": lambda: isinstance(item, (int, float)) and not isinstance(item, bool)}
        if types and not any(checks[t]() for t in types):
            errors.append({"path": path, "message": "类型不符合schema：" + "/".join(types)})
            return
        if "const" in schema and item != schema["const"]:
            errors.append({"path": path, "message": "值不符合契约版本"})
        if "enum" in schema and item not in schema["enum"]:
            errors.append({"path": path, "message": "值不在允许枚举中"})
        if isinstance(item, dict):
            for key in schema.get("required", []):
                if key not in item:
                    errors.append({"path": path + "." + key, "message": "缺少必需字段"})
            properties = schema.get("properties", {})
            for key, child in item.items():
                if key in properties:
                    visit(child, properties[key], path + "." + key)
                elif schema.get("additionalProperties") is False:
                    errors.append({"path": path + "." + key, "message": "未定义字段"})
                elif isinstance(schema.get("additionalProperties"), dict):
                    visit(child, schema["additionalProperties"], path + "." + key)
        elif isinstance(item, list):
            for i, child in enumerate(item):
                visit(child, schema.get("items", {}), f"{path}[{i}]")
    visit(value, json.loads((directory / f"mapping-{kind}.schema.json").read_text(encoding="utf-8")), "$")
    return errors


def _semantic(value):
    if isinstance(value, dict):
        return {k: _semantic(v) for k, v in value.items() if k not in SEMANTIC_IGNORED}
    if isinstance(value, list):
        return [_semantic(v) for v in value]
    return value


def semantic_signatures(package: dict) -> dict:
    """Business signatures include transitive rule/metric dependencies, never package metadata."""
    metrics = {m["id"]: m for m in package["metrics"]}
    rules = {r["id"]: r for r in package["sharedRules"]}
    result, visiting = {}, set()

    def visit(metric_id):
        if metric_id in result:
            return result[metric_id]
        if metric_id in visiting:
            raise ValueError("指标依赖循环：" + metric_id)
        visiting.add(metric_id)
        metric = metrics[metric_id]
        definition = metric["definition"]
        snapshot = {"type": metric["type"], "definition": _semantic(definition),
                    "lineage": _semantic(metric["lineage"]), "processing": _semantic(metric["processing"]),
                    "actualBinding": _semantic(metric.get("actualBinding")),
                    "comparison": _semantic(metric.get("verificationPlan", {}).get("comparison")),
                    "rules": {r: _semantic(rules[r]["definition"]) for r in definition.get("ruleRefs", [])},
                    "dependencies": [{"metricId": ref["metricId"], "signature": visit(ref["metricId"]),
                                      "appliesTo": ref["appliesTo"], "parameterBindings": ref["parameterBindings"]}
                                     for ref in definition.get("metricRefs", [])]}
        result[metric_id] = content_hash(snapshot)
        visiting.remove(metric_id)
        return result[metric_id]

    for metric_id in metrics:
        visit(metric_id)
    return result


def affected_metrics(package: dict, changed_rule_ids=(), changed_metric_ids=()) -> list[str]:
    affected = set(changed_metric_ids)
    rules = set(changed_rule_ids)
    while True:
        old = set(affected)
        for metric in package["metrics"]:
            definition = metric["definition"]
            if rules.intersection(definition.get("ruleRefs", [])) or any(
                    ref["metricId"] in affected for ref in definition.get("metricRefs", [])):
                affected.add(metric["id"])
        if affected == old:
            return sorted(affected)


def query_signature(query: dict) -> str:
    return content_hash({k: query.get(k) for k in ("sql", "parameters", "dependencies", "resultContract", "connectionRef", "dialect")})


def _sql_dependencies(sql: str, required: dict) -> list[str]:
    """Conservative SQL inspection: unsafe or unprovable references remain blocked.

    The runtime still checks every registered physical column against information_schema.
    This is a dependency audit, not a proof that a business formula is correct.
    """
    clean = re.sub(r"--[^\n]*|/\*[\s\S]*?\*/", " ", sql)
    clean = re.sub(r"'(?:''|[^'])*'", "''", clean).replace("`", "").replace('"', '')
    ctes = {m.group(1).lower() for m in re.finditer(r"(?:\bWITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", clean, re.I)}
    physical = {table.lower(): {c.lower() for c in columns} for table, columns in required.items()}
    aliases, virtual_aliases, referenced, problems = {}, set(), set(), []
    reserved = {"where", "on", "join", "left", "right", "inner", "outer", "cross", "group", "order", "limit", "having", "union", "fetch", "offset"}
    for m in re.finditer(r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?", clean, re.I):
        name, alias = m.group(1), m.group(2)
        if "." in name:
            problems.append("SQL首版禁止限定其他schema：" + name)
        table = name.lower()
        if table in ctes:
            if alias and alias.lower() not in reserved:
                virtual_aliases.add(alias.lower())
            continue
        referenced.add(table)
        if table not in physical:
            problems.append("SQL引用未登记对象：" + name)
        aliases[table] = table
        if alias and alias.lower() not in reserved:
            aliases[alias.lower()] = table
    if not referenced:
        problems.append("SQL未能定位已登记物理表")
    # Comma joins are deliberately unsupported rather than silently escaping dependency checks.
    if re.search(r"\bFROM\s+\w+(?:\s+(?:AS\s+)?\w+)?\s*,\s*\w+", clean, re.I):
        problems.append("逗号关联需改成显式JOIN后登记")
    for alias, col in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*|\*)", clean):
        table = aliases.get(alias.lower())
        if table in physical:
            if col == "*":
                problems.append("物理表通配列不能证明最小字段范围：" + alias + ".*")
            elif col.lower() not in physical[table]:
                problems.append("SQL引用未登记列：" + table + "." + col)
    # Unqualified columns cannot be reliably assigned in complex SQL; require explicit aliases.
    for star in re.finditer(r"\bSELECT\s+(?:DISTINCT\s+)?\*\s+FROM\s+([A-Za-z_]\w*)", clean, re.I):
        if star.group(1).lower() not in ctes:
            problems.append("物理表SELECT *不能证明最小字段范围")
    # Catch undeclared unqualified columns too. Unknown syntax is blocked for technical review.
    known = set(physical) | set(aliases) | virtual_aliases | ctes | {c for columns in physical.values() for c in columns}
    known.update(x.lower() for x in re.findall(r"\bAS\s+([A-Za-z_]\w*)", clean, re.I))
    known.update(x.lower() for x in re.findall(r"(?<!:):([A-Za-z_]\w*)", clean))
    known.update(x.lower() for x in re.findall(r"\b([A-Za-z_]\w*)\s*\(", clean))
    known.update("select distinct all as from join left right inner outer full cross on where and or not in is null true false with recursive union intersect except group by order having limit offset fetch first next rows row only asc desc nulls last case when then else end over partition range between unbounded preceding following current cast char varchar decimal numeric signed unsigned integer int date datetime timestamp interval year month day hour minute second collate binary using exists any some div mod escape for of values window rank dense_rank row_number lateral natural recursive double float precision both leading trailing real".split())
    stripped = re.sub(r"'(?:''|[^'])*'", " ", clean)
    stripped = re.sub(r"\b[A-Za-z_]\w*\.[A-Za-z_]\w*", " ", stripped)
    unknown = sorted({t.lower() for t in re.findall(r"\b[A-Za-z_]\w*\b", stripped)} - known)
    if unknown:
        problems.append("SQL存在无法确认归属的列/语法：" + "、".join(unknown[:12]))
    if "@" in clean:
        problems.append("SQL不得访问会话变量")
    return sorted(set(problems))


def question_context(question: dict) -> str:
    return content_hash({k: question.get(k) for k in ("semanticKey", "problem", "affectedMetricIds",
                        "affectedDefinitionFields", "options", "evidenceRefs", "type")})


def validate_package(package: dict, base: dict | None = None, *, allow_template: bool = False) -> dict:
    structural = validate_document(package, "output")
    if structural:
        return {"valid": False, "errors": structural, "warnings": [], "metricSignatures": {}, "queryChecks": {}, "impact": {}}
    try:
        return _validate_package(package, base, allow_template=allow_template)
    except (TypeError, KeyError, AttributeError, ValueError) as exc:
        return {"valid": False, "errors": [{"path": "$", "message": "结构或引用类型无效：" + str(exc)}], "warnings": [], "metricSignatures": {}, "queryChecks": {}, "impact": {}}


def _validate_package(package: dict, base: dict | None = None, *, allow_template: bool = False) -> dict:
    errors, warnings, query_checks = [], [], {}

    def error(path, text):
        errors.append({"path": path, "message": text})

    def collection(path, value):
        if not isinstance(value, list):
            error(path, "必须是数组")
            return []
        return value

    def index(path, values):
        result = {}
        for pos, value in enumerate(collection(path, values)):
            if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]:
                error(f"{path}[{pos}]", "必须有非空id")
                continue
            if value["id"] in result:
                error(path, "重复id：" + value["id"])
            result[value["id"]] = value
        return result

    if not isinstance(package, dict):
        return {"valid": False, "errors": [{"path": "$", "message": "映射包必须是对象"}], "warnings": [], "metricSignatures": {}, "queryChecks": {}, "impact": {}}
    for key in sorted(ROOT_FIELDS - package.keys()):
        error(key, "缺少必需字段")
    for key in sorted(package.keys() - ROOT_FIELDS):
        error(key, "核心包不接受未定义字段")
    if package.get("schemaVersion") != VERSION:
        error("schemaVersion", "仅支持" + VERSION)
    if package.get("template") is not False and not allow_template:
        error("template", "模板禁止作为实际映射包导入")
    for key in ("packageId", "analysisId", "projectId", "moduleId", "moduleName", "environmentId"):
        value = package.get(key)
        if not isinstance(value, str) or not value or len(value) > 160 or "REPLACE_WITH" in value:
            error(key, "必须为已填写的稳定标识/名称，最长160字符")
    manifest = package.get("inputManifest")
    if not isinstance(manifest, dict):
        error("inputManifest", "必须是输入对象")
        manifest = {}
    if manifest.get("template") is not False and not allow_template:
        error("inputManifest.template", "真实输入不能保留模板标记")
    if manifest.get("baseRevisionId") != package.get("baseRevisionId"):
        error("inputManifest.baseRevisionId", "输入与映射基线不一致")
    if manifest.get("projectId") != package.get("projectId") or manifest.get("module", {}).get("id") != package.get("moduleId"):
        error("inputManifest", "输入作用域与包头不一致")
    try:
        canonical_json(package)
    except (ValueError, TypeError):
        error("$", "只能使用有限数字及标准JSON类型")
    sources = index("sourceManifest", package.get("sourceManifest"))
    evidence = set(sources)
    for source in sources.values():
        if source.get("kind") in {"prototype", "live_ui", "screenshot"} and source.get("role") != "metric_evidence":
            error("sourceManifest." + source["id"], "界面资料只能作为目标指标证据")
        for item in source.get("evidence", []) or []:
            if not isinstance(item, dict) or not item.get("id"):
                error("sourceManifest", "证据片段缺少id")
            elif item["id"] in evidence:
                error("sourceManifest", "证据id重复：" + item["id"])
            else:
                evidence.add(item["id"])
    metrics = index("metrics", package.get("metrics"))
    rules = index("sharedRules", package.get("sharedRules"))
    queries = index("queries", package.get("queries"))
    questions = index("questions", package.get("questions"))
    cases = index("validationCases", package.get("validationCases"))
    for field in ("coverage", "pendingAnswers", "decisions", "validations"):
        collection(field, package.get(field))
    if not isinstance(package.get("analysisSummary"), (dict, list)):
        error("analysisSummary", "必须是摘要数组或对象")
    for field in ("checkpoint", "changeSet"):
        if not isinstance(package.get(field), dict):
            error(field, "必须是对象")

    def refs(path, obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in {"evidenceRefs", "questionIds", "prerequisiteQuestionIds"} and value is not None:
                    allowed = evidence if key == "evidenceRefs" else questions
                    for item in collection(path + "." + key, value):
                        if item not in allowed:
                            error(path + "." + key, "悬空引用：" + str(item))
                elif key not in {"inputManifest", "ruleIllustration"}:
                    refs(path + "." + key, value)
        elif isinstance(obj, list):
            for pos, item in enumerate(obj):
                refs(f"{path}[{pos}]", item)
    refs("$", package)
    binding_by_metric, steps_by_metric = {}, {}
    all_bindings = {}
    for mid, metric in metrics.items():
        path = "metrics." + mid
        for field in ("name", "type", "businessCategory", "definition", "lineage", "processing", "expectedResult", "actualBinding", "verificationPlan", "status"):
            if field not in metric:
                error(path + "." + field, "缺少字段")
        definition = metric.get("definition")
        if not isinstance(definition, dict):
            error(path + ".definition", "必须为业务定义对象")
            continue
        for field in ("meaning", "formula", "unit", "grain", "scope", "timeScope", "components", "validityRules", "deduplication", "nullPolicy", "precision", "ruleRefs", "metricRefs", "evidenceRefs", "questionIds"):
            if field not in definition:
                error(path + ".definition." + field, "缺少口径字段；未知用null并关联问题")
        for rule in definition.get("ruleRefs", []):
            if rule not in rules:
                error(path, "规则引用不存在：" + rule)
            else:
                for field, shared in rules[rule].get("definition", {}).items():
                    local = definition.get(field)
                    if local not in (None, [], {}, "") and local != shared:
                        error(path, "本地与共享口径冲突：" + field)
        for ref in definition.get("metricRefs", []):
            if not isinstance(ref, dict) or ref.get("metricId") not in metrics:
                error(path, "指标依赖不存在")
                continue
            if not ref.get("appliesTo") or not isinstance(ref.get("parameterBindings"), list):
                error(path, "指标依赖需明确用途与参数对应")
            for param in ref.get("parameterBindings", []):
                if not param.get("targetParameter") or ((param.get("sourceParameter") is None) == (param.get("literalValue") is None)):
                    error(path, "引用参数必须指定目标并二选一来源参数/固定值")
                target_names = {p["name"] for q in queries.values() if q.get("metricId") == ref["metricId"] for p in q.get("parameters", [])}
                source_names = {p["name"] for q in queries.values() if q.get("metricId") == mid for p in q.get("parameters", [])}
                if param.get("targetParameter") not in target_names or (param.get("sourceParameter") and param["sourceParameter"] not in source_names):
                    error(path, "跨指标参数引用未在双方查询中登记")
        nodes = index(path + ".nodes", metric.get("lineage", {}).get("nodes", []))
        steps = index(path + ".steps", metric.get("processing", {}).get("steps", []))
        bindings = {}
        for node in nodes.values():
            if node.get("layer") not in LAYERS:
                error(path, "节点层级无效：" + node["id"])
            for binding in node.get("physicalBindings") or []:
                bid = binding.get("id")
                if not bid or bid in bindings:
                    error(path, "绑定id缺失/重复")
                    continue
                bindings[bid] = binding
                if bid in all_bindings and all_bindings[bid] != binding:
                    error(path, "跨指标同id绑定内容不同：" + bid)
                all_bindings[bid] = binding
                for field in ("environmentId", "connectionRef", "dialect", "schema", "objectName", "fieldMap", "status", "evidenceRefs"):
                    if field not in binding:
                        error(path + ".bindings." + bid, "缺少" + field)
                if not IDENTIFIER.fullmatch(binding.get("objectName", "")) or not isinstance(binding.get("fieldMap"), dict):
                    error(path, "物理对象/字段映射无效")
                elif any(not isinstance(col, str) or not IDENTIFIER.fullmatch(col) for col in binding["fieldMap"].values()):
                    error(path, "物理字段名无效")
        for sid, step in steps.items():
            if step.get("kind") not in {"filter", "join", "map", "deduplicate", "aggregate", "calculate", "rank", "bucket", "select_result"}:
                error(path, "加工类型无效：" + sid)
            for nid in [*(step.get("inputNodeIds") or []), step.get("outputNodeId")]:
                if nid not in nodes:
                    error(path, "加工节点不存在：" + str(nid))
            for dep in step.get("dependsOn", []):
                if dep not in steps:
                    error(path, "步骤依赖不存在：" + dep)
        def visit_step(sid, visiting, done):
            if sid in visiting:
                error(path, "加工依赖循环：" + sid)
                return
            if sid in done or sid not in steps:
                return
            for dep in steps[sid].get("dependsOn", []):
                visit_step(dep, visiting | {sid}, done)
            done.add(sid)
        done = set()
        for sid in steps:
            visit_step(sid, set(), done)
        binding_by_metric[mid], steps_by_metric[mid] = bindings, steps
        for field in ("expectedResult", "actualBinding"):
            reference = metric.get(field) or {}
            if reference.get("nodeId") and reference["nodeId"] not in nodes:
                error(path + "." + field, "结果节点不存在")
            if reference.get("queryId") and reference["queryId"] not in queries:
                error(path + "." + field, "结果查询不存在")
        for layer in metric.get("verificationPlan", {}).get("queriesByLayer", []):
            for qid in layer.get("queryIds", []):
                if qid not in queries or queries[qid].get("metricId") != mid or queries[qid].get("layer") != layer.get("layer"):
                    error(path, "核验计划查询归属不匹配：" + qid)
        for cid in metric.get("verificationPlan", {}).get("caseIds", []):
            if cid not in cases or cases[cid].get("metricId") != mid:
                error(path, "核验用例不存在或归属不匹配：" + cid)
    for qid, query in queries.items():
        path, blocked, required = "queries." + qid, [], {}
        mid = query.get("metricId")
        if mid not in metrics:
            error(path, "指标不存在")
            continue
        if query.get("layer") not in LAYERS or query.get("dialect") not in {"mysql", "oracle"}:
            error(path, "查询层或方言无效")
        if query.get("kind") not in {"count", "detail", "calculate"} or query.get("purpose") not in {"input_count", "input_detail", "expected_value", "application_actual", "reference"}:
            error(path, "查询类型/用途无效")
        bindings = binding_by_metric.get(mid, {})
        for dep in query.get("dependencies", []):
            binding = bindings.get(dep.get("bindingId"))
            if not binding:
                error(path, "查询绑定不存在：" + str(dep.get("bindingId")))
                continue
            columns = dep.get("columns", [])
            if not columns or not set(columns).issubset(set(binding["fieldMap"].values())):
                error(path, "依赖列为空或未在绑定登记")
            required.setdefault(binding["objectName"], []).extend(columns)
            if binding.get("environmentId") != package.get("environmentId") or binding.get("connectionRef") != query.get("connectionRef") or binding.get("dialect") != query.get("dialect"):
                error(path, "绑定环境/连接/方言不一致")
            if binding.get("status") != "observed":
                blocked.append("物理绑定尚未核实：" + binding["id"])
        required = {k: sorted(set(v)) for k, v in required.items()}
        if not required:
            blocked.append("缺少物理字段依赖")
        if query.get("connectionRef") not in {"source", "analytics"}:
            blocked.append("连接引用未支持")
        if (query.get("layer") == "source") != (query.get("connectionRef") == "source"):
            error(path, "层级与连接引用不一致")
        prereqs = set(query.get("prerequisiteQuestionIds", []))
        for sid in query.get("stepIds", []):
            step = steps_by_metric.get(mid, {}).get(sid)
            if not step:
                error(path, "执行步骤不存在：" + sid)
            else:
                prereqs.update(step.get("questionIds", []))
        if query.get("purpose") == "expected_value":
            definition = deepcopy(metrics[mid].get("definition", {}))
            prereqs.update(definition.get("questionIds", []))
            for rid in definition.get("ruleRefs", []):
                prereqs.update(rules.get(rid, {}).get("questionIds", []))
                for field, value in rules.get(rid, {}).get("definition", {}).items():
                    if definition.get(field) in (None, [], {}, ""):
                        definition[field] = value
            for field in ("meaning", "formula", "unit", "grain", "scope", "timeScope", "nullPolicy"):
                if definition.get(field) in (None, "", {}):
                    blocked.append("计算口径尚未明确：" + field)
        # An answer reference is only provisional here; store rechecks against signed server answers.
        adopted = {d.get("questionId") for d in package.get("decisions", []) if d.get("answerId")}
        blocked.extend("口径问题未落实：" + q for q in sorted(prereqs - adopted))
        names = [p.get("name") for p in query.get("parameters", [])]
        if len(set(names)) != len(names) or any(not isinstance(n, str) or not IDENTIFIER.fullmatch(n) for n in names):
            error(path, "参数名无效/重复")
        for p in query.get("parameters", []):
            if p.get("type") not in {"string", "integer", "number", "date", "boolean"}:
                error(path, "参数类型无效")
            option = p.get("optionSource")
            if option:
                b = bindings.get(option.get("bindingId"))
                if not b or option.get("valueColumn") not in b.get("fieldMap", {}).values():
                    error(path, "参数选项绑定/字段不存在")
                label = option.get("labelSource")
                if label:
                    b = bindings.get(label.get("bindingId"))
                    if not b or any(label.get(k) not in b.get("fieldMap", {}).values() for k in ("keyColumn", "labelColumn")):
                        error(path, "参数标签绑定/字段不存在")
        sql = query.get("sql")
        if sql is None:
            blocked.append("SQL尚未建立")
        elif not isinstance(sql, str) or not sql.strip():
            error(path, "SQL必须是非空文本或null")
        else:
            try:
                clean = validate_sql(sql)
                placeholders = set(re.findall(r"(?<!:):([A-Za-z_]\w*)", clean))
                if placeholders != set(names):
                    error(path, "SQL占位符与参数不一致")
                blocked.extend(_sql_dependencies(sql, required))
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                if query.get("sqlChecksum") not in {None, checksum}:
                    error(path, "SQL校验和不一致")
            except ApiError as exc:
                error(path, exc.msg)
        contract = query.get("resultContract") or {}
        if not isinstance(contract.get("columns"), list):
            error(path, "必须登记结果字段契约")
        if query.get("kind") == "count" and not any(c.get("key") == "matched_records" and c.get("semanticRole") == "matched_records" for c in contract.get("columns", [])):
            error(path, "count必须返回matched_records并登记其语义")
        if query.get("purpose") == "application_actual":
            actual = metrics[mid].get("actualBinding") or {}
            if actual.get("queryId") != qid or actual.get("kind") not in {"table", "view", "result_query"} or not actual.get("evidenceRefs"):
                blocked.append("独立应用实值绑定或依据缺失")
            expected_id = (metrics[mid].get("expectedResult") or {}).get("queryId")
            if expected_id in queries and sql and sql.strip() == (queries[expected_id].get("sql") or "").strip():
                error(path, "不能复制需求复算SQL作为应用实值")
        query_checks[qid] = {"requiredColumns": required, "executionApproval": "blocked" if blocked else "documented",
                              "schemaOnlyBlocked": bool(blocked) and all(r.startswith("物理绑定尚未核实：") for r in blocked),
                              "blockedReasons": sorted(set(blocked)), "signature": query_signature(query)}
    for cid, case in cases.items():
        if case.get("metricId") not in metrics:
            error("validationCases." + cid, "指标不存在")
        ids = [case.get("execution", {}).get("queryId")]
        for ds in case.get("samplePlan", {}).get("inputDatasets", []):
            ids.extend([ds.get("queryId"), ds.get("countQueryId")])
        for qid in ids:
            if qid not in queries or queries[qid].get("metricId") != case.get("metricId"):
                error("validationCases." + cid, "用例查询不存在/归属不匹配：" + str(qid))
        if case.get("execution", {}).get("actualRows") or case.get("expected", {}).get("rows"):
            error("validationCases." + cid, "映射包只能引用执行证据，不能内嵌真实核算记录")
    for qid, question in questions.items():
        if not question.get("semanticKey") or not question.get("title") or not question.get("problem"):
            error("questions." + qid, "问题缺少业务说明或语义键")
        for mid in question.get("affectedMetricIds", []):
            if mid not in metrics:
                error("questions." + qid, "问题引用指标不存在")
        if question.get("contextHash") not in {None, question_context(question)}:
            error("questions." + qid, "问题上下文哈希不一致")
    signatures, impact = {}, {"changedRuleIds": [], "affectedMetricIds": [], "unaffectedMetricIds": sorted(metrics)}
    if not errors:
        try:
            signatures = semantic_signatures(package)
        except (ValueError, KeyError, TypeError) as exc:
            error("metrics", str(exc))
    if base and not errors:
        old_signatures = semantic_signatures(base)
        before_rules = {r["id"]: r for r in base["sharedRules"]}
        changed_rules = sorted(k for k in set(before_rules) | set(rules) if _semantic(before_rules.get(k)) != _semantic(rules.get(k)))
        changed = sorted(k for k, sig in signatures.items() if old_signatures.get(k) != sig)
        old_queries = {q["id"]: q for q in base["queries"]}
        changed_query_metrics = {q["metricId"] for qid, q in queries.items() if qid not in old_queries or query_signature(q) != query_signature(old_queries[qid])}
        changed_query_metrics.update(q["metricId"] for qid, q in old_queries.items() if qid not in queries)
        affected = set(affected_metrics(base, changed_rules, changed)) | set(affected_metrics(package, changed_rules, changed))
        deleted = set(old_signatures) - set(signatures)
        retired = {r.get("metricId", r.get("id")): r.get("reason") for r in (package.get("changeSet", {}).get("retired") or []) if isinstance(r, dict)}
        for mid in deleted:
            if not retired.get(mid):
                error("changeSet.retired", "删除指标必须给出明确退役理由：" + mid)
        scope = set(manifest.get("scope", {}).get("metricIds") or [])
        if scope and not (set(changed) | changed_query_metrics | deleted).issubset(scope):
            error("inputManifest.scope", "存在本次范围外业务或SQL变更：" + "、".join(sorted((set(changed) | changed_query_metrics | deleted) - scope)))
        impact = {"changedRuleIds": changed_rules, "affectedMetricIds": sorted(affected), "changedQueryMetricIds": sorted(changed_query_metrics), "unaffectedMetricIds": sorted(set(metrics) - affected - changed_query_metrics), "deletedMetricIds": sorted(deleted)}
        if changed_rules:
            review = package.get("changeSet", {}).get("impactReview") or {}
            reviewed = set(review.get("reviewedMetricIds") or [])
            unresolved = set(review.get("unresolvedMetricIds") or [])
            if not affected.issubset(reviewed) or unresolved:
                warnings.append({"path": "changeSet.impactReview", "message": "共用口径影响尚未处理完整；允许草稿，禁止生效", "blocksActivation": True})
            if not review.get("basis"):
                warnings.append({"path": "changeSet.impactReview.basis", "message": "共用口径变更缺少检查漏登记依赖的依据", "blocksActivation": True})
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "metricSignatures": signatures, "queryChecks": query_checks, "impact": impact}

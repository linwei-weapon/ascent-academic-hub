"""Project mapping business assets into the existing verification consumer contract."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json

from .config import ASSETS, database_config
from .mapping_contract import canonical_json

STEP_LABELS = {"filter": "按已登记条件筛选", "join": "按已登记关联键连接数据",
               "map": "按字段映射转换数据", "deduplicate": "按已登记规则去重",
               "aggregate": "按指标粒度汇总", "calculate": "按指标公式计算",
               "rank": "按已登记规则排序", "bucket": "按业务区间分组",
               "select_result": "选取本指标对应的结果"}


def _text(value):
    if value is None:
        return "待核实"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "；".join(_text(v) for v in value) or "无"
    if isinstance(value, dict):
        labels = {"result": "结果粒度", "observationEntity": "观察对象", "deduplicationEntity": "去重对象",
                  "dimensions": "维度", "organizationRule": "组织范围", "populationRule": "统计对象",
                  "kind": "类型", "parameter": "参数", "asOfRule": "截止规则", "zeroDenominator": "分母为零",
                  "meaning": "含义", "calculation": "计算精度", "comparison": "对照精度", "roundingRule": "舍入规则",
                  "keys": "去重键", "appliesTo": "适用范围", "finalAttemptSelection": "最终成绩选择",
                  "from": "来源", "to": "目标", "expression": "处理", "text": "说明"}
        return "；".join((labels.get(k, "说明") + "：" if k != "text" else "") + _text(v) for k, v in value.items()) or "无"
    return str(value)


def _step_text(step: dict) -> str:
    return _text(step.get("physicalPredicate") or step.get("fieldMappings") or step.get("description")
                 or STEP_LABELS.get(step.get("kind"), "加工步骤待说明"))


def metric_sources(package: dict, metric: dict) -> list[dict]:
    """Send the cited evidence with the metric, without unrelated document excerpts."""
    references = set()

    def collect(value):
        if isinstance(value, dict):
            references.update(value.get("evidenceRefs") or [])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(metric)
    for rule in package.get("sharedRules", []):
        if rule["id"] in metric["definition"].get("ruleRefs", []):
            collect(rule)
    sources = []
    for source in package.get("sourceManifest", []):
        # Full schema snapshots remain in the frozen package. The reader needs the
        # cited excerpt and locator here, not every column in both databases.
        evidence = [{key: deepcopy(value) for key, value in item.items() if key != "schemaSnapshot"}
                    for item in source.get("evidence", []) if item.get("id") in references]
        if evidence:
            sources.append({**{key: deepcopy(value) for key, value in source.items() if key != "evidence"},
                            "evidence": evidence})
    return sources


def layer_grain(nodes: list[dict]) -> str:
    physical = [node for node in nodes if node.get("physicalBindings")]
    grains = list(dict.fromkeys(_text(node.get("grain")) for node in physical or nodes))
    return "多表关联；各表粒度见下方" if len(grains) > 1 else (grains[0] if grains else "待登记")


def consumer_entries(entries: list[dict]) -> list[dict]:
    """An already-associated component does not need a second, generated home-page task."""
    def automatic(entry):
        return (entry.get("internalCompatibilityAnchor") is True
                and entry.get("id", "").startswith("mapping:")
                and entry.get("requirementId", "").startswith("mapping-anchor:"))
    established = {mid for entry in entries if not automatic(entry)
                   for mid in [entry["metricId"], *entry.get("evidenceMetricIds", [])]}
    return [entry for entry in entries if not (automatic(entry) and entry["metricId"] in established)]


@lru_cache(maxsize=2)
def _consumer_labels(module_id: str = "teaching-overview") -> dict[str, str]:
    """Read presentation labels only for early frozen bindings that omitted their name.

    This never supplies metric definitions, formulas, SQL, or a database-failure fallback.
    New revisions freeze the consumer name directly in bindings_json.
    """
    if module_id != "teaching-overview":
        return {}
    path = ASSETS / "catalog" / "teaching-overview.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    return {entry["id"]: entry["name"] for entry in document.get("indicatorSystem", {}).get("entries", [])
            if isinstance(entry.get("name"), str) and entry["name"].strip()}


def consumer_label(entry: dict, metric: dict, module_id: str = "teaching-overview") -> str:
    if isinstance(entry.get("name"), str) and entry["name"].strip():
        return entry["name"]
    alias = next((value for value in entry.get("aliases", []) if isinstance(value, str) and value.strip()), None)
    if alias and alias not in {metric["id"], metric["name"]}:
        return alias
    return _consumer_labels(module_id).get(entry["id"]) or alias or metric["name"]


def catalog(revision: dict) -> dict:
    package, bindings = revision["package"], revision["bindings"]
    by_id, metrics = {}, []
    questions = {q["id"]: q for q in package["questions"]}
    for metric in package["metrics"]:
        definition = deepcopy(metric["definition"])
        for rule in package["sharedRules"]:
            if rule["id"] in definition.get("ruleRefs", []):
                for key, value in rule["definition"].items():
                    if definition.get(key) in (None, [], {}, ""):
                        definition[key] = value
        components = {c["key"]: c for c in definition.get("components", [])}
        issues = [questions[q]["title"] for q in definition.get("questionIds", []) if q in questions]
        refs = [ref for source in package["sourceManifest"] for ref in source.get("evidence", [])
                if ref["id"] in definition.get("evidenceRefs", [])
                and (package["moduleId"] != "ai-briefing" or source.get("role") == "requirement")]
        sections = list(dict.fromkeys(str(e.get("locator", {}).get("section")) for e in refs if e.get("locator", {}).get("section")))
        converted = {"id": metric["id"], "name": metric["name"], "type": metric["type"],
                     "definition": _text(definition.get("meaning")), "formula": _text(definition.get("formula")),
                     "grain": _text(definition.get("grain")), "unit": definition.get("unit") or "",
                     "numerator": _text(components.get("numerator", {}).get("expression")),
                     "denominator": _text(components.get("denominator", {}).get("expression")),
                     "scope": [_text(definition.get("scope")), _text(definition.get("timeScope"))],
                     "nullPolicy": _text(definition.get("nullPolicy")), "sourceSections": sections, "issues": issues,
                     "mappingStatus": metric.get("status", {}).get("mappingStatus", "partial"),
                     "managementUse": definition.get("businessPurpose") or "", "mappingNote": "数据库冻结映射版本；业务核验状态以实际记录为准",
                     "businessCategory": metric.get("businessCategory"), "calculationSteps": [
                         _step_text(step) for step in metric["processing"]["steps"]],
                     "boundaryChecks": [_text(definition.get("nullPolicy")), _text(definition.get("precision"))],
                     "components": [c.get("name", c["key"]) + "：" + _text(c.get("expression")) for c in definition.get("components", [])],
                     "semanticSignature": revision["validation"]["metricSignatures"].get(metric["id"])}
        by_id[metric["id"]] = converted
        metrics.append(converted)
    entries = []
    for old in consumer_entries(bindings["entries"]):
        metric = by_id[old["metricId"]]
        entries.append({**deepcopy(old), "name": consumer_label(old, metric, package["moduleId"]), "meaning": metric["definition"], "formula": metric["formula"],
                        "components": metric["components"], "sourceSections": metric["sourceSections"], "pendingIssues": metric["issues"]})
    requirements = []
    for req_id, anchor in bindings["requirements"].items():
        ids = list(dict.fromkeys(mid for e in entries if e["requirementId"] == req_id
                                for mid in [e["metricId"], *e.get("evidenceMetricIds", [])]))
        if not ids:
            continue
        names = [by_id[mid]["name"] for mid in ids]
        requirements.append({**deepcopy(anchor), "title": "、".join(names), "description": "；".join(by_id[mid]["definition"] for mid in ids),
                             "category": "metric", "acceptanceCriteria": [by_id[mid]["formula"] for mid in ids], "metricIds": ids,
                             "pagePaths": anchor.get("pagePaths", []), "source": anchor.get("source", {"startLine": 0, "endLine": 0}),
                             "issues": [issue for mid in ids for issue in by_id[mid]["issues"]]})
    return {"schemaVersion": package["schemaVersion"], "module": {**bindings.get("module", {}), "id": package["moduleId"], "name": package["moduleName"]},
            "requirements": requirements, "metrics": metrics, "conflicts": [],
            "indicatorSystem": {**bindings.get("indicatorSystem", {}), "entries": entries},
            "mappingRevisionId": revision["revisionId"], "mappingSummary": {"revisionId": revision["revisionId"],
                "schemaVersion": package["schemaVersion"], "packageId": package["packageId"], "metricCount": len(metrics), "questionCount": len(questions)},
            "mappingQuestions": list(questions.values())}


def queries_document(revision: dict) -> dict:
    package = revision["package"]
    metrics = []
    for metric in package["metrics"]:
        layers = []
        all_bindings = {b["id"]: b for n in metric["lineage"]["nodes"] for b in n.get("physicalBindings") or []}
        for layer_id, name in (("source", "贴源层"), ("fact", "事实层"), ("application", "应用层")):
            nodes = [n for n in metric["lineage"]["nodes"] if n["layer"] == layer_id]
            plans = [p for p in metric["verificationPlan"]["queriesByLayer"] if p["layer"] == layer_id]
            queries = []
            for source in package["queries"]:
                if source["metricId"] != metric["id"] or source["layer"] != layer_id:
                    continue
                query = deepcopy(source)
                check = revision["validation"]["queryChecks"][source["id"]]
                reasons = list(check["blockedReasons"])
                config = database_config(layer_id)
                for dep in source.get("dependencies", []):
                    binding = all_bindings[dep["bindingId"]]
                    configured_schema = config.service_name if config.engine == "oracle" else config.database
                    # Oracle schema can be the authenticated schema rather than the service name.
                    if binding.get("dialect") == "mysql" and binding.get("schema") != configured_schema:
                        reasons.append("物理绑定schema与当前连接不一致")
                query.update({"requiredColumns": check["requiredColumns"], "executionApproval": "blocked" if reasons else "documented",
                              "blockedReason": "；".join(dict.fromkeys(reasons)), "blockedReasons": reasons,
                              "schemaOnlyBlocked": bool(reasons) and all(r.startswith("物理绑定尚未核实：") for r in reasons),
                              "checksum": hashlib.sha256(source["sql"].encode()).hexdigest() if source.get("sql") else None,
                              "version": source.get("version") or "unversioned", "mappingRevisionId": revision["revisionId"],
                              "metricSemanticSignature": revision["validation"]["metricSignatures"].get(metric["id"]),
                              "physicalBindings": all_bindings,
                              "resultRole": "requirement_recalculation" if source["purpose"] == "expected_value" else "application_actual" if source["purpose"] == "application_actual" else "source_evidence"})
                queries.append(query)
            gaps = list(dict.fromkeys(p["gap"] for p in plans if p.get("gap")))
            node_ids = {n["id"] for n in nodes}
            processing = [s for s in metric["processing"]["steps"] if s.get("outputNodeId") in node_ids]
            physical_tables = list(dict.fromkeys(b["objectName"] for n in nodes for b in n.get("physicalBindings") or []))
            is_reference = layer_id == "application" and not any(q["purpose"] == "application_actual" for q in queries)
            layers.append({"id": layer_id, "name": name, "tables": physical_tables,
                           "grain": layer_grain(nodes),
                           "transform": list(dict.fromkeys(_step_text(s) for s in processing)),
                           "issues": gaps, "remainingGaps": gaps, "status": "partial" if gaps else "documented", "queries": queries,
                           "mappingMode": ("reference_from_fact" if any(t.upper().startswith("ACT_") for t in physical_tables) else "related_table_evidence") if is_reference else "physical_table" if physical_tables else "virtual_result",
                           "directSource": "、".join(dict.fromkeys(n["logicalName"] for n in nodes)), "metricResultStatus": "mapped" if layer_id != "application" or metric["actualBinding"].get("status") == "mapped" else "unmapped",
                           "metricResultReason": metric["actualBinding"].get("reason", "") if layer_id == "application" else ""})
        metrics.append({"metricId": metric["id"], "layers": layers, "mappingRevisionId": revision["revisionId"], "mappingMetric": deepcopy(metric),
                        "mappingSources": metric_sources(package, metric),
                        "sharedRules": [r for r in package["sharedRules"] if r["id"] in metric["definition"].get("ruleRefs", [])],
                        "validationCases": [c for c in package["validationCases"] if c["metricId"] == metric["id"]]})
    return {"schemaVersion": package["schemaVersion"], "mappingRevisionId": revision["revisionId"], "metrics": metrics}

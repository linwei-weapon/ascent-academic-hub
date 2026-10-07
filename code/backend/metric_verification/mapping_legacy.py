"""One-time migration of reviewed 106 business definitions; never a runtime authority.

The legacy catalog remains a compatibility/layout source only.  This module does
not read student rows, connect to a database, execute SQL, or approve definitions.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
ASSET_REL = Path("code/metric-verification")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _category(metric):
    mid = metric["id"]
    if mid in {"O-01", "MV106-TERM-COURSE-COUNT", "MV106-TEACHER-COUNT"}:
        return "教学规模"
    if "PLAN" in mid or mid in {"O-16", "MV106-REQUIRED-FAILURE-COUNT"}:
        return "培养方案进度"
    if any(x in mid for x in ("ALERT", "RULE", "FOLLOWUP", "ATTENTION", "DIFFICULTY")) or mid in {"O-13", "O-14"}:
        return "预警与核查结果"
    if metric["type"] in {"ranking", "distribution", "difference", "comparison"}:
        return "分布与比较"
    if any(x in mid for x in ("STUDENT", "CURRENT", "UNRESOLVED", "HISTORY", "EARNED", "GROWTH", "STATUS")) or mid == "O-06":
        return "个人学业结果"
    if any(x in mid for x in ("COURSE", "ATTEMPT", "PASS", "SCORE")) or mid in {"O-09", "O-11", "O-20", "O-22", "O-23"}:
        return "课程修读结果"
    return "整体学业表现"


def _shape(metric):
    if metric["id"] == "MV106-COLLEGE-EXCESS-IMPACT": return "ranking"
    return {"ranking": "ranking", "distribution": "distribution", "collection": "collection",
            "classification": "collection"}.get(metric["type"], "scalar")


def _question(qid, title, text, mids, refs, analysis, owner="data_owner"):
    q = {"id": qid, "semanticKey": qid.lower(), "status": "open", "ownerRole": owner,
         "title": title, "problem": text, "type": "technical_gap" if owner != "product_manager" else "business_rule_ambiguity",
         "affectedMetricIds": mids, "evidenceRefs": refs, "options": [], "recommendation": None,
         "blockedActions": ["受影响的正式计算或应用对照"], "unaffectedActions": ["查看已知输入与记录数", "处理其他明确指标"],
         "analysisId": analysis, "affectedDefinitionFields": [], "appliedRevisionId": None,
         "customAnswerAllowed": True}
    from .mapping_contract import question_context
    q["contextHash"] = question_context(q)
    return q


def _column(key, metric, role=None):
    role = role or {"candidate_metric_value": "metric_value", "numerator": "numerator",
                    "denominator": "denominator", "matched_records": "matched_records"}.get(key, "supporting")
    unit = metric.get("unit", "") if role == "metric_value" else ""
    if role == "matched_records": unit = "条"
    if role in {"numerator", "denominator"}:
        unit = "人次" if metric["id"] == "O-11" else "人" if metric["id"] == "O-10" else ""
    return {"key": key, "label": metric["name"] if role == "metric_value" else key,
            "dataType": "integer" if role == "matched_records" else "decimal", "unit": unit,
            "semanticRole": role, "nullMeaning": "无可计算结果；不等同于0或查询失败"}


def _result_contract(query, metric, layer_queries):
    sql = query.get("sql", "")
    kind = query["kind"]
    if kind == "count":
        keys = ["matched_records"]
    elif kind == "detail":
        keys = []  # Physical columns remain visible in the captured execution.
    else:
        keys = [k for k in ("candidate_metric_value", "numerator", "denominator", "input_records", "students_with_gpa", "included_credits")
                if re.search(r"\bAS\s+" + k + r"\b", sql, re.I)]
    shape = _shape(metric) if kind == "calculate" else "scalar" if kind == "count" else "collection"
    if metric["id"] == "MV106-GPA-DISTRIBUTION" and kind == "calculate": keys = ["bucket", "student_count", "share_percent"]
    if metric["id"] == "MV106-SCORE-DISTRIBUTION" and kind == "calculate": keys = ["score_bucket", "attempt_count", "share_percent"]
    count = next((q["id"] for q in layer_queries if q["kind"] == "count" and q["dialect"] == query["dialect"]), None)
    cols = [_column(k, metric) for k in keys]
    for c in cols:
        if c["key"] in {"bucket", "score_bucket"}: c.update(dataType="string", semanticRole="dimension")
        if c["key"] == "share_percent": c.update(unit="%", semanticRole="share")
    return {"shape": shape, "rowKey": ["bucket"] if keys and keys[0] == "bucket" else [], "ordering": [],
            "rowCountMeaning": "输入记录总数" if kind == "count" else "查询输出行数，与输入记录数及学生数分开",
            "columns": cols, "completeness": {"expected": "complete", "truncationPolicy": "block_auto_import",
                                               "totalCountQueryId": count if kind == "detail" else None}}


def build_initial_package(repo_root=None, technical_dir=None):
    """Convert the reviewed legacy artifacts, retaining limitations and provenance.

    This explicitly selected migration is useful for initial seeding only. Future
    updates use the persisted package baseline through metric_mapping.py.
    """
    root = Path(repo_root or ROOT)
    assets = root / ASSET_REL
    old = _read(assets / "catalog/teaching-overview.json")
    oldq = _read(assets / "queries/teaching-overview.json")
    template = _read(assets / "contracts/mapping-output.template.json")
    inp = _read(assets / "contracts/mapping-input.template.json")
    analysis = "ANALYSIS-106-INITIAL-20260930"
    reqpath = root / old["module"]["sourceDocument"]
    lines = reqpath.read_text(encoding="utf-8-sig").splitlines()
    inp.update(template=False, analysisId=analysis)
    inp["scope"]["metricIds"] = [m["id"] for m in old["metrics"]]
    inp["scope"]["businessCategories"] = sorted({_category(m) for m in old["metrics"]})
    inp["sources"] = [s for s in inp["sources"] if s["role"] != "metric_evidence"]
    inp["sources"][0].update(contentHash=hashlib.sha256(reqpath.read_bytes()).hexdigest(), sections=["2.4", "3—10", "12", "13.2"])
    inp["environment"].update(sourceConnectionProfileRef="metric-verification:source", analyticsConnectionProfileRef="metric-verification:analytics")
    package = {k: deepcopy(v) for k, v in template.items() if k not in {"metrics", "queries", "questions", "validationCases", "sourceManifest", "coverage", "sharedRules"}}
    package.update(template=False, analysisId=analysis, inputManifest=inp, baseRevisionId=None,
                   sourceManifest=[], coverage=[], metrics=[], queries=[], questions=[], sharedRules=[],
                   validationCases=[], validations=[], pendingAnswers=[], decisions=[])
    for src in inp["sources"]:
        package["sourceManifest"].append({**deepcopy(src), "evidence": []})
    reqsource = package["sourceManifest"][0]
    for req in old["requirements"]:
        start, end = req.get("source", {}).get("startLine"), req.get("source", {}).get("endLine")
        if not req.get("metricIds"): continue
        excerpt = "\n".join(lines[start - 1:end]) if start and end else req.get("sourceExcerpt")
        reqsource["evidence"].append({"id": "E-" + req["id"], "locator": {"section": req["section"], "lineStart": start, "lineEnd": end},
                                      "excerpt": excerpt, "status": "captured"})
        package["coverage"].append({"id": "C-" + req["id"], "sourceRef": reqsource["id"], "locator": req["section"],
                                    "disposition": "included", "metricIds": req["metricIds"],
                                    "reason": "仅抽取本段业务指标；组成留在定义中，页面与权限条款不生成指标"})
    package["coverage"].append({"id": "C-SCOPE-EXCLUSIONS", "sourceRef": reqsource["id"], "locator": "1、2.1—2.3、2.5、各路径/下钻说明、11",
                                "disposition": "excluded", "metricIds": [], "reason": "页面组织、权限功能和AI交互不是本Skill业务指标；范围约束仍由消费端执行"})
    for name, role, rel in (("SRC-LEGACY-MAPPING", "mapping_baseline", "catalog/teaching-overview.json"),
                            ("SRC-LEGACY-QUERIES", "query_baseline", "queries/teaching-overview.json")):
        path = assets / rel
        package["sourceManifest"].append({"id": name, "kind": "document", "role": role, "title": "106既有审阅资产迁移基线",
                                           "location": (ASSET_REL / rel).as_posix(), "version": "2.0.0",
                                           "contentHash": hashlib.sha256(path.read_bytes()).hexdigest(),
                                           "evidence": [{"id": "E-" + name, "locator": {"jsonPointer": "/metrics"},
                                                         "excerpt": "沿用已登记物理字段与SQL；不继承历史运行成功为本次通过。", "status": "captured"}]})
    design_text = ""
    # Original documents are read only when an explicitly supplied local directory exists.
    for src in package["sourceManifest"]:
        if src["id"] in {"SRC-ORACLE-V6", "SRC-DESIGN-V6"}:
            src["availability"] = "original_not_located_in_repository"
            src["evidence"] = []
            if technical_dir:
                title = "Oracle源表字段完整清单V6.0(2).md" if src["id"] == "SRC-ORACLE-V6" else "中国矿业大学学业分析平台数据库设计文档V6.0(3).md"
                original = Path(technical_dir) / title
                if original.is_file():
                    text = original.read_text(encoding="utf-8-sig")
                    src.update(location=original.as_posix(), contentHash=hashlib.sha256(original.read_bytes()).hexdigest(), availability="captured")
                    if src["id"] == "SRC-DESIGN-V6": design_text = text
                    chunks = list(re.finditer(r"(?m)^#{2,5} .+$", text))
                    wanted = {t for m in oldq["metrics"] for l in m["layers"] for t in l.get("tables", [])}
                    for i, heading in enumerate(chunks):
                        table = next((t for t in sorted(wanted, key=len, reverse=True) if re.search(r"\b" + re.escape(t) + r"\b", heading.group())), None)
                        if not table or any(e["id"] == "E-" + src["id"] + "-" + table for e in src["evidence"]): continue
                        end = chunks[i + 1].start() if i + 1 < len(chunks) else len(text)
                        src["evidence"].append({"id": "E-" + src["id"] + "-" + table,
                            "locator": {"heading": heading.group(), "lineStart": text[:heading.start()].count("\n") + 1},
                            "excerpt": text[heading.start():end].strip(), "status": "captured"})
                    input_src = next(s for s in inp["sources"] if s["id"] == src["id"])
                    input_src.update(location=src["location"], contentHash=src["contentHash"])
    byquery = {m["metricId"]: m for m in oldq["metrics"]}
    refs = {m["id"]: ["E-" + r["id"] for r in old["requirements"] if m["id"] in r.get("metricIds", [])] for m in old["metrics"]}
    grade_mids = [m["id"] for m in old["metrics"] if any("ACT_GRADE_ATTEMPT" in l.get("tables", []) for l in byquery[m["id"]]["layers"])
                  and m["id"] not in {"MV106-GPA-ARITHMETIC", "MV106-HISTORICAL-FAILED-COURSES", "MV106-STUDENT-COURSE-RESULT"}]
    package["sharedRules"] = [
        {"id": "RULE-VALID-GRADE", "name": "真实有效成绩", "definition": {"validityRules": ["已发布、未作废、结果明确；真实来源、同一业务范围。源枚举映射与事实字段分别核验。"]}, "evidenceRefs": ["E-R106-03-05", "E-SRC-LEGACY-QUERIES"], "questionIds": []},
        {"id": "RULE-NULL-RATIO", "name": "比例空值与可比性", "definition": {"nullPolicy": "分母为0或来源缺失返回空；分母大于0而分子为0才为0。比率变化用百分点。"}, "evidenceRefs": ["E-R106-02-04"] if any(e["id"] == "E-R106-02-04" for e in reqsource["evidence"]) else ["E-R106-03-05"], "questionIds": []},
    ]
    dependencies = {
        "O-10": [("O-08", "components.numerator"), ("O-02", "components.denominator")],
        "O-19": [("O-02", "components.numerator"), ("O-01", "components.denominator")],
        "O-14": [("O-13", "components.numerator"), ("O-01", "components.denominator")],
        "O-11": [("O-09", "components.numerator"), ("MV106-VALID-ATTEMPT-COUNT", "components.denominator")],
        "MV106-COLLEGE-EXCESS-IMPACT": [("O-10", "formula.college_and_school_rate"), ("O-02", "formula.college_population")],
        "MV106-GPA-DISTRIBUTION": [("MV106-STUDENT-TERM-GPA", "formula.student_gpa")],
        "O-05": [("MV106-STUDENT-TERM-GPA", "formula.student_gpa")],
        "MV106-GPA-RANK": [("O-05", "formula.college_gpa")],
    }
    for oldm in old["metrics"]:
        mid = oldm["id"]
        mr = refs[mid]
        shape = _shape(oldm)
        metric = {"id": mid, "name": oldm["name"], "type": oldm["type"], "version": "1.0.0",
                  "businessCategory": _category(oldm), "definition": {
                      "businessPurpose": oldm.get("managementUse") or oldm["definition"], "meaning": oldm["definition"],
                      "formula": oldm["formula"], "unit": oldm.get("unit"),
                      "grain": {"result": oldm.get("grain"), "observationEntity": oldm.get("grain"), "deduplicationEntity": None, "dimensions": []},
                      "components": [{"key": k, "name": oldm[k], "unit": None, "expression": oldm[k]} for k in ("numerator", "denominator") if oldm.get(k)],
                      "validityRules": [], "deduplication": {"keys": [], "appliesTo": oldm["formula"], "finalAttemptSelection": None},
                      "timeScope": {"kind": "requirement_defined", "parameter": None, "asOfRule": oldm.get("grain")},
                      "nullPolicy": None if oldm["type"] == "ratio" else {"zeroDenominator": "null", "meaning": oldm.get("nullPolicy")},
                      "scope": {"organizationRule": "既有服务端当前身份范围", "populationRule": oldm.get("scope", [])},
                      "precision": {"calculation": "不在中间步骤四舍五入", "comparison": None, "roundingRule": "以106明确精度为准；无要求时保留原值"},
                      "evidenceRefs": mr, "questionIds": [], "ruleRefs": (["RULE-VALID-GRADE"] if mid in grade_mids else []) + (["RULE-NULL-RATIO"] if oldm["type"] == "ratio" else []),
                      "metricRefs": [{"metricId": target, "appliesTo": use, "parameterBindings": []} for target, use in dependencies.get(mid, [])]},
                  "lineage": {"nodes": []}, "processing": {"steps": []},
                  "expectedResult": {"nodeId": mid + "-expected", "queryId": None, "shape": shape},
                  "actualBinding": {"status": "unmapped", "kind": None, "nodeId": None, "queryId": None, "valueField": None,
                                    "evidenceRefs": [], "questionIds": [], "reason": "尚无本轮同条件独立应用实值；物理对象原值与事实参考不冒充应用结果"},
                  "status": {"definitionStatus": oldm.get("definitionStatus", "documented"), "mappingStatus": "partial",
                             "schemaStatus": "not_checked", "queryStatus": "registered_not_verified", "actualBindingStatus": "unmapped"},
                  "verificationPlan": {"queriesByLayer": [], "caseIds": [], "comparison": {"shape": shape, "dimensions": [],
                       "requiredConditions": ["同一业务范围", "同一业务时点", "相同规则、单位和精度", "完整或明确抽样范围"],
                       "actualValueMode": "manual_observation", "judgmentOwner": "authorized_human"}, "closureStatus": "not_verified"}}
        if oldm.get("issues"):
            qid = "Q-" + mid + "-DEFINITION"
            package["questions"].append(_question(qid, oldm["name"] + "的待核实口径与数据条件", "；".join(oldm["issues"]), [mid], mr, analysis))
            if not any(q.get("kind") == "calculate" and q.get("executionApproval") == "documented"
                       for l in byquery[mid]["layers"] if l["id"] == "fact" for q in l.get("queries", [])):
                metric["definition"]["questionIds"].append(qid)
        nodes = metric["lineage"]["nodes"]
        nodes.append({"id": mid + "-expected", "layer": "application", "role": "expected_result", "objectType": "virtual_result",
                      "logicalName": "需求结果：" + oldm["name"], "physicalBindings": [], "fields": [], "grain": oldm.get("grain"), "evidenceRefs": mr, "questionIds": []})
        for layer in byquery[mid]["layers"]:
            lid = layer["id"]
            qs = layer.get("queries", [])
            fields = {}
            for q in qs:
                for table, columns in q.get("requiredColumns", {}).items(): fields.setdefault((q["dialect"], table), set()).update(columns)
            lookup = {}
            for (dialect, table), columns in fields.items():
                bid = mid + "-" + lid + "-" + dialect + "-" + table
                lookup[(dialect, table)] = bid
                nodes.append({"id": "N-" + bid, "layer": lid, "role": "business_input" if lid != "application" else "related_application_object",
                              "objectType": "table", "logicalName": table, "fields": sorted(columns), "grain": layer.get("grain"),
                              "physicalBindings": [{"id": bid, "environmentId": "test-114", "connectionRef": "source" if lid == "source" else "analytics",
                                   "dialect": dialect, "schema": ("edu_source" if lid == "source" else "edu_analytics_v3") if dialect == "mysql" else None,
                                   "objectName": table, "fieldMap": {c: c for c in sorted(columns)}, "status": "design_only", "evidenceRefs": ["E-SRC-LEGACY-QUERIES"]}],
                              "evidenceRefs": ["E-SRC-LEGACY-QUERIES"], "questionIds": []})
            gaps = list(dict.fromkeys(layer.get("remainingGaps", []) + layer.get("issues", [])))
            metric["verificationPlan"]["queriesByLayer"].append({"layer": lid, "queryIds": [q["id"] for q in qs],
                                                                 "gap": "；".join(gaps) or (None if qs else layer.get("closureReason", "暂无独立查询"))})
            sid = mid + "-" + lid + "-processing"
            result_node = mid + "-expected"
            if lid != "fact":
                result_node = mid + "-" + lid + "-evidence"
                nodes.append({"id": result_node, "layer": lid, "role": "source_evidence" if lid == "source" else "related_application_evidence",
                    "objectType": "virtual_result", "logicalName": "来源原值证据" if lid == "source" else "待核对的应用对象原值/事实参考",
                    "physicalBindings": [], "fields": [], "grain": layer.get("grain"), "evidenceRefs": ["E-SRC-LEGACY-QUERIES"], "questionIds": []})
            metric["processing"]["steps"].append({"id": sid, "kind": "calculate" if lid == "fact" else "select_result",
                "inputNodeIds": ["N-" + b for b in lookup.values()], "outputNodeId": result_node, "dependsOn": [],
                "definitionFields": ["formula", "scope", "timeScope", "ruleRefs"], "fieldMappings": [], "join": None,
                "physicalPredicate": None, "description": layer.get("transform", []), "evidenceRefs": ["E-SRC-LEGACY-QUERIES"], "questionIds": []})
            for oq in qs:
                blocked = oq.get("blockedReason") if oq.get("executionApproval") != "documented" else None
                prereq = []
                if blocked:
                    qid = "Q-" + oq["id"]
                    package["questions"].append(_question(qid, oldm["name"] + "查询条件待核实", blocked, [mid], mr, analysis))
                    prereq.append(qid)
                kind = oq["kind"]
                purpose = "input_count" if kind == "count" else "input_detail" if kind == "detail" else "reference" if lid == "application" else "expected_value"
                params = []
                for param in oq.get("parameters", []):
                    option = None
                    name = param["name"]
                    for (dialect, table), cols in fields.items():
                        if dialect != oq["dialect"] or name == "student_id": continue
                        col = name
                        if name.endswith("_batch_id"):
                            hint = name[:-9].upper()
                            if hint not in table: continue
                            col = "batch_id"
                        if col in cols:
                            option = {"bindingId": lookup[(dialect, table)], "valueColumn": col, "labelSource": None}
                            break
                    params.append({**param, "default": None, "defaultPolicy": "explicit_selection", "optionSource": option})
                nq = {"id": oq["id"], "metricId": mid, "layer": lid, "kind": kind, "purpose": purpose,
                      "dialect": oq["dialect"], "version": oq["version"], "sql": oq.get("sql"),
                      "sqlChecksum": hashlib.sha256(oq["sql"].encode()).hexdigest() if oq.get("sql") else None,
                      "parameters": params, "dependencies": [{"bindingId": lookup[(oq["dialect"], t)], "columns": cs} for t, cs in oq.get("requiredColumns", {}).items()],
                      "resultContract": _result_contract(oq, oldm, qs), "prerequisiteQuestionIds": prereq,
                      "technicalChecks": None, "blockedReason": blocked, "stepIds": [sid] if kind == "calculate" else [],
                      "connectionRef": "source" if lid == "source" else "analytics", "title": oq.get("title") or oldm["name"] + " / " + lid + " / " + kind}
                package["queries"].append(nq)
                if lid == "fact" and kind == "calculate" and not blocked:
                    metric["expectedResult"]["queryId"] = nq["id"]
        # Source -> fact links come from the original design's field mapping rows,
        # not from similarity of object names or a blanket source -> application arrow.
        for fact in [n for n in nodes if n["layer"] == "fact" and n["objectType"] == "table"]:
            target_table = fact["logicalName"]
            section = re.search(r"(?m)^#{3,5} .*\b" + re.escape(target_table) + r"\b.*$", design_text)
            if not section: continue
            following = re.search(r"(?m)^#{2,5} ", design_text[section.end():])
            fragment = design_text[section.end():section.end() + following.start()] if following else design_text[section.end():]
            mappings, input_nodes = [], []
            for line in fragment.splitlines():
                columns = [c.strip().strip('`') for c in line.split('|')]
                if len(columns) < 7 or not columns[1].isdigit(): continue
                field = columns[2]
                if field not in fact["fields"]: continue
                match = re.search(r"\b([A-Z][A-Z_0-9]*)\.([A-Z][A-Z_0-9]*)\b", columns[4])
                if not match: continue
                table, source_field = match.groups()
                for source_node in nodes:
                    if source_node["layer"] != "source" or source_node["logicalName"] != table or source_field not in source_node["fields"]: continue
                    mappings.append({"from": source_node["id"] + "." + source_field, "to": fact["id"] + "." + field,
                                     "expression": "按V6设计映射；实际ETL枚举、类型和时点仍需源事实对照"})
                    input_nodes.append(source_node["id"])
            eid = "E-SRC-DESIGN-V6-" + target_table
            if mappings:
                metric["processing"]["steps"].append({"id": fact["id"] + "-source-map", "kind": "map", "inputNodeIds": sorted(set(input_nodes)),
                    "outputNodeId": fact["id"], "dependsOn": [], "definitionFields": [], "fieldMappings": mappings, "join": None,
                    "physicalPredicate": None, "evidenceRefs": [eid], "questionIds": []})
        package["metrics"].append(metric)
    metric_by_id = {m["id"]: m for m in package["metrics"]}
    query_by_id = {q["id"]: q for q in package["queries"]}
    for metric in package["metrics"]:
        own = next((q for q in package["queries"] if q["metricId"] == metric["id"] and q["layer"] == "fact" and q["kind"] == "calculate"), None)
        own_names = {p["name"] for p in own["parameters"]} if own else set()
        for ref in metric["definition"]["metricRefs"]:
            target = next((q for q in package["queries"] if q["metricId"] == ref["metricId"] and q["layer"] == "fact" and q["kind"] == "calculate"), None)
            names = {p["name"] for p in target["parameters"]} if target else set()
            ref["parameterBindings"] = [{"targetParameter": n, "sourceParameter": n, "literalValue": None} for n in sorted(names & own_names)]
            if metric["id"] == "MV106-COLLEGE-EXCESS-IMPACT" and ref["metricId"] == "O-10":
                ref["appliesTo"] = "formula：分别在当前学院及全校授权范围计算同口径O-10；组织范围变换须在排序SQL中明确，不能把同一组织结果同时当两方"
    o10 = metric_by_id["O-10"]["definition"]
    o10.update(grain={"result": "组织范围×学期", "observationEntity": "成绩修读尝试", "deduplicationEntity": "学生", "dimensions": ["semester_id", "organization_id", "major_id", "grade"]},
        deduplication={"keys": ["student_id"], "appliesTo": "分子分母分别去重", "finalAttemptSelection": "本期至少一次有效未通过即计入；不按课程最后结果覆盖"},
        timeScope={"kind": "semester", "parameter": "semester_id", "asOfRule": "当次留存的所选学期真实记录；成绩/学生批次独立选择，不承诺历史重取"})
    o10["components"] = [{"key": "numerator", "name": "未通过学生数", "unit": "人", "expression": "有效成绩集合中is_pass=0的student_id去重数"},
                         {"key": "denominator", "name": "有效成绩学生数", "unit": "人", "expression": "同一有效成绩集合student_id去重数"}]
    o10["precision"]["comparison"] = {"mode": "absolute", "tolerance": "0.000001", "unit": "%", "basis": "SQL独立核算容差；页面显示比较另按原始精度记录"}
    # Preserve already confirmed user decisions as source evidence, never invent service answer IDs.
    for conflict in old["conflicts"]:
        if not conflict.get("userConfirmed"): continue
        eid = "E-DECISION-" + conflict["id"]
        package["sourceManifest"].append({"id": "SRC-DECISION-" + conflict["id"], "kind": "user_decision", "role": "confirmed_business_decision",
            "title": conflict["id"], "location": old["module"]["sourceDocument"] + "#13.2", "version": None, "contentHash": _hash(conflict["resolution"]),
            "evidence": [{"id": eid, "locator": {"section": "13.2", "decisionId": conflict["id"]}, "excerpt": conflict["resolution"], "status": "captured"}]})
        package["sharedRules"].append({"id": "RULE-" + conflict["id"], "name": "已确认业务决定 " + conflict["id"],
            "definition": {"businessRule": conflict["resolution"]}, "evidenceRefs": [eid], "questionIds": []})
        targets = {"C106-04": ["O-21", "MV106-COURSE-TOP6-MEAN-SCORE"], "C106-08": ["MV106-FOLLOWUP-COUNT", "MV106-ALERT-CHANGE"],
                   "C106-13": ["MV106-COLLEGE-EXCESS-IMPACT"]}[conflict["id"]]
        for m in package["metrics"]:
            if m["id"] in targets: m["definition"]["ruleRefs"].append("RULE-" + conflict["id"])
    for mid in ("O-10", "MV106-GPA-DISTRIBUTION"):
        case = deepcopy(template["validationCases"][0])
        case.update(id="CASE-" + mid + "-BOUNDED-REAL", metricId=mid, title="限定真实输入的独立核算：" + mid, evidenceRefs=refs[mid])
        case.pop("ruleIllustration", None)
        case["samplePlan"]["inputDatasets"] = [{"queryId": mid + "-fact-detail-mysql", "countQueryId": mid + "-fact-count-mysql",
            "role": "raw_input", "coverageNote": "读取有效性过滤前的同范围记录；完整count与明细必须一致。限定学生和学期不改变SQL。"}]
        case["execution"]["queryId"] = mid + "-fact-calculate-mysql"
        package["validationCases"].append(case)
        next(m for m in package["metrics"] if m["id"] == mid)["verificationPlan"]["caseIds"].append(case["id"])
    observation = {"id": "SRC-TEST-APPLICATION", "kind": "live_ui", "role": "metric_evidence",
        "title": "114测试系统教学数据总览的实际指标", "location": "http://114.215.189.215/#/admin",
        "version": None, "contentHash": None, "authority": "observation_only", "use": "identify_metric_or_observe_actual",
        "evidence": [], "metricObservation": {"metricId": "O-10", "metricLabel": "当前挂科学生率",
            "locator": None, "filterContext": None, "identityContext": None, "unit": "%", "observedAt": None,
            "dataAsOf": None, "dataNature": "unknown", "snapshotRef": None,
            "note": "用户指定同登录用户、同数据库的114测试系统；等待实际观察，不以本地演示数据替代。"}}
    package["sourceManifest"].append(observation)
    inp["sources"].append({k: deepcopy(v) for k, v in observation.items() if k != "evidence"})
    # The same source uncertainty should be answered once, not once per metric,
    # dialect or SQL kind. Keep genuine different questions separate.
    merged_questions, replacements = {}, {}
    for question in package["questions"]:
        key = (question["ownerRole"], question["problem"], question["type"])
        if key not in merged_questions:
            merged_questions[key] = question
        else:
            existing = merged_questions[key]
            replacements[question["id"]] = existing["id"]
            existing["affectedMetricIds"] = sorted(set(existing["affectedMetricIds"] + question["affectedMetricIds"]))
            existing["evidenceRefs"] = sorted(set(existing["evidenceRefs"] + question["evidenceRefs"]))
    package["questions"] = list(merged_questions.values())
    from .mapping_contract import question_context
    for question in package["questions"]:
        if len(question["affectedMetricIds"]) > 1:
            question["title"] = "共用数据条件：" + question["problem"][:50]
        question["contextHash"] = question_context(question)
    def replace_questions(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"questionIds", "prerequisiteQuestionIds"} and isinstance(child, list):
                    value[key] = sorted({replacements.get(q, q) for q in child})
                else: replace_questions(child)
        elif isinstance(value, list):
            for child in value: replace_questions(child)
    replace_questions(package)
    ids = [m["id"] for m in package["metrics"]]
    package["changeSet"] = {"added": ids, "changed": [], "retired": [], "invalidateEvidenceFor": [],
        "summary": "从既有106分析迁移真实业务指标及SQL；没有页面树、权限需求或原始学生明细；不继承旧SQL成功为本轮验收。",
        "impactReview": {"changedRuleIds": [], "reviewedMetricIds": ids, "affectedMetricIds": ids, "unaffectedMetricIds": [], "unresolvedMetricIds": [],
                         "basis": "初始建库；共用有效成绩与比例空值规则、明确跨指标引用已经登记，数据/应用缺口仍开放。"}}
    package["analysisSummary"] = [{"step": "requirements_and_legacy_migration", "status": "organized", "inputRefs": ["SRC-REQ-106", "SRC-LEGACY-MAPPING", "SRC-LEGACY-QUERIES"],
        "outputRefs": ids, "evidenceSummary": "核对106业务章节与指标词典；教学规模、学业结果、课程、培养进度和预警结果均保留，内部组成不新增指标。SQL技术验证与应用对照尚未开展。",
        "openQuestionIds": [q["id"] for q in package["questions"]], "completedAt": None}]
    package["checkpoint"] = {"lastCompletedStage": "organized", "affectedMetricIds": ids, "unappliedAnswerIds": [],
                              "reason": "待契约检查、持久化、当次证据留存与真实应用对照；历史批次不可依赖。"}
    package["packageId"] = "PKG-106-INITIAL-" + _hash({"metrics": package["metrics"], "queries": package["queries"], "sources": package["sourceManifest"]})[:20]
    return package

"""Build the reviewed C-BRIEF-01 mapping asset; never connect or write to a database.

The resulting package still needs protected save/activate and current-run semantic proof.
Historical evidence is not a current validation result.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
from backend.metric_verification.mapping_contract import content_hash, validate_package

REQ = "文档/4-需求文档/4.7-AI管理决策/新增-4.7-AI管理决策.md"
TECH = "文档/4-需求文档/4.7-AI管理决策/expert-design-v3-20260916/04-数据与运行技术规格.md"
IDS = ["AI-C-0" + str(i) for i in range(1, 7)]
SPECS = [
    ("首修人次", "count", "人次", "N=有效首修成绩记录数", "n", []),
    ("首修通过人次", "count", "人次", "P=有效首修成绩中通过记录数", "p", []),
    ("首修通过率", "ratio", "%", "100×P/N", "ROUND(100*CAST(p AS DECIMAL(38,18))/NULLIF(n,0),2)", ["AI-C-01", "AI-C-02"]),
    ("首修未通过人次", "count", "人次", "U=N−P；当次首修有效集合及二元通过语义成立后使用", "n-p", ["AI-C-01", "AI-C-02"]),
    ("已接入可核记录的首修通过率参照", "ratio", "%", "100×ΣP/ΣN；同学期、同授权开课范围全部有效课程的加权比例", None, ["AI-C-01", "AI-C-02"]),
    ("观察课程数", "count", "门", "COUNT(U>0且P×ΣN<ΣP×N的有效课程)", None, ["AI-C-01", "AI-C-02", "AI-C-04", "AI-C-05"]),
]
FIELDS = {
    "source": {"grade": ["ID", "COURSE_ID", "SEMESTER_ID", "RETAKE", "PUBLISHED", "PASSED", "STATE"],
               "course": ["ID", "NAME_ZH", "DEFAULT_OPEN_DEPART_ID"]},
    "fact": {"act_grade_attempt": ["id", "course_id", "semester_id", "is_retake", "is_published", "is_void", "is_pass", "source_row_no"],
             "act_course": ["id", "course_id", "name", "organization_id"]},
    "application": {"agg_course_pass_stat": ["id", "course_id", "semester_id", "first_attempts", "first_pass", "failures", "rule_version", "calculated_at", "source"],
                    "act_course": ["id", "course_id", "name", "organization_id"]},
}
PARAMS = [
    {"name": "semester_id", "label": "所选学期", "type": "integer", "required": True},
    {"name": "organization_id", "label": "开课院系（空值仅限已有全校授权）", "type": "integer", "required": False},
    {"name": "course_id", "label": "课程（核算样本可限定；参照随同一完整范围重新计算）", "type": "integer", "required": False},
]
for parameter in PARAMS:
    parameter.update(source="business", default=None, defaultPolicy="explicit_selection", optionSource=None)


def inputs(layer):
    if layer == "source":
        return """SELECT g.COURSE_ID AS course_id,g.SEMESTER_ID AS semester_id,
 g.RETAKE AS is_retake,g.PUBLISHED AS is_published,NULL AS is_void,g.PASSED AS is_pass,g.STATE AS source_state
FROM grade g JOIN course c ON c.ID=g.COURSE_ID
WHERE g.SEMESTER_ID=:semester_id
 AND (:organization_id IS NULL OR c.DEFAULT_OPEN_DEPART_ID=:organization_id)
 AND (:course_id IS NULL OR g.COURSE_ID=:course_id)"""
    if layer == "fact":
        return """SELECT g.course_id,g.semester_id,g.is_retake,g.is_published,g.is_void,g.is_pass
FROM act_grade_attempt g JOIN act_course c ON c.course_id=g.course_id
WHERE CAST(g.semester_id AS DECIMAL(20,0))=:semester_id
 AND (:organization_id IS NULL OR CAST(c.organization_id AS DECIMAL(20,0))=:organization_id)
 AND (:course_id IS NULL OR CAST(g.course_id AS DECIMAL(20,0))=:course_id)"""
    return """SELECT a.id,a.course_id,a.semester_id,a.first_attempts,a.first_pass,a.failures,a.rule_version,a.calculated_at,a.source,
 COUNT(*) OVER(PARTITION BY a.course_id,a.semester_id) AS record_versions
FROM agg_course_pass_stat a JOIN act_course c ON c.course_id=a.course_id
WHERE CAST(a.semester_id AS DECIMAL(20,0))=:semester_id
 AND (:organization_id IS NULL OR CAST(c.organization_id AS DECIMAL(20,0))=:organization_id)
 AND (:course_id IS NULL OR CAST(a.course_id AS DECIMAL(20,0))=:course_id)"""


def cohort(layer):
    prefix = "WITH input_rows AS (\n" + inputs(layer) + "\n)"
    if layer == "application":
        return prefix + """, valid_courses AS (
 SELECT course_id,semester_id,first_attempts AS n,first_pass AS p FROM input_rows
 WHERE record_versions=1 AND first_attempts>0 AND first_pass>=0 AND first_pass<=first_attempts
 AND first_attempts=FLOOR(first_attempts) AND first_pass=FLOOR(first_pass)
)"""
    predicate = ("is_retake=0 AND is_published=1 AND is_void=0 AND is_pass IN(0,1)" if layer == "fact"
                 else "is_retake=0 AND is_published=1 AND is_pass IN(0,1)")
    return prefix + """, valid_courses AS (
 SELECT course_id,semester_id,COUNT(*) AS n,SUM(CASE WHEN is_pass=1 THEN 1 ELSE 0 END) AS p
 FROM input_rows WHERE """ + predicate + """
 GROUP BY course_id,semester_id
)"""


def calculation(layer, number):
    prefix = cohort(layer)
    if number <= 4:
        return prefix + "\nSELECT course_id,semester_id," + SPECS[number - 1][4] + " AS metric_value,n AS denominator,p AS numerator FROM valid_courses ORDER BY course_id"
    if number == 5:
        return prefix + "\nSELECT ROUND(100*CAST(SUM(p) AS DECIMAL(38,18))/NULLIF(SUM(n),0),2) AS metric_value,SUM(p) AS numerator,SUM(n) AS denominator,COUNT(*) AS included_courses FROM valid_courses"
    return prefix + """, scope_totals AS (SELECT SUM(n) AS scope_n,SUM(p) AS scope_p FROM valid_courses)
SELECT COUNT(*) AS metric_value FROM valid_courses v CROSS JOIN scope_totals s
WHERE v.n-v.p>0 AND v.p*s.scope_n<s.scope_p*v.n"""


def column(key, unit="", role="supporting", data_type="integer"):
    if data_type == "integer" and key in {"course_id", "semester_id", "rule_version", "source", "source_state", "calculated_at"}:
        data_type = "string"
    return {"key": key, "label": key, "unit": unit, "dataType": data_type,
            "semanticRole": role, "nullMeaning": "未知或不可计算；不强行显示0"}


def build():
    template = json.loads((ROOT / "code/metric-verification/contracts/mapping-output.template.json").read_text(encoding="utf-8"))
    package = deepcopy(template)
    package.update(template=False, packageId="ai-briefing-c01-v1-reviewed-20261006", analysisId="ai-briefing-c01",
                   moduleId="ai-briefing", moduleName="AI简报", baseRevisionId=None)
    manifest = package["inputManifest"]
    manifest.update(template=False, analysisId=package["analysisId"], mode="initial", baseRevisionId=None,
                    module={"id": "ai-briefing", "name": "AI简报"})
    manifest["scope"].update(metricIds=IDS, businessCategories=["课程首修观察"],
                             exclusionReason="仅建立C-BRIEF-01使用的独立业务指标；运行控制、对话和页面原型不作指标")
    manifest["sources"] = [{"id": "REQ-AI", "kind": "document", "role": "requirement", "title": "AI简报首修业务口径", "location": REQ,
                            "version": "V3.3", "contentHash": hashlib.sha256((ROOT / REQ).read_bytes()).hexdigest(), "sections": ["5.4.1"], "authority": "requirement"}]
    manifest["environment"].update(sourceConnectionProfileRef="backend/.env.metric-verification:source",
                                  analyticsConnectionProfileRef="backend/.env.metric-verification:analytics",
                                  schemaSnapshotRefs=["E-SCHEMA-SOURCE", "E-SCHEMA-FACT", "E-SCHEMA-APPLICATION"])
    manifest["delivery"].update(mode="activate", authorizationRef="用户本轮开始开发及真实测试授权；保护接口仍重验实际管理身份")
    manifest["checks"].update(mode="documents", sampleScope={"semester_id": 301, "organization_id": 39, "course_id": 10774})
    manifest["interaction"]["existingDecisionRefs"] = ["REQ-AI:5.4.1", "TECH-AI:14.5.11"]
    requirement_lines = (ROOT / REQ).read_text(encoding="utf-8").splitlines()
    section_start = next(i for i, line in enumerate(requirement_lines) if line.startswith("#### 5.4.1"))
    section_end = next((i for i in range(section_start + 1, len(requirement_lines)) if requirement_lines[i].startswith("#### ") or requirement_lines[i].startswith("### ")), len(requirement_lines))
    package["sourceManifest"] = [
        {"id": "REQ-AI", "kind": "document", "role": "requirement", "title": "AI简报首修业务口径", "location": REQ,
         "version": "V3.3", "contentHash": manifest["sources"][0]["contentHash"],
         "evidence": [{"id": "E-REQ-C01", "locator": {"section": "5.4.1", "lineStart": section_start + 1, "lineEnd": section_end}, "excerpt": "\n".join(requirement_lines[section_start:section_end]), "status": "captured"}]},
        {"id": "TECH-AI", "kind": "document", "role": "implementation_boundary", "title": "发布准入与数据边界", "location": TECH,
         "version": "V3.3", "contentHash": hashlib.sha256((ROOT / TECH).read_bytes()).hexdigest(),
         "evidence": [{"id": "E-GATE-C01", "locator": {"section": "14.5.11"}, "excerpt": "映射登记不代替当次加工语义、独立复算与三层可比性核查。未知整体覆盖与不稳定历史批次保留边界。", "status": "captured"}]},
    ]
    for layer, tables in FIELDS.items():
        package["sourceManifest"].append({"id": "SCHEMA-" + layer.upper(), "kind": "schema_snapshot", "role": "source_schema" if layer == "source" else "analytics_schema",
            "title": "114当次实际字段：" + layer, "location": "information_schema.COLUMNS", "version": None, "contentHash": content_hash(tables),
            "evidence": [{"id": "E-SCHEMA-" + layer.upper(), "locator": {"objects": list(tables)}, "schemaSnapshot": tables,
                          "excerpt": "2026-10-06实际只读字段核查。source课程DEFAULT_OPEN_DEPART_ID到act_course.organization_id须按当次范围核查，不能凭字段名泛化。", "status": "captured"}]})
    manifest["sources"] = [{**{key: deepcopy(value) for key, value in source.items() if key != "evidence"},
                            "authority": "requirement" if source["role"] == "requirement" else "design_evidence"}
                           for source in package["sourceManifest"]]
    validity_rules = ["源RETAKE=0、PUBLISHED=1、PASSED IN(0,1)；事实is_retake=0、is_published=1、is_void=0、is_pass IN(0,1)", "is_retake为空属于未知；不能当首修。源组织映射、同口径版本可比及P⊆N以当次服务证明为准", "应用课程×学期唯一，N/P为整数、N>0且0≤P≤N；重复、未知与零分母分别计数排除"]
    package.update(metrics=[], queries=[], validationCases=[], questions=[], pendingAnswers=[], decisions=[],
                   sharedRules=[{"id": "RULE-C01-COHORT", "name": "同范围首修有效集合", "definition": {"validityRules": validity_rules}, "evidenceRefs": ["E-REQ-C01", "E-GATE-C01"], "questionIds": []}])
    package["coverage"] = [{"id": "C-C01", "sourceRef": "REQ-AI", "locator": "5.4.1", "disposition": "included", "metricIds": IDS, "reason": "覆盖首修事实、差额、同范围参照与观察数量；原failures仅保留原字段，未新增同名指标"}]
    for number, (name, kind, unit, formula, expression, dependencies) in enumerate(SPECS, 1):
        mid = IDS[number - 1]
        metric = {"id": mid, "name": name, "type": kind, "businessCategory": "课程首修观察", "version": "1.0.0",
            "definition": {"meaning": formula, "formula": formula, "unit": unit, "businessPurpose": "用首修表现和涉及人次定位需进一步了解的课程；不评价教学质量或教师责任",
                "grain": "授权开课院系范围×学期" if number >= 5 else "课程×学期", "scope": {"organizationRule": "当前身份已授权开课院系；学院参照独立读取本范围", "populationRule": "同范围所有已接入且首修口径可核的有效课程"},
                "timeScope": {"kind": "selected_semester", "parameter": "semester_id", "asOfRule": "按所选学期；数据时点未知则披露未知"},
                "components": [{"key": "numerator", "name": "首修通过人次P", "expression": "有效首修集合中通过记录数", "unit": "人次"}, {"key": "denominator", "name": "首修人次N", "expression": "完整二元状态的已发布、未作废、显式非重修成绩记录", "unit": "人次"}],
                "validityRules": [],
                "deduplication": {"keys": ["course_id", "semester_id"], "appliesTo": "聚合记录唯一性；重复整课排除，不任选一条", "finalAttemptSelection": None},
                "nullPolicy": {"zeroDenominator": "null", "meaning": "整体覆盖未知。没有有效课程时参照未知、观察数量0并说明；首修语义未成立则只保留支持的原字段，不输出U或观察"},
                "precision": {"calculation": "精确整数交叉比较，计算过程中不四舍五入", "comparison": {"mode": "exact", "tolerance": 0, "unit": unit}, "roundingRule": "显示比例保留两位小数，不以显示值参与筛选或排序"},
                "ruleRefs": ["RULE-C01-COHORT"], "metricRefs": [{"metricId": ref, "appliesTo": "formula", "parameterBindings": [{"targetParameter": p["name"], "sourceParameter": p["name"], "literalValue": None} for p in PARAMS]} for ref in dependencies],
                "evidenceRefs": ["E-REQ-C01", "E-GATE-C01"], "questionIds": []},
            "lineage": {"nodes": []}, "processing": {"steps": []},
            "expectedResult": {"nodeId": mid + "-fact-result", "queryId": mid + "-fact-calculate", "shape": "scalar" if number >= 5 else "table"},
            "actualBinding": {"kind": "result_query", "nodeId": mid + "-application-result", "queryId": mid + "-application-calculate", "valueField": "metric_value", "status": "mapped", "reason": "直接读取真实聚合原字段；派生值按同一业务口径投影，正式可用性由当次服务准入证明", "evidenceRefs": ["E-SCHEMA-APPLICATION", "E-GATE-C01"], "questionIds": []},
            "verificationPlan": {"queriesByLayer": [], "caseIds": ["CASE-" + mid], "closureStatus": "pending_runtime_validation",
                                 "comparison": {"mode": "same_scope_three_layers", "boundary": "同范围三层分别读取；不把当前数值一致视作历史批次或ETL时点对齐"}},
            "status": {"mappingStatus": "documented", "businessVerification": "not_run"}}
        for layer, tables in FIELDS.items():
            nodeids = []
            bindings = []
            for table, fields in tables.items():
                nid = mid + "-" + layer + "-" + table
                nodeids.append(nid)
                bid = nid + "-binding"
                metric["lineage"]["nodes"].append({"id": nid, "layer": layer, "logicalName": table, "objectType": "table", "grain": "课程×学期聚合行" if table == "agg_course_pass_stat" else "课程主数据记录" if table.endswith("course") else "单条成绩记录", "role": "business_input", "fields": fields,
                    "physicalBindings": [{"id": bid, "environmentId": "test-114", "connectionRef": "source" if layer == "source" else "analytics", "dialect": "mysql", "schema": "edu_source" if layer == "source" else "edu_analytics_v3", "objectName": table, "fieldMap": {f: f for f in fields}, "status": "observed", "evidenceRefs": ["E-SCHEMA-" + layer.upper()]}], "evidenceRefs": ["E-SCHEMA-" + layer.upper()], "questionIds": []})
                bindings.append({"bindingId": bid, "columns": fields})
            resultid = mid + "-" + layer + "-result"
            metric["lineage"]["nodes"].append({"id": resultid, "layer": layer, "logicalName": name + "层结果", "objectType": "virtual_result", "grain": metric["definition"]["grain"], "fields": [], "physicalBindings": [], "role": "expected_result" if layer != "application" else "application_actual", "evidenceRefs": ["E-REQ-C01"], "questionIds": []})
            sid = mid + "-" + layer + "-process"
            metric["processing"]["steps"].append({"id": sid, "kind": "calculate", "dependsOn": [], "inputNodeIds": nodeids, "outputNodeId": resultid, "definitionFields": ["formula", "scope", "validityRules"], "physicalPredicate": "显式首修0、已发布且二元状态；应用唯一有效课程集合", "fieldMappings": [{"from": "+".join(nodeids), "to": resultid + ".metric_value", "expression": formula}], "description": "源组织字段映射必须当次核查；当次语义/版本可比/独立核算准入与SQL技术执行分开记录", "questionIds": [], "evidenceRefs": ["E-REQ-C01", "E-SCHEMA-" + layer.upper()]})
            prefix = "WITH input_rows AS (\n" + inputs(layer) + "\n)"
            if layer == "application":
                detail_sql = prefix + "\nSELECT id,course_id,semester_id,first_attempts,first_pass,failures,rule_version,calculated_at,source,record_versions FROM input_rows ORDER BY course_id,id"
                count_sql = prefix + "\nSELECT COUNT(*) AS matched_records FROM input_rows"
                detailkeys = ["id", "course_id", "semester_id", "first_attempts", "first_pass", "failures", "rule_version", "calculated_at", "source", "record_versions"]
            else:
                state_field = ",source_state" if layer == "source" else ""
                groups = ", state_groups AS (SELECT course_id,semester_id,is_retake,is_published,is_void,is_pass" + state_field + ",COUNT(*) AS attempts FROM input_rows GROUP BY course_id,semester_id,is_retake,is_published,is_void,is_pass" + state_field + ")"
                detail_sql = prefix + groups + "\nSELECT course_id,semester_id,is_retake,is_published,is_void,is_pass" + state_field + ",attempts FROM state_groups ORDER BY course_id,is_retake,is_published,is_void,is_pass"
                count_sql = prefix + groups + "\nSELECT COUNT(*) AS matched_records,COALESCE(SUM(attempts),0) AS source_records FROM state_groups"
                detailkeys = ["course_id", "semester_id", "is_retake", "is_published", "is_void", "is_pass", "attempts"]
                if layer == "source":
                    detailkeys.append("source_state")
            qids = []
            for qkind, sql in [("count", count_sql), ("detail", detail_sql), ("calculate", calculation(layer, number))]:
                qid = mid + "-" + layer + "-" + qkind
                qids.append(qid)
                cols = [column("matched_records", "条", "matched_records")] if qkind == "count" else [column(k) for k in detailkeys] if qkind == "detail" else [column("metric_value", unit, "metric_value", "decimal" if kind == "ratio" else "integer")]
                if qkind == "count" and layer != "application":
                    cols.extend([column("source_records", "条")])
                    cols[0]["label"] = "核算分组记录数"
                    cols[1]["label"] = "原始成绩记录数"
                if qkind == "detail" and layer == "source":
                    next(c for c in cols if c["key"] == "is_void")["label"] = "源端作废状态未提供"
                    next(c for c in cols if c["key"] == "source_state")["label"] = "源端STATE原值"
                if qkind == "calculate" and number <= 4:
                    cols.extend([column("course_id", data_type="string"), column("semester_id", data_type="string"), column("numerator", "人次", "numerator"), column("denominator", "人次", "denominator")])
                if qkind == "calculate" and number == 5:
                    cols.extend([column("numerator", "人次", "numerator"), column("denominator", "人次", "denominator"), column("included_courses", "门")])
                package["queries"].append({"id": qid, "metricId": mid, "layer": layer, "kind": qkind, "purpose": "input_count" if qkind == "count" else "input_detail" if qkind == "detail" else "application_actual" if layer == "application" else "expected_value", "title": name + " · " + layer + " · " + qkind, "version": "1.0.0", "dialect": "mysql", "connectionRef": "source" if layer == "source" else "analytics", "sql": sql + "\n", "sqlChecksum": hashlib.sha256((sql + "\n").encode()).hexdigest(), "parameters": deepcopy(PARAMS), "dependencies": deepcopy(bindings), "stepIds": [sid] if qkind == "calculate" else [], "prerequisiteQuestionIds": [], "blockedReason": None,
                    "resultContract": {"shape": "scalar" if qkind == "count" or (qkind == "calculate" and number >= 5) else "table", "columns": cols, "rowKey": ["course_id", "semester_id"] if qkind == "calculate" and number <= 4 else [], "rowCountMeaning": "核算分组记录总数（attempts保留原始成绩人次）" if layer != "application" and qkind != "calculate" else "课程聚合记录／指标结果", "completeness": {"expected": "complete", "totalCountQueryId": mid + "-" + layer + "-count" if qkind == "detail" else None, "truncationPolicy": "block_auto_import"}, "ordering": ["course_id"] if qkind == "detail" else []}})
            metric["verificationPlan"]["queriesByLayer"].append({"layer": layer, "queryIds": qids, "gap": "源开课院系与事实组织关系按本次范围证明；时点未齐保留待核" if layer == "source" else None})
        source_grade, source_course = mid + "-source-grade", mid + "-source-course"
        fact_grade, fact_course = mid + "-fact-act_grade_attempt", mid + "-fact-act_course"
        app_agg = mid + "-application-agg_course_pass_stat"
        metric["processing"]["steps"].extend([
            {"id": mid + "-source-fact-map", "kind": "map", "dependsOn": [], "inputNodeIds": [source_grade, source_course], "outputNodeId": fact_grade,
             "fieldMappings": [{"from": source_grade + "." + src, "to": fact_grade + "." + target, "expression": "按业务键/原值核对；不是生产ETL实现证明"} for src, target in [("ID", "source_row_no"), ("COURSE_ID", "course_id"), ("SEMESTER_ID", "semester_id"), ("RETAKE", "is_retake"), ("PUBLISHED", "is_published"), ("PASSED", "is_pass")]],
             "description": "源grade.ID与事实source_row_no以数值键核对，is_void无独立源字段故保持未知；STATE原值另留存。贴源全集覆盖和历史时点仍未知", "evidenceRefs": ["E-SCHEMA-SOURCE", "E-SCHEMA-FACT", "E-GATE-C01"], "questionIds": []},
            {"id": mid + "-course-org-map", "kind": "map", "dependsOn": [], "inputNodeIds": [source_course], "outputNodeId": fact_course,
             "fieldMappings": [{"from": source_course + ".ID", "to": fact_course + ".course_id", "expression": "业务课程键；act_course.id为代理键，不用于成绩课程关联"}, {"from": source_course + ".DEFAULT_OPEN_DEPART_ID", "to": fact_course + ".organization_id", "expression": "本次范围逐课程核查；不推定全库或历史成立"}],
             "evidenceRefs": ["E-SCHEMA-SOURCE", "E-SCHEMA-FACT", "E-GATE-C01"], "questionIds": []},
            {"id": mid + "-fact-app-aggregate", "kind": "aggregate", "dependsOn": [mid + "-source-fact-map"], "inputNodeIds": [fact_grade, fact_course], "outputNodeId": app_agg,
             "physicalPredicate": "is_retake=0 AND is_published=1 AND is_void=0 AND is_pass IN(0,1)，按业务course_id×semester_id分组",
             "fieldMappings": [{"from": fact_grade, "to": app_agg + ".first_attempts", "expression": "有效首修记录COUNT(*)，按当次同范围核对"}, {"from": fact_grade + ".is_pass", "to": app_agg + ".first_pass", "expression": "同一有效首修集合中is_pass=1计数；P为N子集"}],
             "description": "登记需求复算与真实应用原字段的核对关系；真实rule_version及首修语义以当次证明决定，不声称旧SQLite脚本代表114加工", "evidenceRefs": ["E-REQ-C01", "E-SCHEMA-FACT", "E-SCHEMA-APPLICATION", "E-GATE-C01"], "questionIds": []}
        ])
        package["metrics"].append(metric)
        package["validationCases"].append({"id": "CASE-" + mid, "metricId": mid, "title": name + "限定真实分组输入独立核算", "target": "requirement_to_sql", "method": "capture_inputs_and_result_then_independent_expectation_before_disclosure", "evidenceRefs": ["E-REQ-C01"],
            "samplePlan": {"requirement": "保留同范围完整成绩状态分组与原始人次；输入分组count必须与明细一致。无学生标识输出", "parameters": None, "recordCount": None, "scopeReason": "单课程/学期，或可完整留存的合法小范围；不能由小样本推全库", "inputDatasets": [{"queryId": mid + "-fact-detail", "countQueryId": mid + "-fact-count", "role": "raw_state_counts"}], "capture": {"status": "not_run"}, "completeness": "not_checked"},
            "execution": {"queryId": mid + "-fact-calculate", "status": "not_run", "actualRows": None}, "expected": {"method": "independent_calculation_from_retained_inputs_before_result_disclosure", "rows": None, "status": "not_run"}, "comparison": {"status": "not_run", "differences": [], "coverage": "bounded_sample"}})
    package["analysisSummary"] = {"summary": "C-BRIEF-01独立应用指标、三层字段及只读SQL已整理。此包未执行、未注册、未证明当次业务语义", "remainingConditions": ["保护服务保存/生效/真实SYS定义与页面绑定回读", "每次正式运行独立核算、当次首修集合语义、组织映射及rule_version可比证明", "三层时点、数据整体覆盖仍据真实证据判定；历史批次不可稳定重取"]}
    package["validations"] = []
    package["checkpoint"] = {"lastCompletedStage": "requirements_and_actual_fields_reviewed", "affectedMetricIds": IDS, "unappliedAnswerIds": [], "reason": "待实际保护接口入库及真实运行验证"}
    package["changeSet"] = {"added": IDS, "changed": [], "retired": [], "invalidateEvidenceFor": [], "summary": "新增ai-briefing独立模块，不变更106或其head", "impactReview": {"changedRuleIds": [], "reviewedMetricIds": IDS, "affectedMetricIds": IDS, "unaffectedMetricIds": [], "unresolvedMetricIds": [], "basis": "新增六个在业务输出中独立使用的指标；N/P为需求显式展示项，筛选与页面布局不作指标"}}
    report = validate_package(package)
    if not report["valid"]:
        raise ValueError(report["errors"])
    return package, report


if __name__ == "__main__":
    package, report = build()
    target = ROOT / "code/metric-verification/mappings/ai-briefing/package.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "metrics": len(package["metrics"]), "queries": len(package["queries"]),
                      "valid": report["valid"], "blockedQueries": {qid: check["blockedReasons"] for qid, check in report["queryChecks"].items() if check["executionApproval"] != "documented"},
                      "storage": "not_persisted", "businessVerification": "not_run"}, ensure_ascii=False))

"""Turn an owned, current scalar calculation into a traceable comparison draft."""
import json

from backend.api.envelope import ApiError
from . import registry, mapping_store
from .database import connection


EXTRA_COLUMNS = {
    "input_records": ("参与计算的成绩记录数", "人次"),
    "students_with_gpa": ("有学期GPA的学生数", "人"),
    "numeric_score_attempts": ("有数值成绩的人次", "人次"),
    "passed_credits": ("通过记录的学分合计", "学分"),
    "attempted_credits": ("有效记录的学分合计", "学分"),
    "included_credits": ("参与计算的学分", "学分"),
    "score_sum": ("成绩合计", "分"),
    "valid_students": ("有效成绩学生数", "人"),
    "excluded_out_of_range": ("排除的超范围成绩人次", "人次"),
}
RATIO_COLUMNS = {
    "O-10": (("未通过学生数", "人"), ("有效成绩学生数", "人")),
    "O-11": (("未通过人次", "人次"), ("有效成绩人次", "人次")),
    "MV106-COURSE-EXCELLENT-RATE": (("优秀人次", "人次"), ("有效百分制成绩人次", "人次")),
}


def expected_draft(requirement_id: str, scenario_id: str, execution_id: str, actor: dict) -> dict:
    scene = registry.scenario(scenario_id, requirement_id)
    with connection("application") as conn, conn.cursor() as cur:
        cur.execute("""SELECT metric_id,query_id,query_version,query_checksum,layer_name,
            parameters_json,result_json,executed_at FROM sys_metric_verification_execution
            WHERE execution_id=%s AND requirement_id=%s AND actor=%s AND identity_id=%s""",
                    (execution_id, requirement_id, actor["username"], actor["identity_id"]))
        stored = cur.fetchone()
    if not stored or stored["metric_id"] != scene["metricId"]:
        raise ApiError("查询证据不属于当前指标或工作身份", code=403, status_code=403)
    snapshot = json.loads(stored["result_json"])
    if snapshot.get("moduleId", "teaching-overview") != mapping_store.scope()[1]:
        raise ApiError("查询证据不属于当前指标模块", status_code=403)
    if snapshot.get("executionUse") == "definition_validation":
        raise ApiError("定义验证样本不直接带入业务验收；请执行当前生效版本的同范围复算", status_code=409)
    query = registry.find_query(stored["query_id"])
    if snapshot.get("scenarioId") != scenario_id:
        raise ApiError("请在当前指标场景取得查询结果", status_code=422)
    if (query.get("executionApproval") != "documented"
            or query["version"] != stored["query_version"] or query["checksum"] != stored["query_checksum"]
            or snapshot.get("requirementChecksum") != registry.requirement_checksum(requirement_id)
            or snapshot.get("scenarioChecksum") != registry.scenario_checksum(scenario_id)):
        raise ApiError("需求或SQL已变化，请重新查询后带入", status_code=409)
    if (snapshot.get("status") != "success" or query["kind"] != "calculate"
            or query["layer"] not in {"source", "fact"} or snapshot.get("truncated")
            or snapshot.get("returnedRows") != 1 or scene.get("comparisonKind") != "scalar"):
        raise ApiError("只能带入本场景贴源层或事实层完整的单值复算；记录数、明细和应用参考值不能代替指标", status_code=422)
    values = snapshot.get("metrics") or {}
    contract = query.get("resultContract") or {}
    declared = contract.get("columns") or []
    value_columns = [c for c in declared if c.get("semanticRole") == "metric_value"]
    value_key = value_columns[0]["key"] if len(value_columns) == 1 else "candidate_metric_value"
    if value_key not in values:
        raise ApiError("该查询尚未登记可带入的单值结果", status_code=422)
    metric = next(m for m in registry.catalog()["metrics"] if m["id"] == scene["metricId"])
    fields = [(value_key, (scene["name"], metric.get("unit", "")))]
    ratio = RATIO_COLUMNS.get(scene["metricId"])
    if ratio:
        if not {"numerator", "denominator"}.issubset(values):
            raise ApiError("比例结果缺少分子或分母，请重新执行完整复算", status_code=422)
        fields.extend(zip(("numerator", "denominator"), ratio))
    if declared:
        known = {key for key, _ in fields}
        fields.extend((c["key"], (c.get("label", c["key"]), c.get("unit", ""))) for c in declared
                      if c["key"] in values and c["key"] not in known
                      and c.get("semanticRole") in {"numerator", "denominator", "supporting"})
    else:
        fields.extend((key, label) for key, label in EXTRA_COLUMNS.items() if key in values)
    rows = [{"label": label, "unit": unit, "actual": "", "expected": "" if values[key] is None else str(values[key]),
             "expectedKey": key} for key, (label, unit) in fields if key in values]
    params = json.loads(stored["parameters_json"])
    labels = {p["name"]: p.get("label", p["name"]) for p in query["parameters"]}
    scope_keys = ("organization_id", "college_id", "major_id", "grade", "student_id", "course_id")
    scope = "；".join(f"{labels.get(k, k)}={params[k] if params[k] is not None else '未限定'}" for k in scope_keys if k in params)
    period = "；".join(f"{labels.get(k, k)}={params[k]}" for k in ("semester_id", "previous_semester_id", "term_id") if params.get(k) is not None)
    versions = "；".join(f"{labels.get(k, k)}={v}" for k, v in params.items() if v is not None and ("batch" in k or "version" in k))
    layer = "贴源层" if query["layer"] == "source" else "事实层"
    return {"expectedExecutionId": execution_id, "scope": scope or "按登记SQL的查询范围", "period": period or "本查询未限定学期",
            "dataVersion": versions, "startLayer": query["layer"],
            "expectedSource": f"{layer}复算 · {query['id']} · SQL {stored['query_version']} · 执行 {execution_id}",
            "expectedObservedAt": stored["executed_at"], "rows": rows, "parameters": params}


def validate_binding(comparison: dict | None, requirement_id: str, scenario_id: str, actor: dict) -> str | None:
    if not comparison or not comparison.get("expectedExecutionId"):
        return None
    eid = comparison["expectedExecutionId"]
    draft = expected_draft(requirement_id, scenario_id, eid, actor)
    for key in ("scope", "period", "dataVersion", "startLayer", "expectedSource", "expectedObservedAt"):
        if comparison.get(key, "") != draft[key]:
            raise ApiError("带入的查询条件或来源已变更，请重新查询或清除带入结果", status_code=409)
    bound = [row for row in comparison.get("rows", []) if row.get("expectedKey")]
    for expected in draft["rows"]:
        matches = [r for r in bound if r["expectedKey"] == expected["expectedKey"]]
        if len(matches) != 1 or any(matches[0].get(k) != expected[k] for k in ("label", "unit", "expected")):
            raise ApiError("带入的复算值与已保存SQL证据不一致，请重新带入", status_code=409)
    if len(bound) != len(draft["rows"]):
        raise ApiError("带入的复算组成项已变化，请重新带入", status_code=409)
    return eid

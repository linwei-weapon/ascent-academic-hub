"""Immutable module revisions and append-only answers in the configured analytics database."""
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from uuid import uuid4

from backend.api.envelope import ApiError
from .config import ASSETS, database_config
from .database import connection
from .mapping_contract import canonical_json, content_hash, validate_package, question_context


MODULES = {"teaching-overview": "教学数据总览", "ai-briefing": "AI简报"}
_module = ContextVar("metric_mapping_module", default="teaching-overview")
AI_BRIEFING_PAGE = "/admin/reports/decision"


def checked_module(module_id: str | None) -> str:
    selected = module_id if module_id is not None else "teaching-overview"
    if selected not in MODULES:
        raise ApiError("指标模块仅支持教学数据总览与AI简报", status_code=422)
    return selected


@contextmanager
def module_scope(module_id: str | None = None):
    """Request-local selection; never mutate an environment variable or another request."""
    token = _module.set(checked_module(module_id))
    try:
        yield scope()
    finally:
        _module.reset(token)


def scope() -> tuple[str, str, str]:
    return (os.getenv("MV_MAPPING_PROJECT", "highedu"), _module.get(),
            os.getenv("MV_MAPPING_ENVIRONMENT", "test-114"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(cursor):
    return cursor.fetchone()


def _scope_check(package):
    if tuple(package.get(k) for k in ("projectId", "moduleId", "environmentId")) != scope():
        raise ApiError("映射包不属于当前服务配置的项目、模块与环境", status_code=403)


def table_ready() -> bool:
    if not database_config("application").configured:
        return False
    with connection("application") as conn, conn.cursor() as cursor:
        cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('sys_metric_mapping_revision','sys_metric_mapping_head','sys_metric_mapping_question')")
        return len(cursor.fetchall()) == 3


def get_head(module_id: str | None = None, *, allow_empty: bool = False) -> dict:
    if module_id is not None:
        with module_scope(module_id):
            return get_head(allow_empty=allow_empty)
    project, module, environment = scope()
    empty = {"revisionId": None, "lockVersion": 0, "projectId": project, "moduleId": module,
             "environmentId": environment, "legacyMode": True}
    if os.getenv("MV_MAPPING_MODE", "auto") == "legacy":
        return {**empty, "legacyReason": "explicit_legacy_mode"}
    if not database_config("application").configured:
        if os.getenv("MV_MAPPING_MODE") == "required":
            raise ApiError("映射数据库尚未配置，禁止回退本地定义", status_code=503)
        return {**empty, "legacyReason": "database_not_configured"}
    if not table_ready():
        raise ApiError("映射表尚未迁移，请执行现有migrate入口；禁止静默回退旧定义", status_code=503)
    with connection("application") as conn, conn.cursor() as cursor:
        cursor.execute("SELECT revision_id,lock_version FROM sys_metric_mapping_head WHERE project_id=%s AND module_id=%s AND environment_id=%s", scope())
        row = _one(cursor)
    if not row or not row["revision_id"]:
        if os.getenv("MV_MAPPING_MODE") == "required" and not allow_empty:
            raise ApiError("当前作用域没有生效映射版本，禁止回退本地定义", status_code=503)
        return {**empty, "legacyReason": "no_active_revision"}
    return {**empty, "revisionId": row["revision_id"], "lockVersion": row["lock_version"], "legacyMode": False}


def _decode(row) -> dict:
    return {"revisionId": row["revision_id"], "packageId": row["package_id"], "packageHash": row["package_hash"],
            "createdAt": row["created_at"], "createdBy": row["created_by"], "baseRevisionId": row["base_revision_id"],
            "package": json.loads(row["package_json"]), "validation": json.loads(row["validation_json"]),
            "bindings": json.loads(row["bindings_json"])}


def _read_revision(cursor, revision_id):
    cursor.execute("SELECT * FROM sys_metric_mapping_revision WHERE revision_id=%s AND project_id=%s AND module_id=%s AND environment_id=%s", (revision_id, *scope()))
    row = _one(cursor)
    if not row:
        raise ApiError("映射版本不存在或不属于当前环境", code=404, status_code=404)
    result = _decode(row)
    if content_hash(result["package"]) != result["packageHash"]:
        raise ApiError("映射快照完整性校验失败", status_code=503)
    return result


def get_revision(revision_id: str, module_id: str | None = None) -> dict:
    if module_id is not None:
        with module_scope(module_id):
            return get_revision(revision_id)
    with connection("application") as conn, conn.cursor() as cursor:
        result = _read_revision(cursor, revision_id)
        cursor.execute("SELECT revision_id FROM sys_metric_mapping_head WHERE project_id=%s AND module_id=%s AND environment_id=%s", scope())
        row = _one(cursor)
        result["current"] = bool(row and row["revision_id"] == revision_id)
        return result


def list_revisions(analysis_id: str | None = None, module_id: str | None = None) -> list[dict]:
    if module_id is not None:
        with module_scope(module_id):
            return list_revisions(analysis_id)
    sql = "SELECT revision_id,package_id,package_hash,analysis_id,base_revision_id,created_at,created_by FROM sys_metric_mapping_revision WHERE project_id=%s AND module_id=%s AND environment_id=%s"
    args = list(scope())
    if analysis_id:
        sql += " AND analysis_id=%s"
        args.append(analysis_id)
    with connection("application") as conn, conn.cursor() as cursor:
        cursor.execute(sql + " ORDER BY created_at DESC LIMIT 100", args)
        return [{"revisionId": r["revision_id"], "packageId": r["package_id"], "packageHash": r["package_hash"],
                 "analysisId": r["analysis_id"], "baseRevisionId": r["base_revision_id"], "createdAt": r["created_at"], "createdBy": r["created_by"]} for r in cursor.fetchall()]


def legacy_bindings(package: dict, previous: dict | None = None) -> dict:
    """Freeze consumer-owned navigation/anchors only. Formulas and SQL remain solely in package."""
    from .mapping_adapter import consumer_entries, consumer_label
    if previous:
        result = deepcopy(previous)
    elif package["moduleId"] == "teaching-overview":
        legacy = json.loads((ASSETS / "catalog" / "teaching-overview.json").read_text(encoding="utf-8-sig"))
        system = legacy.get("indicatorSystem", {})
        result = {"module": legacy.get("module", {}), "indicatorSystem": {k: deepcopy(v) for k, v in system.items() if k != "entries"},
                  "entries": [], "requirements": {}, "schemaVersion": "1.0.0"}
        for entry in system.get("entries", []):
            result["entries"].append({k: deepcopy(v) for k, v in entry.items() if k in {"id", "metricId", "requirementId", "pageId", "group", "name", "aliases", "status", "comparisonKind", "evidenceMetricIds"}})
        for req in legacy.get("requirements", []):
            result["requirements"][req["id"]] = {k: deepcopy(v) for k, v in req.items() if k in {"id", "section", "area", "pagePaths", "source", "sourceExcerpt"}}
    else:
        requirement_source = next((source for source in package["sourceManifest"] if source.get("role") == "requirement"), {})
        result = {"module": {"id": package["moduleId"], "name": package["moduleName"]},
                  "indicatorSystem": {"pages": [{"id": "home", "name": "AI简报"}],
                                      "groups": ["课程首修观察"]},
                  "entries": [], "requirements": {}, "schemaVersion": "1.0.0"}
        result["module"].update(sourceDocument=requirement_source.get("title"), version=requirement_source.get("version"))
    metric_ids = {m["id"] for m in package["metrics"]}
    result["entries"] = [e for e in result["entries"] if e["metricId"] in metric_ids]
    for entry in result["entries"]:
        entry["evidenceMetricIds"] = [mid for mid in entry.get("evidenceMetricIds", []) if mid in metric_ids]
    result["entries"] = consumer_entries(result["entries"])
    metrics_by_id = {m["id"]: m for m in package["metrics"]}
    for entry in result["entries"]:
        entry["name"] = consumer_label(entry, metrics_by_id[entry["metricId"]], package["moduleId"])
    associated = {mid for entry in result["entries"] for mid in [entry["metricId"], *entry.get("evidenceMetricIds", [])]}
    for metric in package["metrics"]:
        if metric["id"] not in associated:
            req_id = "mapping-anchor:" + metric["id"]
            result["entries"].append({"id": "mapping:" + metric["id"], "metricId": metric["id"], "requirementId": req_id, "name": metric["name"],
                                      "pageId": "home", "group": metric.get("businessCategory", "其他"), "aliases": [],
                                      "status": "explicit", "comparisonKind": "collection" if metric.get("expectedResult", {}).get("shape") == "table" else metric.get("expectedResult", {}).get("shape", "scalar"),
                                      "evidenceMetricIds": [], "internalCompatibilityAnchor": True})
            result["requirements"][req_id] = {"id": req_id, "section": "指标映射内部关联", "area": package["moduleName"],
                                                "pagePaths": [AI_BRIEFING_PAGE] if package["moduleId"] == "ai-briefing" else [],
                                                "internalCompatibilityAnchor": True}
            if package["moduleId"] == "ai-briefing":
                cited = [evidence for source in package["sourceManifest"] if source.get("role") == "requirement"
                         for evidence in source.get("evidence", []) if evidence["id"] in metric["definition"].get("evidenceRefs", [])]
                if cited:
                    locator = cited[0].get("locator", {})
                    result["requirements"][req_id].update(section=locator.get("section", "首修业务指标"),
                        source={"startLine": locator.get("lineStart", 0), "endLine": locator.get("lineEnd", 0)},
                        sourceExcerpt=cited[0].get("excerpt"))
    used = {e["requirementId"] for e in result["entries"]}
    result["requirements"] = {k: v for k, v in result["requirements"].items() if k in used}
    return result


def _question_row(cursor, question_id, *, lock=False):
    cursor.execute("SELECT * FROM sys_metric_mapping_question WHERE project_id=%s AND module_id=%s AND environment_id=%s AND question_id=%s" + (" FOR UPDATE" if lock else ""), (*scope(), question_id))
    return _one(cursor)


def _verify_decisions(cursor, package, *, latest=False):
    for decision in package.get("decisions", []):
        qid, answer_id = decision.get("questionId"), decision.get("answerId")
        if not qid or not answer_id:
            raise ApiError("正式决定必须引用服务返回的questionId与answerId", status_code=422)
        row = _question_row(cursor, qid, lock=latest)
        if not row:
            raise ApiError("答复尚未入库，先提交含问题的草稿和pendingAnswers", status_code=409)
        matches = [a for a in json.loads(row["answers_json"]) if a["answerId"] == answer_id]
        if not matches or matches[0]["contextHash"] != row["context_hash"]:
            raise ApiError("决定引用的答复已过期或不存在", status_code=409)
        if matches[0].get("choiceId") == "defer":
            raise ApiError("暂缓答复不能作为已经落实的正式决定", status_code=409)
        valid_answers = [a for a in json.loads(row["answers_json"]) if a["contextHash"] == row["context_hash"]]
        if latest and valid_answers[-1]["answerId"] != answer_id:
            raise ApiError("问题已有新答复，请重新分析后生效", status_code=409)
        question = next((q for q in package["questions"] if q["id"] == qid), None)
        if not question or question_context(question) != row["context_hash"]:
            raise ApiError("映射包问题上下文与服务不一致", status_code=409)
        answered_scope = matches[0]["scope"]
        answered_ids = answered_scope.get("metricIds", []) if isinstance(answered_scope, dict) else answered_scope if isinstance(answered_scope, list) else [v.strip() for v in answered_scope.split(",")]
        if not set(question["affectedMetricIds"]).issubset(set(answered_ids)):
            raise ApiError("答复仅覆盖部分指标，不能解除整个问题的计算阻断", status_code=409)


def save_package(package: dict, actor: dict) -> dict:
    _scope_check(package)
    try:
        serialized = canonical_json(package)
    except (TypeError, ValueError):
        raise ApiError("映射包必须是有限数值和标准JSON结构", status_code=422) from None
    if len(serialized.encode("utf-8")) > 12 * 1024 * 1024:
        raise ApiError("映射包超过12MiB；样本数据应保存在受控证据记录", status_code=422)
    package_hash = content_hash(package)
    with connection("application", write=True) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT * FROM sys_metric_mapping_revision WHERE project_id=%s AND module_id=%s AND environment_id=%s AND package_id=%s", (*scope(), package.get("packageId")))
        prior = _one(cursor)
        if prior:
            if prior["package_hash"] != package_hash:
                raise ApiError("相同packageId不能提交不同内容", status_code=409)
            return {**_decode(prior), "idempotent": True, "state": "saved"}
        # Reserve a lockable head even before the first activation, closing initial-publish races.
        cursor.execute("INSERT IGNORE INTO sys_metric_mapping_head(project_id,module_id,environment_id,revision_id,lock_version,updated_by,updated_at) VALUES(%s,%s,%s,NULL,0,%s,%s)", (*scope(), actor["username"], now()))
        cursor.execute("SELECT revision_id FROM sys_metric_mapping_head WHERE project_id=%s AND module_id=%s AND environment_id=%s FOR UPDATE", scope())
        head = _one(cursor)["revision_id"]
        # Another publisher may have saved the same key while this request waited for head.
        # A locking read is required here: a normal repeatable-read SELECT can see the old snapshot.
        cursor.execute("SELECT * FROM sys_metric_mapping_revision WHERE project_id=%s AND module_id=%s AND environment_id=%s AND package_id=%s FOR UPDATE", (*scope(), package.get("packageId")))
        concurrent = _one(cursor)
        if concurrent:
            if concurrent["package_hash"] != package_hash:
                raise ApiError("相同packageId不能提交不同内容", status_code=409)
            return {**_decode(concurrent), "idempotent": True, "state": "saved"}
        if package.get("baseRevisionId") != head:
            raise ApiError("映射基线已变化，请读取当前版本后重新组包", status_code=409)
        base_revision = _read_revision(cursor, head) if head else None
        validation = validate_package(package, base_revision["package"] if base_revision else None)
        if not validation["valid"]:
            reasons = "；".join(e["path"] + ":" + e["message"] for e in validation["errors"][:8])
            raise ApiError("映射契约检查失败：" + reasons, status_code=422)
        _verify_decisions(cursor, package)
        for question in package["questions"]:
            qid, context_hash = question["id"], question_context(question)
            prior_question = _question_row(cursor, qid, lock=True)
            if prior_question:
                # Never replace existing answers with a stale package's embedded status.
                if prior_question["context_hash"] != context_hash:
                    base_question = next((q for q in base_revision["package"]["questions"] if q["id"] == qid), None) if base_revision else None
                    if not base_question or question_context(base_question) != prior_question["context_hash"]:
                        raise ApiError("问题已被其他草稿更新，请读取最新问题再分析", status_code=409)
                    cursor.execute("UPDATE sys_metric_mapping_question SET semantic_key=%s,context_hash=%s,question_json=%s,status='open',applied_revision_id=NULL,lock_version=lock_version+1,updated_at=%s WHERE project_id=%s AND module_id=%s AND environment_id=%s AND question_id=%s", (question["semanticKey"], context_hash, canonical_json(question), now(), *scope(), qid))
            else:
                cursor.execute("INSERT INTO sys_metric_mapping_question(project_id,module_id,environment_id,question_id,semantic_key,context_hash,question_json,answers_json,status,applied_revision_id,lock_version,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'open',NULL,0,%s)", (*scope(), qid, question["semanticKey"], context_hash, canonical_json(question), "[]", now()))
        revision_id, created_at = str(uuid4()), now()
        bindings = legacy_bindings(package, base_revision["bindings"] if base_revision else None)
        cursor.execute("INSERT INTO sys_metric_mapping_revision(revision_id,project_id,module_id,environment_id,package_id,analysis_id,base_revision_id,schema_version,package_hash,package_json,validation_json,bindings_json,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                       (revision_id, *scope(), package["packageId"], package["analysisId"], head, package["schemaVersion"], package_hash, canonical_json(package), canonical_json(validation), canonical_json(bindings), actor["username"], created_at))
        result = _read_revision(cursor, revision_id)
    return {**result, "idempotent": False, "state": "draft", "readbackVerified": True}


def list_questions(*, metric_id=None, status=None, submission_id=None, revision_id=None) -> list[dict]:
    with connection("application") as conn, conn.cursor() as cursor:
        frozen = _read_revision(cursor, revision_id)["package"] if revision_id else None
        frozen_questions = {q["id"]: q for q in frozen["questions"]} if frozen else None
        adopted_answers = {d["answerId"] for d in frozen["decisions"]} if frozen else set()
        cursor.execute("SELECT * FROM sys_metric_mapping_question WHERE project_id=%s AND module_id=%s AND environment_id=%s ORDER BY updated_at,question_id", scope())
        results = []
        for row in cursor.fetchall():
            question, answers = json.loads(row["question_json"]), json.loads(row["answers_json"])
            current_status = row["status"]
            context_hash = row["context_hash"]
            context_current = True
            applied_revision_id = row["applied_revision_id"]
            if frozen_questions is not None:
                if row["question_id"] not in frozen_questions:
                    continue
                question = deepcopy(frozen_questions[row["question_id"]])
                context_hash = question_context(question)
                context_current = context_hash == row["context_hash"]
                answers = [a for a in answers if a["contextHash"] == context_hash]
                if not context_current:
                    # Keep the definition and its old answers together; a draft is not a new active rule.
                    current_status = "superseded"
                    question["problem"] += "（该问题已有新的草稿上下文；此处保留当前映射版本的说明，不能继续按旧上下文答复。）"
                    applied_revision_id = revision_id if any(a["answerId"] in adopted_answers for a in answers) else None
            if metric_id and metric_id not in question.get("affectedMetricIds", []):
                continue
            if status and current_status != status:
                continue
            if submission_id and not any(a["submissionId"] == submission_id for a in answers):
                continue
            results.append({**question, "contextHash": context_hash, "contextCurrent": context_current,
                            "status": current_status, "answers": answers,
                            "appliedRevisionId": applied_revision_id, "lockVersion": row["lock_version"]})
        return results


def answer_question(question_id: str, body: dict, actor: dict) -> dict:
    body = deepcopy(body)
    if body.get("contextHash") and body.get("questionContextHash") and body["contextHash"] != body["questionContextHash"]:
        raise ApiError("答复上下文标识不一致", status_code=422)
    if "contextHash" not in body and "questionContextHash" in body:
        body["contextHash"] = body.pop("questionContextHash")
    else:
        body.pop("questionContextHash", None)
    for key in ("submissionId", "contextHash", "rawAnswer", "scope", "opinionSourceRef"):
        if not body.get(key):
            raise ApiError("答复缺少" + key, status_code=422)
    if any(not isinstance(body[k], str) for k in ("submissionId", "contextHash", "rawAnswer", "opinionSourceRef")):
        raise ApiError("答复标识、原文与意见来源必须为文本", status_code=422)
    if not isinstance(body["scope"], (dict, list, str)):
        raise ApiError("答复范围必须是指标ID列表或明确的metricIds对象", status_code=422)
    if len(body["rawAnswer"]) > 10000 or len(body["submissionId"]) > 160:
        raise ApiError("答复长度超限", status_code=422)
    with connection("application", write=True) as conn, conn.cursor() as cursor:
        row = _question_row(cursor, question_id, lock=True)
        if not row:
            raise ApiError("问题尚未入库", code=404, status_code=404)
        answers = json.loads(row["answers_json"])
        body_hash = content_hash(body)
        for answer in answers:
            if answer["submissionId"] == body["submissionId"]:
                if answer["submissionHash"] != body_hash:
                    raise ApiError("同一submissionId不能覆盖原始答复", status_code=409)
                return {**answer, "idempotent": True}
        if body["contextHash"] != row["context_hash"]:
            raise ApiError("问题上下文已变化，请重新读取问题", status_code=409)
        question = json.loads(row["question_json"])
        answer_scope = body["scope"]
        if isinstance(answer_scope, dict):
            metric_ids = answer_scope.get("metricIds", [])
        elif isinstance(answer_scope, list):
            metric_ids = answer_scope
        else:
            metric_ids = [v.strip() for v in answer_scope.split(",")]
        if not isinstance(metric_ids, list) or any(not isinstance(mid, str) for mid in metric_ids):
            raise ApiError("答复范围只能包含指标ID文本", status_code=422)
        if not metric_ids or not set(metric_ids).issubset(set(question["affectedMetricIds"])):
            raise ApiError("答复适用范围必须明确为本问题影响的指标ID", status_code=422)
        origin = body["opinionSourceRef"]
        origin_kind = "authenticated_submission" if origin in {"current_actor", "指标核验：当前登录用户提交"} else None
        if not origin_kind:
            # A recorded external opinion must point to frozen source material in a saved draft.
            cursor.execute("SELECT package_json FROM sys_metric_mapping_revision WHERE project_id=%s AND module_id=%s AND environment_id=%s ORDER BY created_at DESC LIMIT 100", scope())
            for saved in cursor.fetchall():
                materials = json.loads(saved["package_json"])["sourceManifest"]
                if any(origin in {s["id"], *(e["id"] for e in s.get("evidence", []))} for s in materials if s.get("kind") == "user_decision"):
                    origin_kind = "recorded_source_reference"
                    break
            if not origin_kind:
                raise ApiError("原意见来源未在草稿冻结；先保存原始意见来源，不冒充原作者", status_code=409)
        options = {o.get("id", o.get("choiceId")) for o in question.get("options") or []}
        if body.get("choiceId") and body["choiceId"] != "defer" and body["choiceId"] not in options:
            raise ApiError("答复选项不属于当前问题", status_code=422)
        # The actor is a recorder, not an impersonated original opinion author.
        answer = {**deepcopy(body), "answerId": str(uuid4()), "questionId": question_id, "recordedBy": actor["username"],
                  "identityId": actor["identity_id"], "recordedAt": now(), "submissionHash": body_hash,
                  "originKind": origin_kind, "opinionAuthorVerified": origin_kind == "authenticated_submission"}
        answers.append(answer)
        status = "deferred" if body.get("choiceId") == "defer" else "answered"
        cursor.execute("UPDATE sys_metric_mapping_question SET answers_json=%s,status=%s,applied_revision_id=NULL,lock_version=lock_version+1,updated_at=%s WHERE project_id=%s AND module_id=%s AND environment_id=%s AND question_id=%s", (canonical_json(answers), status, now(), *scope(), question_id))
    return {**answer, "idempotent": False}


def activate_revision(revision_id: str, expected_head: str | None, actor: dict) -> dict:
    with connection("application", write=True) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT revision_id,lock_version FROM sys_metric_mapping_head WHERE project_id=%s AND module_id=%s AND environment_id=%s FOR UPDATE", scope())
        head = _one(cursor)
        if not head:
            raise ApiError("请先保存完整映射草稿", status_code=409)
        if head["revision_id"] == revision_id:
            return {"revisionId": revision_id, "state": "active", "idempotent": True, "lockVersion": head["lock_version"]}
        if head["revision_id"] != expected_head:
            raise ApiError("当前生效版本已变化，禁止覆盖其他人的更新", status_code=409)
        revision = _read_revision(cursor, revision_id)
        if revision["baseRevisionId"] != expected_head:
            raise ApiError("草稿不是基于当前版本，请重新组包", status_code=409)
        package = revision["package"]
        if package.get("pendingAnswers"):
            raise ApiError("尚有离线答复未同步落实，不能生效", status_code=409)
        base_package = _read_revision(cursor, expected_head)["package"] if expected_head else None
        activation_validation = validate_package(package, base_package)
        if not activation_validation["valid"]:
            raise ApiError("映射包未通过当前服务契约检查，请重新校验并保存草稿", status_code=409)
        if any(w.get("blocksActivation") for w in activation_validation.get("warnings", [])):
            raise ApiError("共用口径影响尚未处理完整，不能生效", status_code=409)
        _verify_decisions(cursor, package, latest=True)
        for question in package["questions"]:
            row = _question_row(cursor, question["id"], lock=True)
            if not row or row["context_hash"] != question_context(question):
                raise ApiError("问题上下文已有更新，请重新分析后生效", status_code=409)
        if package["moduleId"] == "ai-briefing":
            _register_ai_metadata(cursor, revision)
        cursor.execute("UPDATE sys_metric_mapping_head SET revision_id=%s,lock_version=lock_version+1,updated_by=%s,updated_at=%s WHERE project_id=%s AND module_id=%s AND environment_id=%s", (revision_id, actor["username"], now(), *scope()))
        for decision in package["decisions"]:
            cursor.execute("UPDATE sys_metric_mapping_question SET status='resolved',applied_revision_id=%s,lock_version=lock_version+1,updated_at=%s WHERE project_id=%s AND module_id=%s AND environment_id=%s AND question_id=%s", (revision_id, now(), *scope(), decision["questionId"]))
    return {"revisionId": revision_id, "packageHash": revision["packageHash"], "state": "active", "idempotent": False, "lockVersion": head["lock_version"] + 1}


def _metadata_values(metric: dict, package: dict, revision_id: str) -> dict:
    actual_id = (metric.get("actualBinding") or {}).get("queryId")
    query = next((q for q in package["queries"] if q["id"] == actual_id), None)
    if not query or query.get("purpose") != "application_actual" or not query.get("sql"):
        raise ApiError("AI简报指标必须先登记独立应用查询：" + metric["id"], status_code=409)
    from .mapping_adapter import _text
    return {"metric_code": metric["id"], "metric_name": metric["name"], "metric_type": metric["type"],
            "data_source": ",".join(sorted({b["objectName"] for n in metric["lineage"]["nodes"]
                                          for b in n.get("physicalBindings", []) if n["layer"] == "application"})),
            "sql_template": query["sql"], "definition_status": "published", "implementation_status": "actual",
            "technical_kpi_id": metric["id"], "boundary": _text(metric["definition"].get("nullPolicy"))[:500],
            "management_value": (metric["definition"].get("businessPurpose") or "")[:500],
            "grain": _text(metric["definition"]["grain"])[:128], "update_cycle": "按指定学期查询",
            "version": metric.get("version") or "1.0.0", "source_kind": "real",
            "definition_source": "mapping:ai-briefing:" + revision_id,
            "page_refs": canonical_json([AI_BRIEFING_PAGE]), "enabled": 1}


def _register_ai_metadata(cursor, revision: dict):
    """Only called by the protected activation transaction; source/fact tables are never written."""
    package = revision["package"]
    for position, metric in enumerate(package["metrics"]):
        if not metric["id"].startswith("AI-"):
            raise ApiError("AI简报指标编码须属于AI命名空间，禁止覆盖106指标", status_code=409)
        actual_id = (metric.get("actualBinding") or {}).get("queryId")
        check = revision["validation"]["queryChecks"].get(actual_id, {})
        if check.get("executionApproval") != "documented":
            raise ApiError("应用指标查询仍有未解决的物理或口径条件：" + metric["id"], status_code=409)
        values = _metadata_values(metric, package, revision["revisionId"])
        cursor.execute("SELECT id,definition_source FROM sys_metric_definition WHERE metric_code=%s FOR UPDATE", (metric["id"],))
        prior = _one(cursor)
        if prior and not (prior.get("definition_source") or "").startswith("mapping:ai-briefing:"):
            raise ApiError("指标编码已由其他维护入口使用，请核对后关联：" + metric["id"], status_code=409)
        columns = list(values)
        stamp = datetime.now(timezone.utc).replace(tzinfo=None)
        if prior:
            cursor.execute("UPDATE sys_metric_definition SET " + ",".join(k + "=%s" for k in columns)
                           + ",updated_at=%s WHERE id=%s", (*values.values(), stamp, prior["id"]))
        else:
            cursor.execute("INSERT INTO sys_metric_definition(" + ",".join(columns) + ",cache_ttl,created_at,updated_at) VALUES("
                           + ",".join(["%s"] * (len(columns) + 3)) + ")", (*values.values(), 0, stamp, stamp))
        cursor.execute("SELECT id FROM sys_metric_page_binding WHERE metric_code=%s AND page_path=%s FOR UPDATE",
                       (metric["id"], AI_BRIEFING_PAGE))
        binding = _one(cursor)
        if binding:
            cursor.execute("UPDATE sys_metric_page_binding SET enabled=1,position=%s,sort_order=%s WHERE id=%s",
                           ("course-first-attempt-observation", position, binding["id"]))
        else:
            cursor.execute("INSERT INTO sys_metric_page_binding(metric_code,page_path,position,sort_order,enabled,created_at) VALUES(%s,%s,%s,%s,1,%s)",
                           (metric["id"], AI_BRIEFING_PAGE, "course-first-attempt-observation", position, stamp))


def registration_status(revision_id: str, module_id: str | None = None) -> dict:
    """Resolve current authoritative SYS rows; a client boolean cannot supply registration evidence."""
    if module_id is not None:
        with module_scope(module_id):
            return registration_status(revision_id)
    with connection("application") as conn, conn.cursor() as cursor:
        revision = _read_revision(cursor, revision_id)
        package = revision["package"]
        cursor.execute("SELECT revision_id FROM sys_metric_mapping_head WHERE project_id=%s AND module_id=%s AND environment_id=%s", scope())
        head = _one(cursor)
        current = bool(head and head["revision_id"] == revision_id)
        refs = []
        for metric in package["metrics"]:
            if package["moduleId"] != "ai-briefing":
                raise ApiError("本登记依据接口仅用于AI简报", status_code=422)
            expected = _metadata_values(metric, package, revision_id)
            cursor.execute("SELECT * FROM sys_metric_definition WHERE metric_code=%s", (metric["id"],))
            actual = _one(cursor)
            cursor.execute("SELECT enabled FROM sys_metric_page_binding WHERE metric_code=%s AND page_path=%s", (metric["id"], AI_BRIEFING_PAGE))
            binding = _one(cursor)
            registered = bool(actual and binding and binding["enabled"] == 1
                              and all(actual.get(k) == v for k, v in expected.items()))
            refs.append({"metricCode": metric["id"], "version": actual.get("version") if actual else None,
                         "definitionStatus": actual.get("definition_status") if actual else None,
                         "implementationStatus": actual.get("implementation_status") if actual else None,
                         "enabled": bool(actual and actual.get("enabled")), "pageRef": AI_BRIEFING_PAGE,
                         "registered": registered,
                         "semanticSignature": revision["validation"]["metricSignatures"].get(metric["id"])})
    return {"registered": current and bool(refs) and all(r["registered"] for r in refs), "metrics": refs,
            "pagePath": AI_BRIEFING_PAGE, "mappingRef": {"moduleId": package["moduleId"], "revisionId": revision_id,
                                                          "packageHash": revision["packageHash"], "current": current}}

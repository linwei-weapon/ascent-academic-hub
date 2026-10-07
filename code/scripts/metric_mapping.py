"""Metric mapping workflow; offline assembly and authenticated service operations.

No database credential, direct SQL connection, or production business API is used.
Run --help for the four commands. Stdout is a concise JSON receipt, never a token.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
from backend.metric_verification.mapping_contract import (  # noqa: E402
    affected_metrics, canonical_json, content_hash, semantic_signatures, validate_package)


class WorkflowError(ValueError):
    pass


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise WorkflowError("无法读取有效JSON文件：" + str(path)) from None


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def unwrap_package(value):
    if isinstance(value, dict) and isinstance(value.get("package"), dict): return value["package"]
    if isinstance(value, dict) and isinstance(value.get("packageJson"), dict): return value["packageJson"]
    return value


def prepare_work(input_data, base=None, package=None):
    if input_data.get("template") is not False:
        raise WorkflowError("请填写真实输入，不能执行template=true模板")
    if not input_data.get("analysisId") or not input_data.get("module", {}).get("id"):
        raise WorkflowError("输入缺少analysisId或module.id")
    current = package or base
    if current and current.get("moduleId") != input_data["module"]["id"]:
        raise WorkflowError("输入模块与基线/映射包不同")
    wanted = set(input_data.get("scope", {}).get("metricIds") or [])
    if not wanted and current:
        wanted = {m["id"] for m in current["metrics"]}
    byid = {m["id"]: m for m in (current or {}).get("metrics", [])}
    dependencies = set(wanted)
    while True:
        before = set(dependencies)
        for mid in list(dependencies):
            for ref in byid.get(mid, {}).get("definition", {}).get("metricRefs", []): dependencies.add(ref["metricId"])
        if before == dependencies: break
    changed_rules = input_data.get("scope", {}).get("changedRuleIds") or []
    affected = set(affected_metrics(current, changed_rules, wanted)) if current else wanted
    return {"schemaVersion": "3.1.0", "analysisId": input_data["analysisId"], "baseRevisionId": input_data.get("baseRevisionId"),
            "scope": deepcopy(input_data["scope"]), "requestedMetricIds": sorted(wanted),
            "dependencyMetricIds": sorted(dependencies - wanted), "affectedMetricIds": sorted(affected),
            "impactReviewRequiredMetricIds": sorted(affected | dependencies),
            "missingMetricIds": sorted(dependencies - byid.keys()),
            "metrics": [deepcopy(m) for m in (current or {}).get("metrics", []) if m["id"] in dependencies | affected],
            "knownDecisions": deepcopy((current or {}).get("decisions", [])),
            "questions": [deepcopy(q) for q in (current or {}).get("questions", []) if set(q.get("affectedMetricIds", [])) & (dependencies | affected)],
            "checkpoint": deepcopy((current or {}).get("checkpoint")), "storageStatus": "not_persisted"}


def assemble_package(candidate, base=None, *, partial=False):
    """Merge explicitly partial work, retaining unrelated objects from the baseline."""
    candidate = deepcopy(candidate)
    if not base:
        if partial: raise WorkflowError("局部组包必须提供基线")
        return candidate
    if not candidate.get("baseRevisionId"):
        raise WorkflowError("更新必须填写服务返回的baseRevisionId")
    for key in ("projectId", "moduleId", "environmentId"):
        if base.get(key) != candidate.get(key): raise WorkflowError("更新作用域与基线不同：" + key)
    if partial:
        for key in ("metrics", "queries", "questions", "sharedRules", "validationCases", "sourceManifest", "coverage"):
            merged = {item["id"]: deepcopy(item) for item in base.get(key, [])}
            merged.update({item["id"]: item for item in candidate.get(key, [])})
            candidate[key] = list(merged.values())
        retired = {x.get("metricId", x.get("id")) for x in candidate.get("changeSet", {}).get("retired", []) if isinstance(x, dict) and x.get("reason")}
        candidate["metrics"] = [m for m in candidate["metrics"] if m["id"] not in retired]
        candidate["queries"] = [q for q in candidate["queries"] if q["metricId"] not in retired]
    # Detailed validation rejects silent deletes, unrelated modifications and dangling references.
    return candidate


def offline_validate(package, base=None):
    report = validate_package(package, base)
    report["packageHash"] = content_hash(package)
    report["counts"] = {k: len(package.get(k, [])) for k in ("metrics", "queries", "questions", "validationCases", "coverage")}
    report["checks"] = {"contract": "passed" if report["valid"] else "failed", "runtimeSql": "not_run",
                        "independentCases": "not_run", "businessVerification": "not_run", "storage": "not_persisted"}
    if report["valid"]:
        checks = report["queryChecks"].values()
        report["queryAvailability"] = {"documented": sum(x["executionApproval"] == "documented" for x in checks),
                                       "blocked": sum(x["executionApproval"] != "documented" for x in report["queryChecks"].values())}
    return report


class ServiceClient:
    def __init__(self, profile=None, module_id="teaching-overview"):
        profile = profile or {}
        self.module_id = check_module(module_id)
        self.url = (profile.get("baseUrl") or os.getenv("MV_MAPPING_SERVICE_URL", "")).rstrip("/")
        token_name = profile.get("tokenEnv", "MV_MAPPING_TOKEN")
        identity_name = profile.get("identityEnv", "MV_MAPPING_IDENTITY")
        self._token = os.getenv(token_name, "")
        self._identity = os.getenv(identity_name, "")
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise WorkflowError("配置服务baseUrl，不能在URL中携带凭据")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise WorkflowError("非本机服务须使用HTTPS")
        if not self._token or not self._identity:
            raise WorkflowError("缺少现有授权token/当前身份的环境变量引用；未发送请求、未入库")
        self.timeout = min(60, max(1, int(profile.get("timeoutSeconds", 30))))

    def request(self, method, path, body=None):
        data = canonical_json(body).encode() if body is not None else None
        delimiter = "&" if "?" in path else "?"
        selected_path = path + delimiter + urllib.parse.urlencode({"moduleId": self.module_id})
        request = urllib.request.Request(self.url + "/api/admin/metric-verification" + selected_path, data=data, method=method,
            headers={"Authorization": "Bearer " + self._token, "X-Active-Identity": self._identity, "Content-Type": "application/json"})
        try:
            # Refuse redirects: the authorization must never follow an unexpected host.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs): return None
            with urllib.request.build_opener(NoRedirect).open(request, timeout=self.timeout) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise WorkflowError(f"核验服务返回HTTP {exc.code}；未自动重试或切换连接") from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise WorkflowError("核验服务不可达或响应无效；保留本地包，未确认入库") from None
        if envelope.get("code") not in (0, 200):
            raise WorkflowError("核验服务拒绝操作；请在当前身份下检查服务状态")
        return envelope.get("data")


def check_module(module_id):
    if module_id not in {"teaching-overview", "ai-briefing"}:
        raise WorkflowError("模块仅支持teaching-overview或ai-briefing")
    return module_id


def package_module(package, selected=None):
    module_id = check_module(package.get("moduleId"))
    if selected is not None and selected != module_id:
        raise WorkflowError("--module与映射包moduleId不同；未发送请求")
    return module_id


def publish_package(package, client, mode):
    if hasattr(client, "module_id") and client.module_id != package_module(package):
        raise WorkflowError("服务模块与映射包不同；未发送请求")
    if mode not in {"save_draft", "activate"}: raise WorkflowError("publish仅接受save_draft或activate")
    authorized = package.get("inputManifest", {}).get("delivery", {}).get("mode", "analyze_only")
    if authorized == "analyze_only" or (mode == "activate" and authorized != "activate"):
        raise WorkflowError("交付模式不允许本次操作；不能自动把analyze_only/save_draft升级为生效")
    validation = offline_validate(package)
    if not validation["valid"]: raise WorkflowError("离线契约未通过；先执行validate查看问题")
    saved = client.request("POST", "/mapping/packages", package)
    rid = saved.get("revisionId")
    if not rid: raise WorkflowError("保存回执没有revisionId，未确认入库")
    readback = client.request("GET", "/mapping/revisions/" + urllib.parse.quote(rid, safe=""))
    stored = unwrap_package(readback)
    expected_hash = content_hash(package)
    if not isinstance(stored, dict) or content_hash(stored) != expected_hash:
        raise WorkflowError("包回读内容不一致；不切换生效版本")
    receipt = {"revisionId": rid, "packageHash": expected_hash, "storageStatus": "draft", "readbackVerified": True,
               "answerSync": [], "businessVerification": "not_run"}
    for pending in package.get("pendingAnswers", []):
        qid = pending["questionId"]
        answer = client.request("POST", "/mapping/questions/" + urllib.parse.quote(qid, safe="") + "/answers", pending)
        receipt["answerSync"].append({"questionId": qid, "submissionId": pending["submissionId"], "answerId": answer.get("answerId")})
    if package.get("pendingAnswers"):
        receipt["nextAction"] = "答复已同步；读取answerId，落实受影响规则和SQL，移除pendingAnswers，以新packageId保存最终包。当前版本未生效。"
        return receipt
    if mode == "activate":
        active = client.request("POST", "/mapping/activate", {"revisionId": rid, "expectedHeadRevisionId": package.get("baseRevisionId")})
        receipt.update(storageStatus="active", activation=active)
    return receipt


def live_validate(package, client, revision_id, *, execution_request=None, evidence_id=None, expectation=None):
    """Capture/revisit evidence through the service; raw rows are never a CLI artifact.

    Independent calculation takes place using the service's owned evidence view.
    A later invocation submits that calculation, then reads the disclosed result.
    """
    if hasattr(client, "module_id") and client.module_id != package_module(package):
        raise WorkflowError("服务模块与映射包不同；未发送请求")
    if not revision_id:
        raise WorkflowError("实库核验必须提供已保存的草稿或生效revision-id")
    remote = client.request("GET", "/mapping/revisions/" + urllib.parse.quote(revision_id, safe=""))
    if content_hash(unwrap_package(remote)) != content_hash(package):
        raise WorkflowError("本地包与登记版本不同；先恢复准确版本，不执行SQL")
    execution = None
    if execution_request:
        if evidence_id or expectation:
            raise WorkflowError("取证与提交独立预期分开执行，先取得留存输入")
        query_id = execution_request.get("queryId")
        query = next((q for q in package["queries"] if q["id"] == query_id), None)
        if not query: raise WorkflowError("queryId不属于该映射版本")
        if not execution_request.get("validationCaseId"):
            raise WorkflowError("独立核算必须指定已登记validationCaseId")
        parameters = execution_request.get("parameters") or {}
        if not any(parameters.get(k) is not None for k in ("student_id", "course_id", "organization_id", "major_id")):
            raise WorkflowError("首次核算必须显式限定学生、课程或组织范围")
        payload = {k: execution_request[k] for k in ("requirementId", "scenarioId", "parameters", "limit", "validationCaseId") if k in execution_request}
        payload.update(mappingRevisionId=revision_id, executionUse="definition_validation", sqlVersion=query["version"])
        execution = client.request("POST", "/queries/" + urllib.parse.quote(query_id, safe="") + "/execute", payload)
        if not execution.get("evidenceSaved") or not execution.get("evidenceRef"):
            return {"status": "inconclusive", "runtimeSql": execution.get("status", "unknown"), "evidenceRetention": "not_confirmed",
                    "message": "服务未确认完整留存，不报告独立计算通过"}
        evidence_id = execution["evidenceRef"]
    if not evidence_id: raise WorkflowError("提供execution-request取证，或evidence-id回读已留存证据")
    path = "/executions/" + urllib.parse.quote(evidence_id, safe="")
    evidence = client.request("GET", path + "/evidence")
    if evidence.get("mappingRevisionId") != revision_id:
        raise WorkflowError("留存证据与指定版本不匹配")
    if expectation:
        if expectation.get("inputContentHash") != evidence.get("integrity", {}).get("contentHash"):
            raise WorkflowError("独立预期与留存输入hash不一致")
        evidence = client.request("POST", path + "/independent-expectation", expectation)
        # Read again: a POST response alone does not prove later retrieval.
        evidence = client.request("GET", path + "/evidence")
    validation = evidence.get("validation", {})
    return {"status": validation.get("status", "pending"), "runtimeSql": "executed_with_retained_evidence", "revisionId": revision_id,
            "executionId": evidence_id, "evidenceRetention": "retained", "evidenceReadback": evidence.get("integrity", {}).get("readbackVerified", False),
            "inputContentHash": evidence.get("integrity", {}).get("contentHash"),
            "datasets": [{"queryId": x.get("queryId"), "matchedRecordCount": x.get("matchedRecordCount"),
                          "returnedRecordCount": x.get("returnedRecordCount"), "complete": x.get("complete")} for x in evidence.get("datasets", [])],
            "resultDisclosure": evidence.get("resultDisclosure"), "independentCalculation": validation.get("status", "not_run"),
            "differenceCount": len(validation.get("differences", [])), "businessVerification": "not_run",
            "nextAction": "从已授权服务证据入口独立核算输入，再提交预期" if evidence.get("resultDisclosure") == "withheld" else "按相同业务条件与114系统真实应用实值对照；保存人工判断"}


def delivery_receipt(package, saved):
    """Persist the documented receipt contract, keeping service facts distinct."""
    receipt = read_json(ROOT / "code/metric-verification/contracts/mapping-receipt.template.json")
    receipt.update(template=False, analysisId=package["analysisId"])
    receipt["scope"].update(projectId=package["projectId"], moduleId=package["moduleId"], environmentId=package["environmentId"],
        metricIds=[m["id"] for m in package["metrics"]], businessCategories=sorted({m["businessCategory"] for m in package["metrics"]}))
    receipt["sources"] = {"capturedRefs": [s["id"] for s in package["sourceManifest"] if s.get("contentHash")],
                          "unavailableRefs": [s["id"] for s in package["sourceManifest"] if not s.get("contentHash")]}
    receipt["mapping"].update(status="organized", pendingQuestionIds=[q["id"] for q in package["questions"] if q.get("status") not in {"resolved", "superseded"}],
        candidateMetricIds=[], organizedMetricIds=[m["id"] for m in package["metrics"]], completeMetricIds=[],
        partialMetricIds=[m["id"] for m in package["metrics"]])
    receipt["storage"].update(status=saved["storageStatus"], revisionId=saved["revisionId"], packageHash=saved["packageHash"],
        currentRevisionId=saved["revisionId"] if saved["storageStatus"] == "active" else package.get("baseRevisionId"),
        readbackVerified=saved["readbackVerified"])
    receipt["checks"].update(contract="passed", businessDependencies="passed")
    receipt["answerSync"].update(status="synced_needs_application" if saved["answerSync"] else "not_required",
        pendingSubmissionIds=[], confirmedAnswerIds=[a["answerId"] for a in saved["answerSync"]])
    receipt["changes"] = deepcopy(package["changeSet"])
    receipt["nextAction"] = saved.get("nextAction") or "通过登记版本进行限定真实核算和114应用实值对照；本回执不表示业务验收通过。"
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="读取输入和基线，建立指标工作集；不写库")
    prepare.add_argument("--input", required=True); prepare.add_argument("--base"); prepare.add_argument("--package")
    prepare.add_argument("--output", required=True)
    check = commands.add_parser("validate", help="组装并复用服务契约检查；默认离线")
    check.add_argument("--package", required=True); check.add_argument("--base"); check.add_argument("--partial", action="store_true")
    check.add_argument("--output"); check.add_argument("--report", required=True)
    check.add_argument("--live", action="store_true", help="只经服务核验已登记版本；不直连数据库")
    check.add_argument("--profile"); check.add_argument("--revision-id")
    check.add_argument("--execution-request", help="queryId/requirementId/scenarioId/parameters/validationCaseId/limit，先取证")
    check.add_argument("--evidence-id"); check.add_argument("--expectation-file", help="读留存输入独立核算后填写，不自动生成预期")
    publish = commands.add_parser("publish", help="经现有身份服务保存、回读及按授权生效")
    publish.add_argument("--package", required=True); publish.add_argument("--mode", choices=["save_draft", "activate"], required=True)
    publish.add_argument("--profile"); publish.add_argument("--receipt", required=True)
    resume = commands.add_parser("resume", help="读取服务最新版本和答复，不调度、不改库")
    resume.add_argument("--analysis-id"); resume.add_argument("--revision-id"); resume.add_argument("--package")
    resume.add_argument("--profile"); resume.add_argument("--output", required=True)
    for command in (prepare, check, publish, resume):
        command.add_argument("--module", choices=["teaching-overview", "ai-briefing"],
                             help="显式模块；包操作缺省从包读取，远端resume缺省教学总览")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            input_data = read_json(args.input)
            selected = check_module(input_data.get("module", {}).get("id"))
            if args.module and args.module != selected:
                raise WorkflowError("--module与输入module.id不同")
            result = prepare_work(input_data, unwrap_package(read_json(args.base)) if args.base else None,
                                  unwrap_package(read_json(args.package)) if args.package else None)
            write_json(args.output, result)
            summary = {"status": "prepared", "metrics": len(result["metrics"]), "missingMetricIds": result["missingMetricIds"], "output": args.output}
        elif args.command == "validate":
            base = unwrap_package(read_json(args.base)) if args.base else None
            package = assemble_package(unwrap_package(read_json(args.package)), base, partial=args.partial)
            selected = package_module(package, args.module)
            result = offline_validate(package, base)
            if args.live:
                if not result["valid"]: raise WorkflowError("离线契约失败，未调用实库服务")
                if args.partial: raise WorkflowError("实库验证使用已登记完整包，不能同时partial组包")
                client = ServiceClient(read_json(args.profile) if args.profile else None, selected)
                result["live"] = live_validate(package, client, args.revision_id,
                    execution_request=read_json(args.execution_request) if args.execution_request else None,
                    evidence_id=args.evidence_id, expectation=read_json(args.expectation_file) if args.expectation_file else None)
                result["checks"]["runtimeSql"] = result["live"].get("runtimeSql", "not_run")
            write_json(args.report, result)
            if args.output and result["valid"]: write_json(args.output, package)
            summary = {"status": "passed" if result["valid"] else "failed", "counts": result["counts"], "errors": result["errors"],
                       "warnings": result["warnings"], "queryAvailability": result.get("queryAvailability"), "report": args.report,
                       "runtimeSql": result["checks"]["runtimeSql"], "storage": "not_persisted", "live": result.get("live")}
            print(json.dumps(summary, ensure_ascii=False))
            return 0 if result["valid"] else 2
        elif args.command == "publish":
            package = read_json(args.package)
            client = ServiceClient(read_json(args.profile) if args.profile else None, package_module(package, args.module))
            result = publish_package(package, client, args.mode)
            write_json(args.receipt, delivery_receipt(package, result)); summary = result
        else:
            if args.package and not args.analysis_id and not args.revision_id:
                package = unwrap_package(read_json(args.package))
                package_module(package, args.module)
                result = prepare_work(package["inputManifest"], package=package)
                result["resumeSource"] = "local_only_not_service_state"
            else:
                client = ServiceClient(read_json(args.profile) if args.profile else None, args.module or "teaching-overview")
                if args.revision_id:
                    revision = client.request("GET", "/mapping/revisions/" + urllib.parse.quote(args.revision_id, safe=""))
                elif args.analysis_id:
                    revisions = client.request("GET", "/mapping/revisions?" + urllib.parse.urlencode({"analysisId": args.analysis_id}))
                    items = revisions.get("items", revisions.get("revisions", [])) if isinstance(revisions, dict) else revisions
                    if not items: raise WorkflowError("服务中尚无该分析的版本，使用本地包恢复")
                    revision = client.request("GET", "/mapping/revisions/" + urllib.parse.quote(items[0]["revisionId"], safe=""))
                else: raise WorkflowError("resume需要analysis-id、revision-id或本地package")
                package = unwrap_package(revision)
                head = client.request("GET", "/mapping/head")
                questions = client.request("GET", "/mapping/questions")
                result = {"revision": revision, "currentHead": head, "questions": questions,
                          "work": prepare_work(package["inputManifest"], package=package), "nextAction": "对比最新head与原基线；应用已存答复后再validate/publish"}
            write_json(args.output, result)
            summary = {"status": "resumed", "output": args.output, "mutation": False}
        print(json.dumps(summary, ensure_ascii=False)); return 0
    except (WorkflowError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "message": str(exc)}, ensure_ascii=False)); return 2


if __name__ == "__main__":
    raise SystemExit(main())

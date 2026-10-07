"""HTTP orchestration; permissions and business execution have separate owners."""
from fastapi import APIRouter, Depends, Query, Header
from fastapi.responses import JSONResponse

from backend.api.envelope import ok
from . import store, execution, rules, rule_runner, model_adapter
from backend.api.permission_context import has_action
from .auth import can_manage, current_actor, require_manage, require_use
from .models import (CreateInput, CopyInput, EnabledInput, PackageInput, ResearchInput, ReviewInput, RevisionInput,
                     SaveInput, TestInput, TurnInput, ExecutionInput, RuleInput, RuleSaveInput,
                     RuleConfirmInput, RuleWithdrawInput, IssueInput)
from .runtime import analysis_options
from .selection_options import course_options

router = APIRouter(prefix="/api/admin/expert-resources", tags=["expert-resources"])


def reader(actor=Depends(current_actor)):
    require_use(actor)
    return actor


def manager(actor=Depends(current_actor)):
    require_manage(actor)
    return actor


@router.get("/catalog")
def catalog(actor=Depends(reader)):
    return ok({**store.catalog(actor), "canManage": can_manage(actor), "canUse": True})


@router.get("/options")
def options(actor=Depends(reader)):
    return ok(analysis_options(actor))


@router.get('/options/courses')
def courses(semester_id: str = Query(min_length=1, max_length=128),
            college_id: str | None = Query(default=None, min_length=1, max_length=128),
            actor=Depends(reader)):
    return ok(course_options(actor, semester_id, college_id))


@router.get("/resources/{kind}/{resource_id}")
def resource(kind: str, resource_id: str, actor=Depends(reader)):
    return ok(store.get_resource(kind, resource_id, actor))


@router.put("/resources/{kind}/{resource_id}")
def save(kind: str, resource_id: str, body: SaveInput, actor=Depends(manager)):
    return ok(store.save_resource(kind, resource_id, body.revision, body.content, actor))


@router.post("/resources/{kind}/{resource_id}/test")
def test(kind: str, resource_id: str, body: TestInput, actor=Depends(manager)):
    return ok(store.test_resource(kind, resource_id, body.revision, body.input, actor))


@router.post("/resources/{kind}/{resource_id}/review")
def review(kind: str, resource_id: str, body: ReviewInput, actor=Depends(manager)):
    return ok(store.review_resource(kind, resource_id, body.revision, body.runId, body.accepted, body.note, actor))


@router.post("/resources/{kind}/{resource_id}/publish")
def publish(kind: str, resource_id: str, body: RevisionInput, actor=Depends(manager)):
    return ok(store.publish_resource(kind, resource_id, body.revision, actor))


@router.post("/resources/{kind}/{resource_id}/enabled")
def enabled(kind: str, resource_id: str, body: EnabledInput, actor=Depends(manager)):
    return ok(store.set_enabled(kind, resource_id, body.enabled, actor))


@router.get("/research")
def research_list(search: str = Query(default='',max_length=200), offset: int = Query(default=0,ge=0),
                  limit: int = Query(default=50,ge=1,le=100), actor=Depends(reader)):
    return ok(store.list_research(actor,search,offset,limit))


@router.post("/research")
def create_research(body: ResearchInput, actor=Depends(reader)):
    return ok(store.create_research(body.expertId, body.input, body.question, actor))


@router.get("/research/{research_id}")
def research_detail(research_id: str, actor=Depends(reader)):
    return ok(store.get_research(research_id, actor))


@router.post("/research/{research_id}/turn")
def research_turn(research_id: str, body: TurnInput, actor=Depends(reader)):
    return ok(store.add_turn(research_id, body.input, body.question, actor))


@router.post("/resources/{kind}")
def create_resource(kind: str, body: CreateInput, actor=Depends(manager)):
    return ok(store.create_resource(kind, body.name, actor, body.id, body.templateId, body.category, body.summary, body.content))


@router.post('/skills/package/inspect')
def inspect_package(body: PackageInput, actor=Depends(manager)):
    from .packages import inspect_package
    return ok(inspect_package(body.filename, body.zipBase64))


@router.post('/skills/package')
def install_package(body: PackageInput, actor=Depends(manager)):
    from .packages import inspect_package
    package = inspect_package(body.filename, body.zipBase64)
    return ok(store.install_package(package, actor, body.resourceId, body.revision, body.displayName, body.category))


@router.post("/resources/{kind}/{resource_id}/copy")
def copy_resource(kind: str, resource_id: str, body: CopyInput, actor=Depends(manager)):
    return ok(store.copy_resource(kind, resource_id, body.revision, body.name, actor, body.id))


@router.get("/resources/{kind}/{resource_id}/references")
def resource_references(kind: str, resource_id: str, actor=Depends(manager)):
    return ok(store.references(kind, resource_id))


@router.delete("/resources/{kind}/{resource_id}")
def delete_resource(kind: str, resource_id: str, revision: int = Query(ge=1), actor=Depends(manager)):
    return ok(store.delete_resource(kind, resource_id, revision, actor))


@router.post("/resources/{kind}/{resource_id}/restore")
def restore_resource(kind: str, resource_id: str, body: RevisionInput, actor=Depends(manager)):
    return ok(store.restore_resource(kind, resource_id, body.revision, actor))


@router.get("/archived")
def archived(kind: str | None = None, actor=Depends(manager)):
    return ok(store.archived(kind, actor))


@router.get('/tasks')
def task_list(actor=Depends(reader)):
    return ok(execution.tasks(actor))


@router.get('/models')
def models(actor=Depends(reader)):
    return ok(model_adapter.available_models())


@router.post('/executions', status_code=202)
def execute(body: ExecutionInput, actor=Depends(reader), authorization: str = Header(default=''),
            identity: str = Header(default='', alias='X-Active-Identity')):
    return ok(execution.submit(body.model_dump(exclude_none=True), actor, authorization, identity))


@router.get('/executions/{execution_id}')
def execution_detail(execution_id: str, actor=Depends(reader)):
    return ok(execution.get(execution_id, actor))


@router.get('/execution-requests/{client_request_id}')
def execution_request(client_request_id: str, actor=Depends(reader)):
    return ok(execution.find(client_request_id, actor, missing_ok=True))


@router.post('/executions/{execution_id}/cancel')
def execution_cancel(execution_id: str, actor=Depends(reader)):
    return ok(execution.cancel(execution_id, actor))


@router.get('/results/{result_id}')
def saved_result(result_id: str, actor=Depends(reader)):
    return ok(execution.get_result(result_id, actor))


@router.get('/results/{result_id}/evidence/{evidence_id}')
def saved_evidence(result_id: str, evidence_id: str, offset: int = Query(default=0, ge=0),
                   limit: int = Query(default=20, ge=1, le=200), actor=Depends(reader)):
    return ok(execution.evidence(result_id, evidence_id, actor, offset, limit))


@router.get('/rules')
def rule_list(actor=Depends(reader)):
    return ok({**rules.list_rules(actor), 'canImportConfirmation': has_action(actor, 'policy.confirm.import')})


@router.post('/rules')
def rule_create(body: RuleInput, actor=Depends(manager)):
    return ok(rules.create_rule(body.payload, actor))


@router.put('/rules/{rule_id}/versions/{version}')
def rule_save(rule_id: str, version: str, body: RuleSaveInput, actor=Depends(manager)):
    return ok(rules.update_rule(rule_id, version, body.revision, body.payload, actor))


@router.post('/rules/{rule_id}/versions/{version}/confirm')
def rule_confirm(rule_id: str, version: str, body: RuleConfirmInput, actor=Depends(reader)):
    return ok(rules.confirm_rule(rule_id, version, body.revision, actor, body.confirmation, body.accepted))


@router.post('/rules/{rule_id}/versions/{version}/test')
def rule_test(rule_id: str, version: str, body: RevisionInput, actor=Depends(manager)):
    return ok(rule_runner.run(rule_id, version, body.revision, actor))


@router.post('/rules/{rule_id}/versions/{version}/publish')
def rule_publish(rule_id: str, version: str, body: RevisionInput, actor=Depends(manager)):
    return ok(rules.publish_rule(rule_id, version, body.revision, actor))


@router.post('/rules/{rule_id}/versions/{version}/withdraw')
def rule_withdraw(rule_id: str, version: str, body: RuleWithdrawInput, actor=Depends(manager)):
    return ok(rules.withdraw_rule(rule_id, version, body.revision, actor, body.reason))


@router.get('/research/{research_id}/issues')
def issue_list(research_id: str, actor=Depends(reader)):
    return ok(rules.list_issues(research_id, actor))


@router.post('/research/{research_id}/issues/{issue_id}/events')
def issue_event(research_id: str, issue_id: str, body: IssueInput, actor=Depends(reader)):
    event = body.model_dump(exclude_none=True)
    event['type'] = 'submitted' if body.type == 'source_added' else body.type
    return ok(rules.append_issue_event(research_id, issue_id, event, actor))

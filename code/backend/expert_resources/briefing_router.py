"""Existing identity and response contract for briefings and processing config."""
from typing import Any
from fastapi import APIRouter, Depends, Header, Query
from pydantic import Field

from backend.api.envelope import ok
from . import briefing, processing
from .auth import current_actor, require_manage, require_use
from .models import StrictModel

router = APIRouter(prefix='/api/admin/expert-resources', tags=['expert-briefing'])


class Revision(StrictModel):
    expectedRevision: int = Field(ge=1)


class Operation(Revision):
    clientRequestId: str = Field(min_length=1, max_length=100)
    replacesPublicationId: str | None = Field(default=None, max_length=100)


class Withdrawal(Operation):
    reason: str = Field(min_length=1, max_length=4000)


class Configuration(Revision):
    serviceId: str = 'expert-resources'
    name: str = Field(min_length=1, max_length=200)
    environment: str = 'test-114'
    dataConfigRef: str = 'metric-verification'
    modelConfigRef: str = 'expert-resources'
    automaticEnabled: bool = False
    timeoutSeconds: int = Field(default=180, ge=20, le=300)
    retryLimit: int = Field(default=0, ge=0, le=1)


class Grant(StrictModel):
    scope: dict[str, Any]
    taskIds: list[str]
    validUntil: str = Field(min_length=1, max_length=100)


class Renewal(Revision):
    validUntil: str = Field(min_length=1, max_length=100)


class Preset(StrictModel):
    expectedRevision: int | None = Field(default=None, ge=1)
    id: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)
    expertId: str = Field(min_length=1, max_length=100)
    taskId: str = 'C-PERFORMANCE'
    input: dict[str, Any]
    scope: dict[str, Any]
    collegeMeaning: str = 'course_opening'
    serviceId: str = 'expert-resources'
    grantId: str | None = None
    schedule: dict[str, Any] | None = None
    activeWindow: dict[str, Any] | None = None


@router.get('/processing/config')
def config(actor=Depends(current_actor)):
    return ok(processing.view(actor))


@router.put('/processing/config')
def config_save(body: Configuration, actor=Depends(current_actor)):
    return ok(processing.save(body.model_dump(), actor))


@router.post('/processing/check')
def config_check(body: Revision, actor=Depends(current_actor)):
    return ok(processing.check(body.expectedRevision, actor))


@router.post('/processing/apply')
def config_apply(body: Revision, actor=Depends(current_actor)):
    return ok(processing.apply(body.expectedRevision, actor))


@router.post('/processing/grants')
def grant_create(body: Grant, actor=Depends(current_actor)):
    return ok(processing.grant(body.model_dump(), actor))


@router.delete('/processing/grants/{grant_id}')
def grant_revoke(grant_id: str, expectedRevision: int = Query(ge=1), actor=Depends(current_actor)):
    return ok(processing.revoke(grant_id, expectedRevision, actor))


@router.put('/processing/grants/{grant_id}')
def grant_renew(grant_id: str, body: Renewal, actor=Depends(current_actor)):
    return ok(processing.renew(grant_id, body.expectedRevision, body.validUntil, actor))


@router.post('/processing/recovery/recheck')
def recovery(actor=Depends(current_actor)):
    return ok(processing.recheck(actor))


@router.get('/processing/executions')
def service_executions(offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100), actor=Depends(current_actor)):
    return ok(briefing.service_executions(actor, offset, limit))


@router.get('/briefing/presets')
def presets(expertId: str | None = Query(default=None, max_length=100), actor=Depends(current_actor)):
    return ok(briefing.presets(actor, expertId))


@router.post('/briefing/presets')
def preset_create(body: Preset, actor=Depends(current_actor)):
    return ok(briefing.save(body.model_dump(exclude_none=True), actor))


@router.put('/briefing/presets/{preset_id}')
def preset_save(preset_id: str, body: Preset, actor=Depends(current_actor)):
    return ok(briefing.save(body.model_dump(exclude_unset=True), actor, preset_id))


@router.delete('/briefing/presets/{preset_id}')
def preset_delete(preset_id: str, expectedRevision: int = Query(ge=1), actor=Depends(current_actor)):
    return ok(briefing.remove(preset_id, expectedRevision, actor))


@router.post('/briefing/presets/{preset_id}/trial')
def trial(preset_id: str, body: Operation, actor=Depends(current_actor),
          authorization: str = Header(default=''), identity: str = Header(default='', alias='X-Active-Identity')):
    return ok(briefing.execute(preset_id, body.model_dump(exclude_none=True), actor, authorization, identity, 'trial'))


@router.post('/briefing/presets/{preset_id}/run')
def run(preset_id: str, body: Operation, actor=Depends(current_actor),
        authorization: str = Header(default=''), identity: str = Header(default='', alias='X-Active-Identity')):
    return ok(briefing.execute(preset_id, body.model_dump(exclude_none=True), actor, authorization, identity, 'run'))


@router.post('/briefing/presets/{preset_id}/enable')
def enable(preset_id: str, body: Operation, actor=Depends(current_actor)):
    return ok(briefing.enable(preset_id, body.model_dump(exclude_none=True), actor))


@router.post('/briefing/presets/{preset_id}/pause')
def pause(preset_id: str, body: Operation, actor=Depends(current_actor)):
    return ok(briefing.pause(preset_id, body.expectedRevision, actor))


@router.get('/briefing/presets/{preset_id}/executions')
def preset_executions(preset_id: str, offset: int = Query(default=0, ge=0),
                      limit: int = Query(default=20, ge=1, le=100), actor=Depends(current_actor)):
    return ok(briefing.executions(preset_id, actor, offset, limit))


@router.get('/briefing/publications')
def publications(semesterId: str | None = Query(default=None, max_length=128),
                 collegeId: str | None = Query(default=None, max_length=128), history: bool = False,
                 offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100), actor=Depends(current_actor)):
    return ok(briefing.publications(actor, semesterId, collegeId, history, offset, limit))


@router.get('/briefing/presets/{preset_id}/executions/{execution_id}/evidence/{evidence_id}')
def candidate_evidence(preset_id: str, execution_id: str, evidence_id: str,
                      offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100), actor=Depends(current_actor)):
    return ok(briefing.candidate_evidence(preset_id, execution_id, evidence_id, actor, offset, limit))


@router.get('/briefing/publications/{publication_id}')
def publication(publication_id: str, actor=Depends(current_actor)):
    return ok(briefing.publication(publication_id, actor))


@router.get('/briefing/publications/{publication_id}/evidence/{evidence_id}')
def evidence(publication_id: str, evidence_id: str, offset: int = Query(default=0, ge=0),
             limit: int = Query(default=20, ge=1, le=100), actor=Depends(current_actor)):
    return ok(briefing.evidence(publication_id, evidence_id, actor, offset, limit))


@router.post('/briefing/publications/{publication_id}/withdraw')
def withdraw(publication_id: str, body: Withdrawal, actor=Depends(current_actor)):
    return ok(briefing.withdraw(publication_id, body.model_dump(exclude_none=True), actor))

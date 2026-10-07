"""Authenticated mapping import/read/adoption endpoints; does not execute submitted SQL."""
from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from backend.api.envelope import ok, ApiError
from .auth import current_actor, require_mapping_management, can_manage_mapping
from . import mapping_store

router = APIRouter(prefix="/api/admin/metric-verification/mapping")


class ActivateInput(BaseModel):
    revisionId: str = Field(min_length=1, max_length=120)
    expectedHeadRevisionId: str | None = None


@router.get("/head")
def head(actor: dict = Depends(current_actor)):
    # Bootstrap is a management read, never a fallback for business consumers.
    return ok(mapping_store.get_head(allow_empty=can_manage_mapping(actor)))


@router.get("/revisions")
def revisions(analysisId: str | None = Query(default=None, max_length=160), actor: dict = Depends(current_actor)):
    return ok({"items": mapping_store.list_revisions(analysisId)})


@router.get("/revisions/{revision_id}")
def revision(revision_id: str, actor: dict = Depends(current_actor)):
    return ok(mapping_store.get_revision(revision_id))


@router.get("/registrations/{revision_id}")
def registrations(revision_id: str, actor: dict = Depends(current_actor)):
    return ok(mapping_store.registration_status(revision_id))


@router.post("/packages")
def packages(body: dict = Body(...), actor: dict = Depends(current_actor)):
    require_mapping_management(actor)
    return ok(mapping_store.save_package(body, actor))


@router.get("/questions")
def questions(metricId: str | None = None, status: str | None = None, submissionId: str | None = None,
              mappingRevisionId: str | None = None,
              actor: dict = Depends(current_actor)):
    current = mapping_store.get_head()["revisionId"]
    if mappingRevisionId and mappingRevisionId != current:
        raise ApiError("映射版本已变化，请刷新问题后回答", status_code=409)
    return ok({"items": mapping_store.list_questions(metric_id=metricId, status=status, submission_id=submissionId,
                                                      revision_id=mappingRevisionId),
               "mappingRevisionId": current})


@router.post("/questions/{question_id}/answers")
def answer(question_id: str, body: dict = Body(...), actor: dict = Depends(current_actor)):
    require_mapping_management(actor)
    return ok(mapping_store.answer_question(question_id, body, actor))


@router.post("/activate")
def activate(body: ActivateInput, actor: dict = Depends(current_actor)):
    require_mapping_management(actor)
    return ok(mapping_store.activate_revision(body.revisionId, body.expectedHeadRevisionId, actor))

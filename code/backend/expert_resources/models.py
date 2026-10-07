"""Strict request contracts for expert resource management and research."""
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def bound_payload(cls, value):
        if isinstance(value, dict):
            if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 200_000:
                raise ValueError("请求内容超过允许大小")
            def check(item, depth=0):
                if depth > 24:
                    raise ValueError("请求结构嵌套过深")
                if isinstance(item, str) and len(item) > 24_000:
                    raise ValueError("单个文本字段过长")
                if isinstance(item, (dict, list)):
                    if len(item) > 2000:
                        raise ValueError("请求条目过多")
                    for child in item.values() if isinstance(item, dict) else item:
                        check(child, depth + 1)
            check(value)
        return value


class SaveInput(StrictModel):
    revision: int = Field(ge=1)
    content: dict[str, Any]


class RevisionInput(StrictModel):
    revision: int = Field(ge=1)


class TestInput(RevisionInput):
    input: dict[str, Any] = Field(default_factory=dict)


class ReviewInput(RevisionInput):
    runId: str = Field(min_length=1, max_length=100)
    accepted: bool
    note: str = Field(min_length=1, max_length=4000)


class EnabledInput(StrictModel):
    enabled: bool


class ResearchInput(StrictModel):
    expertId: str = Field(min_length=1, max_length=100)
    input: dict[str, Any] = Field(default_factory=dict)
    question: str = Field(min_length=1, max_length=4000)


class TurnInput(StrictModel):
    input: dict[str, Any] = Field(default_factory=dict)
    question: str = Field(min_length=1, max_length=4000)


class CreateInput(StrictModel):
    id: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    templateId: str | None = Field(default=None, max_length=100)
    category: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=4000)
    content: dict[str, Any] = Field(default_factory=dict)


class PackageInput(StrictModel):
    filename: str = Field(min_length=1, max_length=200)
    zipBase64: str = Field(min_length=1, max_length=2_700_000)
    resourceId: str | None = Field(default=None, max_length=100)
    revision: int | None = Field(default=None, ge=1)
    displayName: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=200)


class CopyInput(RevisionInput):
    id: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)


class ExecutionInput(StrictModel):
    clientRequestId: str = Field(min_length=1, max_length=100)
    expertId: str = Field(min_length=1, max_length=100)
    researchId: str | None = Field(default=None, max_length=100)
    expectedTurn: int = Field(default=0, ge=0)
    mode: Literal['selected_task', 'question', 'clarification_answer']
    expertSelection: Literal['legacy', 'per_turn'] = 'legacy'
    upgradeToVersion: str | None = Field(default=None, max_length=100)
    readMode: Literal['live', 'saved'] = 'live'
    publicationId: str | None = Field(default=None, max_length=100)
    sourceResultId: str | None = Field(default=None, max_length=100)
    objectId: str | None = Field(default=None, max_length=128)
    question: str = Field(default='', max_length=4000)
    input: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    originalTurnId: str | None = Field(default=None, max_length=100)
    clarificationId: str | None = Field(default=None, max_length=100)
    answer: str | None = Field(default=None, max_length=4000)
    retryOfExecutionId: str | None = Field(default=None, max_length=100)

    @field_validator('clientRequestId')
    @classmethod
    def uuid_request(cls, value):
        UUID(value)
        return value

    @field_validator('context')
    @classmethod
    def public_context(cls, value):
        if set(value) - {'note'}:
            raise ValueError('上下文仅接受备注；历史事实和澄清由服务端读取')
        return value


class RuleInput(StrictModel):
    payload: dict[str, Any]


class RuleSaveInput(RuleInput):
    revision: int = Field(ge=1)


class RuleConfirmInput(RevisionInput):
    accepted: bool = True
    confirmation: dict[str, Any]


class RuleWithdrawInput(RevisionInput):
    reason: str = Field(min_length=1, max_length=4000)


class IssueInput(RevisionInput):
    type: Literal['source_added', 'deferred', 'scope_corrected', 'reopened']
    sourceRef: dict[str, Any] | None = None
    reason: str = Field(default='', max_length=4000)

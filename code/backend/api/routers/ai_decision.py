"""AI管理决策（新版）：决策简报、Skill运行、建议追踪接口。

与旧 /api/admin/ai/experts 并存；新链路全部数字由 Skill 代码产出。
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...skills import chat as decision_chat
from ...skills import config_store, llm_client, llm_config, store
from ...skills.briefing import generate_briefing
from ...skills.merger import scope_key
from ...skills.protocol import SkillContext
from ...skills.registry import get_skill, list_skills
from ..deps import (get_current_user, get_db, get_db_rw, get_v2_db,
                    require_admin)
from ..envelope import ApiError, ok
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin/ai/decision", tags=["ai-decision"])


class TrackingIn(BaseModel):
    signalId: str = Field(min_length=3, max_length=200)
    skillId: str = Field(default="", max_length=64)
    headline: str = Field(default="", max_length=500)
    entity: dict = Field(default_factory=dict)
    action: dict = Field(default_factory=dict)
    status: str = Field(pattern="^(open|in_progress|done|dismissed)$")
    assignee: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=500)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    signalId: str = Field(default="", max_length=200)
    history: list[dict] = Field(default_factory=list, max_length=12)


class SkillConfigDraftIn(BaseModel):
    override: dict = Field(default_factory=dict)
    changeReason: str = Field(min_length=2, max_length=200)


class ConfigActionIn(BaseModel):
    configId: int
    changeReason: str = Field(default="", max_length=200)


class LlmConfigIn(BaseModel):
    enabled: bool = False
    base_url: str = Field(default="", max_length=300)
    api_key: str | None = None          # None=保持原密钥，""=清除
    model: str = Field(default="", max_length=100)
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_retries: int = Field(default=1, ge=0, le=1)
    narrative_enabled: bool = True
    chat_enabled: bool = True


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _require_context(user: dict) -> dict:
    context = user.get("permission_context") or {}
    if not context.get("authorized"):
        raise ApiError("当前身份未通过权限上下文校验", code=403, status_code=403)
    return context


@router.get("/skills")
def skills(user: dict = Depends(get_current_user),
           legacy: sqlite3.Connection = Depends(get_db),
           v2: sqlite3.Connection = Depends(get_v2_db),
           rw: sqlite3.Connection = Depends(get_db_rw)):
    """Skill清单：元数据 + 数据体检 + 生效配置版本。"""
    _require_context(user)
    items = []
    for skill in list_skills():
        readiness = skill.check_readiness(legacy, v2)
        _config, version = config_store.resolve_config(rw, skill)
        items.append({
            "skill_id": skill.skill_id,
            "name": skill.name,
            "management_question": skill.management_question,
            "description": skill.description,
            "briefing_tier": skill.briefing_tier,
            "data_boundary": skill.data_boundary,
            "default_config": skill.default_config,
            "config_bounds": skill.config_bounds,
            "config_version": version,
            "data_readiness": readiness,
        })
    return ok({"items": items, "semester": CURRENT_SEMESTER})


@router.post("/skills/{skill_id}/run")
def run_skill(skill_id: str, user: dict = Depends(get_current_user),
              legacy: sqlite3.Connection = Depends(get_db),
              v2: sqlite3.Connection = Depends(get_v2_db),
              rw: sqlite3.Connection = Depends(get_db_rw)):
    """单独运行一个Skill（专题工作区数据源）。"""
    _require_context(user)
    skill = get_skill(skill_id)
    if not skill:
        raise ApiError("Skill不存在", code=404, status_code=404)
    config, version = config_store.resolve_config(rw, skill)
    ctx = SkillContext(user=user, legacy=legacy, v2=v2, config=config,
                       config_version=version, semester=CURRENT_SEMESTER)
    result = skill.run(ctx)
    return ok(result.to_dict())


@router.get("/briefing")
def briefing(user: dict = Depends(get_current_user),
             legacy: sqlite3.Connection = Depends(get_db),
             v2: sqlite3.Connection = Depends(get_v2_db),
             rw: sqlite3.Connection = Depends(get_db_rw),
             force: bool = False):
    """决策简报：指纹命中返回缓存，否则全量生成并落快照。"""
    _require_context(user)
    data = generate_briefing(user, legacy, v2, rw, CURRENT_SEMESTER,
                             force=force)
    return ok(data)


@router.get("/tracking")
def tracking_list(user: dict = Depends(get_current_user),
                  rw: sqlite3.Connection = Depends(get_db_rw)):
    """建议追踪列表（当前用户范围 + 全局）。"""
    _require_context(user)
    skey = scope_key(user)
    items = store.list_tracking(rw, skey)
    return ok({"items": items})


@router.put("/tracking")
def tracking_upsert(body: TrackingIn, user: dict = Depends(get_current_user),
                    rw: sqlite3.Connection = Depends(get_db_rw)):
    """标记/更新某信号的执行状态（一期为手动闭环）。"""
    _require_context(user)
    skey = scope_key(user)
    result = store.upsert_tracking(
        rw,
        {"signal_id": body.signalId, "skill_id": body.skillId,
         "headline": body.headline, "entity": body.entity,
         "action": body.action},
        body.status, user.get("username", ""), skey,
        assignee=body.assignee, note=body.note)
    return ok(result)


@router.get("/llm-status")
def llm_status(user: dict = Depends(get_current_user),
               rw: sqlite3.Connection = Depends(get_db_rw)):
    """LLM增强能力状态（前端据此前置提示"规则生成"口径，不暴露密钥）。"""
    _require_context(user)
    cfg = llm_config.load_config(rw)
    return ok({
        "enabled": bool(cfg.get("enabled")),
        "ready": llm_config.llm_ready(cfg),
        "narrative_enabled": bool(cfg.get("narrative_enabled")),
        "chat_enabled": bool(cfg.get("chat_enabled")),
        "model": cfg.get("model") or "",
        "base_url": cfg.get("base_url") or "",
    })


@router.post("/chat")
def chat(body: ChatIn, user: dict = Depends(get_current_user),
         legacy: sqlite3.Connection = Depends(get_db),
         v2: sqlite3.Connection = Depends(get_v2_db),
         rw: sqlite3.Connection = Depends(get_db_rw)):
    """对话编排（SSE）：meta(意图+引用) → delta(校验后文本分片) → done(结构块+追问)。

    数字防线先于流式：LLM文本先缓冲、通过数字字面量校验才下发；
    校验失败回退模板版，llm_status诚实标注（决策点D3）。
    """
    _require_context(user)
    briefing = generate_briefing(user, legacy, v2, rw, CURRENT_SEMESTER,
                                 force=False)
    cfg = llm_config.load_config(rw)

    def stream():
        try:
            routed = decision_chat.route(body.message, body.signalId, briefing)
            yield _sse("meta", {
                "intent": routed["intent"],
                "intent_label": decision_chat.INTENT_LABELS.get(routed["intent"], ""),
                "cited": routed["cited"],
            })
            result = decision_chat.answer(
                body.message, body.history, routed, briefing, cfg)
            text = result.get("text") or ""
            for i in range(0, max(len(text), 1), 24):
                yield _sse("delta", {"text": text[i:i + 24]})
            yield _sse("done", {
                "blocks": result.get("blocks") or [],
                "followups": result.get("followups") or [],
                "llm_status": result.get("llm_status", "not_used"),
            })
        except Exception:
            yield _sse("error", {"message": "对话服务暂时不可用，请稍后重试"})

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# 学校配置中心（阶段5）：仅系统管理员；配置治理口径见 config_store / llm_config
# ---------------------------------------------------------------------------

@router.get("/config/skills")
def skill_config_list(admin: dict = Depends(require_admin),
                      rw: sqlite3.Connection = Depends(get_db_rw)):
    """全部Skill的默认值、可覆写边界、生效覆写与版本链。"""
    items = []
    for skill in list_skills():
        override, version = config_store.active_override(rw, skill.skill_id)
        config, _ = config_store.resolve_config(rw, skill)
        items.append({
            "skill_id": skill.skill_id,
            "name": skill.name,
            "management_question": skill.management_question,
            "description": skill.description,
            "default_config": skill.default_config,
            "config_bounds": skill.config_bounds,
            "active_config": config,
            "active_override": override,
            "config_version": version,
            "versions": config_store.list_versions(rw, skill.skill_id),
        })
    return ok({"items": items})


@router.post("/config/skills/{skill_id}/draft")
def skill_config_draft(skill_id: str, body: SkillConfigDraftIn,
                       admin: dict = Depends(require_admin),
                       rw: sqlite3.Connection = Depends(get_db_rw)):
    """创建学校覆写草稿（按 config_bounds 白名单校验，公式与数据来源不可覆写）。"""
    skill = get_skill(skill_id)
    if not skill:
        raise ApiError("Skill不存在", code=404, status_code=404)
    try:
        result = config_store.create_draft(
            rw, skill, body.override, body.changeReason,
            admin.get("username", ""))
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    rw.commit()
    return ok(result)


@router.post("/config/skills/{skill_id}/publish")
def skill_config_publish(skill_id: str, body: ConfigActionIn,
                         admin: dict = Depends(require_admin),
                         rw: sqlite3.Connection = Depends(get_db_rw)):
    """发布草稿：先生效后旧版自动退役。"""
    try:
        result = config_store.publish(rw, skill_id, body.configId,
                                      admin.get("username", ""))
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    rw.commit()
    return ok(result)


@router.post("/config/skills/{skill_id}/rollback")
def skill_config_rollback(skill_id: str, body: ConfigActionIn,
                          admin: dict = Depends(require_admin),
                          rw: sqlite3.Connection = Depends(get_db_rw)):
    """回滚到任一历史版本（以其内容为蓝本生成新发布版本，保留审计链）。"""
    try:
        result = config_store.rollback(rw, skill_id, body.configId,
                                       admin.get("username", ""),
                                       body.changeReason)
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    rw.commit()
    return ok(result)


def _masked_llm(cfg: dict) -> dict:
    """LLM配置出参：密钥脱敏（只回尾部4位供辨认，不回原文）。"""
    key = cfg.get("api_key") or ""
    return {
        "enabled": bool(cfg.get("enabled")),
        "base_url": cfg.get("base_url") or "",
        "has_api_key": bool(key),
        "api_key_tail": key[-4:] if key else "",
        "model": cfg.get("model") or "",
        "timeout_seconds": cfg.get("timeout_seconds"),
        "max_retries": cfg.get("max_retries"),
        "narrative_enabled": bool(cfg.get("narrative_enabled")),
        "chat_enabled": bool(cfg.get("chat_enabled")),
        "ready": llm_config.llm_ready(cfg),
    }


@router.get("/config/llm")
def llm_config_get(admin: dict = Depends(require_admin),
                   rw: sqlite3.Connection = Depends(get_db_rw)):
    return ok(_masked_llm(llm_config.load_config(rw)))


@router.put("/config/llm")
def llm_config_put(body: LlmConfigIn, admin: dict = Depends(require_admin),
                   rw: sqlite3.Connection = Depends(get_db_rw)):
    patch = body.model_dump(exclude={"api_key"})
    if body.api_key is not None:
        patch["api_key"] = body.api_key
    saved = llm_config.save_config(rw, patch, admin.get("username", ""))
    return ok(_masked_llm(saved))


@router.post("/config/llm/test")
def llm_config_test(admin: dict = Depends(require_admin),
                    rw: sqlite3.Connection = Depends(get_db_rw)):
    """连通性测试（用已保存的配置试调一次，不要求 enabled）。"""
    cfg = llm_config.load_config(rw)
    try:
        reply = llm_client.test_connection(cfg)
    except llm_client.LLMError as exc:
        return ok({"success": False, "kind": exc.kind, "detail": exc.detail})
    return ok({"success": True, "reply": reply[:80], "model": cfg.get("model")})

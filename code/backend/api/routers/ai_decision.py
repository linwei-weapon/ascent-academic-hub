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
from ...skills import advice, config_store, llm_client, llm_config, store
from ...skills.briefing import build_signal_evidence, generate_briefing
from ...skills.protocol import SkillContext
from ...skills.registry import get_skill, list_skills
from ..deps import (get_current_user, get_db, get_db_rw, get_v2_db,
                    require_admin)
from ..envelope import ApiError, ok
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin/ai/decision", tags=["ai-decision"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    signalId: str = Field(default="", max_length=200)
    history: list[dict] = Field(default_factory=list, max_length=12)


class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    session_id: int | None = None
    signalId: str = Field(default="", max_length=200)


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


# ---------------------------------------------------------------------------
# 专家问策（产品终稿 R4）：每个 Skill 专家一个对话入口，纯对话、不产生办理动作
# ---------------------------------------------------------------------------

@router.get("/ask/experts")
def ask_experts(user: dict = Depends(get_current_user),
                legacy: sqlite3.Connection = Depends(get_db),
                v2: sqlite3.Connection = Depends(get_v2_db),
                rw: sqlite3.Connection = Depends(get_db_rw)):
    """专家库首页：专家档案 + 今日最关键一条 + 示例问法（取自当前用户简报）。"""
    _require_context(user)
    data = generate_briefing(user, legacy, v2, rw, CURRENT_SEMESTER,
                             force=False)
    return ok({"items": advice.expert_list(data)})


@router.post("/ask/{skill_id}")
def ask_skill(skill_id: str, body: AskIn,
              user: dict = Depends(get_current_user),
              legacy: sqlite3.Connection = Depends(get_db),
              v2: sqlite3.Connection = Depends(get_v2_db),
              rw: sqlite3.Connection = Depends(get_db_rw)):
    """专家问策（SSE）：meta(意图+证据编号) → delta(文本分片) → done(结构块+推荐问法)。

    会话落库：按用户+专家隔离；history 由服务端会话重建，客户端无需上传。
    """
    _require_context(user)
    skill = get_skill(skill_id)
    if not skill:
        raise ApiError("专家不存在", code=404, status_code=404)

    username = user.get("username", "")
    session_id = body.session_id
    if session_id is not None:
        if not store.get_session(rw, session_id, username):
            raise ApiError("会话不存在", code=404, status_code=404)
    else:
        session_id = store.create_session(
            rw, username, skill_id, title=body.message[:30],
            context_signal_id=body.signalId)

    briefing = generate_briefing(user, legacy, v2, rw, CURRENT_SEMESTER,
                                 force=False)
    cfg = llm_config.load_config(rw)
    # 服务端重建对话历史（本专家会话内）
    history = [{"role": m["role"], "content": m["content"]}
               for m in store.list_messages(rw, session_id)][-12:]
    store.append_message(rw, session_id, "user", body.message)
    rw.commit()

    sid = session_id

    def stream():
        # 注意：SSE 流在端点返回后才执行，此时请求级连接已关闭；
        # 会话落库必须使用流内独立开启的连接。
        from ..db import get_conn_rw
        rw2 = get_conn_rw()
        try:
            result = advice.ask(body.message, skill_id, body.signalId,
                                history, briefing, cfg)
            yield _sse("meta", {
                "session_id": sid,
                "intent": result.get("intent"),
                "intent_label": result.get("intent_label", ""),
                "evidence_refs": result.get("evidence_refs", []),
                "redirect": result.get("redirect"),
            })
            text = result.get("text") or ""
            for i in range(0, max(len(text), 1), 24):
                yield _sse("delta", {"text": text[i:i + 24]})
            store.append_message(rw2, sid, "assistant", text, {
                "blocks": result.get("blocks") or [],
                "evidence_refs": result.get("evidence_refs", []),
                "suggested_questions": result.get("suggested_questions") or [],
                "boundary": result.get("boundary", ""),
                "intent": result.get("intent"),
                "redirect": result.get("redirect"),
                "llm_status": result.get("llm_status", "not_used"),
            })
            store.touch_session(rw2, sid)
            rw2.commit()
            yield _sse("done", {
                "session_id": sid,
                "blocks": result.get("blocks") or [],
                "suggested_questions": result.get("suggested_questions") or [],
                "boundary": result.get("boundary", ""),
                "redirect": result.get("redirect"),
                "llm_status": result.get("llm_status", "not_used"),
            })
        except Exception:
            yield _sse("error", {"message": "问策服务暂时不可用，请稍后重试"})
        finally:
            rw2.close()

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/ask/sessions")
def ask_sessions(user: dict = Depends(get_current_user),
                 skill_id: str = "",
                 rw: sqlite3.Connection = Depends(get_db_rw)):
    """问策历史会话列表（当前用户；可按专家过滤）。"""
    _require_context(user)
    items = store.list_sessions(rw, user.get("username", ""), skill_id)
    return ok({"items": items})


@router.get("/ask/sessions/{session_id}")
def ask_session_detail(session_id: int,
                       user: dict = Depends(get_current_user),
                       rw: sqlite3.Connection = Depends(get_db_rw)):
    """问策会话回放：按归属校验，他人会话一律 404。"""
    _require_context(user)
    session = store.get_session(rw, session_id, user.get("username", ""))
    if not session:
        raise ApiError("会话不存在", code=404, status_code=404)
    return ok({"session": session,
               "messages": store.list_messages(rw, session_id)})


@router.get("/signals/{signal_id}/evidence")
def signal_evidence(signal_id: str, user: dict = Depends(get_current_user),
                    legacy: sqlite3.Connection = Depends(get_db),
                    v2: sqlite3.Connection = Depends(get_v2_db),
                    rw: sqlite3.Connection = Depends(get_db_rw)):
    """单信号完整证据包：查证窗口（新开浏览器窗口）的数据源。

    走统一权限上下文与数据范围（Skill 按当前身份过滤信号）；
    信号不存在或越权均为 404，不泄露范围外信号的存在性。
    """
    _require_context(user)
    data = generate_briefing(user, legacy, v2, rw, CURRENT_SEMESTER,
                             force=False)
    pack = build_signal_evidence(data, signal_id)
    if not pack:
        raise ApiError("信号不存在或不在当前数据权限范围内",
                       code=404, status_code=404)
    return ok(pack)


@router.get("/tracking")
def tracking_list(user: dict = Depends(get_current_user)):
    """建议追踪已退役：AI决策不形成办理闭环（产品终稿 R1）。

    保留一个版本周期返回 410，避免未更新前端报错；一个周期后删除本端点。
    """
    raise ApiError("建议追踪功能已下线：AI决策不形成办理闭环",
                   code=410, status_code=410)


@router.put("/tracking")
def tracking_upsert(user: dict = Depends(get_current_user)):
    """建议追踪已退役：AI决策不形成办理闭环（产品终稿 R1）。"""
    raise ApiError("建议追踪功能已下线：AI决策不形成办理闭环",
                   code=410, status_code=410)


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
    """旧「决策追问抽屉」SSE 端点（已退役，保留一个版本周期兼容）。

    产品终稿 R4 起，对话入口统一收口到专家问策 POST /ask/{skill_id}；
    前端 ChatDrawer 已删除，本端点无消费方，一个版本周期后移除。

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

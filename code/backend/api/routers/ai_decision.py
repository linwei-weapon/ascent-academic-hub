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
from ...skills.briefing import (build_signal_detail, build_signal_evidence,
                                generate_briefing)
from ...skills.protocol import SkillContext
from ...skills.registry import get_skill, list_skills
from ..deps import (get_current_user, get_db, get_db_rw, get_v2_db,
                    require_admin)
from ..envelope import ApiError, ok
from ..security_governance import write_audit
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
    schemeName: str = Field(default="", max_length=80)
    roleIds: list[str] = Field(default_factory=list, max_length=12)


class ConfigActionIn(BaseModel):
    configId: int
    changeReason: str = Field(default="", max_length=200)


class SchemeImportIn(BaseModel):
    package: dict
    changeReason: str = Field(min_length=2, max_length=200)


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
        _config, version = config_store.resolve_config(
            rw, skill, user.get("role_id")
        )
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
    config, version = config_store.resolve_config(
        rw, skill, user.get("role_id")
    )
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


@router.get("/signals/{signal_id}/detail")
def signal_detail(signal_id: str, fact: str = "",
                  user: dict = Depends(get_current_user),
                  legacy: sqlite3.Connection = Depends(get_db),
                  v2: sqlite3.Connection = Depends(get_v2_db),
                  rw: sqlite3.Connection = Depends(get_db_rw)):
    """数据要素明细清单：点击数字直达该数字代表的业务明细（新开标签页数据源）。

    权限语义与证据包一致：明细行来自 Skill 按当前身份数据范围预计算的
    信号 context，本端点不接受任何客户端筛选参数，越权信号一律 404。
    聚合/判定类数字（无明细语义）返回 400，前端不应为其提供点击入口。
    """
    _require_context(user)
    if not fact:
        raise ApiError("缺少数据要素参数 fact", code=400, status_code=400)
    data = generate_briefing(user, legacy, v2, rw, CURRENT_SEMESTER,
                             force=False)
    detail = build_signal_detail(data, signal_id, fact)
    if detail is None:
        raise ApiError("信号不存在或不在当前数据权限范围内",
                       code=404, status_code=404)
    if not detail.get("drillable"):
        raise ApiError("该数据为聚合/判定值，无明细清单",
                       code=400, status_code=400)
    return ok(detail)


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
                      rw: sqlite3.Connection = Depends(get_db_rw),
                      legacy: sqlite3.Connection = Depends(get_db),
                      v2: sqlite3.Connection = Depends(get_v2_db)):
    """学校分析方案工作台：产品模板、生效方案、草稿与版本链。"""
    items = []
    for skill in list_skills():
        override, version = config_store.active_override(rw, skill.skill_id)
        config, _ = config_store.resolve_config(rw, skill)
        active = config_store.active_metadata(rw, skill.skill_id)
        versions = config_store.list_versions(rw, skill.skill_id)
        items.append({
            "skill_id": skill.skill_id,
            "name": skill.name,
            "management_question": skill.management_question,
            "description": skill.description,
            "briefing_tier": skill.briefing_tier,
            "data_boundary": skill.data_boundary,
            "default_config": skill.default_config,
            "config_bounds": skill.config_bounds,
            "active_config": config,
            "active_override": override,
            "config_version": version,
            "active_scheme": active,
            "versions": versions,
            "data_readiness": skill.check_readiness(legacy, v2),
        })
    versions = [version for item in items for version in item["versions"]]
    llm_status = _masked_llm(llm_config.load_config(rw))
    return ok({
        "items": items,
        "summary": {
            "templates": len(items),
            "schoolActive": sum(
                1 for item in items if item["active_scheme"]
            ),
            "drafts": sum(
                1 for row in versions if row["status"] == "draft"
            ),
            "attention": sum(
                1 for item in items
                if not item["data_readiness"].get("ready")
            ) + sum(
                1 for row in versions
                if row["status"] == "draft"
                and row["test_status"] != "passed"
            ),
        },
        "roleIds": config_store.ANALYSIS_ROLE_IDS,
        "llm": {
            "enabled": llm_status["enabled"],
            "ready": llm_status["ready"],
            "model": llm_status["model"],
        },
        "boundary": (
            "学校方案只调整已登记的管理参数和适用角色；"
            "不改变正式指标公式，不保存组织数据范围，不扩大用户权限。"
        ),
    })


@router.get("/config/skills/{skill_id}/export/{config_id}")
def skill_config_export(
        skill_id: str, config_id: int,
        admin: dict = Depends(require_admin),
        rw: sqlite3.Connection = Depends(get_db_rw)):
    """导出不含业务数据和密钥的学校分析方案包。"""
    skill = get_skill(skill_id)
    row = config_store.get_version(rw, skill_id, config_id)
    if not skill or not row:
        raise ApiError("分析方案不存在", code=404, status_code=404)
    package = {
        "schema": "analysis-scheme/1.0",
        "skillId": skill_id,
        "skillName": skill.name,
        "schemeName": row["scheme_name"],
        "sourceVersion": row["version_no"],
        "baseProtocolVersion": row["base_protocol_version"],
        "override": row["config"],
        "roleIds": row["roleIds"],
        "boundary": (
            "方案包不包含学生、教师、成绩、组织范围或模型密钥；"
            "导入后必须重新执行数据检查和影响预览。"
        ),
    }
    write_audit(
        rw, admin.get("username", ""), "ai.analysis_scheme.export",
        "ai_skill_config", str(config_id), detail={
            "skillId": skill_id, "version": row["version_no"],
        },
    )
    rw.commit()
    return ok(package)


@router.post("/config/schemes/import")
def skill_config_import(
        body: SchemeImportIn, admin: dict = Depends(require_admin),
        rw: sqlite3.Connection = Depends(get_db_rw)):
    """导入方案包为新草稿；导入不会直接发布。"""
    package = body.package or {}
    if package.get("schema") != "analysis-scheme/1.0":
        raise ApiError("不支持的分析方案包版本", code=400, status_code=400)
    skill_id = str(package.get("skillId") or "")
    skill = get_skill(skill_id)
    if not skill:
        raise ApiError("方案包引用的分析模板不存在",
                       code=400, status_code=400)
    try:
        result = config_store.create_draft(
            rw, skill, package.get("override") or {}, body.changeReason,
            admin.get("username", ""),
            str(package.get("schemeName") or f"{skill.name}导入方案"),
            package.get("roleIds") or config_store.ANALYSIS_ROLE_IDS,
        )
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    write_audit(
        rw, admin.get("username", ""), "ai.analysis_scheme.import",
        "ai_skill_config", str(result["configId"]), detail={
            "skillId": skill_id, "sourceVersion": package.get("sourceVersion"),
            "changeReason": body.changeReason,
        },
    )
    rw.commit()
    return ok(result, msg="方案包已导入为草稿，发布前必须重新检查")


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
            admin.get("username", ""), body.schemeName,
            body.roleIds or config_store.ANALYSIS_ROLE_IDS)
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    write_audit(
        rw, admin.get("username", ""), "ai.analysis_scheme.create",
        "ai_skill_config", str(result["configId"]), detail={
            "skillId": skill_id, "schemeName": result["schemeName"],
            "version": result["version"], "roleIds": result["roleIds"],
            "changeReason": body.changeReason,
        },
    )
    rw.commit()
    return ok(result)


@router.put("/config/skills/{skill_id}/draft/{config_id}")
def skill_config_draft_update(
        skill_id: str, config_id: int, body: SkillConfigDraftIn,
        admin: dict = Depends(require_admin),
        rw: sqlite3.Connection = Depends(get_db_rw)):
    """修改草稿；任何修改都会使原发布前检查失效。"""
    skill = get_skill(skill_id)
    if not skill:
        raise ApiError("分析模板不存在", code=404, status_code=404)
    try:
        result = config_store.update_draft(
            rw, skill, config_id, body.override, body.changeReason,
            body.schemeName, body.roleIds or config_store.ANALYSIS_ROLE_IDS,
        )
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    write_audit(
        rw, admin.get("username", ""), "ai.analysis_scheme.update",
        "ai_skill_config", str(config_id), detail={
            "skillId": skill_id, "roleIds": result["roleIds"],
            "changeReason": body.changeReason,
        },
    )
    rw.commit()
    return ok(result)


def _severity_count(result) -> dict:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for signal in result.signals:
        if signal.severity in counts:
            counts[signal.severity] += 1
    return counts


@router.post("/config/skills/{skill_id}/test/{config_id}")
def skill_config_test(
        skill_id: str, config_id: int,
        admin: dict = Depends(require_admin),
        legacy: sqlite3.Connection = Depends(get_db),
        v2: sqlite3.Connection = Depends(get_v2_db),
        rw: sqlite3.Connection = Depends(get_db_rw)):
    """发布前检查：参数、数据、角色、协议和当前学校数据试运行。"""
    skill = get_skill(skill_id)
    if not skill:
        raise ApiError("分析模板不存在", code=404, status_code=404)
    row = config_store.get_version(rw, skill_id, config_id)
    if not row:
        raise ApiError("分析方案草稿不存在", code=404, status_code=404)
    if row["status"] != "draft":
        raise ApiError("只有草稿方案需要发布前检查",
                       code=409, status_code=409)

    parameter_errors = skill.validate_override(row["config"])
    readiness = skill.check_readiness(legacy, v2)
    invalid_roles = [
        role_id for role_id in row["roleIds"]
        if role_id not in config_store.ANALYSIS_ROLE_IDS
    ]
    checks = {
        "parameterBoundary": not parameter_errors,
        "dataReadiness": bool(readiness.get("ready")),
        "roleBoundary": bool(row["roleIds"]) and not invalid_roles,
        "protocolCurrent": (
            row["base_protocol_version"] == "decision-skill/1.0"
        ),
        "sampleRun": False,
    }
    issues = list(parameter_errors)
    issues.extend(
        f"缺少必需数据表：{table}"
        for table in readiness.get("missing_required", [])
    )
    if invalid_roles:
        issues.append("存在不适用角色：" + "、".join(invalid_roles))
    if not checks["protocolCurrent"]:
        issues.append("草稿基于旧分析协议，需要重新生成")

    impact = {
        "available": False, "currentSignals": 0, "draftSignals": 0,
        "signalDelta": 0, "currentHighPriority": 0,
        "draftHighPriority": 0, "highPriorityDelta": 0,
        "newSignalIds": [], "removedSignalIds": [],
    }
    can_run = all(
        checks[key] for key in (
            "parameterBoundary", "dataReadiness",
            "roleBoundary", "protocolCurrent",
        )
    )
    if can_run:
        try:
            current_config, current_version = config_store.resolve_config(
                rw, skill, admin.get("role_id")
            )
            draft_config = dict(skill.default_config)
            draft_config.update(row["config"])
            current_result = skill.run(SkillContext(
                user=admin, legacy=legacy, v2=v2,
                config=current_config, config_version=current_version,
                semester=CURRENT_SEMESTER,
            ))
            draft_result = skill.run(SkillContext(
                user=admin, legacy=legacy, v2=v2,
                config=draft_config, config_version=row["version_no"],
                semester=CURRENT_SEMESTER,
            ))
            current_ids = {signal.signal_id for signal in current_result.signals}
            draft_ids = {signal.signal_id for signal in draft_result.signals}
            current_severity = _severity_count(current_result)
            draft_severity = _severity_count(draft_result)
            current_high = (
                current_severity["critical"] + current_severity["high"]
            )
            draft_high = (
                draft_severity["critical"] + draft_severity["high"]
            )
            impact = {
                "available": True,
                "currentSignals": len(current_ids),
                "draftSignals": len(draft_ids),
                "signalDelta": len(draft_ids) - len(current_ids),
                "currentHighPriority": current_high,
                "draftHighPriority": draft_high,
                "highPriorityDelta": draft_high - current_high,
                "newSignalIds": sorted(draft_ids - current_ids)[:10],
                "removedSignalIds": sorted(current_ids - draft_ids)[:10],
            }
            checks["sampleRun"] = True
        except Exception as exc:
            issues.append(f"当前学校数据试运行失败：{exc}")

    passed = all(checks.values())
    result = {
        "configId": config_id, "skillId": skill_id, "passed": passed,
        "checks": checks, "issues": issues, "readiness": readiness,
        "impact": impact, "testedVersion": row["version_no"],
        "testedScope": "当前系统管理员的全校业务数据权限",
        "boundary": "结果变化仅用于发布影响核查，不形成业务审批结论。",
    }
    try:
        saved = config_store.save_test_result(
            rw, skill_id, config_id, result, admin.get("username", "")
        )
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    write_audit(
        rw, admin.get("username", ""), "ai.analysis_scheme.test",
        "ai_skill_config", str(config_id),
        result="success" if passed else "failed",
        detail={
            "skillId": skill_id, "checks": checks,
            "issues": issues, "impact": impact,
        },
    )
    rw.commit()
    result.update(saved)
    return ok(result)


@router.post("/config/skills/{skill_id}/publish")
def skill_config_publish(skill_id: str, body: ConfigActionIn,
                         admin: dict = Depends(require_admin),
                         rw: sqlite3.Connection = Depends(get_db_rw)):
    """发布草稿：先生效后旧版自动退役。"""
    try:
        result = config_store.publish(rw, skill_id, body.configId,
                                      admin.get("username", ""),
                                      require_test=True)
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    write_audit(
        rw, admin.get("username", ""), "ai.analysis_scheme.publish",
        "ai_skill_config", str(body.configId), detail={
            "skillId": skill_id, "version": result["version"],
        },
    )
    rw.commit()
    return ok(result)


@router.post("/config/skills/{skill_id}/retire")
def skill_config_retire(skill_id: str, body: ConfigActionIn,
                        admin: dict = Depends(require_admin),
                        rw: sqlite3.Connection = Depends(get_db_rw)):
    """停用学校方案后，相关角色立即回退产品默认方案。"""
    try:
        result = config_store.retire(rw, skill_id, body.configId)
    except ValueError as exc:
        raise ApiError(str(exc), code=400, status_code=400)
    write_audit(
        rw, admin.get("username", ""), "ai.analysis_scheme.retire",
        "ai_skill_config", str(body.configId), detail={
            "skillId": skill_id, "version": result["version"],
            "changeReason": body.changeReason,
        },
    )
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
    write_audit(
        rw, admin.get("username", ""), "ai.analysis_scheme.rollback",
        "ai_skill_config", str(result["configId"]), detail={
            "skillId": skill_id, "sourceConfigId": body.configId,
            "version": result["version"], "changeReason": body.changeReason,
        },
    )
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

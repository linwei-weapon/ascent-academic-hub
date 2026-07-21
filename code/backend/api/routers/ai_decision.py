"""AI管理决策（新版）：决策简报、Skill运行、建议追踪接口。

与旧 /api/admin/ai/experts 并存；新链路全部数字由 Skill 代码产出。
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...skills import config_store, store
from ...skills.briefing import generate_briefing
from ...skills.merger import scope_key
from ...skills.protocol import SkillContext
from ...skills.registry import get_skill, list_skills
from ..deps import get_current_user, get_db, get_db_rw, get_v2_db
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

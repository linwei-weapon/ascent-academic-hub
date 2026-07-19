"""管理专家协议、学校配置版本与运行上下文接口。"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...ai_experts import (
    EXPERT_PROTOCOL_VERSION,
    apply_school_override,
    get_expert,
    list_experts,
    validate_expert_definition,
    validate_school_override,
)
from .. import db as dbm
from ..deps import get_current_user, get_db_rw, get_v2_db, require_admin
from ..envelope import ApiError, ok
from ..security_governance import write_audit
from ..settings import CURRENT_SEMESTER


router = APIRouter(prefix="/api/admin/ai/experts", tags=["ai-experts"])

EXPERT_CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS sys_ai_expert_version (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id TEXT NOT NULL,
    version_no TEXT NOT NULL,
    base_definition_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','published','retired')),
    override_json TEXT NOT NULL DEFAULT '{}',
    change_reason TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'override',
    source_version_id INTEGER,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT,
    UNIQUE(expert_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_ai_expert_version_lookup
ON sys_ai_expert_version(expert_id,status,version_id);
CREATE TABLE IF NOT EXISTS sys_ai_analysis_scheme (
    scheme_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id TEXT NOT NULL,
    name TEXT NOT NULL,
    expert_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','published','retired')),
    parameters_json TEXT NOT NULL,
    scope_policy_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_scheme_lookup
ON sys_ai_analysis_scheme(expert_id,status,scheme_id);
"""


class ExpertOverrideIn(BaseModel):
    baseVersion: str
    override: dict[str, Any] = Field(default_factory=dict)
    changeReason: str = Field(min_length=2, max_length=300)


class ExpertInterpretIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    scopeFingerprint: str
    currentParameters: dict[str, Any] = Field(default_factory=dict)
    semester: str | None = None


class AnalysisSchemeIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)
    changeReason: str = Field(default="基于研判会话保存", min_length=2, max_length=300)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _ensure_tables(conn: sqlite3.Connection) -> None:
    for statement in EXPERT_CONFIG_DDL.split(";"):
        if statement.strip():
            conn.execute(statement)


def _require_expert(expert_id: str, role_id: str | None = None) -> dict:
    expert = get_expert(expert_id)
    if not expert:
        raise ApiError("管理专家不存在", code=404, status_code=404)
    errors = validate_expert_definition(expert)
    if errors:
        raise ApiError("管理专家协议无效：" + "；".join(errors), code=500, status_code=500)
    if role_id and role_id not in expert["applicableRoles"]:
        raise ApiError("当前工作身份不适用该管理专家", code=403, status_code=403)
    return expert


def _active_version(conn: sqlite3.Connection, expert_id: str) -> dict | None:
    _ensure_tables(conn)
    return dbm.query_one(conn, """
        SELECT * FROM sys_ai_expert_version
        WHERE expert_id=? AND status='published'
        ORDER BY version_id DESC LIMIT 1
    """, (expert_id,))


def _decode_override(row: dict | None) -> dict:
    if not row:
        return {}
    try:
        value = json.loads(row.get("override_json") or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def resolve_effective_expert(conn: sqlite3.Connection, expert: dict) -> tuple[dict, dict]:
    active = _active_version(conn, expert["expertId"])
    effective = apply_school_override(expert, _decode_override(active))
    effective["effectiveVersion"] = active["version_no"] if active else expert["version"]
    effective["productDefinitionVersion"] = expert["version"]
    version_meta = {
        "versionId": active["version_id"] if active else None,
        "version": effective["effectiveVersion"],
        "status": active["status"] if active else "product_default",
        "source": "school_override" if active else "product_default",
        "publishedAt": active.get("published_at") if active else None,
    }
    return effective, version_meta


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(dbm.query_one(
        conn, "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (table,),
    ))


def _data_readiness(expert: dict, legacy: sqlite3.Connection,
                    v2: sqlite3.Connection) -> dict:
    items = []
    missing_required = []
    for requirement in expert.get("dataRequirements") or []:
        conn = v2 if requirement["database"] == "v2" else legacy
        available = _table_exists(conn, requirement["source"])
        row = {**requirement, "available": available}
        items.append(row)
        if requirement.get("required") and not available:
            missing_required.append(requirement["source"])
    return {
        "ready": not missing_required,
        "missingRequired": missing_required,
        "items": items,
        "boundary": "这里只核查数据表是否接入；字段完整率与业务正确性仍须由专家规则和页面证据继续验证。",
    }


def _scope_context(user: dict) -> dict:
    context = user.get("permission_context") or {}
    detail = context.get("detailScope") or {}
    return {
        "activeIdentityId": context.get("activeIdentityId"),
        "role": context.get("activeRole") or user.get("role_id"),
        "roleName": context.get("activeRoleName"),
        "scopeType": detail.get("type") or "denied",
        "scopeIds": detail.get("sourceScopeIds") or [],
        "scopeFingerprint": context.get("scopeFingerprint"),
        "authorized": bool(context.get("authorized")),
        "naturalLanguageMayExpandScope": False,
    }


def _summary(expert: dict, version: dict) -> dict:
    return {
        "expertId": expert["expertId"],
        "name": expert["name"],
        "description": expert["description"],
        "managementQuestion": expert["managementQuestion"],
        "owners": expert["owners"],
        "version": version,
        "recommendedQuestions": expert["recommendedQuestions"],
        "simulatorEnabled": bool((expert.get("simulator") or {}).get("enabled")),
        "simulatorScenario": (expert.get("simulator") or {}).get("scenario"),
        "configurationSource": expert.get("configurationSource"),
    }


def _bounded_number(spec: dict, raw: str) -> int | float:
    value: int | float = float(raw) if spec.get("type") == "number" else int(raw)
    if spec.get("min") is not None:
        value = max(value, spec["min"])
    if spec.get("max") is not None:
        value = min(value, spec["max"])
    return value


def _interpret_parameters(expert: dict, message: str) -> tuple[dict, list[str]]:
    parameters = expert.get("parameters") or {}
    changes: dict[str, Any] = {}
    matched: list[str] = []
    patterns = {
        "addedClasses": [r"(?:新增|增加|开设)\s*(\d+)\s*个?班"],
        "classCapacity": [r"(?:每班|单班|班容量)\s*(\d+)\s*人"],
        "availableTeachers": [
            r"(?:可协调|安排|增加)?\s*(\d+)\s*名?(?:备份)?教师",
            r"(?:可协调)?(?:备份)?教师(?:改为|为|增加到)?\s*(\d+)\s*名?",
        ],
        "supportCourseLimit": [r"(?:支持|优先看|选择)\s*(\d+)\s*门(?:课程)?"],
        "significantChangePp": [r"(?:波动|变化|差异)(?:阈值)?(?:改为|超过|达到)?\s*(\d+(?:\.\d+)?)\s*个?百分点"],
        "minimumStudents": [r"(?:覆盖|影响)(?:至少|超过|达到)?\s*(\d+)\s*人"],
    }
    for key, regexes in patterns.items():
        if key not in parameters:
            continue
        for pattern in regexes:
            found = re.search(pattern, message)
            if found:
                changes[key] = _bounded_number(parameters[key], found.group(1))
                matched.append(key)
                break
    if "priorityFocus" in parameters:
        if "明确未通过" in message or "挂科" in message:
            changes["priorityFocus"] = "failed"
            matched.append("priorityFocus")
        elif "待核验" in message or "缺证据" in message or "认定" in message:
            changes["priorityFocus"] = "verification"
            matched.append("priorityFocus")
        elif "均衡" in message or "综合" in message:
            changes["priorityFocus"] = "balanced"
            matched.append("priorityFocus")
    return changes, matched


@router.get("")
def expert_catalog(conn: sqlite3.Connection = Depends(get_db_rw),
                   user: dict = Depends(get_current_user)):
    rows = []
    for expert in list_experts(user["role_id"]):
        effective, version = resolve_effective_expert(conn, expert)
        rows.append(_summary(effective, version))
    return ok({
        "protocolVersion": EXPERT_PROTOCOL_VERSION,
        "scope": _scope_context(user),
        "experts": rows,
    })


@router.get("/{expert_id}")
def expert_detail(expert_id: str,
                  conn: sqlite3.Connection = Depends(get_db_rw),
                  v2: sqlite3.Connection = Depends(get_v2_db),
                  user: dict = Depends(get_current_user)):
    expert = _require_expert(expert_id, user["role_id"])
    effective, version = resolve_effective_expert(conn, expert)
    return ok({
        "protocolVersion": EXPERT_PROTOCOL_VERSION,
        "expert": effective,
        "version": version,
        "scope": _scope_context(user),
        "dataReadiness": _data_readiness(effective, conn, v2),
    })


@router.get("/{expert_id}/runtime")
def expert_runtime(expert_id: str, semester: str = CURRENT_SEMESTER,
                   conn: sqlite3.Connection = Depends(get_db_rw),
                   v2: sqlite3.Connection = Depends(get_v2_db),
                   user: dict = Depends(get_current_user)):
    expert = _require_expert(expert_id, user["role_id"])
    effective, version = resolve_effective_expert(conn, expert)
    scope = _scope_context(user)
    if not scope["authorized"]:
        raise ApiError("当前工作身份没有有效数据范围", code=403, status_code=403)
    return ok({
        "expertId": expert_id,
        "expertName": effective["name"],
        "expertVersion": version["version"],
        "semester": semester,
        "scope": scope,
        "dataReadiness": _data_readiness(effective, conn, v2),
        "parameters": {
            key: {"value": spec.get("default"), **spec}
            for key, spec in effective["parameters"].items()
        },
        "recommendedQuestions": effective["recommendedQuestions"],
        "outputs": effective["outputs"],
        "cacheContext": {
            "scopeFingerprint": scope["scopeFingerprint"],
            "role": scope["role"],
            "expertVersion": version["version"],
            "parameterVersion": version["version"],
            "keyParts": ["scopeFingerprint", "role", "expertVersion", "parameterVersion", "semester"],
        },
        "sessionBoundary": {
            "temporaryAdjustmentsChangeOfficialDefinition": False,
            "identitySwitchInvalidatesSession": True,
            "naturalLanguageMayExpandScope": False,
        },
    })


@router.post("/{expert_id}/interpret")
def interpret_expert_message(expert_id: str, body: ExpertInterpretIn,
                             conn: sqlite3.Connection = Depends(get_db_rw),
                             user: dict = Depends(get_current_user)):
    expert = _require_expert(expert_id, user["role_id"])
    effective, version = resolve_effective_expert(conn, expert)
    scope = _scope_context(user)
    if not scope["authorized"]:
        raise ApiError("当前工作身份没有有效数据范围", code=403, status_code=403)
    if not body.scopeFingerprint or body.scopeFingerprint != scope["scopeFingerprint"]:
        raise ApiError("工作身份或数据范围已变化，请重新开始研判", code=409, status_code=409)

    message = body.message.strip()
    reset = any(word in message for word in ("恢复正式口径", "清除临时条件", "恢复默认"))
    scope_terms = ("全校", "其他学院", "全部学院", "跨学院全部学生")
    requested_expansion = any(term in message for term in scope_terms)
    blocked_expansion = requested_expansion and scope["scopeType"] != "all"
    changes, matched = _interpret_parameters(effective, message)
    if reset:
        changes = {
            key: spec.get("default")
            for key, spec in effective["parameters"].items()
        }
        matched = list(changes)

    if blocked_expansion:
        response = (
            "已保留当前授权范围，不能通过对话切换到全校或其他学院。"
            "你仍可在本学院范围内调整下列临时参数。"
        )
    elif reset:
        response = "已恢复该专家当前发布版本的正式默认参数；本次会话中的临时调整已清除。"
    elif changes:
        response = (
            f"我理解你希望临时调整 {len(changes)} 个条件。"
            "这些条件只影响本次研判，重新计算后仍需查看事实证据。"
        )
    else:
        response = (
            "我没有识别到可执行的参数调整。可以直接选择下方推荐问题，"
            "或说明可用班级、班容量、教师数量和关注重点。"
        )
    return ok({
        "expertId": expert_id,
        "expertVersion": version["version"],
        "message": message,
        "understood": bool(changes) or reset,
        "response": response,
        "parameterChanges": changes,
        "matchedParameters": matched,
        "resetToOfficial": reset,
        "scopeRequest": {
            "requestedExpansion": requested_expansion,
            "blocked": blocked_expansion,
            "effectiveScopeType": scope["scopeType"],
            "effectiveScopeIds": scope["scopeIds"],
            "message": "自然语言不能扩大组织或学生范围。",
        },
        "temporaryOnly": True,
        "officialDefinitionChanged": False,
        "recalculate": bool(changes),
        "recommendedQuestions": effective["recommendedQuestions"],
        "traceability": {
            "expertVersion": version["version"],
            "scopeFingerprint": scope["scopeFingerprint"],
            "semester": body.semester or CURRENT_SEMESTER,
            "interpretationMethod": "专家参数词典与边界规则",
            "boundary": "本接口只解释允许的临时参数；正式指标由业务接口计算，LLM不直接计算。",
        },
    })


@router.get("/{expert_id}/schemes")
def list_analysis_schemes(expert_id: str,
                          conn: sqlite3.Connection = Depends(get_db_rw),
                          user: dict = Depends(get_current_user)):
    _require_expert(expert_id, user["role_id"])
    _ensure_tables(conn)
    can_manage = "system.manage" in set(
        (user.get("permission_context") or {}).get("actionPermissions") or []
    )
    status_where = "" if can_manage else " AND status='published'"
    rows = dbm.query(conn, f"""
        SELECT scheme_id,expert_id,name,expert_version,status,parameters_json,
               scope_policy_json,created_by,created_at,published_by,published_at
        FROM sys_ai_analysis_scheme
        WHERE expert_id=? {status_where}
        ORDER BY CASE status WHEN 'published' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
                 scheme_id DESC
    """, (expert_id,))
    for row in rows:
        row["parameters"] = json.loads(row.pop("parameters_json") or "{}")
        row["scopePolicy"] = json.loads(row.pop("scope_policy_json") or "{}")
    return ok(rows)


@router.post("/{expert_id}/schemes")
def create_analysis_scheme(expert_id: str, body: AnalysisSchemeIn,
                           admin: dict = Depends(require_admin),
                           conn: sqlite3.Connection = Depends(get_db_rw)):
    expert = _require_expert(expert_id)
    effective, version = resolve_effective_expert(conn, expert)
    errors = validate_school_override(
        effective, {"parameterDefaults": body.parameters}
    )
    if errors:
        raise ApiError("分析方案参数无效：" + "；".join(errors), code=400, status_code=400)
    _ensure_tables(conn)
    now = _now()
    cursor = conn.execute("""
        INSERT INTO sys_ai_analysis_scheme(
            expert_id,name,expert_version,status,parameters_json,
            scope_policy_json,created_by,created_at
        ) VALUES (?,?,?,?,?,?,?,?)
    """, (
        expert_id, body.name.strip(), version["version"], "draft",
        json.dumps(body.parameters, ensure_ascii=False, sort_keys=True),
        json.dumps({
            "mode": "runtime_permission",
            "naturalLanguageMayExpandScope": False,
            "description": "运行时始终使用当前工作身份的数据权限，方案本身不保存越权组织范围。",
        }, ensure_ascii=False, sort_keys=True),
        admin["username"], now,
    ))
    write_audit(
        conn, admin["username"], "ai.analysis_scheme.create", "ai_analysis_scheme",
        str(cursor.lastrowid), detail={
            "expertId": expert_id,
            "expertVersion": version["version"],
            "changeReason": body.changeReason,
        },
    )
    return ok({
        "schemeId": cursor.lastrowid,
        "status": "draft",
        "expertId": expert_id,
        "expertVersion": version["version"],
    }, msg="学校分析方案草稿已保存，发布后才会成为正式方案")


@router.post("/{expert_id}/schemes/{scheme_id}/publish")
def publish_analysis_scheme(expert_id: str, scheme_id: int,
                            admin: dict = Depends(require_admin),
                            conn: sqlite3.Connection = Depends(get_db_rw)):
    expert = _require_expert(expert_id)
    _ensure_tables(conn)
    row = dbm.query_one(conn, """
        SELECT * FROM sys_ai_analysis_scheme
        WHERE scheme_id=? AND expert_id=?
    """, (scheme_id, expert_id))
    if not row:
        raise ApiError("分析方案不存在", code=404, status_code=404)
    if row["status"] != "draft":
        raise ApiError("只有草稿方案可以发布", code=409, status_code=409)
    _, current_version = resolve_effective_expert(conn, expert)
    if row["expert_version"] != current_version["version"]:
        raise ApiError("专家版本已变化，请用当前版本重新保存方案", code=409, status_code=409)
    now = _now()
    conn.execute("""
        UPDATE sys_ai_analysis_scheme SET status='published',
               published_by=?,published_at=? WHERE scheme_id=?
    """, (admin["username"], now, scheme_id))
    write_audit(
        conn, admin["username"], "ai.analysis_scheme.publish", "ai_analysis_scheme",
        str(scheme_id), detail={"expertId": expert_id, "expertVersion": row["expert_version"]},
    )
    return ok({"schemeId": scheme_id, "status": "published"},
              msg="学校分析方案已发布")


@router.get("/{expert_id}/versions")
def expert_versions(expert_id: str,
                    conn: sqlite3.Connection = Depends(get_db_rw),
                    user: dict = Depends(get_current_user)):
    _require_expert(expert_id, user["role_id"])
    _ensure_tables(conn)
    rows = dbm.query(conn, """
        SELECT version_id,expert_id,version_no,base_definition_version,status,
               change_reason,action,source_version_id,created_by,created_at,
               published_by,published_at
        FROM sys_ai_expert_version WHERE expert_id=?
        ORDER BY version_id DESC
    """, (expert_id,))
    return ok(rows)


@router.post("/{expert_id}/versions")
def create_expert_version(expert_id: str, body: ExpertOverrideIn,
                          admin: dict = Depends(require_admin),
                          conn: sqlite3.Connection = Depends(get_db_rw)):
    expert = _require_expert(expert_id)
    if body.baseVersion != expert["version"]:
        raise ApiError("产品专家版本已变化，请重新加载后再配置", code=409, status_code=409)
    errors = validate_school_override(expert, body.override)
    if errors:
        raise ApiError("学校配置无效：" + "；".join(errors), code=400, status_code=400)
    _ensure_tables(conn)
    serial = int(dbm.scalar(
        conn, "SELECT COUNT(*) FROM sys_ai_expert_version WHERE expert_id=?",
        (expert_id,),
    ) or 0) + 1
    version_no = f"{expert['version']}-school.{serial}"
    cursor = conn.execute("""
        INSERT INTO sys_ai_expert_version(
            expert_id,version_no,base_definition_version,status,override_json,
            change_reason,action,created_by,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        expert_id, version_no, expert["version"], "draft",
        json.dumps(body.override, ensure_ascii=False, sort_keys=True),
        body.changeReason.strip(), "override", admin["username"], _now(),
    ))
    write_audit(
        conn, admin["username"], "ai.expert.version.create", "ai_expert",
        expert_id, detail={"versionId": cursor.lastrowid, "version": version_no},
    )
    return ok({"versionId": cursor.lastrowid, "version": version_no, "status": "draft"},
              msg="学校专家配置草稿已创建")


@router.post("/{expert_id}/versions/{version_id}/publish")
def publish_expert_version(expert_id: str, version_id: int,
                           admin: dict = Depends(require_admin),
                           conn: sqlite3.Connection = Depends(get_db_rw)):
    expert = _require_expert(expert_id)
    _ensure_tables(conn)
    row = dbm.query_one(conn, """
        SELECT * FROM sys_ai_expert_version
        WHERE version_id=? AND expert_id=?
    """, (version_id, expert_id))
    if not row:
        raise ApiError("专家配置版本不存在", code=404, status_code=404)
    if row["status"] != "draft":
        raise ApiError("只有草稿版本可以发布", code=409, status_code=409)
    if row["base_definition_version"] != expert["version"]:
        raise ApiError("草稿基于旧产品版本，需重新生成后发布", code=409, status_code=409)
    errors = validate_school_override(expert, _decode_override(row))
    if errors:
        raise ApiError("学校配置无效：" + "；".join(errors), code=400, status_code=400)
    now = _now()
    conn.execute("""
        UPDATE sys_ai_expert_version SET status='retired'
        WHERE expert_id=? AND status='published'
    """, (expert_id,))
    conn.execute("""
        UPDATE sys_ai_expert_version
        SET status='published',published_by=?,published_at=?
        WHERE version_id=?
    """, (admin["username"], now, version_id))
    write_audit(
        conn, admin["username"], "ai.expert.version.publish", "ai_expert",
        expert_id, detail={"versionId": version_id, "version": row["version_no"]},
    )
    return ok({"versionId": version_id, "version": row["version_no"], "status": "published"},
              msg="学校专家配置已发布")


@router.post("/{expert_id}/versions/{version_id}/rollback")
def rollback_expert_version(expert_id: str, version_id: int,
                            admin: dict = Depends(require_admin),
                            conn: sqlite3.Connection = Depends(get_db_rw)):
    expert = _require_expert(expert_id)
    _ensure_tables(conn)
    target = dbm.query_one(conn, """
        SELECT * FROM sys_ai_expert_version
        WHERE version_id=? AND expert_id=? AND status IN ('published','retired')
    """, (version_id, expert_id))
    if not target:
        raise ApiError("只能回滚到已发布或已退役版本", code=409, status_code=409)
    serial = int(dbm.scalar(
        conn, "SELECT COUNT(*) FROM sys_ai_expert_version WHERE expert_id=?",
        (expert_id,),
    ) or 0) + 1
    version_no = f"{expert['version']}-school.{serial}"
    now = _now()
    conn.execute("""
        UPDATE sys_ai_expert_version SET status='retired'
        WHERE expert_id=? AND status='published'
    """, (expert_id,))
    cursor = conn.execute("""
        INSERT INTO sys_ai_expert_version(
            expert_id,version_no,base_definition_version,status,override_json,
            change_reason,action,source_version_id,created_by,created_at,
            published_by,published_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        expert_id, version_no, expert["version"], "published",
        target["override_json"], f"回滚到 {target['version_no']}", "rollback",
        target["version_id"], admin["username"], now, admin["username"], now,
    ))
    write_audit(
        conn, admin["username"], "ai.expert.version.rollback", "ai_expert",
        expert_id, detail={
            "versionId": cursor.lastrowid,
            "version": version_no,
            "sourceVersionId": target["version_id"],
        },
    )
    return ok({
        "versionId": cursor.lastrowid,
        "version": version_no,
        "status": "published",
        "sourceVersionId": target["version_id"],
    }, msg="专家配置已回滚并生成新的发布版本")

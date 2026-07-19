"""系统管理收口：学校参数、分析方案总览、测试、适用角色和停用。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...ai_experts import get_expert, list_experts, validate_school_override
from .. import db as dbm
from ..deps import get_db_rw, require_admin
from ..envelope import ApiError, ok
from ..security_governance import write_audit
from ..settings import CURRENT_SEMESTER
from .ai_experts import _ensure_tables, resolve_effective_expert


router = APIRouter(prefix="/api/admin/system", tags=["system-management"])

SYSTEM_PARAMETER_DDL = """
CREATE TABLE IF NOT EXISTS sys_system_parameter (
    parameter_key TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    value_type TEXT NOT NULL,
    description TEXT NOT NULL,
    editable INTEGER NOT NULL DEFAULT 1,
    options_json TEXT NOT NULL DEFAULT '[]',
    updated_by TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sys_system_parameter_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    parameter_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    version INTEGER NOT NULL,
    change_reason TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_system_parameter_history
ON sys_system_parameter_history(parameter_key,history_id);
"""

PARAMETER_DEFAULTS = [
    ("school.name", "学校信息", "学校名称", "示范高校", "string",
     "用于页面标题、管理简报抬头和方案输出，不作为教务组织机构真值。", []),
    ("school.code", "学校信息", "学校代码", "demo-university", "string",
     "用于数据交换和部署实例识别。", []),
    ("semester.current", "学期与数据", "当前业务学期", CURRENT_SEMESTER, "string",
     "用于默认筛选；实际可选学期仍以已接入数据为准。", []),
    ("semester.teaching_supply", "学期与数据", "教学任务学期", "2023-2024-1", "string",
     "当前教学任务和排课资源证据所属学期。", []),
    ("data.refresh_mode", "学期与数据", "数据更新时间策略", "由学校数据交换平台触发", "string",
     "平台只消费数据，不在本系统维护教务主数据。", []),
    ("ai.enabled", "大模型接入", "大模型能力启用", True, "boolean",
     "关闭后仍保留确定性指标和规则研判，不调用模型生成解释。", []),
    ("ai.provider_mode", "大模型接入", "模型接入方式", "school_approved_cloud", "enum",
     "学校批准后可使用云端大模型，也可切换为校内部署模型；本页不保存密钥。 ",
     ["school_approved_cloud", "private_model", "disabled"]),
    ("ai.allowed_scope", "大模型接入", "允许数据范围", "authorized_business_data", "enum",
     "模型只能处理当前工作身份已获授权的数据，不能扩大组织或学生范围。",
     ["authorized_business_data", "aggregate_only"]),
    ("ai.response_mode", "大模型接入", "生成模式", "stable_demo_plus_model_samples", "enum",
     "原型以稳定规则结果为主体，少量样例使用模型生成并保留来源。",
     ["stable_demo_plus_model_samples", "deterministic_only", "model_online"]),
    ("cache.management_seconds", "性能与展示", "管理要情缓存", 300, "integer",
     "管理要情快照的缓存秒数；数据版本变化时自动失效。", []),
    ("cache.decision_seconds", "性能与展示", "决策研判缓存", 300, "integer",
     "相同角色、范围、专家版本和参数的研判缓存秒数。", []),
    ("display.default_page_size", "性能与展示", "默认表格行数", 20, "integer",
     "列表默认每页行数，不改变导出范围。", []),
    ("display.show_data_source", "性能与展示", "显示数据来源", True, "boolean",
     "在业务页面和AI结果中持续显示来源、时间和口径边界。", []),
]


class ParameterUpdateIn(BaseModel):
    value: Any
    changeReason: str = Field(min_length=2, max_length=300)


class SchemeRolesIn(BaseModel):
    roleIds: list[str] = Field(default_factory=list)


def _ensure_system_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SYSTEM_PARAMETER_DDL)
    for key, category, name, value, value_type, description, options in PARAMETER_DEFAULTS:
        dbm.execute(conn, """
            INSERT OR IGNORE INTO sys_system_parameter(
              parameter_key,category,name,value_json,value_type,description,
              editable,options_json
            ) VALUES(?,?,?,?,?,?,1,?)
        """, (
            key, category, name, json.dumps(value, ensure_ascii=False),
            value_type, description, json.dumps(options, ensure_ascii=False),
        ))
    _ensure_tables(conn)


def _decode_json(value: str, fallback: Any = None) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _validate_parameter(row: dict, value: Any) -> None:
    value_type = row["value_type"]
    if value_type == "string" and not isinstance(value, str):
        raise ApiError("参数必须为文本", code=400, status_code=400)
    if value_type == "boolean" and not isinstance(value, bool):
        raise ApiError("参数必须为布尔值", code=400, status_code=400)
    if value_type == "integer" and (
            not isinstance(value, int) or isinstance(value, bool)):
        raise ApiError("参数必须为整数", code=400, status_code=400)
    if value_type == "integer" and not 1 <= value <= 86400:
        raise ApiError("数值参数超出允许范围", code=400, status_code=400)
    if value_type == "enum":
        options = _decode_json(row.get("options_json") or "[]", [])
        if value not in options:
            raise ApiError("参数值不在允许选项中", code=400, status_code=400)


@router.get("/parameters")
def list_system_parameters(_: dict = Depends(require_admin),
                           conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_system_tables(conn)
    rows = dbm.query(conn, """
        SELECT parameter_key,category,name,value_json,value_type,description,
               editable,options_json,updated_by,updated_at,version
        FROM sys_system_parameter ORDER BY category,parameter_key
    """)
    for row in rows:
        row["value"] = _decode_json(row.pop("value_json"))
        row["options"] = _decode_json(row.pop("options_json"), [])
        row["editable"] = bool(row["editable"])
    return ok({
        "parameters": rows,
        "boundary": "系统参数不包含学业预警规则；业务规则继续在学业预警监控中治理。",
        "secretBoundary": "模型密钥、统一身份认证密钥和数据库口令由部署环境管理，不在页面保存或回显。",
    })


@router.put("/parameters/{parameter_key:path}")
def update_system_parameter(parameter_key: str, body: ParameterUpdateIn,
                            admin: dict = Depends(require_admin),
                            conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_system_tables(conn)
    row = dbm.query_one(
        conn, "SELECT * FROM sys_system_parameter WHERE parameter_key=?",
        (parameter_key,),
    )
    if not row:
        raise ApiError("系统参数不存在", code=404, status_code=404)
    if not row["editable"]:
        raise ApiError("该参数为只读", code=409, status_code=409)
    _validate_parameter(row, body.value)
    next_version = int(row["version"] or 1) + 1
    dbm.execute(conn, """
        INSERT INTO sys_system_parameter_history(
          parameter_key,value_json,version,change_reason,changed_by
        ) VALUES(?,?,?,?,?)
    """, (
        parameter_key, row["value_json"], row["version"],
        body.changeReason.strip(), admin["username"],
    ))
    dbm.execute(conn, """
        UPDATE sys_system_parameter
        SET value_json=?,updated_by=?,updated_at=datetime('now','localtime'),
            version=?
        WHERE parameter_key=?
    """, (
        json.dumps(body.value, ensure_ascii=False), admin["username"],
        next_version, parameter_key,
    ))
    write_audit(
        conn, admin["username"], "system.parameter.update", "system_parameter",
        parameter_key, detail={
            "version": next_version, "changeReason": body.changeReason.strip()
        },
    )
    return ok({"parameterKey": parameter_key, "version": next_version},
              msg="系统参数已保存")


@router.get("/analysis-schemes")
def list_managed_analysis_schemes(_: dict = Depends(require_admin),
                                  conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_system_tables(conn)
    schemes = dbm.query(conn, """
        SELECT scheme_id,expert_id,name,expert_version,status,parameters_json,
               created_by,created_at,published_by,published_at
        FROM sys_ai_analysis_scheme
        ORDER BY CASE status WHEN 'published' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
                 scheme_id DESC
    """)
    for scheme in schemes:
        scheme["parameters"] = _decode_json(scheme.pop("parameters_json"), {})
        scheme["roleIds"] = [
            row["role_id"] for row in dbm.query(
                conn,
                "SELECT role_id FROM sys_ai_analysis_scheme_role "
                "WHERE scheme_id=? ORDER BY role_id",
                (scheme["scheme_id"],),
            )
        ]
    versions = dbm.query(conn, """
        SELECT version_id,expert_id,version_no,base_definition_version,status,
               change_reason,action,source_version_id,created_by,created_at,
               published_by,published_at
        FROM sys_ai_expert_version ORDER BY expert_id,version_id DESC
    """)
    experts = []
    for expert in list_experts():
        effective, version = resolve_effective_expert(conn, expert)
        experts.append({
            "expertId": expert["expertId"],
            "name": expert["name"],
            "productVersion": expert["version"],
            "effectiveVersion": version["version"],
            "versionSource": version["source"],
            "applicableRoles": effective["applicableRoles"],
            "configurable": effective["configurable"],
        })
    return ok({
        "experts": experts,
        "schemes": schemes,
        "versions": versions,
        "boundary": "学校方案只调整白名单参数和适用角色，不复制页面、不改变指标公式，也不保存组织数据范围。",
    })


@router.post("/analysis-schemes/{scheme_id}/test")
def test_analysis_scheme(scheme_id: int, admin: dict = Depends(require_admin),
                         conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_system_tables(conn)
    scheme = dbm.query_one(
        conn, "SELECT * FROM sys_ai_analysis_scheme WHERE scheme_id=?",
        (scheme_id,),
    )
    if not scheme:
        raise ApiError("分析方案不存在", code=404, status_code=404)
    expert = get_expert(scheme["expert_id"])
    if not expert:
        raise ApiError("方案引用的管理专家不存在", code=409, status_code=409)
    effective, version = resolve_effective_expert(conn, expert)
    parameters = _decode_json(scheme["parameters_json"], {})
    errors = validate_school_override(
        effective, {"parameterDefaults": parameters}
    )
    roles = [
        row["role_id"] for row in dbm.query(
            conn,
            "SELECT role_id FROM sys_ai_analysis_scheme_role WHERE scheme_id=?",
            (scheme_id,),
        )
    ]
    invalid_roles = [
        role_id for role_id in roles
        if role_id not in effective["applicableRoles"]
    ]
    checks = {
        "expertExists": True,
        "expertVersionCurrent": scheme["expert_version"] == version["version"],
        "parametersValid": not errors,
        "rolesValid": not invalid_roles,
        "permissionBoundary": True,
    }
    passed = all(checks.values())
    write_audit(
        conn, admin["username"], "ai.analysis_scheme.test",
        "ai_analysis_scheme", str(scheme_id),
        result="success" if passed else "failed",
        detail={"checks": checks, "errors": errors, "invalidRoles": invalid_roles},
    )
    return ok({
        "schemeId": scheme_id,
        "passed": passed,
        "checks": checks,
        "errors": errors,
        "invalidRoles": invalid_roles,
        "testedVersion": version["version"],
    })


@router.put("/analysis-schemes/{scheme_id}/roles")
def update_analysis_scheme_roles(scheme_id: int, body: SchemeRolesIn,
                                 admin: dict = Depends(require_admin),
                                 conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_system_tables(conn)
    scheme = dbm.query_one(
        conn, "SELECT * FROM sys_ai_analysis_scheme WHERE scheme_id=?",
        (scheme_id,),
    )
    if not scheme:
        raise ApiError("分析方案不存在", code=404, status_code=404)
    expert = get_expert(scheme["expert_id"])
    if not expert:
        raise ApiError("方案引用的管理专家不存在", code=409, status_code=409)
    role_ids = list(dict.fromkeys(body.roleIds))
    invalid = [
        role_id for role_id in role_ids
        if role_id not in expert["applicableRoles"]
    ]
    if invalid:
        raise ApiError(
            "存在不适用该专家的角色：" + "、".join(invalid),
            code=400,
            status_code=400,
        )
    dbm.execute(
        conn, "DELETE FROM sys_ai_analysis_scheme_role WHERE scheme_id=?",
        (scheme_id,),
    )
    for role_id in role_ids:
        dbm.execute(conn, """
            INSERT INTO sys_ai_analysis_scheme_role(scheme_id,role_id)
            VALUES(?,?)
        """, (scheme_id, role_id))
    write_audit(
        conn, admin["username"], "ai.analysis_scheme.roles_update",
        "ai_analysis_scheme", str(scheme_id), detail={"roleIds": role_ids},
    )
    return ok({"schemeId": scheme_id, "roleIds": role_ids},
              msg="方案适用角色已保存")


@router.post("/analysis-schemes/{scheme_id}/retire")
def retire_analysis_scheme(scheme_id: int, admin: dict = Depends(require_admin),
                           conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_system_tables(conn)
    scheme = dbm.query_one(
        conn, "SELECT * FROM sys_ai_analysis_scheme WHERE scheme_id=?",
        (scheme_id,),
    )
    if not scheme:
        raise ApiError("分析方案不存在", code=404, status_code=404)
    if scheme["status"] == "retired":
        raise ApiError("分析方案已经停用", code=409, status_code=409)
    dbm.execute(
        conn,
        "UPDATE sys_ai_analysis_scheme SET status='retired' WHERE scheme_id=?",
        (scheme_id,),
    )
    write_audit(
        conn, admin["username"], "ai.analysis_scheme.retire",
        "ai_analysis_scheme", str(scheme_id),
        detail={"previousStatus": scheme["status"]},
    )
    return ok({"schemeId": scheme_id, "status": "retired"},
              msg="分析方案已停用")

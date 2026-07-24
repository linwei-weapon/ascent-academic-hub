"""统一权限上下文：当前工作身份、动作权限、明细范围和比较范围。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from typing import Optional

from . import db as dbm
from .envelope import ApiError

ALL_SCOPE_ROLES = {
    "school_leader", "dean", "dept_operation", "dept_research",
    "dept_practice", "quality_office",
}
SCOPED_ROLE_TYPES = {
    "college_dean": "college",
    "college_secretary": "college",
    "dept_director": "major",
    "counselor": "class",
    "teacher": "teacher",
    "class_adviser": "staff_relation",
    "mentor": "staff_relation",
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(dbm.query_one(
        conn,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ))


def _active_clause(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"{prefix}status='active' "
        f"AND ({prefix}valid_from IS NULL OR {prefix}valid_from<=?) "
        f"AND ({prefix}valid_to IS NULL OR {prefix}valid_to>=?)"
    )


def resolve_identity(conn: sqlite3.Connection, user: dict,
                     requested_identity_id: Optional[str] = None) -> dict:
    """解析当前工作身份；新表尚未迁移时兼容sys_user.role_id。"""
    if not _table_exists(conn, "sys_user_role"):
        return {
            "user_role_id": f"legacy:{user['username']}:{user.get('role_id') or ''}",
            "username": user["username"],
            "role_id": user.get("role_id"),
            "is_default": 1,
            "source": "legacy_fallback",
        }
    today = date.today().isoformat()
    params: list = [user["username"], today, today]
    where = ["username=?", _active_clause()]
    if requested_identity_id:
        where.append("user_role_id=?")
        params.append(requested_identity_id)
    identity = dbm.query_one(conn, f"""
        SELECT user_role_id,username,role_id,is_default,valid_from,valid_to,status,source
        FROM sys_user_role
        WHERE {' AND '.join(where)}
        ORDER BY is_default DESC,user_role_id
        LIMIT 1
    """, tuple(params))
    if not identity:
        message = "当前工作身份不存在或已失效" if requested_identity_id else "账号没有有效工作身份"
        raise ApiError(message, code=403, status_code=403)
    return identity


def list_identities(conn: sqlite3.Connection, username: str) -> list[dict]:
    if not _table_exists(conn, "sys_user_role"):
        row = dbm.query_one(
            conn,
            "SELECT username,role_id FROM sys_user WHERE username=?",
            (username,),
        )
        return [{
            "identityId": f"legacy:{username}:{row['role_id']}",
            "roleId": row["role_id"],
            "roleName": row["role_id"],
            "isDefault": True,
            "source": "legacy_fallback",
        }] if row else []
    today = date.today().isoformat()
    rows = dbm.query(conn, f"""
        SELECT ur.user_role_id,ur.role_id,ur.is_default,ur.valid_from,ur.valid_to,
               ur.source,r.name role_name
        FROM sys_user_role ur
        LEFT JOIN sys_role r ON r.role_id=ur.role_id
        WHERE ur.username=? AND {_active_clause('ur')}
        ORDER BY ur.is_default DESC,ur.user_role_id
    """, (username, today, today))
    return [{
        "identityId": row["user_role_id"],
        "roleId": row["role_id"],
        "roleName": row.get("role_name") or row["role_id"],
        "isDefault": bool(row["is_default"]),
        "validFrom": row.get("valid_from"),
        "validTo": row.get("valid_to"),
        "source": row.get("source"),
    } for row in rows]


def _staff_id(conn: sqlite3.Connection, username: str) -> Optional[str]:
    if not _table_exists(conn, "sys_user_staff"):
        return None
    today = date.today().isoformat()
    row = dbm.query_one(conn, f"""
        SELECT staff_id FROM sys_user_staff
        WHERE username=? AND {_active_clause()}
        ORDER BY valid_from DESC,staff_id LIMIT 1
    """, (username, today, today))
    return row["staff_id"] if row else None


def _staff_relation_version(staff_id: Optional[str], role_id: str) -> Optional[str]:
    """人员关系变化必须改变范围指纹，避免复用换班/换导师前的缓存。"""
    if not staff_id or role_id not in {"counselor", "class_adviser", "mentor"}:
        return None
    relation_types = {
        "class_adviser": ["class_adviser"],
        "mentor": ["学业导师", "导师", "mentor"],
        "counselor": ["counselor"],
    }[role_id]
    try:
        conn = dbm.get_v2_conn()
        try:
            placeholders = ",".join("?" * len(relation_types))
            rows = dbm.query(conn, f"""
                SELECT student_id,relation_type,valid_from,valid_to,status,
                       source_updated_at
                FROM staff_student_scope
                WHERE staff_id=? AND relation_type IN ({placeholders})
                  AND COALESCE(status,'active')='active'
                  AND date(valid_from)<=date('now')
                  AND (valid_to IS NULL OR date(valid_to)>=date('now'))
                ORDER BY relation_type,student_id,valid_from
            """, tuple([staff_id] + relation_types))
        finally:
            conn.close()
    except Exception:
        return "relationship-source-unavailable"
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _identity_scopes(conn: sqlite3.Connection, identity: dict) -> list[dict]:
    if _table_exists(conn, "sys_user_scope") and not str(
            identity["user_role_id"]).startswith("legacy:"):
        today = date.today().isoformat()
        return dbm.query(conn, f"""
            SELECT scope_type,scope_id,valid_from,valid_to,source
            FROM sys_user_scope
            WHERE user_role_id=? AND {_active_clause()}
            ORDER BY scope_type,scope_id
        """, (identity["user_role_id"], today, today))
    role = dbm.query_one(
        conn, "SELECT data_scope_type FROM sys_role WHERE role_id=?",
        (identity["role_id"],),
    )
    if not role or role["data_scope_type"] == "all":
        return []
    return [{
        "scope_type": role["data_scope_type"],
        "scope_id": row["scope_id"],
        "source": "legacy_fallback",
    } for row in dbm.query(
        conn, "SELECT scope_id FROM sys_role_scope WHERE role_id=? ORDER BY scope_id",
        (identity["role_id"],),
    )]


def _menus(conn: sqlite3.Connection, role_id: str) -> list[str]:
    if not _table_exists(conn, "sys_role_menu"):
        return []
    return [row["menu_id"] for row in dbm.query(conn, """
        SELECT rm.menu_id FROM sys_role_menu rm
        LEFT JOIN sys_menu m ON m.menu_id=rm.menu_id
        WHERE rm.role_id=? AND (m.parent_id IS NOT NULL OR m.menu_id IS NULL)
        ORDER BY COALESCE(m.sort_order,0),rm.menu_id
    """, (role_id,))]


def _actions(conn: sqlite3.Connection, role_id: str) -> list[str]:
    if not _table_exists(conn, "sys_role_action"):
        return []
    return [row["action_id"] for row in dbm.query(
        conn,
        "SELECT action_id FROM sys_role_action WHERE role_id=? ORDER BY action_id",
        (role_id,),
    )]


def build_permission_context(conn: sqlite3.Connection, user: dict,
                             requested_identity_id: Optional[str] = None) -> dict:
    identity = resolve_identity(conn, user, requested_identity_id)
    role_id = identity["role_id"]
    role = dbm.query_one(
        conn, "SELECT name,data_scope_type FROM sys_role WHERE role_id=?",
        (role_id,),
    )
    if not role:
        raise ApiError("工作身份引用的角色不存在", code=403, status_code=403)
    scope_type = role.get("data_scope_type") or SCOPED_ROLE_TYPES.get(role_id)
    scopes = _identity_scopes(conn, identity)
    scope_ids = sorted({row["scope_id"] for row in scopes if row.get("scope_id")})
    staff_id = _staff_id(conn, user["username"])
    if role_id in {"counselor", "class_adviser", "mentor"} and staff_id and not scope_ids:
        scope_type = "staff_relation"

    if scope_type == "all":
        authorized = True
        detail_scope = {"type": "all", "sourceScopeIds": []}
    else:
        authorized = bool(scope_ids) or (scope_type == "staff_relation" and bool(staff_id))
        detail_scope = {
            "type": scope_type or "denied",
            "sourceScopeIds": scope_ids,
        }
        if scope_type == "college":
            detail_scope["collegeIds"] = scope_ids
        elif scope_type == "major":
            detail_scope["majorIds"] = scope_ids
        elif scope_type == "class":
            detail_scope["classIds"] = scope_ids
        elif scope_type == "teacher":
            detail_scope["teacherIds"] = scope_ids

    comparison_scope = {
        "type": "school_aggregate" if (
            scope_type == "all" or scope_type in {"college", "major"}
        ) else "none",
        "allowOtherOrganizations": scope_type in {"all", "college", "major"},
        "minimumGroupSize": 10,
    }
    fingerprint_input = {
        "username": user["username"],
        "identity": identity["user_role_id"],
        "role": role_id,
        "staff": staff_id,
        "staffRelationVersion": _staff_relation_version(staff_id, role_id),
        "scope": detail_scope,
        "comparison": comparison_scope,
        "authorized": authorized,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "userId": str(user.get("user_id") or user["username"]),
        "username": user["username"],
        "staffId": staff_id,
        "activeIdentityId": identity["user_role_id"],
        "activeRole": role_id,
        "activeRoleName": role.get("name") or role_id,
        "authorized": authorized,
        "authorizationIssue": None if authorized else "当前工作身份缺少有效数据范围或人员关系",
        "menuPermissions": _menus(conn, role_id),
        "actionPermissions": _actions(conn, role_id),
        "detailScope": detail_scope,
        "comparisonScope": comparison_scope,
        "fieldPolicy": {
            "studentIdentity": "detail_scope_only",
            "export": "authorized_only",
        },
        "scopeFingerprint": f"sha256:{fingerprint}",
    }


def require_authorized_context(context: dict) -> dict:
    if not context.get("authorized"):
        raise ApiError(
            context.get("authorizationIssue") or "当前工作身份没有有效数据范围",
            code=403,
            status_code=403,
        )
    return context


def has_action(user: dict, action_id: str) -> bool:
    context = user.get("permission_context") or {}
    return action_id in set(context.get("actionPermissions") or [])


def v2_student_scope(context: dict, conn: sqlite3.Connection,
                     alias: str = "s") -> tuple[str, list]:
    """把统一权限上下文转换为V2学生查询范围。范围缺失时拒绝。"""
    require_authorized_context(context)
    detail = context.get("detailScope") or {}
    scope_type = detail.get("type")
    if scope_type == "all":
        return "", []
    if scope_type == "staff_relation":
        staff_id = context.get("staffId")
        if not staff_id:
            raise ApiError("当前身份未关联有效人员工号", code=403, status_code=403)
        role = context.get("activeRole")
        relation_types = {
            "class_adviser": ["class_adviser"],
            "mentor": ["学业导师", "导师", "mentor"],
            "counselor": ["counselor"],
        }.get(role)
        condition = ""
        params: list = [staff_id]
        if relation_types:
            condition = f" AND relation_type IN ({','.join('?' * len(relation_types))})"
            params.extend(relation_types)
        return (f"""{alias}.student_id IN (
            SELECT student_id FROM staff_student_scope
            WHERE staff_id=?{condition}
              AND COALESCE(status,'active')='active'
              AND date(valid_from)<=date('now')
              AND (valid_to IS NULL OR date(valid_to)>=date('now'))
        )""", params)

    source_ids = detail.get("sourceScopeIds") or []
    if scope_type not in {"college", "major", "class"} or not source_ids:
        raise ApiError("当前身份没有可映射的V2学生范围", code=403, status_code=403)
    role_id = context.get("activeRole")
    placeholders = ",".join("?" * len(source_ids))
    mappings = dbm.query(conn, f"""
        SELECT scope_type,source_scope_id,organization_id,major_code,class_code
        FROM access_scope_mapping
        WHERE role_id=? AND mapping_status='mapped'
          AND source_scope_id IN ({placeholders})
        ORDER BY source_scope_id
    """, tuple([role_id] + source_ids))
    column_by_type = {
        "college": "organization_id",
        "major": "major_code",
        "class": "class_code",
    }
    column = column_by_type[scope_type]
    mapped_sources = {
        row["source_scope_id"] for row in mappings
        if row.get("scope_type") == scope_type and row.get(column)
    }
    values = sorted({
        row[column] for row in mappings
        if row.get("scope_type") == scope_type and row.get(column)
    })
    if mapped_sources != set(source_ids):
        raise ApiError("当前身份的V2数据范围未完整映射", code=403, status_code=403)
    return f"{alias}.{column} IN ({','.join('?' * len(values))})", values


def v2_lesson_scope(context: dict, conn: sqlite3.Connection,
                    alias: str = "tl") -> tuple[str, list]:
    """教学任务按开课组织授权；其他受限类型默认返回空范围。"""
    return v2_organization_scope(context, conn, alias)


def v2_organization_scope(context: dict, conn: sqlite3.Connection,
                          alias: str = "o",
                          column: str = "organization_id") -> tuple[str, list]:
    """按V2组织机构限定教学业务对象；非学院受限身份默认返回空范围。

    该范围用于教学任务、课程责任组织和课程结果等不直接包含学生维度的
    业务对象。学院身份必须完成全部源范围映射，避免映射缺失时扩大为全校。
    """
    require_authorized_context(context)
    detail = context.get("detailScope") or {}
    if detail.get("type") == "all":
        return "", []
    if detail.get("type") != "college":
        return "1=0", []
    source_ids = detail.get("sourceScopeIds") or []
    if not source_ids:
        raise ApiError("当前身份没有可映射的V2学院范围", code=403, status_code=403)
    role_id = context.get("activeRole")
    placeholders = ",".join("?" * len(source_ids))
    mappings = dbm.query(conn, f"""
        SELECT source_scope_id,organization_id
        FROM access_scope_mapping
        WHERE role_id=? AND scope_type='college' AND mapping_status='mapped'
          AND source_scope_id IN ({placeholders})
        ORDER BY source_scope_id
    """, tuple([role_id] + source_ids))
    mapped_sources = {
        row["source_scope_id"] for row in mappings if row.get("organization_id")
    }
    values = sorted({
        row["organization_id"] for row in mappings if row.get("organization_id")
    })
    if mapped_sources != set(source_ids) or not values:
        raise ApiError("当前身份的V2学院范围未完整映射", code=403, status_code=403)
    # 部分历史教学任务把organization_id落成了学院名称，而课程、学生维度使用
    # 组织代码。只扩展同一权威组织表中的代码—名称等价值，不做模糊匹配。
    if _table_exists(conn, "dim_organization"):
        placeholders = ",".join("?" * len(values))
        names = [
            row["name"] for row in dbm.query(conn, f"""
                SELECT name FROM dim_organization
                WHERE organization_id IN ({placeholders})
            """, tuple(values)) if row.get("name")
        ]
        values = sorted(set(values + names))
    return f"{alias}.{column} IN ({','.join('?' * len(values))})", values

"""复用原型已连接环境的身份校验；不读取或计算原系统的指标接口。"""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import Header

from backend.api.envelope import ApiError
from backend.api.permission_context import has_action
from .config import CODE


def authentication_origin() -> str:
    # The existing frontend test target remains the sole shared origin setting.
    text = (CODE / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    match = re.search(r"test:\s*\{[^}]*apiTarget:\s*['\"]([^'\"]+)", text)
    if not match:
        raise ApiError("无法读取原型现有登录环境配置", status_code=503)
    origin = match.group(1).rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ApiError("原型登录环境配置无效", status_code=503)
    return origin


def normalize_actor(payload: dict) -> dict:
    context = payload.get("permissionContext") or {}
    actor = {
        "username": payload.get("username"), "name": payload.get("name"),
        "identity_id": payload.get("activeIdentityId"),
        "permission_context": context, "menus": payload.get("menus") or [],
    }
    if (not actor["username"] or not actor["identity_id"] or context.get("authorized") is not True
            or context.get("activeIdentityId") != actor["identity_id"]):
        raise ApiError("当前工作身份没有有效数据权限", code=403, status_code=403)
    if not any(has_action(actor, action) for action in ("definition.read", "definition.manage", "system.manage")):
        raise ApiError("当前身份无权使用指标核验", code=403, status_code=403)
    return actor


def remote_identity_payload(authorization: str, identity: str = "") -> dict:
    """Verify the existing test session; feature permissions belong to its caller."""
    if not authorization.lower().startswith("bearer "):
        raise ApiError("请先登录", code=401, status_code=401)
    request = Request(authentication_origin() + "/api/auth/me", headers={
        "Authorization": authorization, "X-Active-Identity": identity,
        "Accept": "application/json",
    })
    # Retry one transient read failure; every successful attempt still validates
    # the current identity remotely. No cached identity or local fallback.
    for attempt in range(2):
        try:
            with urlopen(request, timeout=8) as response:
                envelope = json.load(response)
            break
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise ApiError("当前登录或工作身份无效", code=exc.code, status_code=exc.code) from None
            if attempt == 0 and exc.code in (502, 503, 504):
                continue
            raise ApiError("登录环境暂时无法校验身份", status_code=503) from None
        except (URLError, TimeoutError, ConnectionError):
            if attempt == 0:
                continue
            raise ApiError("登录环境暂时无法校验身份", status_code=503) from None
        except ValueError:
            raise ApiError("登录环境暂时无法校验身份", status_code=503) from None
    if not isinstance(envelope, dict) or envelope.get("code") != 0 or not isinstance(envelope.get("data"), dict):
        raise ApiError("登录环境未返回有效身份", code=401, status_code=401)
    payload = envelope["data"]
    if identity and payload.get("activeIdentityId") != identity:
        raise ApiError("工作身份已变化，请重新选择身份", code=403, status_code=403)
    return payload


def current_actor(authorization: str = Header(default=""),
                  identity: str = Header(default="", alias="X-Active-Identity")) -> dict:
    return normalize_actor(remote_identity_payload(authorization, identity))


def can_execute(actor: dict) -> bool:
    context = actor.get("permission_context") or {}
    return (context.get("authorized") is True and has_action(actor, "system.manage")
            and (context.get("detailScope") or {}).get("type") == "all")


def require_execution(actor: dict) -> None:
    if not can_execute(actor):
        raise ApiError("当前仅向具备系统管理及全校数据权限的工作身份开放数据库核验", code=403, status_code=403)


def can_manage_mapping(actor: dict) -> bool:
    context = actor.get("permission_context") or {}
    return context.get("authorized") is True and any(
        has_action(actor, action) for action in ("definition.manage", "system.manage"))


def require_mapping_management(actor: dict) -> None:
    if not can_manage_mapping(actor):
        raise ApiError("当前身份没有指标口径维护权限", code=403, status_code=403)


def can_record(actor: dict) -> bool:
    context = actor.get("permission_context") or {}
    return context.get("authorized") is True and any(
        has_action(actor, action) for action in ("definition.read", "definition.manage", "system.manage"))


def require_record(actor: dict) -> None:
    if not can_record(actor):
        raise ApiError("当前身份没有指标核对记录权限", code=403, status_code=403)


def menu_for_actor(actor: dict) -> dict:
    parent = next((m for m in actor["menus"] if not m.get("parent_id") and
                   (m.get("title") == "系统管理" or m.get("path") == "/admin/system")), None)
    parent_id = parent["menu_id"] if parent else "metric-verification-system"
    return {
        "authorized": True, "canExecute": can_execute(actor), "mappingManage": can_manage_mapping(actor),
        "parent": parent or {"menu_id": parent_id, "parent_id": None, "title": "系统管理", "path": "/admin/system", "sort_order": 90},
        "menu": {"menu_id": "metric-verification", "parent_id": parent_id,
                 "title": "指标核验", "path": "/admin/system/metric-verification", "icon": "", "sort_order": 65},
    }

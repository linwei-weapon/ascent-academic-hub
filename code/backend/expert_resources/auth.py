"""Reuse test identity verification and the central action permission contract."""
from fastapi import Header
from backend.api.envelope import ApiError
from backend.api.permission_context import has_action
from backend.metric_verification.auth import remote_identity_payload


def normalize_actor(payload):
    context = payload.get('permissionContext') or {}
    actor = {'username': payload.get('username'), 'name': payload.get('name'),
             'identity_id': payload.get('activeIdentityId'),
             'permission_context': context, 'menus': payload.get('menus') or []}
    if (not actor['username'] or not actor['identity_id'] or not context.get('scopeFingerprint')
            or context.get('authorized') is not True
            or context.get('activeIdentityId') != actor['identity_id']):
        raise ApiError('当前工作身份或数据范围无效', code=403, status_code=403)
    return actor


def current_actor(authorization: str = Header(default=''),
                  identity: str = Header(default='', alias='X-Active-Identity')):
    return normalize_actor(remote_identity_payload(authorization, identity))


def can_manage(actor):
    return has_action(actor, 'system.manage')


def require_manage(actor):
    if not can_manage(actor):
        raise ApiError('当前身份没有专家资源管理权限', code=403, status_code=403)
    return actor


def require_use(actor):
    if can_manage(actor):
        return actor
    scope = actor.get('permission_context', {}).get('detailScope') or {}
    # Test server already grants this action for AI analysis. Its RBAC has no
    # local prototype's expert_team.use action; do not create a parallel role list.
    if has_action(actor, 'ai.analyze') and scope.get('type') in {'all', 'college'}:
        return actor
    raise ApiError('当前身份没有专家分析权限或有效学院范围', code=403, status_code=403)


def can_use(actor):
    try:
        require_use(actor)
        return True
    except ApiError:
        return False


def access(actor):
    entries = []
    def add(title, path, parent_title, parent_path, order, child_order=70):
        parent = next((m for m in actor['menus'] if not m.get('parent_id') and
                       (m.get('title') == parent_title or m.get('path') == parent_path)), None)
        parent = parent or {'menu_id': 'er-' + parent_title, 'parent_id': None,
                           'title': parent_title, 'path': parent_path, 'sort_order': order}
        if not any(item['menu_id'] == parent['menu_id'] for item in entries):
            entries.append(parent)
        entries.append({'menu_id': 'er-' + title, 'parent_id': parent['menu_id'],
                        'title': title, 'path': path, 'sort_order': child_order})
    if can_manage(actor):
        add('专家管理', '/admin/system/expert-management', '系统管理', '/admin/system', 90, 70)
        add('技能管理', '/admin/system/skill-management', '系统管理', '/admin/system', 90, 71)
        add('MCP管理', '/admin/system/mcp-management', '系统管理', '/admin/system', 90, 72)
        add('后台处理服务', '/admin/system/background-processing', '系统管理', '/admin/system', 90, 73)
    if can_use(actor):
        add('AI简报', '/admin/reports/decision', 'AI管理决策', '/admin/reports', 20, 1)
        add('专家问策', '/admin/reports/advice', 'AI管理决策', '/admin/reports', 20, 2)
    return {'authorized': bool(entries), 'canManage': can_manage(actor),
            'canUse': can_use(actor), 'menus': entries}

// 角色与功能权限接口：只封装原有请求，不解释或修正后台业务数据。
import { http } from '@/utils/http'

// 读取角色列表及原有范围配置。
export function listRoles<T = any>(): Promise<T> {
  return http.get<T>('/admin/rbac/roles')
}

// 读取角色授权抽屉使用的菜单目录。
export function listRoleMenuOptions<T = any>(): Promise<T> {
  return http.get<T>('/admin/rbac/menus')
}

// 读取页面与关键动作的可授权目录。
export function listRoleActionOptions<T = any>(): Promise<T> {
  return http.get<T>('/admin/rbac/actions')
}

// 提交角色编辑字段，保留原范围含义。
export function updateRole<T = any>(roleId: string | number, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/roles/${roleId}`, body)
}

// 提交角色创建表单，后续菜单授权仍独立保存。
export function createRole<T = any>(body: unknown): Promise<T> {
  return http.post<T>('/admin/rbac/roles', body)
}

// 删除用户已确认的角色，关联账号校验由后端执行。
export function deleteRole<T = any>(roleId: string | number): Promise<T> {
  return http.del<T>(`/admin/rbac/roles/${roleId}`)
}

// 读取角色已授权的菜单，供抽屉恢复勾选。
export function getRoleMenus<T = any>(roleId: string | number): Promise<T> {
  return http.get<T>(`/admin/rbac/roles/${roleId}/menus`)
}

// 读取角色已授权的页面和关键动作。
export function getRoleActions<T = any>(roleId: string | number): Promise<T> {
  return http.get<T>(`/admin/rbac/roles/${roleId}/actions`)
}

// 一并提交选中的菜单和动作，沿用原权限保存协议。
export function saveRolePermissions<T = any>(roleId: string | number, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/roles/${roleId}/permissions`, body)
}

// 由后端汇总角色的有效菜单、动作和范围预览。
export function previewRolePermissions<T = any>(roleId: string | number): Promise<T> {
  return http.get<T>(`/admin/rbac/roles/${roleId}/permission-preview`)
}

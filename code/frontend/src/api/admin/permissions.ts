// 数据权限接口：只封装原有请求，不解释或修正后台业务数据。
import { http } from '@/utils/http'

// 按页面关键词读取账号数据权限准备度。
export function listDataPermissions<T = any>(query: string | URLSearchParams): Promise<T> {
  return http.get<T>(`/admin/rbac/data-permissions${query}`)
}

// 读取身份编辑使用的角色与组织范围选项。
export function getPermissionOptions<T = any>(): Promise<T> {
  return http.get<T>('/admin/rbac/data-permissions/options')
}

// 按用户名读取人员映射、工作身份和数据范围。
export function getUserPermissions<T = any>(username: string): Promise<T> {
  return http.get<T>(`/admin/rbac/data-permissions/${encodeURIComponent(username)}`)
}

// 提交账号与人员的关联信息，保持原映射契约。
export function updateStaffBinding<T = any>(username: string, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/data-permissions/${encodeURIComponent(username)}/staff`, body)
}

// 为指定账号提交工作身份及原有效期字段。
export function createWorkIdentity<T = any>(username: string, body: unknown): Promise<T> {
  return http.post<T>(`/admin/rbac/data-permissions/${encodeURIComponent(username)}/identities`, body)
}

// 提交既有工作身份的编辑或启停字段。
export function updateWorkIdentity<T = any>(username: string, identityId: string | number, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/data-permissions/${encodeURIComponent(username)}/identities/${encodeURIComponent(identityId)}`, body)
}

// 删除指定账号的工作身份，保留原关联校验。
export function deleteWorkIdentity<T = any>(username: string, identityId: string | number): Promise<T> {
  return http.del<T>(`/admin/rbac/data-permissions/${encodeURIComponent(username)}/identities/${encodeURIComponent(identityId)}`)
}

// 保存指定工作身份的数据范围，不在前端扩展授权。
export function updateIdentityScopes<T = any>(username: string, identityId: string | number, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/data-permissions/${encodeURIComponent(username)}/identities/${encodeURIComponent(identityId)}/scopes`, body)
}

// 由后端计算指定工作身份的有效权限预览。
export function previewUserPermissions<T = any>(username: string, identityId: string | number): Promise<T> {
  return http.get<T>(`/admin/rbac/data-permissions/${encodeURIComponent(username)}/preview/${encodeURIComponent(identityId)}`)
}

// 按关键词及关系类型读取带班、带生关系。
export function listStaffRelationships<T = any>(query: string | URLSearchParams): Promise<T> {
  return http.get<T>(`/admin/rbac/data-permissions/relationships/list?${query}`)
}

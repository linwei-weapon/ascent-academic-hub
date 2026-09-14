// 账号管理接口：只封装原有请求，不解释或修正后台业务数据。
import { http } from '@/utils/http'

// 按页面已应用的筛选和分页读取账号列表及服务端汇总。
export function listAccounts<T = any>(query: string | URLSearchParams): Promise<T> {
  return http.get<T>(`/admin/rbac/users?${query}`)
}

// 读取账号创建与筛选使用的角色选项。
export function listAccountRoles<T = any>(): Promise<T> {
  return http.get<T>('/admin/rbac/roles')
}

// 按用户主键读取账号详情及关联信息。
export function getAccount<T = any>(userId: string | number): Promise<T> {
  return http.get<T>(`/admin/rbac/users/${userId}`)
}

// 提交账号编辑字段，可编辑范围由原接口校验。
export function updateAccount<T = any>(userId: string | number, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/users/${userId}`, body)
}

// 提交本地账号创建表单，保留原来源和状态字段。
export function createAccount<T = any>(body: unknown): Promise<T> {
  return http.post<T>('/admin/rbac/users', body)
}

// 保存账号的认证主体映射，冲突校验由后端执行。
export function updateAuthMapping<T = any>(userId: string | number, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/users/${userId}/auth-identity`, body)
}

// 提交账号启停状态与操作原因。
export function updateAccountStatus<T = any>(userId: string | number, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/users/${userId}/status`, body)
}

// 提交账号归档状态和原因，历史关系由后端保留。
export function archiveAccount<T = any>(userId: string | number, body: unknown): Promise<T> {
  return http.post<T>(`/admin/rbac/users/${userId}/archive`, body)
}

// 提交已由页面确认的本地账号新密码。
export function resetAccountPassword<T = any>(userId: string | number, body: unknown): Promise<T> {
  return http.post<T>(`/admin/rbac/users/${userId}/reset-pwd`, body)
}

// 读取学校统一认证接入准备度，供交付资料核对。
export function getAccountReadiness<T = any>(): Promise<T> {
  return http.get<T>('/admin/rbac/users/readiness')
}

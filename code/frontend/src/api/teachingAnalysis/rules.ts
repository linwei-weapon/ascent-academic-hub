// 预警规则治理业务请求：保留原端点、编码、参数和响应，不在前端改写统计口径。
import { http, getToken } from '@/utils/http'
import type { UrlValue } from './shared'

// 读取候选规则，保留原字段和响应约定。
export function getDiscoveredRules<T = any>(): Promise<T> {
  return http.get<T>('/admin/settings/rules/discovered')
}

// 读取规则发现预览，保留原字段和响应约定。
export function getDiscoveryPreview<T = any>(): Promise<T> {
  return http.get<T>('/admin/settings/rules/discovery/preview')
}

// 提交规则发现任务，保留原字段和响应约定。
export function discoverRules<T = any>(body?: unknown): Promise<T> {
  return http.post<T>('/admin/settings/rules/discover', body)
}

// 读取规则发现进度，保留原字段和响应约定。
export function getDiscoveryStatus<T = any>(): Promise<T> {
  return http.get<T>('/admin/settings/rules/discovery/status')
}

// 提交候选规则采纳或忽略，保留原字段和响应约定。
export function updateDiscoveredRule<T = any>(ruleId: UrlValue, body?: unknown): Promise<T> {
  return http.put<T>(`/admin/settings/rules/discovered/${ruleId}`, body)
}

// 读取规则治理动作权限，保留原字段和响应约定。
export function getRulePermissions<T = any>(): Promise<T> {
  return http.get<T>('/admin/settings/rule-permissions/me')
}

// 提交规则变更草稿，保留原字段和响应约定。
export function createRuleChange<T = any>(ruleId: UrlValue, body?: unknown): Promise<T> {
  return http.post<T>(`/admin/settings/rules/${ruleId}/changes`, body)
}

// 读取变更试算脚本，保留原字段和响应约定。
export function getRuleTrialScript<T = any>(changeId: UrlValue): Promise<T> {
  return http.get<T>(`/admin/settings/rule-changes/${changeId}/trial-script`)
}

// 提交变更试算脚本内容，保留原字段和响应约定。
export function updateRuleTrialScript<T = any>(changeId: UrlValue, body?: unknown): Promise<T> {
  return http.put<T>(`/admin/settings/rule-changes/${changeId}/trial-script`, body)
}

// 读取变更候选名单，保留原字段和响应约定。
export function getRuleCandidates<T = any>(changeId: UrlValue, page: UrlValue): Promise<T> {
  return http.get<T>(`/admin/settings/rule-changes/${changeId}/candidates?page=${page}&page_size=20`)
}

// 读取变更影响分析，保留原字段和响应约定。
export function getRuleAnalysis<T = any>(changeId: UrlValue): Promise<T> {
  return http.get<T>(`/admin/settings/rule-changes/${changeId}/analysis`)
}

// 读取规则变更列表，保留原字段和响应约定。
export function getRuleChanges<T = any>(): Promise<T> {
  return http.get<T>('/admin/settings/rule-changes')
}

// 提交规则影响试算，保留原字段和响应约定。
export function evaluateRuleChange<T = any>(changeId: UrlValue): Promise<T> {
  return http.post<T>(`/admin/settings/rule-changes/${changeId}/evaluate`)
}

// 提交规则送审，保留原字段和响应约定。
export function submitRuleChange<T = any>(changeId: UrlValue): Promise<T> {
  return http.post<T>(`/admin/settings/rule-changes/${changeId}/submit`)
}

// 提交规则发布，保留原字段和响应约定。
export function publishRuleChange<T = any>(changeId: UrlValue): Promise<T> {
  return http.post<T>(`/admin/settings/rule-changes/${changeId}/publish`)
}

// 提交规则激活，保留原字段和响应约定。
export function activateRuleChange<T = any>(changeId: UrlValue): Promise<T> {
  return http.post<T>(`/admin/settings/rule-changes/${changeId}/activate`)
}

// 提交规则回滚，保留原字段和响应约定。
export function rollbackRuleChange<T = any>(changeId: UrlValue): Promise<T> {
  return http.post<T>(`/admin/settings/rule-changes/${changeId}/rollback`)
}

// 提交规则审核，保留原字段和响应约定。
export function reviewRuleChange<T = any>(changeId: UrlValue, body?: unknown): Promise<T> {
  return http.post<T>(`/admin/settings/rule-changes/${changeId}/review`, body)
}

// 读取现行规则，保留原字段和响应约定。
export function getRules<T = any>(): Promise<T> {
  return http.get<T>('/admin/settings')
}

// 保留原候选导出的认证方式与 Response，不改变已有接口兼容。
export function exportRuleCandidates(changeId: UrlValue): Promise<Response> {
  return fetch(`/api/admin/settings/rule-changes/${changeId}/candidates.csv`,
    { headers: { Authorization: `Bearer ${getToken()}` } })
}

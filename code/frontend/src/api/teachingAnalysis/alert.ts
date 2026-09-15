// 学业预警监控业务请求：保留原端点、编码、参数和响应，不在前端改写统计口径。
import { http, getToken, getActiveIdentity } from '@/utils/http'
import type { UrlValue } from './shared'
import { withQuery } from './shared'

// 读取预警学生画像，保留原字段和响应约定。
export function getAlertStudent<T = any>(studentId: UrlValue): Promise<T> {
  return http.get<T>(`/admin/student/${studentId}`)
}

// 读取预警事件，保留原字段和响应约定。
export function getAlertEvent<T = any>(eventId: UrlValue): Promise<T> {
  return http.get<T>(`/admin/alert-events/${eventId}`)
}

// 提交事件核查记录，保留原字段和响应约定。
export function createAlertFollowup<T = any>(eventId: UrlValue, body?: unknown): Promise<T> {
  return http.post<T>(`/admin/alert-events/${eventId}/followups`, body)
}

// 提交事件核查状态，保留原字段和响应约定。
export function updateAlertStatus<T = any>(eventId: UrlValue, body?: unknown): Promise<T> {
  return http.put<T>(`/admin/alert-events/${eventId}/status`, body)
}

// 读取低年级学生画像，保留原字段和响应约定。
export function getEarlyRiskStudent<T = any>(studentId: UrlValue): Promise<T> {
  return http.get<T>(`/admin/student/${studentId}`)
}

// 读取名单筛选选项，保留原字段和响应约定。
export function getAlertOptions<T = any>(query: URLSearchParams): Promise<T> {
  return http.get<T>(withQuery('/admin/alerts/options', query))
}

// 读取预警汇总，保留原字段和响应约定。
export function getAlertSummary<T = any>(query: URLSearchParams): Promise<T> {
  return http.get<T>(withQuery('/admin/alerts/summary', query))
}

// 读取预警学生名单，保留原字段和响应约定。
export function getAlertStudents<T = any>(query: URLSearchParams): Promise<T> {
  return http.get<T>(withQuery('/admin/alerts/students', query))
}

// 读取预警分布，保留原字段和响应约定。
export function getAlertDistribution<T = any>(query: URLSearchParams): Promise<T> {
  return http.get<T>(withQuery('/admin/alerts/distribution', query))
}

// 读取预警时间分布，保留原字段和响应约定。
export function getAlertTimeDistribution<T = any>(query: URLSearchParams): Promise<T> {
  return http.get<T>(withQuery('/admin/alerts/time-distribution', query))
}

// 读取优先核查对象，保留原字段和响应约定。
export function getAlertPriority<T = any>(query: URLSearchParams): Promise<T> {
  return http.get<T>(withQuery('/admin/alerts/priority', query))
}

// 读取规则轨迹，保留原字段和响应约定。
export function getAlertTrajectory<T = any>(ruleId: string | number | boolean, level: string | number | boolean): Promise<T> {
  return http.get<T>(`/admin/alerts/trajectory?rule_id=${encodeURIComponent(ruleId)}&level=${encodeURIComponent(level)}`)
}

// 读取低年级观察选项，保留原字段和响应约定。
export function getEarlySetbackOptions<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/v2/topics/early-setback/options?${query}`)
}

// 读取低年级风险观察，保留原字段和响应约定。
export function getEarlySetback<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/v2/topics/early-setback?${query}`)
}

// 导出沿用 Bearer 和当前身份头，原始响应由页面处理。
export function exportAlertStudents(params: URLSearchParams): Promise<Response> {
  const headers: Record<string, string> = {}
  const token = getToken()
  const activeIdentity = getActiveIdentity()
  if (token) headers.Authorization = `Bearer ${token}`
  if (token && activeIdentity) headers['X-Active-Identity'] = activeIdentity
  return fetch(`/api${withQuery('/admin/alerts/students.csv', params)}`, { headers })
}

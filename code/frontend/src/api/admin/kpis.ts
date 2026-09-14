// 指标与口径管理接口：只封装原有请求，不解释或修正后台业务数据。
import { http, getActiveIdentity, getToken } from '@/utils/http'

// 读取指标目录的定义与实现状态汇总。
export function getMetricSummary<T = any>(): Promise<T> {
  return http.get<T>('/admin/settings/metric-catalog/summary')
}

// 按指标筛选和分页读取目录，不在前端重算口径。
export function listMetrics<T = any>(query: string | URLSearchParams): Promise<T> {
  return http.get<T>(`/admin/settings/metric-catalog?${query}`)
}

// 读取指标与业务页面的绑定及一致性信息。
export function listMetricPages<T = any>(): Promise<T> {
  return http.get<T>('/admin/settings/metric-catalog/pages')
}

// 按指标编号读取定义、页面绑定和变更记录。
export function getMetric<T = any>(metricId: string | number): Promise<T> {
  return http.get<T>(`/admin/settings/metric-catalog/${encodeURIComponent(metricId)}`)
}

// 按当前指标筛选取得 CSV 响应，沿用原 Bearer 与身份头及下载错误处理。
export function exportMetricCatalog(query: URLSearchParams): Promise<Response> {
  const headers: Record<string, string> = { Authorization: `Bearer ${getToken()}` }
  if (getActiveIdentity()) headers['X-Active-Identity'] = getActiveIdentity()
  return fetch(`/api/admin/settings/metric-catalog/export?${query}`, { headers })
}

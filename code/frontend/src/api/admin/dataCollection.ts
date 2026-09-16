// 数据采集监控接口：只封装原有请求，不解释或修正后台业务数据。
import { getActiveIdentity, getToken, http } from '@/utils/http'

// 读取采集总览和可用任务，沿用服务端统计口径。
export function getCollectionOverview<T = any>(): Promise<T> {
  return http.get<T>('/admin/system/data-collection/overview')
}

// 按当前业务域、状态和分页读取数据源。
export function listCollectionSources<T = any>(query: string | URLSearchParams): Promise<T> {
  return http.get<T>(`/admin/system/data-collection/sources?${query}`)
}

// 按现有筛选与分页读取任务运行记录。
export function listCollectionRuns<T = any>(query: string | URLSearchParams): Promise<T> {
  return http.get<T>(`/admin/system/data-collection/runs?${query}`)
}

// 按原前一百条数据源范围读取接入确认清单。
export function getCollectionChecklist<T = any>(): Promise<T> {
  return http.get<T>('/admin/system/data-collection/sources?page=1&page_size=100')
}

// 按数据源编码读取接入状态及关联证据。
export function getCollectionSource<T = any>(code: string): Promise<T> {
  return http.get<T>(`/admin/system/data-collection/sources/${encodeURIComponent(code)}`)
}

// 读取指定运行记录的结果与技术证据。
export function getCollectionRun<T = any>(runId: string | number): Promise<T> {
  return http.get<T>(`/admin/system/data-collection/runs/${runId}`)
}

// 提交用户确认的重跑任务，任务执行由后端负责。
export function triggerCollectionTask<T = any>(body: unknown): Promise<T> {
  return http.post<T>('/admin/system/data-collection/trigger', body)
}

// 静默查询任务状态，错误提示和重试节奏由页面控制。
export function pollCollectionRun<T = any>(runId: string | number): Promise<T> {
  return http.getSilent<T>(`/admin/system/data-collection/runs/${runId}`)
}

// 读取接入核验清单 CSV，沿用原认证头，由页面负责下载和错误提示。
export function exportCollectionChecklist(): Promise<Response> {
  const headers: Record<string, string> = { Authorization: `Bearer ${getToken()}` }
  const identity = getActiveIdentity()
  if (identity) headers['X-Active-Identity'] = identity
  return fetch('/api/admin/system/data-collection/checklist.csv', { headers })
}

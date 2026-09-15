/** 表格偏好的存储边界：隔离用户与工作身份，校验文本数据，不在这里发起列表请求。 */
import { authStore } from '@/store/auth'
import { isTableDensity, type TablePreferences } from '@/types/table'

/** 与既有 DataTable 使用相同的身份解析顺序，兼容策略由接入页面选择存储标识和版本。 */
export function tablePreferenceKey(storageKey: string, configVersion: string | number = 1): string {
  const user = authStore.user
  const identity = user?.activeIdentityId
    || user?.permissionContext?.activeIdentityId
    || user?.permissionContext?.activeRole
    || user?.role
    || 'anonymous-role'
  return `bi_table_pref:${user?.username || 'anonymous'}:${identity}:${storageKey}:v${configVersion}`
}

/** 损坏或部分过期的偏好只丢弃无效字段，列是否仍存在由组件按当前列定义检查。 */
export function readTablePreferences(key: string): TablePreferences {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return {}
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    const saved = value as Record<string, unknown>
    const result: TablePreferences = {}
    for (const field of ['order', 'hidden'] as const) {
      if (Array.isArray(saved[field])) {
        result[field] = [...new Set(saved[field].filter((key): key is string => typeof key === 'string'))]
      }
    }
    if (isTableDensity(saved.density)) result.density = saved.density
    if (typeof saved.pageSize === 'number' && Number.isSafeInteger(saved.pageSize) && saved.pageSize > 0) {
      result.pageSize = saved.pageSize
    }
    return result
  } catch {
    return {}
  }
}

/** 存储被禁用时仍允许本次页面交互，不把浏览器偏好错误变成列表加载错误。 */
export function writeTablePreferences(key: string, value: TablePreferences): void {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* 当前展示仍然有效。 */ }
}

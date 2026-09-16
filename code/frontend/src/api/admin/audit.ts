// 审计日志接口：只封装原有请求，不解释或修正后台业务数据。
import { http } from '@/utils/http'

// 按操作类型和分页读取审计记录及可选动作。
export function listSecurityAudit<T = any>(query: string | URLSearchParams): Promise<T> {
  return http.get<T>('/admin/rbac/security-audit?' + query)
}

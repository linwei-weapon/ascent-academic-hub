// 系统参数接口：只封装原有请求，不解释或修正后台业务数据。
import { http } from '@/utils/http'

// 读取平台参数及其分类、选项和边界说明。
export function getSystemParameters<T = any>(): Promise<T> {
  return http.get<T>('/admin/system/parameters')
}

// 按参数键提交新值及变更原因。
export function updateSystemParameter<T = any>(parameterKey: string, body: unknown): Promise<T> {
  return http.put<T>(`/admin/system/parameters/${parameterKey}`, body)
}

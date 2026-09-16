// 基础报表接口：保留原筛选、结果包络及快照下载协议。
import { http } from '@/utils/http'

// 读取当前工作身份授权的学期、年级、学院、专业和班级选项。
export function getBasicReportOptions<T = any>(): Promise<T> {
  return http.get<T>('/admin/basic-reports/options')
}

// 以原接口标识和已应用参数读取报表，统计与权限继续由后端处理。
export function getBasicReport<T = any>(slug: string, query: URLSearchParams): Promise<T> {
  return http.get<T>(`/admin/basic-reports/${slug}?${query}`)
}

// 下载已查询结果对应的快照，认证头和服务端文件名复用公共下载函数。
export function downloadBasicReport(slug: string, query: URLSearchParams): Promise<void> {
  return http.download(`/admin/basic-reports/${slug}/export?${query}`)
}

// 教学数据总览业务请求：保留原端点、编码、参数和响应，不在前端改写统计口径。
import { http } from '@/utils/http'
import type { UrlValue } from './shared'

// 读取课程画像，保留原字段和响应约定。
export function getCourseOverview<T = any>(courseId: UrlValue, query: UrlValue): Promise<T> {
  return http.get<T>('/admin/course/' + courseId + query)
}

// 读取学院聚合对比，保留原字段和响应约定。
export function getCollegeComparison<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/admin/meta/college-comparison${query}`)
}

// 读取学院概览，保留原字段和响应约定。
export function getCollegeOverview<T = any>(collegeId: UrlValue, query: UrlValue): Promise<T> {
  return http.get<T>('/admin/college/' + collegeId + query)
}

// 读取全校教学概览，保留原字段和响应约定。
export function getDashboard<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/admin/dashboard${query}`)
}

// 读取专业概览，保留原字段和响应约定。
export function getMajorOverview<T = any>(majorId: UrlValue, query: UrlValue): Promise<T> {
  return http.get<T>('/admin/major/' + majorId + query)
}

// 学生成长与学业分析业务请求：保留原端点、编码、参数和响应，不在前端改写统计口径。
import { http } from '@/utils/http'
import type { UrlValue } from './shared'

// 读取学生学业概览，保留原字段和响应约定。
export function getStudentGrowthOverview<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/admin/students/growth/overview?${query}`)
}

// 读取学生组织对比，保留原字段和响应约定。
export function getStudentGrowthOrganizations<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/admin/students/growth/organizations?${query}`)
}

// 读取学生学业名单，保留原字段和响应约定。
export function getStudentGrowthList<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/admin/students/growth/list?${query}`)
}

// 读取学生清单，保留原字段和响应约定。
export function getStudentList<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/admin/students/list?${query}`)
}

// 读取当前人员负责学生，保留原字段和响应约定。
export function getMyStudents<T = any>(): Promise<T> {
  return http.get<T>('/admin/students/my-scope')
}

// 读取学生详情，保留原字段和响应约定。
export function getStudentDetail<T = any>(studentId: UrlValue): Promise<T> {
  return http.get<T>('/admin/student/' + studentId)
}

// 读取学生成长轨迹，保留原字段和静默失败约定。
export function getStudentGrowth<T = any>(studentId: UrlValue): Promise<T> {
  return http.getSilent<T>('/v2/students/' + studentId + '/growth?timeline_limit=80')
}

// 读取待核查方案课程，保留原字段和静默失败约定。
export function getStudentActionableCourses<T = any>(studentId: UrlValue): Promise<T> {
  return http.getSilent<T>('/v2/students/' + studentId + '/plan-courses?actionable=true&limit=200')
}

// 读取未完成方案课程，保留原字段和静默失败约定。
export function getStudentIncompleteCourses<T = any>(studentId: UrlValue): Promise<T> {
  return http.getSilent<T>('/v2/students/' + studentId + '/plan-courses?status=not_completed&limit=100')
}

// 读取学生方案建议，保留原字段和静默失败约定。
export function getStudentAdvice<T = any>(studentId: UrlValue): Promise<T> {
  return http.getSilent<T>('/v2/students/' + studentId + '/advice')
}

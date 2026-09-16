// 教学运行分析业务请求：保留原端点、编码、参数和响应，不在前端改写统计口径。
import { http } from '@/utils/http'
import type { UrlValue } from './shared'

// 读取教室占用，保留原字段和响应约定。
export function getClassroomOccupancy<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/admin/operation/classroom-occupancy?' + query)
}

// 读取开课明细，保留原字段和响应约定。
export function getCourseOfferings<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/admin/operation/courses/offerings?' + query)
}

// 读取开课供给汇总，保留原字段和响应约定。
export function getCourseSupply<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/admin/operation/courses' + query)
}

// 读取教学数据上下文，保留原字段和响应约定。
export function getOperationContext<T = any>(): Promise<T> {
  return http.get<T>('/admin/operation/data-context')
}

// 读取排课结构，保留原字段和响应约定。
export function getScheduleStrategy<T = any>(semester: string | number | boolean): Promise<T> {
  return http.get<T>(`/v2/topics/schedule-strategy?semester=${encodeURIComponent(semester)}`)
}

// 读取调停课分析，保留原字段和响应约定。
export function getScheduleChanges<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/admin/operation/schedule-changes' + query)
}

// 读取教师负荷，保留原字段和响应约定。
export function getTeacherLoad<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/admin/operation/teacher-load?' + query)
}

// 读取课程结果，保留原字段和响应约定。
export function getCourseQuality<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/v2/topics/course-quality?' + query)
}

// 读取课程结果明细，保留原字段和响应约定。
export function getCourseQualityDetail<T = any>(courseId: string | number | boolean, query: UrlValue): Promise<T> {
  return http.get<T>(`/v2/topics/course-quality/${encodeURIComponent(courseId)}/detail?${query}`)
}

// 师资保障分析业务请求：保留原端点、编码、参数和响应，不在前端改写统计口径。
import { http } from '@/utils/http'
import type { UrlValue } from './shared'

// 读取教师概览，保留原字段和响应约定。
export function getTeacherOverview<T = any>(teacherId: UrlValue, query: UrlValue): Promise<T> {
  return http.get<T>('/admin/faculty/' + teacherId + query)
}

// 读取教师排课记录，保留原字段和响应约定。
export function getTeacherSchedulePreference<T = any>(teacherId: UrlValue, semester: string | number | boolean): Promise<T> {
  return http.get<T>(`/v2/teachers/${encodeURIComponent(String(teacherId))}/schedule-preference?semester=${encodeURIComponent(semester)}`)
}

// 读取师资保障总览，保留原字段和响应约定。
export function getFacultyOverview<T = any>(semester: string | number | boolean): Promise<T> {
  return http.get<T>(`/admin/faculty/management-overview?semester=${encodeURIComponent(semester)}`)
}

// 读取课程师资列表，保留原字段和响应约定。
export function getFacultyCourses<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>(`/admin/faculty/management-courses?${query}`)
}

// 读取课程团队证据，保留原字段和响应约定。
export function getFacultyCourse<T = any>(courseId: string | number | boolean, semester: string | number | boolean): Promise<T> {
  return http.get<T>(`/admin/faculty/management-course/${encodeURIComponent(courseId)}?semester=${encodeURIComponent(semester)}`)
}

// 读取教师教学经历，保留原字段和响应约定。
export function getFacultyTeacher<T = any>(teacherId: string | number | boolean, query: UrlValue): Promise<T> {
  return http.get<T>(`/admin/faculty/management-teacher/${encodeURIComponent(teacherId)}?${query}`)
}

// 读取课程团队搜索，保留原字段和响应约定。
export function searchFacultyTeam<T = any>(keyword: string | number | boolean): Promise<T> {
  return http.get<T>('/admin/faculty/team/search?q=' + encodeURIComponent(keyword))
}

// 读取团队课程资料，保留原字段和响应约定。
export function getTeamCourse<T = any>(courseId: string | number | boolean, semester: string | number | boolean): Promise<T> {
  return http.get<T>(`/admin/faculty/management-course/${encodeURIComponent(courseId)}?semester=${encodeURIComponent(semester)}`)
}

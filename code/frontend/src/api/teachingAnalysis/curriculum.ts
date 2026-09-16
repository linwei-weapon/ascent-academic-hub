// 培养质量分析业务请求：保留原端点、编码、参数和响应，不在前端改写统计口径。
import { http } from '@/utils/http'
import type { UrlValue } from './shared'

// 读取课程目标达成情况，保留原字段和响应约定。
export function getCourseObjectives<T = any>(majorId: UrlValue): Promise<T> {
  return http.get<T>('/admin/curriculum/objectives/' + majorId)
}

// 读取培养规则变更列表，保留原字段和响应约定。
export function getCurriculumRuleChanges<T = any>(): Promise<T> {
  return http.get<T>('/admin/curriculum/rule-changes')
}

// 读取培养规则选项，保留原字段和响应约定。
export function getCurriculumRuleOptions<T = any>(): Promise<T> {
  return http.get<T>('/admin/curriculum/rule-options')
}

// 提交培养规则变更草稿，保留原字段和响应约定。
export function createCurriculumRuleChange<T = any>(body?: unknown): Promise<T> {
  return http.post<T>('/admin/curriculum/rule-changes', body)
}

// 提交培养规则送审或激活，保留原字段和响应约定。
export function actOnCurriculumRuleChange<T = any>(changeId: UrlValue, action: UrlValue, body?: unknown): Promise<T> {
  return http.post<T>(`/admin/curriculum/rule-changes/${changeId}/${action}`, body)
}

// 提交培养规则审核，保留原字段和响应约定。
export function reviewCurriculumRuleChange<T = any>(changeId: UrlValue, body?: unknown): Promise<T> {
  return http.post<T>(`/admin/curriculum/rule-changes/${changeId}/review`, body)
}

// 读取培养规则变更详情，保留原字段和响应约定。
export function getCurriculumRuleChange<T = any>(changeId: UrlValue): Promise<T> {
  return http.get<T>(`/admin/curriculum/rule-changes/${changeId}`)
}

// 读取培养规则影响预览，保留原字段和响应约定。
export function previewCurriculumRuleChange<T = any>(changeId: UrlValue): Promise<T> {
  return http.get<T>(`/admin/curriculum/rule-changes/${changeId}/preview`)
}

// 读取毕业要求对应方案，保留原字段和响应约定。
export function getGraduateRequirementPlan<T = any>(planId: UrlValue): Promise<T> {
  return http.get<T>('/v2/curriculum/plans/' + planId)
}

// 读取培养方案执行概览，保留原字段和响应约定。
export function getCurriculumOverview<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/v2/curriculum/management-overview?' + query)
}

// 读取方案瓶颈课程，保留原字段和响应约定。
export function getCurriculumCourses<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/v2/curriculum/management-courses?' + query)
}

// 读取方案核查学生名单，保留原字段和响应约定。
export function getCurriculumStudents<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/v2/curriculum/management-students?' + query)
}

// 读取方案学生证据，保留原字段和响应约定。
export function getCurriculumStudentEvidence<T = any>(studentId: string | number | boolean): Promise<T> {
  return http.get<T>('/v2/topics/graduation-readiness/student/' + encodeURIComponent(studentId))
}

// 读取当前培养方案，保留原字段和响应约定。
export function getCurriculumPlan<T = any>(planId: UrlValue): Promise<T> {
  return http.get<T>('/v2/curriculum/plans/' + planId)
}

// 读取培养方案选项，保留原字段和响应约定。
export function getCurriculumOptions<T = any>(): Promise<T> {
  return http.get<T>('/v2/curriculum/options')
}

// 读取方案完成进度，保留原字段和响应约定。
export function getPlanProgress<T = any>(planId: UrlValue): Promise<T> {
  return http.get<T>(`/v2/curriculum/progress/${planId}?limit=1000`)
}

// 读取学生方案课程，保留原字段和响应约定。
export function getProgressStudentCourses<T = any>(studentId: string | number | boolean): Promise<T> {
  return http.get<T>(`/v2/students/${encodeURIComponent(studentId)}/plan-courses?limit=1000`)
}

// 读取毕业核查选项，保留原字段和响应约定。
export function getGraduationOptions<T = any>(): Promise<T> {
  return http.get<T>('/v2/curriculum/options')
}

// 读取毕业准备核查，保留原字段和响应约定。
export function getGraduationReadiness<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/v2/topics/graduation-readiness?' + query)
}

// 读取毕业准备学生证据，保留原字段和响应约定。
export function getGraduationStudent<T = any>(studentId: string | number | boolean): Promise<T> {
  return http.get<T>('/v2/topics/graduation-readiness/student/' + encodeURIComponent(studentId))
}

// 读取课程保障学生名单，保留原字段和响应约定。
export function getGraduationSupplyStudents<T = any>(query: UrlValue): Promise<T> {
  return http.get<T>('/v2/curriculum/management-students?' + query)
}

// 读取毕业课程保障证据，保留原字段和响应约定。
export function getGraduationSupply<T = any>(encodedCourseId: UrlValue, querySuffix: UrlValue): Promise<T> {
  return http.get<T>('/v2/curriculum/course-supply/' + encodedCourseId + querySuffix)
}

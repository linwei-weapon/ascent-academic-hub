import { http } from './http'

export interface AIInsightQuery {
  scenario?: string
  level?: string
  type?: string
  status?: string
  college?: string
}

export function getStudentAIInsight(studentId: string, scenario = 'alert') {
  return http.get<any>(`/admin/ai/insight/student/${encodeURIComponent(studentId)}?scenario=${encodeURIComponent(scenario)}`)
}

export function getAlertSummaryAIInsight(query: AIInsightQuery = {}) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value) params.set(key, value)
  }
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/alert-summary${qs ? `?${qs}` : ''}`)
}

export function getGraduationStudentAIInsight(studentId: string) {
  return http.get<any>(`/admin/ai/insight/graduation-readiness/student/${encodeURIComponent(studentId)}`)
}

export function getGraduationCourseAIInsight(courseId: string) {
  return http.get<any>(`/admin/ai/insight/graduation-readiness/course/${encodeURIComponent(courseId)}`)
}

export function getOperationCourseAIInsight(courseId: string, semester?: string) {
  const params = new URLSearchParams()
  if (semester) params.set('semester', semester)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/operation/course-offering/${encodeURIComponent(courseId)}${qs ? `?${qs}` : ''}`)
}

export function getClassroomOccupancyAIInsight(query: { semester?: string; building?: string; includeEvening?: boolean } = {}) {
  const params = new URLSearchParams()
  if (query.semester) params.set('semester', query.semester)
  if (query.building) params.set('building', query.building)
  if (query.includeEvening !== undefined) params.set('include_evening', String(query.includeEvening))
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/operation/classroom-occupancy${qs ? `?${qs}` : ''}`)
}

export function getScheduleChangesAIInsight(query: { semester?: string; college?: string } = {}) {
  const params = new URLSearchParams()
  if (query.semester) params.set('semester', query.semester)
  if (query.college) params.set('college', query.college)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/operation/schedule-changes${qs ? `?${qs}` : ''}`)
}

export function getScheduleTeacherAIInsight(teacherId: string, semester?: string) {
  const params = new URLSearchParams()
  if (semester) params.set('semester', semester)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/operation/schedule-changes/teacher/${encodeURIComponent(teacherId)}${qs ? `?${qs}` : ''}`)
}

export function getTeacherLoadAIInsight(query: { semester?: string; college?: string; title?: string } = {}) {
  const params = new URLSearchParams()
  if (query.semester) params.set('semester', query.semester)
  if (query.college) params.set('college', query.college)
  if (query.title) params.set('title', query.title)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/operation/teacher-load${qs ? `?${qs}` : ''}`)
}

export function getTeacherLoadTeacherAIInsight(teacherId: string, semester?: string) {
  const params = new URLSearchParams()
  if (semester) params.set('semester', semester)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/operation/teacher-load/teacher/${encodeURIComponent(teacherId)}${qs ? `?${qs}` : ''}`)
}

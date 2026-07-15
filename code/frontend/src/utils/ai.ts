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

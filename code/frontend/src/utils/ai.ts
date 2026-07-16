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

export function getFacultyResourceAIInsight(semester?: string) {
  const params = new URLSearchParams()
  if (semester) params.set('semester', semester)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/faculty-resource-risk${qs ? `?${qs}` : ''}`)
}

export function getFacultyCourseAIInsight(courseId: string, semester?: string) {
  const params = new URLSearchParams()
  if (semester) params.set('semester', semester)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/insight/faculty-resource-risk/course/${encodeURIComponent(courseId)}${qs ? `?${qs}` : ''}`)
}

export function getManagementBriefing(query: { period?: 'morning' | 'term'; semester?: string } = {}) {
  const params = new URLSearchParams()
  if (query.period) params.set('period', query.period)
  if (query.semester) params.set('semester', query.semester)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/briefing/management${qs ? `?${qs}` : ''}`)
}

export function getGraduationCourseSupportSimulation(query: {
  semester?: string
  limit?: number
  addedClasses?: number
  classCapacity?: number
  availableTeachers?: number
  priorityFocus?: 'balanced' | 'failed' | 'verification'
} = {}) {
  const params = new URLSearchParams()
  if (query.semester) params.set('semester', query.semester)
  if (query.limit) params.set('limit', String(query.limit))
  if (query.addedClasses !== undefined) params.set('added_classes', String(query.addedClasses))
  if (query.classCapacity !== undefined) params.set('class_capacity', String(query.classCapacity))
  if (query.availableTeachers !== undefined) params.set('available_teachers', String(query.availableTeachers))
  if (query.priorityFocus) params.set('priority_focus', query.priorityFocus)
  const qs = params.toString()
  return http.get<any>(`/admin/ai/simulation/graduation-course-support${qs ? `?${qs}` : ''}`)
}

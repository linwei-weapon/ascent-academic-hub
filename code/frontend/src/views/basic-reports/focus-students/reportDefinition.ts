// 重点关注学生名单：维护原报表编号、查询条件和结果列，计算仍由后端负责。
import type { BasicReportDefinition } from '@/types/basicReports'
import { c } from '../shared/reportColumns'

export const reportDefinition: BasicReportDefinition = {
    reportId: 'RPT-07', slug: 'rpt-07', title: '重点关注学生名单', path: '/admin/basic-reports/focus-students', requiredFilters: ['semesterId'],
    columns: [c('sequence', '序号', { width: 76, fixed: 'left', region: 'identity' }), c('name', '姓名', { fixed: 'left', region: 'identity' }), c('studentId', '学号', { minWidth: 145, fixed: 'left', region: 'identity' }), c('majorClass', '专业班级', { minWidth: 220 }), c('mentor', '导师'), c('failedCredits', '挂科学分'), c('unresolvedCourseCount', '挂科门数'), c('courseEvidence', '具体情况', { minWidth: 390, tooltip: false })],
  }

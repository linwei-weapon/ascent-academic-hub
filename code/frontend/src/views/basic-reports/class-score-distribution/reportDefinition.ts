// 各班级成绩分布：维护原报表编号、查询条件和结果列，计算仍由后端负责。
import type { BasicReportDefinition } from '@/types/basicReports'
import { c, base } from '../shared/reportColumns'

export const reportDefinition: BasicReportDefinition = {
    reportId: 'RPT-04B', slug: 'rpt-04b', title: '各班级成绩分布', path: '/admin/basic-reports/class-score-distribution', requiredFilters: [...base, 'organizationId', 'majorCode'],
    columns: [c('classCode', '班级', { minWidth: 180, fixed: 'left', region: 'identity' }), c('rankedStudents', '总人数'), c('top20Display', '专业前20%', { minWidth: 150 }), c('top20To50Display', '专业前20-50%', { minWidth: 170 }), c('top50To80Display', '专业前50-80%', { minWidth: 170 }), c('bottom20Display', '专业后20%', { minWidth: 150 })],
  }

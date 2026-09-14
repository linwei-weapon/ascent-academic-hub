// 各班大学英语四级通过情况：维护原报表编号、查询条件和结果列，计算仍由后端负责。
import type { BasicReportDefinition } from '@/types/basicReports'
import { c, rate, base } from '../shared/reportColumns'

export const reportDefinition: BasicReportDefinition = {
    reportId: 'RPT-06', slug: 'rpt-06', title: '各班大学英语四级通过情况', path: '/admin/basic-reports/cet4-pass', requiredFilters: base,
    columns: [c('classCode', '班级', { minWidth: 180, fixed: 'left', region: 'identity' }), c('studentCount', '总人数'), c('cet4PassedStudents', '四级通过人数'), rate('cet4PassRate', '四级通过率'), c('cet4PassRateRank', '四级通过率排行', { minWidth: 140, align: 'center', required: true })],
  }

// 各班级挂科门数具体情况：维护原报表编号、查询条件和结果列，计算仍由后端负责。
import type { BasicReportDefinition } from '@/types/basicReports'
import { c, base } from '../shared/reportColumns'

export const reportDefinition: BasicReportDefinition = {
    reportId: 'RPT-04A', slug: 'rpt-04a', title: '各班级挂科门数具体情况', path: '/admin/basic-reports/class-failure-count', requiredFilters: base,
    columns: [c('classCode', '班级', { minWidth: 180, fixed: 'left', region: 'identity' }), c('studentCount', '总人数'), c('oneToTwo', '1-2科'), c('threeToFive', '3-5科'), c('sixOrMore', '5科以上')],
  }

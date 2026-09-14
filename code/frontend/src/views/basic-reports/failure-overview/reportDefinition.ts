// 年级总体挂科情况：维护原报表编号、查询条件和结果列，计算仍由后端负责。
import type { BasicReportDefinition } from '@/types/basicReports'
import { c, base } from '../shared/reportColumns'

export const reportDefinition: BasicReportDefinition = {
    reportId: 'RPT-01', slug: 'rpt-01', title: '年级总体挂科情况', path: '/admin/basic-reports/failure-overview', requiredFilters: base,
    columns: [c('category', '本科生', { minWidth: 300, fixed: 'left', region: 'identity' }), c('gender', '性别', { width: 90 }), c('countDisplay', '人数'), c('rateDisplay', '比例', { minWidth: 190, align: 'right' })],
    mergeBy: { category: 'categoryKey' },
  }

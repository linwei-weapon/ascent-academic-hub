// 各专业整体与男女挂科率比较：维护原报表编号、查询条件和结果列，计算仍由后端负责。
import type { BasicReportDefinition } from '@/types/basicReports'
import { c, rate, base } from '../shared/reportColumns'

export const reportDefinition: BasicReportDefinition = {
    reportId: 'RPT-03', slug: 'rpt-03', title: '各专业整体与男女挂科率比较', path: '/admin/basic-reports/major-gender-failure', requiredFilters: base,
    columns: [c('majorName', '专业', { minWidth: 220, fixed: 'left', region: 'identity' }), c('studentCountDisplay', '专业人数'), c('failedStudentsDisplay', '整体挂科人数'), rate('failureRate', '整体挂科率'), c('maleFailureDisplay', '男生挂科率', { minWidth: 180 }), c('femaleFailureDisplay', '女生挂科率', { minWidth: 180 })],
  }

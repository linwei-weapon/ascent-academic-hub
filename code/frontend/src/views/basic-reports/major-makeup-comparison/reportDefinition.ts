// 各专业补考前后挂科率比较：维护原报表编号、查询条件和结果列，计算仍由后端负责。
import type { BasicReportDefinition } from '@/types/basicReports'
import { c, rate, base } from '../shared/reportColumns'

export const reportDefinition: BasicReportDefinition = {
    reportId: 'RPT-02', slug: 'rpt-02', title: '各专业补考前后挂科率比较', path: '/admin/basic-reports/major-makeup-comparison', requiredFilters: base,
    columns: [c('majorName', '专业名称', { minWidth: 180, fixed: 'left', region: 'identity' }), c('studentCountDisplay', '专业人数'), c('failedBeforeDisplay', '已挂人数'), rate('failedBeforeRate', '挂科率（补考前）'), c('failedAfterDisplay', '在挂人数'), rate('failedAfterRate', '挂科率（补考后）'), rate('passRate', '通过率')],
  }

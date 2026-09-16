// 按原访问地址汇总九张基础报表定义，保持编号、顺序及默认回退目标。
import type { BasicReportDefinition } from '@/types/basicReports'
export type { BasicReportDefinition, BasicReportFilter } from '@/types/basicReports'
import { reportDefinition as definition1 } from '../failure-overview/reportDefinition'
import { reportDefinition as definition2 } from '../major-makeup-comparison/reportDefinition'
import { reportDefinition as definition3 } from '../major-gender-failure/reportDefinition'
import { reportDefinition as definition4 } from '../class-failure-count/reportDefinition'
import { reportDefinition as definition5 } from '../class-score-distribution/reportDefinition'
import { reportDefinition as definition6 } from '../course-makeup-comparison/reportDefinition'
import { reportDefinition as definition7 } from '../cet4-pass/reportDefinition'
import { reportDefinition as definition8 } from '../focus-students/reportDefinition'
import { reportDefinition as definition9 } from '../academic-warning-roster/reportDefinition'

export const reportDefinitions: Record<string, BasicReportDefinition> = {
  '/admin/basic-reports/failure-overview': definition1,
  '/admin/basic-reports/major-makeup-comparison': definition2,
  '/admin/basic-reports/major-gender-failure': definition3,
  '/admin/basic-reports/class-failure-count': definition4,
  '/admin/basic-reports/class-score-distribution': definition5,
  '/admin/basic-reports/course-makeup-comparison': definition6,
  '/admin/basic-reports/cet4-pass': definition7,
  '/admin/basic-reports/focus-students': definition8,
  '/admin/basic-reports/academic-warning-roster': definition9,
}

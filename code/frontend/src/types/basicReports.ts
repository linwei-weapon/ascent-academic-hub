// 基础报表的前端定义和展示组件参数，沿用现有筛选字段及列协议。
import type { AppTableColumn } from '@/types/table'

export type BasicReportFilter = 'semesterId' | 'entryGrade' | 'organizationId' | 'majorCode' | 'classCode'

export interface BasicReportDefinition {
  reportId: string
  slug: string
  title: string
  path: string
  requiredFilters: BasicReportFilter[]
  columns: AppTableColumn[]
  mergeBy?: Record<string, string>
}

export interface BasicReportTableProps {
  definition: BasicReportDefinition
  result: any
  spanMethod: (parameters: any) => number[]
  rowClassName: (parameters: any) => string
}

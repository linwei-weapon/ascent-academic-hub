/** 公共表格的展示契约；业务字段和查询请求仍由各页面定义。 */
import type { TableColumnCtx } from 'element-plus'

export type TableDensity = 'compact' | 'default' | 'loose'
export type TableRow = Record<string, any>
export type TableColumnRegion = 'identity' | 'business' | 'action'

export interface AppTableColumn {
  /** 稳定标识，同时作为 col-* / header-* 插槽的后缀。 */
  key: string
  label: string
  prop?: string
  /** 固定像素宽度，适合操作列；设置后优先于 minWidth，不参与剩余空间分配。 */
  width?: number | string
  /** 普通数据列使用最小宽度；组件按此比例分配剩余空间，窄屏时保留横向滚动。 */
  minWidth?: number | string
  align?: 'left' | 'center' | 'right'
  /** 仅固定横向滚动位置；搭配 minWidth 时仍可自适应列宽。 */
  fixed?: boolean | 'left' | 'right'
  sortable?: boolean | 'custom'
  defaultVisible?: boolean
  /** 必选列不能被偏好隐藏；识别列和操作列的区域保持稳定。 */
  required?: boolean
  region?: TableColumnRegion
  tooltip?: boolean
  formatter?: (row: TableRow, column: TableColumnCtx<TableRow>, value: unknown, index: number) => string
}

export interface TablePreferences {
  order?: string[]
  hidden?: string[]
  density?: TableDensity
  /** 仅保留旧记录中的页长；新的页面本地分页不从该字段恢复。 */
  pageSize?: number
}

export const TABLE_PAGE_SIZES = [10, 20, 50, 100] as const
export const DEFAULT_TABLE_PAGE_SIZE = 20

export const TABLE_DENSITY_SIZES = {
  compact: 'small',
  default: 'default',
  loose: 'large',
} as const

/** 本地存储是文本边界，不能仅靠类型断言信任保存的密度值。 */
export function isTableDensity(value: unknown): value is TableDensity {
  return value === 'compact' || value === 'default' || value === 'loose'
}

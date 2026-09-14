// 基础报表列工厂：复用原列默认值、比例和空值显示。
import type { DataTableColumn } from '@/components/DataTable.vue'
import type { BasicReportFilter } from '@/types/basicReports'

// 按原精度显示比例，空值保持破折号，不重新计算报表指标。
const pct = (_row: any, _column: any, value: number | null) => value == null ? '—' : `${(value * 100).toFixed(2)}%`

// 沿用原空值展示，保留数值零和非空文本。
const dash = (_row: any, _column: any, value: any) => value == null || value === '' ? '—' : value

// 建立固定业务列的默认展示参数，具体报表可覆盖宽度等属性。
export const c = (key: string, label: string, extra: Partial<DataTableColumn> = {}): DataTableColumn => ({
  key, label, minWidth: 120, tooltip: true, formatter: dash, required: true, ...extra,
})

// 为比例列复用原百分比格式和右对齐规则。
export const rate = (key: string, label: string) => c(key, label, { align: 'right', formatter: pct })

// 复用原学期与年级必选组合，各报表继续按定义选择。
export const base: BasicReportFilter[] = ['semesterId', 'entryGrade']

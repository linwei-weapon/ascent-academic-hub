// 基础报表列工厂：复用原列默认值、比例和空值显示。
import type { AppTableColumn } from '@/types/table'
import type { BasicReportFilter } from '@/types/basicReports'

// 按原精度显示比例，空值保持破折号，不重新计算报表指标。
const pct: AppTableColumn['formatter'] = (_row, _column, value) => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`

// 沿用原空值展示，保留数值零和非空文本。
const dash = (_row: any, _column: any, value: any) => value == null || value === '' ? '—' : value

// 建立固定业务列的默认展示参数，具体报表可覆盖宽度等属性。
export const c = (key: string, label: string, extra: Partial<AppTableColumn> = {}): AppTableColumn => ({
  key, label, minWidth: 120, align: 'center', tooltip: true, formatter: dash, required: true, ...extra,
})

// 比例沿用原百分比精度，展示与其他列统一居中。
export const rate = (key: string, label: string) => c(key, label, { formatter: pct })

// 复用原学期与年级必选组合，各报表继续按定义选择。
export const base: BasicReportFilter[] = ['semesterId', 'entryGrade']

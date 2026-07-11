/**
 * 纯前端导出（零依赖）：CSV（UTF-8 BOM + Blob 下载）+ PDF（走浏览器打印）。
 * 不引入 xlsx/sheetjs/jspdf。导出当前页已加载/已筛选的数据。
 */

export interface ExportCol {
  prop: string
  label: string
  /** 可选：从行取值（用于含 html 渲染列时取原始值）。缺省取 row[prop]。 */
  value?: (row: any) => any
}

function csvCell(v: any): string {
  if (v === null || v === undefined) return ''
  const s = String(v)
  // 含逗号/双引号/换行：用双引号包裹，内部双引号转义为两个
  if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"'
  return s
}

export function exportCsv(filename: string, columns: ExportCol[], rows: any[]): void {
  const header = columns.map(c => csvCell(c.label)).join(',')
  const body = rows.map(row =>
    columns.map(c => csvCell(c.value ? c.value(row) : row[c.prop])).join(',')
  ).join('\r\n')
  const content = '\uFEFF' + header + '\r\n' + body  // UTF-8 BOM，Excel 正确识别中文
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.csv') ? filename : filename + '.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function printReport(): void {
  window.print()
}

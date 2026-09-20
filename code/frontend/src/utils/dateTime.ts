export type DateTimeValue = string | number | Date | null | undefined

export interface DateTimeOptions {
  precision?: 'second' | 'minute' | 'date'
  includeYear?: boolean
  fallback?: string
}

const beijingFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

/**
 * 默认显示 YYYY-MM-DD HH:mm:ss。带时区的时间、Date 和毫秒时间戳统一显示北京时间；
 * 无时区字符串保留原钟面时间。仅有年月或日期时保留原精度，不补造时间。
 */
export function formatDateTime(value: DateTimeValue, options: DateTimeOptions = {}): string {
  const { precision = 'second', includeYear = true, fallback = '—' } = options
  if (value == null || value === '') return fallback

  let date: Date | undefined
  let dateText = ''
  let timeText = ''
  if (typeof value === 'string') {
    const text = value.trim()
    // 接受接口常用的 ISO / SQL 时间格式，避免依赖浏览器对模糊日期的解析。
    const match = /^(\d{4})-(\d{2})(?:-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:?\d{2})?)?)?$/i.exec(text)
    if (!match) return fallback
    const [, year, month, day, hour, minute, second, fraction, zone] = match
    const datePart = `${year}-${month}-${day || '01'}`
    const calendarDate = new Date(`${datePart}T00:00:00Z`)
    if (Number.isNaN(calendarDate.getTime()) || calendarDate.toISOString().slice(0, 10) !== datePart) return fallback
    if (hour !== undefined && (Number(hour) > 23 || Number(minute) > 59 || Number(second || 0) > 59)) return fallback

    dateText = day ? datePart : `${year}-${month}`
    if (hour !== undefined) {
      timeText = `${hour}:${minute}:${second || '00'}`
      if (zone) {
        const offset = zone.toUpperCase() === 'Z' ? 'Z' : zone.replace(/([+-]\d{2})(\d{2})$/, '$1:$2')
        const millis = fraction ? `.${fraction.slice(0, 3).padEnd(3, '0')}` : ''
        date = new Date(`${datePart}T${timeText}${millis}${offset}`)
      }
    }
  } else if (value instanceof Date || typeof value === 'number') {
    date = new Date(value instanceof Date ? value.getTime() : value)
  } else {
    return fallback
  }

  if (date) {
    if (Number.isNaN(date.getTime())) return fallback
    const parts = Object.fromEntries(beijingFormatter.formatToParts(date).map(part => [part.type, part.value]))
    dateText = `${parts.year}-${parts.month}-${parts.day}`
    timeText = `${parts.hour}:${parts.minute}:${parts.second}`
  }

  const displayDate = includeYear ? dateText : dateText.slice(5)
  if (!timeText || precision === 'date') return displayDate
  return `${displayDate} ${precision === 'minute' ? timeText.slice(0, 5) : timeText}`
}

/** 信号卡片共享元信息：四种卡片（结论/风险/方案/证据）统一取用。 */
import type { DecisionSignal } from '@/types/decision'
import { SEVERITY_META, CHANGE_META, TRACKING_META } from '@/types/decision'

export function severityMeta(s: DecisionSignal) {
  return SEVERITY_META[s.severity] || SEVERITY_META.low
}

export function changeMeta(s: DecisionSignal) {
  return CHANGE_META[s.change] || CHANGE_META.ongoing
}

export function trackingMeta(s: DecisionSignal) {
  const status = s.tracking?.status || ''
  return TRACKING_META[status] || { label: status, tag: 'info' as const }
}

export function confidenceLabel(s: DecisionSignal): string {
  return ({ high: '高', medium: '中', limited: '有限' } as Record<string, string>)[s.confidence]
    || s.confidence
}

/** 依据数字：默认取前 n 条，可点击下钻证据卡。 */
export function factEntries(s: DecisionSignal, n = 4): [string, unknown][] {
  return Object.entries(s.facts || {}).slice(0, n)
}

export function evidenceTitle(s: DecisionSignal): string {
  return `数据表 ${s.evidence.table} · 条件 ${s.evidence.condition} · ${s.data_boundary}`
}

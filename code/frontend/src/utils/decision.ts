// AI 查证导航工具；旧请求导入路径通过 API 兼容导出继续可用。
export * from '@/api/aiDecision/briefing'
export * from '@/api/aiDecision/evidence'
export * from '@/api/aiDecision/configuration'
export * from '@/api/aiDecision/advice'

/** 统一的查证入口：只读证据页在新浏览器标签页打开，noopener 隔离，主标签页状态不动。
    不带 width/height 等窗口特征参数，确保浏览器按用户默认开新标签页而非弹窗。 */
export function openEvidenceWindow(signalId: string) {
  const url = `${window.location.origin}${window.location.pathname}#/admin/verify/signal/${encodeURIComponent(signalId)}`
  window.open(url, '_blank', 'noopener')
}

/** 明细清单在新浏览器标签页打开（与查证窗口同一策略），主对话窗口状态不动。 */
export function openDetailWindow(signalId: string, fact: string) {
  const url = `${window.location.origin}${window.location.pathname}#/admin/verify/signal/${encodeURIComponent(signalId)}/detail?fact=${encodeURIComponent(fact)}`
  window.open(url, '_blank', 'noopener')
}

import type {
  AIInterventionStatus,
  AIManagementAction,
  AIManagementInsight,
} from '@/types/ai'

const interventionLabels: Record<AIInterventionStatus, string> = {
  action_required: '需优先核查',
  verification_required: '优先核验',
  watch: '持续观察',
  no_intervention: '当前无需AI介入',
}

function normalizeSourceLabel(label: string) {
  if (label === '离线大模型研判样本') return label
  return String(label || '规则研判')
    .replace('AI增强研判样本', 'AI辅助研判')
    .replace('AI增强管理简报样本', 'AI辅助管理简报')
    .replace('AI增强决策模拟样本', 'AI辅助决策模拟')
    .replace('AI增强', 'AI辅助')
    .replace('样本', '')
}

function roleTokens(roleName: string) {
  const value = String(roleName || '')
  if (value.includes('教务处') || value.includes('系统管理') || value.includes('校领导')) return ['教务处']
  if (value.includes('学院')) return ['二级学院', '学院']
  if (value.includes('辅导员')) return ['辅导员']
  if (value.includes('班主任') || value.includes('导师')) return ['班主任', '导师']
  if (value.includes('排课') || value.includes('运行')) return ['排课', '运行']
  return []
}

function roleAction(raw: any, roleName: string): AIManagementAction | null {
  const suggestions = Array.isArray(raw?.suggestions) ? raw.suggestions : []
  const tokens = roleTokens(roleName)
  const backend = raw?.primaryAction || {}
  const backendMatchesRole = !tokens.length || tokens.some((token) => String(backend?.role || '').includes(token))
  if (backend?.action && backendMatchesRole) {
    return {
      role: backend.role || roleName || '当前授权管理角色',
      action: backend.action,
      detail: backend.detail || '',
      timing: backend.timing || '下一业务节点前',
      expectedResult: backend.expectedResult || '形成已核实的问题清单和后续处理依据',
    }
  }
  const matched = suggestions.find((item: any) => tokens.some((token) => String(item?.role || '').includes(token)))
  if (!matched) return null
  return {
    role: matched.role || roleName || '当前授权管理角色',
    action: matched.action || '查看业务证据并确认核查范围',
    detail: matched.detail || '',
    timing: raw?.primaryAction?.timing || '下一业务节点前',
    expectedResult: raw?.primaryAction?.expectedResult || '形成已核实的问题清单和后续处理依据',
  }
}

function fallbackStatus(raw: any): AIInterventionStatus {
  const risk = String(raw?.riskLevel || '').toLowerCase()
  const tone = String(raw?.riskTone || '').toLowerCase()
  if (risk === 'critical' || risk === 'high' || tone === 'danger') return 'action_required'
  if (risk === 'warning' || risk === 'medium' || tone === 'warning') return 'watch'
  if (risk === 'low' || tone === 'success') return 'no_intervention'
  return 'watch'
}

export function normalizeAIInsight(raw: any, roleName = ''): AIManagementInsight | null {
  if (!raw) return null
  const status = (raw.intervention?.status || fallbackStatus(raw)) as AIInterventionStatus
  const evidence = Array.isArray(raw.evidence) ? raw.evidence : []
  const reasons = Array.isArray(raw.reasons) ? raw.reasons.filter(Boolean).slice(0, 3) : []
  const backendAction = raw.primaryAction || {}
  const matchedAction = roleAction(raw, roleName)
  const primaryAction: AIManagementAction = matchedAction || {
    role: backendAction.role || roleName || '当前授权管理角色',
    action: backendAction.action || raw.nextActions?.[0] || '查看业务证据并确认是否需要纳入本轮核查',
    detail: backendAction.detail || '',
    timing: backendAction.timing || '下一业务节点前',
    expectedResult: backendAction.expectedResult || '形成已核实的问题清单和后续处理依据',
  }
  const alternativeSource = Array.isArray(raw.suggestions)
    ? raw.suggestions
    : Array.isArray(raw.alternativeActions) ? raw.alternativeActions : []
  const alternativeActions = alternativeSource
    .filter((item: any) => item?.action && item.action !== primaryAction.action)
    .slice(0, 2)
  const profile = raw.profile || {}
  const meta = [profile.college, profile.major, profile.className].filter(Boolean).join(' · ')
  return {
    raw,
    targetName: raw.targetName || raw.targetId || '当前对象',
    targetMeta: meta || raw.scopeLabel || '当前分析范围',
    generatedAt: raw.generatedAt || raw.traceability?.asOfTime || '',
    sourceLabel: normalizeSourceLabel(raw.sourceLabel),
    confidence: raw.confidence || '中',
    intervention: {
      status,
      label: raw.intervention?.label || interventionLabels[status],
      priority: raw.intervention?.priority || (status === 'action_required' ? 'high' : status === 'verification_required' || status === 'watch' ? 'medium' : 'low'),
      priorityReasons: raw.intervention?.priorityReasons || reasons,
    },
    decision: {
      headline: raw.decision?.headline || raw.summary || '当前对象需要结合业务证据进一步核查。',
      whyNow: raw.decision?.whyNow || reasons,
      impactScope: raw.decision?.impactScope || evidence.slice(0, 3).map((item: any) => `${item.label} ${item.value}`).join('；'),
      consequence: raw.decision?.consequence || '若不先核查关键证据，可能造成管理注意力分散或判断依据不足。',
    },
    comparison: {
      available: Boolean(raw.comparison?.available),
      baseline: raw.comparison?.baseline || '当前仅有单期或当前快照证据，不能判断是否恶化或改善。',
      changes: Array.isArray(raw.comparison?.changes) ? raw.comparison.changes : [],
    },
    primaryAction,
    alternativeActions,
    evidence,
    focusItems: Array.isArray(raw.focusItems) ? raw.focusItems : [],
    traceability: raw.traceability || {},
    explanationSources: raw.explanationSources || raw.traceability?.explanationSources || [],
    limitations: Array.isArray(raw.limitations) ? raw.limitations : [],
  }
}

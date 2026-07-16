export type AIInterventionStatus =
  | 'action_required'
  | 'verification_required'
  | 'watch'
  | 'no_intervention'

export interface AIIntervention {
  status: AIInterventionStatus
  label: string
  priority: 'high' | 'medium' | 'low'
  priorityReasons: string[]
}

export interface AIManagementAction {
  role: string
  action: string
  detail?: string
  timing?: string
  expectedResult?: string
}

export interface AIComparison {
  available: boolean
  baseline: string
  changes: string[]
}

export interface AIManagementDecision {
  headline: string
  whyNow: string[]
  impactScope: string
  consequence: string
}

export interface AIManagementInsight {
  raw: any
  targetName: string
  targetMeta: string
  generatedAt: string
  sourceLabel: string
  confidence: string
  intervention: AIIntervention
  decision: AIManagementDecision
  comparison: AIComparison
  primaryAction: AIManagementAction
  alternativeActions: AIManagementAction[]
  evidence: any[]
  focusItems: any[]
  traceability: any
  explanationSources: any[]
  limitations: string[]
}

/** AI管理决策（新版）类型定义：与 backend/skills/protocol.py 对齐。 */

export type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

export type Severity = 'critical' | 'high' | 'medium' | 'low'
export type SignalChange = 'new' | 'upgraded' | 'ongoing' | 'resolved'

export interface SignalAction {
  owner: string
  what: string
  when: string
  rationale: string
}

export interface SignalEvidence {
  table: string
  condition: string
  verify_route: string
  freshness: string
}

export interface SignalEntity {
  type: string
  id: string
  name: string
}

export interface TrackingState {
  status: 'open' | 'in_progress' | 'done' | 'dismissed'
  assignee?: string | null
  note?: string | null
  updated_at?: string | null
}

export interface DecisionSignal {
  signal_id: string
  skill_id: string
  signal_type: string
  severity: Severity
  headline: string
  facts: Record<string, string>
  entity: SignalEntity
  action: SignalAction
  consequence: string
  confidence: string
  evidence: SignalEvidence
  context: Record<string, any>
  related: string[]
  data_boundary: string
  change: SignalChange
  suggested_questions: string[]
  hotspot: boolean
  tracking: TrackingState | null
}

export interface SkillSection {
  skill_id: string
  skill_name: string
  management_question: string
  summary_stats: Record<string, any>
  exclusions: { what: string; why: string }[]
  data_readiness: { ready: boolean; items: any[] }
  data_boundary: string
  config_version: string
  signals: DecisionSignal[]
}

export interface FollowupItem {
  signal_id: string
  skill_id: string
  headline: string
  entity: SignalEntity
  action: SignalAction
  status: string
  assignee?: string | null
  note?: string | null
  updated_at?: string | null
  state: 'active' | 'signal_gone' | 'recheck' | 'closed' | 'dismissed'
  state_note: string
}

export interface DecisionBriefing {
  topline: string
  urgency: 'normal' | 'elevated' | 'critical'
  urgency_rationale: string
  priority_items: DecisionSignal[]
  skill_sections: SkillSection[]
  watch_items: DecisionSignal[]
  positive_developments: DecisionSignal[]
  previous_followup: FollowupItem[]
  resolved_since_last: { signal_id: string; severity: string; headline: string }[]
  generated_at: string
  data_freshness: Record<string, string>
  generation_method: 'rule_template' | 'llm_enhanced'
  snapshot_fingerprint: string
  stats: Record<string, Record<string, any>>
  semester: string
  cache_hit?: boolean
}

export interface SkillMeta {
  skill_id: string
  name: string
  management_question: string
  description: string
  briefing_tier: 'main' | 'aux' | 'topic'
  data_boundary: string
  default_config: Record<string, any>
  config_bounds: Record<string, any>
  config_version: string
  data_readiness: { ready: boolean; items: any[] }
}

/** 对话编排（阶段4）：SSE 事件载荷 */
export type ChatIntent = 'verify' | 'simulate' | 'compare' | 'attribute' | 'open'

export interface ChatCitedSignal {
  signal_id: string
  skill_id: string
  severity: Severity
  headline: string
  facts: Record<string, string>
  entity: SignalEntity
  action: SignalAction
  consequence: string
  evidence: SignalEvidence
  change: SignalChange
  suggested_questions: string[]
}

export interface ChatBlock {
  layer: 'facts' | 'hypothesis' | 'action' | 'points'
  title: string
  text?: string
  verify?: string
  items?: string[]
}

export interface ChatMetaEvent {
  intent: ChatIntent
  intent_label: string
  cited: ChatCitedSignal[]
}

export interface ChatDoneEvent {
  blocks: ChatBlock[]
  followups: string[]
  llm_status: string
}

export interface LlmStatus {
  enabled: boolean
  ready: boolean
  narrative_enabled: boolean
  chat_enabled: boolean
  model: string
  base_url: string
}

export const SEVERITY_META: Record<Severity, { label: string; tag: TagType; color: string }> = {
  critical: { label: '紧急', tag: 'danger', color: '#c45656' },
  high: { label: '重点', tag: 'danger', color: '#e6a23c' },
  medium: { label: '关注', tag: 'warning', color: '#b88230' },
  low: { label: '观察', tag: 'info', color: '#909399' },
}

export const CHANGE_META: Record<SignalChange, { label: string; tag: TagType }> = {
  new: { label: '新出现', tag: 'danger' },
  upgraded: { label: '已升级', tag: 'warning' },
  ongoing: { label: '持续', tag: 'info' },
  resolved: { label: '已消除', tag: 'success' },
}

export const TRACKING_META: Record<string, { label: string; tag: TagType }> = {
  open: { label: '待处理', tag: 'info' },
  in_progress: { label: '进行中', tag: 'warning' },
  done: { label: '已完成', tag: 'success' },
  dismissed: { label: '已忽略', tag: 'info' },
}

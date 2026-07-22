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
  /** 可下钻明细的 facts 标签（来自 Skill.detail_specs 契约）；未列出的数字是聚合/判定值，不可点击 */
  drillable_facts?: string[]
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

export interface DecisionBriefing {
  topline: string
  urgency: 'normal' | 'elevated' | 'critical'
  urgency_rationale: string
  priority_items: DecisionSignal[]
  skill_sections: SkillSection[]
  watch_items: DecisionSignal[]
  positive_developments: DecisionSignal[]
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

/** 问策回复结构块（归因三明治/要点列表）。旧「决策追问抽屉」SSE 类型已随 R4 移除。 */
export interface ChatBlock {
  layer: 'facts' | 'hypothesis' | 'action' | 'points'
  title: string
  text?: string
  verify?: string
  items?: string[]
}

export interface LlmStatus {
  enabled: boolean
  ready: boolean
  narrative_enabled: boolean
  chat_enabled: boolean
  model: string
  base_url: string
}

/** 查证窗口（新开浏览器窗口）：单信号完整证据包，与后端 build_signal_evidence 对齐。 */
export interface SignalEvidencePack {
  signal: DecisionSignal
  skill: {
    skill_id: string
    skill_name: string
    management_question: string
    config_version: string
    data_boundary: string
    data_readiness: { ready: boolean; items: any[] }
    exclusions: { what: string; why: string }[]
  }
  semester: string
  generated_at: string
  generation_method: string
  data_freshness: string
  summary_stats: Record<string, any>
}

/* ---- 专家问策（R4）：/admin/ai/decision/ask/* ---- */

/** 专家库卡片：GET /ask/experts 的 items 元素 */
export interface AdviceExpert {
  skill_id: string
  name: string
  title: string
  icon: string
  management_question: string
  description: string
  boundary: string
  example_questions: string[]
  data_readiness: { ready: boolean; items: any[] }
  signal_count: number
  top_signal: { signal_id: string; severity: Severity; headline: string } | null
}

/** 对话中的编号证据引用（与正文 [n] 一一对应） */
export interface AdviceEvidenceRef {
  n: number
  signal_id: string
  severity: Severity
  headline: string
  facts: Record<string, string>
  entity: SignalEntity
  /** 该信号可下钻明细的 facts 标签 */
  drillable_facts?: string[]
}

/** 明细清单页（新开标签页）：GET /signals/{id}/detail 的载荷 */
export interface SignalDetail {
  drillable: boolean
  signal_id: string
  fact: string
  fact_value: string
  title: string
  headline: string
  columns: { key: string; label: string }[]
  rows: Record<string, any>[]
  total: number
  truncated: boolean
  skill: { skill_id: string; skill_name: string }
  semester: string
  generated_at: string
  data_boundary: string
  verify_route: string
}

/** 越界指路：拒答时指向对应专家 */
export interface AdviceRedirect {
  skill_id: string
  name: string
}

export interface AdviceMetaEvent {
  session_id: string
  intent: string
  intent_label: string
  evidence_refs: AdviceEvidenceRef[]
  redirect: AdviceRedirect | null
}

export interface AdviceDoneEvent {
  session_id: string
  blocks: ChatBlock[]
  suggested_questions: string[]
  boundary: string
  redirect: AdviceRedirect | null
  llm_status: string
}

/** 历史会话列表项：GET /ask/sessions 的 items 元素 */
export interface AdviceSession {
  session_id: string
  username: string
  skill_id: string
  title: string
  context_signal_id: string | null
  created_at: string
  updated_at: string
}

/** 历史消息：payload 携带当轮结构化回答 */
export interface AdviceSessionMessage {
  message_id: number
  role: string
  content: string
  payload: {
    blocks?: ChatBlock[]
    evidence_refs?: AdviceEvidenceRef[]
    suggested_questions?: string[]
    boundary?: string
    intent?: string
    intent_label?: string
    redirect?: AdviceRedirect | null
    llm_status?: string
  } | null
  created_at: string
}

export interface AdviceSessionDetail {
  session: AdviceSession
  messages: AdviceSessionMessage[]
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

// 学校分析方案及模型配置类型，从既有接口原样提取。
/* ---- 学校配置中心（阶段5，仅系统管理员） ---- */

export interface SkillConfigVersion {
  config_id: number
  version_no: string
  status: 'draft' | 'published' | 'retired'
  change_reason: string
  created_by: string
  created_at: string
  published_by?: string | null
  published_at?: string | null
}

export interface SkillConfigInfo {
  skill_id: string
  name: string
  management_question: string
  description: string
  default_config: Record<string, any>
  config_bounds: Record<string, { type: string; min?: number; max?: number; options?: any[] }>
  active_config: Record<string, any>
  active_override: Record<string, any>
  config_version: string
  versions: SkillConfigVersion[]
}

export interface AnalysisSchemeDraftPayload {
  override: Record<string, any>
  changeReason: string
  schemeName?: string
  roleIds?: string[]
}

export interface LlmConfigView {
  enabled: boolean
  base_url: string
  has_api_key: boolean
  api_key_tail: string
  model: string
  timeout_seconds: number
  max_retries: number
  narrative_enabled: boolean
  chat_enabled: boolean
  ready: boolean
}

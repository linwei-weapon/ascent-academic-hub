/** AI管理决策（新版 Skill 链路）接口：/admin/ai/decision/* */
import { http, getToken, getActiveIdentity } from './http'
import type {
  ChatDoneEvent, ChatMetaEvent, DecisionBriefing, LlmStatus,
  SignalAction, SignalEntity, SkillMeta, SkillSection,
} from '@/types/decision'

export function getDecisionSkills() {
  return http.get<{ items: SkillMeta[]; semester: string }>('/admin/ai/decision/skills')
}

export function runDecisionSkill(skillId: string) {
  return http.post<SkillSection & { run_at?: string }>(
    `/admin/ai/decision/skills/${encodeURIComponent(skillId)}/run`)
}

export function getDecisionBriefing(force = false) {
  const qs = force ? '?force=true' : ''
  return http.get<DecisionBriefing>(`/admin/ai/decision/briefing${qs}`)
}

export interface TrackingPayload {
  signalId: string
  skillId?: string
  headline?: string
  entity?: SignalEntity
  action?: SignalAction
  status: 'open' | 'in_progress' | 'done' | 'dismissed'
  assignee?: string
  note?: string
}

export function getDecisionTracking() {
  return http.get<{ items: Record<string, unknown>[] }>('/admin/ai/decision/tracking')
}

export function updateDecisionTracking(body: TrackingPayload) {
  return http.put<any>('/admin/ai/decision/tracking', body)
}

export function getDecisionLlmStatus() {
  return http.get<LlmStatus>('/admin/ai/decision/llm-status')
}

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

export function getDecisionSkillConfigs() {
  return http.get<{ items: SkillConfigInfo[] }>('/admin/ai/decision/config/skills')
}

export function createSkillConfigDraft(skillId: string, override: Record<string, any>, changeReason: string) {
  return http.post<any>(`/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/draft`,
    { override, changeReason })
}

export function publishSkillConfig(skillId: string, configId: number) {
  return http.post<any>(`/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/publish`,
    { configId })
}

export function rollbackSkillConfig(skillId: string, configId: number, changeReason = '') {
  return http.post<any>(`/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/rollback`,
    { configId, changeReason })
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

export function getDecisionLlmConfig() {
  return http.get<LlmConfigView>('/admin/ai/decision/config/llm')
}

/** api_key: undefined=保持原密钥；''=清除；其他=更新 */
export function saveDecisionLlmConfig(body: Omit<LlmConfigView, 'has_api_key' | 'api_key_tail' | 'ready'> & { api_key?: string }) {
  return http.put<LlmConfigView>('/admin/ai/decision/config/llm', body)
}

export function testDecisionLlmConnection() {
  return http.post<{ success: boolean; kind?: string; detail?: string; reply?: string; model?: string }>(
    '/admin/ai/decision/config/llm/test')
}

export interface ChatStreamHandlers {
  onMeta?: (e: ChatMetaEvent) => void
  onDelta?: (text: string) => void
  onDone?: (e: ChatDoneEvent) => void
  onError?: (message: string) => void
}

/** 对话编排（SSE）：POST + ReadableStream 读取，不走 http 封装的 envelope。 */
export async function streamDecisionChat(
  body: { message: string; signalId?: string; history?: { role: string; content: string }[] },
  handlers: ChatStreamHandlers,
): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const identity = getActiveIdentity()
  if (token && identity) headers['X-Active-Identity'] = identity

  const res = await fetch('/api/admin/ai/decision/chat', {
    method: 'POST', headers, body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    let msg = `对话服务异常（${res.status}）`
    try {
      const data = await res.json()
      if (data?.msg) msg = data.msg
    } catch { /* ignore */ }
    handlers.onError?.(msg)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      let event = '', data = ''
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim()
        else if (line.startsWith('data: ')) data = line.slice(6)
      }
      if (!event || !data) continue
      try {
        const parsed = JSON.parse(data)
        if (event === 'meta') handlers.onMeta?.(parsed)
        else if (event === 'delta') handlers.onDelta?.(parsed.text || '')
        else if (event === 'done') handlers.onDone?.(parsed)
        else if (event === 'error') handlers.onError?.(parsed.message || '对话服务异常')
      } catch { /* 忽略半包 */ }
    }
  }
}

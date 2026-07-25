/** AI管理决策（新版 Skill 链路）接口：/admin/ai/decision/* */
import { http, getToken, getActiveIdentity } from './http'
import type {
  AdviceDoneEvent, AdviceExpert, AdviceMetaEvent, AdviceSession, AdviceSessionDetail,
  DecisionBriefing, LlmStatus, SignalDetail,
  SignalEvidencePack, SkillMeta, SkillSection,
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

export function getDecisionLlmStatus() {
  return http.get<LlmStatus>('/admin/ai/decision/llm-status')
}

/* ---- 查证窗口（R2：新开浏览器窗口的只读证据页） ---- */

export function getSignalEvidence(signalId: string) {
  return http.get<SignalEvidencePack>(
    `/admin/ai/decision/signals/${encodeURIComponent(signalId)}/evidence`)
}

/** 统一的查证入口：只读证据页在新浏览器标签页打开，noopener 隔离，主标签页状态不动。
    不带 width/height 等窗口特征参数，确保浏览器按用户默认开新标签页而非弹窗。 */
export function openEvidenceWindow(signalId: string) {
  const url = `${window.location.origin}${window.location.pathname}#/admin/verify/signal/${encodeURIComponent(signalId)}`
  window.open(url, '_blank', 'noopener')
}

/* ---- 明细清单（数据要素数字 → 该数字代表的业务明细，新开标签页） ---- */

export function getSignalDetail(signalId: string, fact: string) {
  return http.get<SignalDetail>(
    `/admin/ai/decision/signals/${encodeURIComponent(signalId)}/detail?fact=${encodeURIComponent(fact)}`)
}

/** 明细清单在新浏览器标签页打开（与查证窗口同一策略），主对话窗口状态不动。 */
export function openDetailWindow(signalId: string, fact: string) {
  const url = `${window.location.origin}${window.location.pathname}#/admin/verify/signal/${encodeURIComponent(signalId)}/detail?fact=${encodeURIComponent(fact)}`
  window.open(url, '_blank', 'noopener')
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

export interface AnalysisSchemeDraftPayload {
  override: Record<string, any>
  changeReason: string
  schemeName?: string
  roleIds?: string[]
}

export function createSkillConfigDraft(
  skillId: string,
  override: Record<string, any>,
  changeReason: string,
  schemeName = '',
  roleIds: string[] = [],
) {
  return http.post<any>(`/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/draft`,
    { override, changeReason, schemeName, roleIds })
}

export function updateSkillConfigDraft(
  skillId: string,
  configId: number,
  body: AnalysisSchemeDraftPayload,
) {
  return http.put<any>(
    `/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/draft/${configId}`,
    body,
  )
}

export function testSkillConfig(skillId: string, configId: number) {
  return http.post<any>(
    `/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/test/${configId}`,
  )
}

export function publishSkillConfig(skillId: string, configId: number) {
  return http.post<any>(`/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/publish`,
    { configId })
}

export function rollbackSkillConfig(skillId: string, configId: number, changeReason = '') {
  return http.post<any>(`/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/rollback`,
    { configId, changeReason })
}

export function retireSkillConfig(skillId: string, configId: number, changeReason = '') {
  return http.post<any>(
    `/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/retire`,
    { configId, changeReason },
  )
}

export function exportSkillConfig(skillId: string, configId: number) {
  return http.get<any>(
    `/admin/ai/decision/config/skills/${encodeURIComponent(skillId)}/export/${configId}`,
  )
}

export function importSkillConfig(pkg: Record<string, any>, changeReason: string) {
  return http.post<any>('/admin/ai/decision/config/schemes/import', {
    package: pkg,
    changeReason,
  })
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

/* 旧「决策追问抽屉」链路（POST /chat + streamDecisionChat）已随 R4 退役：
   对话入口统一收口到专家问策（/ask/*）。后端 /chat 保留一个版本周期兼容。 */

/* ---- 专家问策（R4）：/admin/ai/decision/ask/* ---- */

export function getAdviceExperts() {
  return http.get<{ items: AdviceExpert[] }>('/admin/ai/decision/ask/experts')
}

export function getAdviceSessions(skillId: string) {
  return http.get<{ items: AdviceSession[] }>(
    `/admin/ai/decision/ask/sessions?skill_id=${encodeURIComponent(skillId)}`)
}

export function getAdviceSession(sessionId: string) {
  return http.get<AdviceSessionDetail>(
    `/admin/ai/decision/ask/sessions/${encodeURIComponent(sessionId)}`)
}

export interface AdviceStreamHandlers {
  onMeta?: (e: AdviceMetaEvent) => void
  onDelta?: (text: string) => void
  onDone?: (e: AdviceDoneEvent) => void
  onError?: (message: string) => void
}

/** 专家问策（SSE）：与 streamDecisionChat 同模式，POST + ReadableStream，不走 envelope。 */
export async function streamAdviceAsk(
  skillId: string,
  body: { message: string; session_id?: string; signalId?: string },
  handlers: AdviceStreamHandlers,
): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const identity = getActiveIdentity()
  if (token && identity) headers['X-Active-Identity'] = identity

  const res = await fetch(`/api/admin/ai/decision/ask/${encodeURIComponent(skillId)}`, {
    method: 'POST', headers, body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    let msg = `问策服务异常（${res.status}）`
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
        else if (event === 'error') handlers.onError?.(parsed.message || '问策服务异常')
      } catch { /* 忽略半包 */ }
    }
  }
}

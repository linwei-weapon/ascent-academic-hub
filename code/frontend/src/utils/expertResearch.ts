import { getActiveIdentity, getToken } from './http'
import type { TeamDocument, TeamExpert, TeamPlan, TeamRequest, TeamResult, TeamSession, TeamTable } from './expertTeam'

export type ResearchScope = Omit<Partial<TeamRequest>, 'focus'> & { plan_id: string; focus?: TeamRequest['focus'] | 'foundation_main' }
export type RunStatus = 'queued' | 'running' | 'cancel_requested' | 'cancelling' | 'completed' | 'succeeded' | 'partial' | 'failed' | 'cancelled' | 'stopped' | 'timed_out' | string
export interface ResearchRun { id: string; status: RunStatus; error?: string }
export interface SavedText { text: string; revision: number; saved_at?: string }
export interface ResearchExpert extends TeamExpert { enabled: boolean; availability: string; scenarios: (TeamExpert['scenarios'][number] & { release?: 'limited' | 'deferred'; missing?: string[] })[] }
export interface ResearchCatalog { version: string; mode: 'structured'; notice: string; role_view: 'director' | 'dean'; experts: ResearchExpert[]; plans: TeamPlan[]; semesters: string[] }
export interface PlanComparator extends TeamPlan { shared: number; union: number; subset_overlap: number; source_count: number; target_count: number; source_pending: number; target_pending: number; examples: { id: string; name: string }[] }
export interface ComparatorRecommendation { source_plan_id: string; focus: string; candidates: PlanComparator[]; source_count: number; source_pending: number; eligible_count: number; method: string; boundary: string; empty_reason: string }
export interface ResearchResult extends TeamResult { id: string; body?: string; management_note?: string; decision_summary?: string; request_receipt?: string; critical_issues?: { plan: string; file: string; text: string }[]; discussion_points?: { title: string; detail: string; needed: string; source: string }[]; actual_experts?: string[]; method_unavailable?: boolean; contributions?: { expert_id: string; result: TeamResult }[] }
export interface ResearchTurn { id: string; seq?: number; message: string; created_at: string; run: ResearchRun; result?: ResearchResult }
export interface ResearchQuestion { id: string; text: string; kind: 'data' | 'choice'; status: 'open' | 'deferred' | 'resolved'; revision: number }
export interface MaterialSummary { id: string; title: string; created_at: string; result_id: string; opinion_revision: number }
export interface DiscussionMemo { version: string; title?: string; sections: { title: string; paragraphs: string[] }[]; appendix_tables: TeamTable[]; methods: string[]; sources: { file: string; detail?: string }[] }
export interface ResearchMaterial extends MaterialSummary { research_id: string; snapshot: { result: ResearchResult; opinion: SavedText; questions: ResearchQuestion[]; discussion_memo?: DiscussionMemo }; stale: boolean }
export interface ResearchSummary { id: string; title: string; updated_at: string; status: 'active' | 'archived'; metadata_revision: number; matched_turn_id?: string; match_seq?: number; snippet?: string }
export interface Research extends ResearchSummary {
  context_epoch: number; scope: ResearchScope; participants_revision: number
  participants: { expert_id: string; status: 'active' | 'excluded'; origin: 'manual' | 'automatic' }[]
  draft: SavedText; opinion: SavedText; turns: ResearchTurn[]; active_run: ResearchRun | null
  current_result: ResearchResult | null; questions: ResearchQuestion[]; materials: MaterialSummary[]; next_before?: number | null
}
export interface ResearchSources { documents: TeamDocument[]; methods: string[]; sources: { file: string; hash?: string; detail?: string }[]; tables: TeamTable[]; source_bundle?: unknown }
export interface SaveTextBody { text: string; revision: number; client_request_id: string }
export interface SubmitResearch { message: string; scope: ResearchScope; client_request_id: string; expert_id?: string }
export class ResearchApiError extends Error { constructor(message: string, public status: number) { super(message); this.name = 'ResearchApiError' } }
const root = '/admin/expert-research/v3'
const enc = encodeURIComponent

// Keep status codes for independent draft conflicts without changing the shared client.
async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const token = getToken(), identity = getActiveIdentity()
  const response = await fetch(`/api${root}${path}`, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(token && identity ? { 'X-Active-Identity': identity } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (token !== getToken() || identity !== getActiveIdentity()) throw new ResearchApiError('工作身份已变化，请重新打开研究。', 4090)
  let payload: { code?: number; msg?: string; detail?: string; data?: T }
  try { payload = await response.json() } catch { throw new ResearchApiError('未收到有效响应，请保留文字后重试。', response.status) }
  if (!response.ok || payload.code !== 0) throw new ResearchApiError(payload.msg || payload.detail || '操作未完成，请稍后重试。', response.status)
  return payload.data as T
}
export const researchApi = {
  comparators: (planId: string, focus = 'non_common') => request<ComparatorRecommendation>(`/comparators?plan_id=${enc(planId)}&focus=${enc(focus)}`),
  catalog: () => request<ResearchCatalog>('/catalog'),
  list: (q = '', archived = false, cursor = '') => request<{ items: ResearchSummary[]; next_cursor?: string }>(`/researches?q=${enc(q)}&archived=${archived}${cursor ? `&before=${enc(cursor)}` : ''}`),
  get: (id: string, before?: number) => request<Research>(`/researches/${enc(id)}${before == null ? '' : `?before=${before}`}`),
  create: (body: SubmitResearch) => request<Research>('/researches', 'POST', body),
  turn: (id: string, body: SubmitResearch & { expected_context_epoch: number; kind: 'analysis' }) => request<Research>(`/researches/${enc(id)}/turns`, 'POST', body),
  cancel: (id: string, runId: string) => request<Research>(`/researches/${enc(id)}/cancel`, 'POST', { run_id: runId }),
  metadata: (id: string, body: { revision: number; title?: string; status?: 'active' | 'archived' }) => request<Research>(`/researches/${enc(id)}/metadata`, 'PUT', body),
  participant: (id: string, revision: number, expert_id: string, action: 'add' | 'exclude') => request<Research>(`/researches/${enc(id)}/participants`, 'PUT', { revision, expert_id, action }),
  text: (id: string, field: 'draft' | 'opinion') => request<SavedText>(id === 'new' ? '/drafts/new' : `/researches/${enc(id)}/${field}`),
  saveText: (id: string, field: 'draft' | 'opinion', body: SaveTextBody) => request<SavedText>(id === 'new' ? '/drafts/new' : `/researches/${enc(id)}/${field}`, 'PUT', body),
  opinionVersions: (id: string) => request<{ items: SavedText[] }>(`/researches/${enc(id)}/opinion/versions`),
  question: (id: string, text: string, kind: 'data' | 'choice') => request<Research>(`/researches/${enc(id)}/questions`, 'POST', { text, kind }),
  updateQuestion: (id: string, q: ResearchQuestion, status: 'open' | 'deferred') => request<Research>(`/researches/${enc(id)}/questions/${enc(q.id)}`, 'PUT', { revision: q.revision, status }),
  sources: (id: string, resultId: string) => request<ResearchSources>(`/researches/${enc(id)}/sources/${enc(resultId)}`),
  materials: (id: string) => request<{ items: MaterialSummary[] }>(`/researches/${enc(id)}/materials`),
  makeMaterial: (id: string, body: { result_id: string; opinion_revision: number; include_opinion: boolean; question_revisions: { id: string; revision: number }[] }) => request<ResearchMaterial>(`/researches/${enc(id)}/materials`, 'POST', body),
  material: (id: string) => request<ResearchMaterial>(`/materials/${enc(id)}`),
  legacy: () => request<{ items: { id: string; title: string; expert_id: string; updated_at: string }[] }>('/legacy'),
  legacyItem: (id: string) => request<TeamSession>(`/legacy/${enc(id)}`),
}
export async function downloadResearchMaterial(id: string): Promise<void> {
  const token = getToken(), identity = getActiveIdentity()
  const response = await fetch(`/api${root}/materials/${enc(id)}/download.docx`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(token && identity ? { 'X-Active-Identity': identity } : {}) } })
  if (identity !== getActiveIdentity() || token !== getToken()) throw new ResearchApiError('工作身份已变化，已取消下载。', 4090)
  if (!response.ok) { let msg = '讨论稿下载未完成。'; try { const data = await response.json(); msg = data.msg || data.detail || msg } catch { /* Keep the safe download error. */ } throw new ResearchApiError(msg, response.status) }
  const blob = await response.blob()
  if (identity !== getActiveIdentity() || token !== getToken()) throw new ResearchApiError('工作身份已变化，已取消下载。', 4090)
  const match = (response.headers.get('content-disposition') || '').match(/filename\*=UTF-8''([^;]+)/i)
  let filename = '研究讨论稿.docx'; try { if (match) filename = decodeURIComponent(match[1]) } catch { /* Use default for invalid header. */ }
  const url = URL.createObjectURL(blob), anchor = document.createElement('a')
  anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export const newRequestId = () => globalThis.crypto?.randomUUID?.() || `research-${Date.now()}-${Math.random().toString(36).slice(2)}`
export const researchDate = (value?: string) => !value ? '时间未提供' : Number.isNaN(new Date(value).getTime()) ? value : new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
export const isRunning = (run?: ResearchRun | null) => !!run && ['queued', 'pending', 'running', 'cancel_requested', 'cancelling'].includes(run.status)
export const runLabel = (status: RunStatus) => (({ queued: '等待处理', pending: '等待处理', running: '正在分析', cancel_requested: '正在停止', cancelling: '正在停止', completed: '已完成', succeeded: '已完成', partial: '部分完成', partial_success: '部分完成', needs_input: '需明确范围', failed: '未完成', cancelled: '已停止', stopped: '已停止', timed_out: '处理超时' } as Record<string, string>)[status] || '状态待确认')
export const shouldSendKey = (event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'isComposing' | 'keyCode'>, composing: boolean) => event.key === 'Enter' && event.ctrlKey && !composing && !event.isComposing && event.keyCode !== 229
export const clearAcceptedText = (current: string, submitted: string) => current === submitted ? '' : current
export const appendWithoutOverwrite = (current: string, addition: string) => `${current}${current.trim() ? '\n' : ''}${addition}`
export const researchPlanLabel = (plan?: Pick<TeamPlan, 'plan_name' | 'grade'>) => !plan ? '' : !plan.grade || plan.plan_name.includes(`${plan.grade}级`) ? plan.plan_name : `${plan.plan_name} · ${plan.grade}级`
export const comparableResearchPlans = (plans: TeamPlan[], sourceId: string) => {
  const source = plans.find(plan => plan.plan_id === sourceId)
  if (!source?.grade || !source.training_type?.trim()) return []
  return plans.filter(plan => plan.plan_id !== source.plan_id && plan.grade === source.grade && !!plan.training_type?.trim() && plan.training_type === source.training_type && (!source.version || plan.version === source.version) && (!source.family || plan.family !== source.family))
}

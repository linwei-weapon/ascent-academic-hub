// 研究工作区 API：保留冲突状态码、身份切换检查与文件下载协议。
import { getActiveIdentity, getToken } from '@/utils/http'
import type { TeamSession } from '@/types/expertTeam'
import type { ResearchScope, RunStatus, ResearchRun, SavedText, ResearchExpert, ResearchCatalog, PlanComparator, ComparatorRecommendation, ResearchResult, ResearchTurn, ResearchQuestion, MaterialSummary, DiscussionMemo, ResearchMaterial, ResearchSummary, Research, ResearchSources, SaveTextBody, SubmitResearch } from '@/types/expertResearch'
export type * from '@/types/expertResearch'

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

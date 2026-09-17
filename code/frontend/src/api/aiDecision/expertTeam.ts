// 专家团旧会话 API：沿用公共 HTTP、身份头与原端点。
import { http } from '@/utils/http'
import type { TeamScenario, TeamExpert, TeamPlan, TeamStudent, TeamFocus, TeamTable, TeamDocument, TeamRequest, TeamResult, TeamSession } from '@/types/expertTeam'
export type * from '@/types/expertTeam'

const root = '/admin/expert-team'
export const getTeamCatalog = () => http.get<{ experts: TeamExpert[]; plans: TeamPlan[]; semesters: string[]; conversation_note: string }>(`${root}/catalog`)
export const analyzeTeam = (request: TeamRequest) => http.post<TeamSession>(`${root}/analyze`, request)
export const listTeamSessions = () => http.get<{ items: Pick<TeamSession, 'id' | 'expert_id' | 'title' | 'updated_at'>[] }>(`${root}/sessions`)
export const getTeamSession = (id: string) => http.get<TeamSession>(`${root}/sessions/${encodeURIComponent(id)}`)
export const saveTeamSession = (id: string, body: { revision: number; draft?: string; note?: string }) => http.put<TeamSession>(`${root}/sessions/${encodeURIComponent(id)}`, body)
export const askTeam = (id: string, body: { revision: number; message: string; table_id?: string; row_index?: number }) => http.post<TeamSession>(`${root}/sessions/${encodeURIComponent(id)}/ask`, body)
export const reviseTeam = (id: string, body: { revision: number; analysis: TeamRequest }) => http.post<TeamSession>(`${root}/sessions/${encodeURIComponent(id)}/revise`, body)
export const getTeamStudents = (plan: string, query: string) => http.get<{ items: TeamStudent[]; limit: number }>(`${root}/students?plan_id=${encodeURIComponent(plan)}&q=${encodeURIComponent(query)}`)
export const getTeamSnapshots = (plan: string) => http.get<{ items: { id: string; created_at: string }[] }>(`${root}/graduation-snapshots?plan_id=${encodeURIComponent(plan)}`)
export const saveTeamSnapshot = (id: string, revision: number) => http.post<{ id: string; created_at: string }>(`${root}/sessions/${encodeURIComponent(id)}/snapshot`, { revision })

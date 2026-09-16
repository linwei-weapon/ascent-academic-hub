import { http } from './http'

export interface TeamScenario { id: string; name: string; description: string }
export interface TeamExpert { id: string; name: string; purpose: string; question: string; group: string; icon: string; scenarios: TeamScenario[] }
export interface TeamPlan { plan_id: string; plan_name: string; major_name: string; grade: number; version: string; source: string; course_rows: number; training_type: string; family: string }
export interface TeamStudent { student_id: string; display_name: string; entry_grade: number; major_name: string }
export type TeamFocus = 'non_common' | 'foundation' | 'main' | 'practice' | 'required' | 'all'
export interface TeamTable { id: string; title: string; columns: { key: string; label: string }[]; rows: Record<string, any>[]; note: string }
export interface TeamDocument { plan: string; file: string; status: string; issues: string[]; sections: { title: string; text: string }[]; basis: string; hash?: string }
export interface TeamRequest { expert_id: string; scenario: string; plan_id: string; target_plan_id?: string; semester?: string; course_id?: string; focus?: TeamFocus; student_id?: string; baseline_id?: string }
export interface TeamResult {
  expert_id: string; scenario: string; title: string; headline: string; status: string; tables: TeamTable[];
  documents: TeamDocument[]; candidates: (TeamPlan & { structural_similarity: number | null; focus_similarity: number | null; shared: number; required_coverage: number | null; additional_required: number })[];
  missing: string[]; limitations: string[]; methods: string[]; version: string; scope_label: string;
  data_time: string; data_time_note: string; suggestions: string[]; semester?: string;
  sources?: { file: string; hash: string; detail?: string }[];
  comparison?: { source: TeamPlan; target: TeamPlan; focus_shared?: number; focus_union?: number; focus_similarity?: number | null;
    target_required?: number; potential_required?: number; additional_required?: number; choice_required?: number };
  focus_label?: string; student?: TeamStudent; draft_text?: string;
  course?: { id: string; name: string }; course_options?: { id: string; name: string }[];
  snapshot?: { population: number; source_times: string[]; rule_version: string; counts?: Record<string, number> };
  baseline?: { id: string; created_at: string; population: number };
}
export interface TeamSession {
  id: string; expert_id: string; title: string; revision: number; request: TeamRequest; result: TeamResult;
  messages: { role: string; text: string; kind?: string; basis?: string }[]; draft: string; note: string; updated_at: string;
}
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

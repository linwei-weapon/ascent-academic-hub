// 专家团研究 DTO：保留独立草稿、版本和运行状态契约。
import type { TeamDocument, TeamExpert, TeamPlan, TeamRequest, TeamResult, TeamSession, TeamTable } from '@/types/expertTeam'

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

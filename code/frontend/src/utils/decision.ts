/** AI管理决策（新版 Skill 链路）接口：/admin/ai/decision/* */
import { http } from './http'
import type {
  DecisionBriefing, SignalAction, SignalEntity, SkillMeta, SkillSection,
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

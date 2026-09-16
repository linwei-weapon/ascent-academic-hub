// 决策简报与专家分析请求：读取简报、可用专家和模型状态。
import { http } from '@/utils/http'
import type { DecisionBriefing, LlmStatus, SkillMeta, SkillSection } from '@/types/decision'

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

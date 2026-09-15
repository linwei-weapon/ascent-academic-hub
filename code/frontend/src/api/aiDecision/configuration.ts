// 学校分析方案与模型配置请求：供系统管理共用，保留原版本治理协议。
import { http } from '@/utils/http'
import type { SkillConfigInfo, AnalysisSchemeDraftPayload, LlmConfigView } from '@/types/decisionConfig'
export type { SkillConfigInfo, SkillConfigVersion, AnalysisSchemeDraftPayload, LlmConfigView } from '@/types/decisionConfig'

export function getDecisionSkillConfigs() {
  return http.get<{ items: SkillConfigInfo[] }>('/admin/ai/decision/config/skills')
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

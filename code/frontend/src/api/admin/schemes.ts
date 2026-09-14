// 系统管理方案入口：共用既有 AI 配置请求，保持导入、导出和版本操作契约。
export {
  createSkillConfigDraft, exportSkillConfig, getDecisionSkillConfigs,
  importSkillConfig, publishSkillConfig, retireSkillConfig,
  rollbackSkillConfig, testSkillConfig, updateSkillConfigDraft,
  getDecisionLlmConfig, saveDecisionLlmConfig, testDecisionLlmConnection,
} from '@/utils/decision'

// 研究工作区的日期、状态与输入辅助；兼容旧请求导出。
import type { TeamPlan } from '@/types/expertTeam'
import type { ResearchRun, RunStatus } from '@/types/expertResearch'
export * from '@/api/aiDecision/expertResearch'

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

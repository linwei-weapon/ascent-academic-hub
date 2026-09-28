// AI 管理决策路由：由 index.ts 统一注册，沿用原 URL、组件复用与兼容跳转。
import type { RouteRecordRaw } from 'vue-router'

export const aiDecisionRoutes: RouteRecordRaw[] = [
  // AI 当前入口与历史链接兼容
  // AI 分组默认入口
  { path: 'reports', redirect: '/admin/reports/decision' },
  // 决策简报
  { path: 'reports/decision', component: () => import('@/views/ai-decision/decision/index.vue') },
  // 专家分析工作区
  { path: 'reports/decision/skills/:skillId', component: () => import('@/views/ai-decision/decision/workspaces/SkillWorkspace.vue') },
  // 专家问策（R4）：专家库 + 三栏纯对话页
  // 专家库
  { path: 'reports/advice', component: () => import('@/views/ai-decision/advice/index.vue') },
  // 专家对话
  { path: 'reports/advice/:skillId', component: () => import('@/views/ai-decision/advice/Chat.vue') },
  // 专家团研究工作区：保留既有菜单 URL，由服务端校验身份与范围。
  { path: 'reports/expert-team', component: () => import('@/views/ai-decision/expert-team/index.vue') },
  // 旧「管理要情」「决策研判」已废弃，统一收口到 Skill 链路决策简报
  // 旧管理要情入口
  { path: 'reports/management-briefing', redirect: '/admin/reports/decision' },
  // 旧决策模拟入口
  { path: 'reports/decision-simulation', redirect: '/admin/reports/decision' },
]

// 查证独立窗口沿用根级路由，不挂载管理端 Layout。
export const aiEvidenceRoutes: RouteRecordRaw[] = [
  // 查证窗口（R2）：独立只读证据页，不挂 Layout，专供新开浏览器窗口
  // 独立信号查证页
  { path: '/admin/verify/signal/:signalId', component: () => import('@/views/ai-decision/verify/SignalEvidence.vue') },
  // 明细清单页：数据要素数字直达业务明细，同样独立只读、新开标签页
  // 独立数据要素明细页
  { path: '/admin/verify/signal/:signalId/detail', component: () => import('@/views/ai-decision/verify/SignalDetail.vue') },
]

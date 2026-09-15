// 全应用路由入口：代码按业务归属组织，URL 与后端菜单授权保持原契约。
import type { App } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from '@/utils/http'
import { authStore, fetchMe } from '@/store/auth'
import { homePathForUser, menuKeyOfPath } from '@/utils/menu'
import { systemRoutes } from './modules/system'
import { basicReportRoutes } from './modules/basicReports'
import { teachingAnalysisRoutes } from './modules/teachingAnalysis'
import { aiDecisionRoutes, aiEvidenceRoutes } from './modules/aiDecision'

const AppLayout = () => import('@/layouts/AppLayout.vue')

export const router = createRouter({
  history: createWebHashHistory(),
  // 后退时恢复浏览位置，其余导航回到页面顶部。
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition || { top: 0 }
  },
  routes: [
    { path: '/login', component: () => import('@/views/Login.vue') },
    ...aiEvidenceRoutes,
    {
      path: '/admin', component: AppLayout,
      children: [
        { path: '', redirect: '/admin/dashboard' },
        // 教学管理分析
        ...teachingAnalysisRoutes,
        // AI 管理决策
        ...aiDecisionRoutes,

        // 基础报表
        ...basicReportRoutes,

        // 系统管理
        ...systemRoutes,

        // 无权限
        { path: 'forbidden', component: () => import('@/views/Forbidden.vue') },
      ]
    },
    { path: '/', redirect: '/admin/dashboard' },
    { path: '/:pathMatch(.*)*', redirect: '/admin/dashboard' },
  ]
})

// 部署新前端后，已打开的旧页面可能仍引用上一版本分片。
// 此时菜单路由已变化，但页面组件无法加载；自动刷新一次恢复到当前新版本。
router.onError((error) => {
  const message = String(error?.message || error)
  if (!/Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(message)) return
  const key = 'sa_chunk_reload'
  const lastReload = Number(sessionStorage.getItem(key) || 0)
  if (Date.now() - lastReload < 10000) return
  sessionStorage.setItem(key, String(Date.now()))
  location.reload()
})

// 依据现有菜单授权判断路由准入，保留学生详情和查证窗口的共享入口。
function isAllowed(path: string): boolean {
  const has = (p: string) => authStore.menus.some(m => m.path === p)
  // 学生详情可由「预警查看」或「学生学业分析」进入
  if (path.startsWith('/admin/student/')) return has('/admin/alert') || has('/admin/students/analysis')
  // 学生清单：拥有预警查看或学生学业分析菜单权限的角色可访问（5 类角色）
  if (path === '/admin/students/list') return has('/admin/alert') || has('/admin/students/analysis')
  // 查证窗口：拥有 AI管理决策入口的角色可访问（服务端仍按信号数据范围二次鉴权）
  if (path.startsWith('/admin/verify/')) return has('/admin/reports/decision')
  // 专家问策：与 AI管理决策同一准入（服务端仍按当前身份与数据范围二次鉴权）
  if (path.startsWith('/admin/reports/advice')) return has('/admin/reports/decision')
  return has(menuKeyOfPath(path))
}

router.beforeEach(async (to) => {
  const token = getToken()

  if (to.path === '/login') {
    if (!token) return true
    if (!authStore.user) {
      try {
        await fetchMe()
      } catch {
        return true
      }
    }
    return homePathForUser(authStore.user, authStore.menus)
  }
  if (!token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  // 刷新后用 token 恢复会话
  if (!authStore.user) {
    try {
      await fetchMe()
    } catch {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  // 已登录但当前工作身份没有有效组织范围或人员关系时，统一进入拒绝页。
  // 后端仍会返回空范围/403；这里补充明确的用户反馈，避免“页面有框架但数据全空”。
  if (
    to.path.startsWith('/admin')
    && to.path !== '/admin/forbidden'
    && authStore.user?.permissionContext?.authorized === false
  ) {
    return {
      path: '/admin/forbidden',
      query: {
        from: to.fullPath,
        reason: authStore.user.permissionContext.authorizationIssue || '当前工作身份没有有效数据范围',
      },
      replace: true,
    }
  }
  // 菜单级准入
  if (to.path === '/admin/forbidden') return true
  if (to.path.startsWith('/admin') && !isAllowed(to.path)) {
    return {
      path: '/admin/forbidden',
      query: { from: to.fullPath },
      replace: true,
    }
  }
  return true
})

// 在应用启动时注册路由，使用统一的登录恢复和权限守卫。
export function initRouter(app: App<Element>): void { app.use(router) }
export const HOME_PAGE_PATH = '/admin/dashboard'

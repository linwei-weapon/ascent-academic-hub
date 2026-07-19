import type { App } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from '@/utils/http'
import { authStore, fetchMe } from '@/store/auth'
import { homePathForUser, menuKeyOfPath } from '@/utils/menu'

const AdminLayout = () => import('@/views/admin/Layout.vue')

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/Login.vue') },
    {
      path: '/admin', component: AdminLayout,
      children: [
        // ====== 数据大屏（五级） ======
        { path: '', redirect: '/admin/dashboard' },
        { path: 'dashboard', component: () => import('@/views/admin/dashboard/index.vue') },
        { path: 'college/:id', component: () => import('@/views/admin/dashboard/Detail.vue') },
        { path: 'major/:id', component: () => import('@/views/admin/dashboard/MajorDetail.vue') },
        { path: 'course/:id', component: () => import('@/views/admin/dashboard/CourseDetail.vue') },
        { path: 'student/:id', component: () => import('@/views/admin/student/Detail.vue') },

        // ====== 预警查看 ======
        { path: 'alert', component: () => import('@/views/admin/alert/Workspace.vue') },
        { path: 'alert/monitor', redirect: '/admin/alert?tab=monitor' },
        { path: 'alert/rules', redirect: '/admin/alert?tab=rules' },
        { path: 'alert/discovery', redirect: '/admin/alert?tab=rules' },

        // ====== 教学运行分析 ======
        { path: 'operation/courses', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/classroom', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/schedule-changes', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/teacher-load', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/schedule-analysis', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/course-quality', component: () => import('@/views/admin/operation/Index.vue') },

        // ====== 培养质量分析 ======
        { path: 'curriculum', component: () => import('@/views/admin/curriculum/index.vue') },
        { path: 'curriculum/progress', component: () => import('@/views/admin/curriculum/Progress.vue') },  // V1.1
        { path: 'curriculum/course-objectives/:id', component: () => import('@/views/admin/curriculum/CourseObjectives.vue') },
        { path: 'curriculum/graduate-requirements/:id', component: () => import('@/views/admin/curriculum/GraduateRequirements.vue') },

        // ====== 师资结构分析 ======
        { path: 'faculty', component: () => import('@/views/admin/faculty/Index.vue') },
        { path: 'faculty/team', component: () => import('@/views/admin/faculty/Team.vue') },
        { path: 'faculty/:id', component: () => import('@/views/admin/faculty/Detail.vue') },

        // ====== 学生学业分析 ======
        { path: 'students/analysis', component: () => import('@/views/admin/students/Analysis.vue') },
        { path: 'students/list', component: () => import('@/views/admin/students/List.vue') },

        // ====== AI管理决策（旧事实专题保留兼容重定向） ======
        { path: 'reports', redirect: '/admin/reports/management-briefing' },
        { path: 'reports/early-setback', redirect: '/admin/alert?tab=early-risk' },
        { path: 'reports/graduation-readiness', redirect: '/admin/curriculum?tab=graduation-readiness' },
        { path: 'reports/course-quality', redirect: '/admin/operation/course-quality' },
        { path: 'reports/faculty-resource-risk', redirect: '/admin/faculty' },
        { path: 'reports/schedule-strategy', redirect: '/admin/operation/schedule-analysis' },
        { path: 'reports/management-briefing', component: () => import('@/views/admin/reports/ManagementBriefing.vue') },
        { path: 'reports/decision-simulation', component: () => import('@/views/admin/reports/DecisionSimulation.vue') },

        // ====== 系统管理（账号 / 菜单 / 角色） ======
        { path: 'system/accounts', component: () => import('@/views/admin/system/Accounts.vue') },
        { path: 'system/menus', component: () => import('@/views/admin/system/Menus.vue') },
        { path: 'system/roles', component: () => import('@/views/admin/system/Roles.vue') },
        { path: 'system/permissions', component: () => import('@/views/admin/system/Permissions.vue') },
        { path: 'system/audit', component: () => import('@/views/admin/system/Audit.vue') },
        { path: 'system/kpis', component: () => import('@/views/admin/system/Kpis.vue') },
        { path: 'system/schemes', component: () => import('@/views/admin/system/Schemes.vue') },

        // ====== 系统设置 ======
        { path: 'settings', component: () => import('@/views/admin/system/Parameters.vue') },
        { path: 'forbidden', component: () => import('@/views/admin/Forbidden.vue') },
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

function isAllowed(path: string): boolean {
  const has = (p: string) => authStore.menus.some(m => m.path === p)
  // 学生详情可由「预警查看」或「学生学业分析」进入
  if (path.startsWith('/admin/student/')) return has('/admin/alert') || has('/admin/students/analysis')
  // 学生清单：拥有预警查看或学生学业分析菜单权限的角色可访问（5 类角色）
  if (path === '/admin/students/list') return has('/admin/alert') || has('/admin/students/analysis')
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

export function initRouter(app: App<Element>): void { app.use(router) }
export const HOME_PAGE_PATH = '/admin/dashboard'

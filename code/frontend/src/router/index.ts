import type { App } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from '@/utils/http'
import { authStore, fetchMe } from '@/store/auth'

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
        { path: 'alert', component: () => import('@/views/admin/alert/index.vue') },
        { path: 'alert/discovery', component: () => import('@/views/admin/alert/Discovery.vue') },

        // ====== 教学运行分析 ======
        { path: 'operation/courses', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/classroom', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/schedule-changes', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/teacher-load', component: () => import('@/views/admin/operation/Index.vue') },
        { path: 'operation/schedule-analysis', component: () => import('@/views/admin/operation/Index.vue') },

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

        // ====== 报表中心 ======
        { path: 'reports', component: () => import('@/views/admin/curriculum/Reports.vue') },
        { path: 'reports/early-setback', component: () => import('@/views/admin/reports/EarlySetback.vue') },

        // ====== 系统管理（账号 / 菜单 / 角色） ======
        { path: 'system/accounts', component: () => import('@/views/admin/system/Accounts.vue') },
        { path: 'system/menus', component: () => import('@/views/admin/system/Menus.vue') },
        { path: 'system/roles', component: () => import('@/views/admin/system/Roles.vue') },
        { path: 'system/audit', component: () => import('@/views/admin/system/Audit.vue') },
        { path: 'system/kpis', component: () => import('@/views/admin/system/Kpis.vue') },

        // ====== 系统设置 ======
        { path: 'settings', component: () => import('@/views/admin/settings/index.vue') },
      ]
    },
    { path: '/', redirect: '/admin/dashboard' },
    { path: '/:pathMatch(.*)*', redirect: '/admin/dashboard' },
  ]
})

/** 子路径 → 所属一级菜单 path（与 Layout 高亮一致），用于菜单级准入判断 */
function menuKeyOf(p: string): string {
  if (p.startsWith('/admin/alert/')) return '/admin/alert'
  if (p.startsWith('/admin/college/')) return '/admin/dashboard'
  if (p.startsWith('/admin/major/')) return '/admin/dashboard'
  if (p.startsWith('/admin/course/')) return '/admin/dashboard'
  if (p.startsWith('/admin/operation/')) return '/admin/operation/courses'
  if (p.startsWith('/admin/curriculum/')) return '/admin/curriculum'
  if (p.startsWith('/admin/reports/')) return '/admin/reports'
  if (p.startsWith('/admin/faculty/')) return '/admin/faculty'
  if (p.startsWith('/admin/students/')) return p  // 学生学业子页保留自身路径
  if (p === '/admin/system/audit') return '/admin/system/accounts'
  if (p === '/admin/system/kpis') return '/admin/system/accounts'
  if (p.startsWith('/admin/system/')) return p    // 系统管理子页保留自身路径
  return p
}

function isAllowed(path: string): boolean {
  const has = (p: string) => authStore.menus.some(m => m.path === p)
  // 学生详情可由「预警查看」或「学生学业分析」进入
  if (path.startsWith('/admin/student/')) return has('/admin/alert') || has('/admin/students/analysis')
  // 学生清单：拥有预警查看或学生学业分析菜单权限的角色可访问（5 类角色）
  if (path === '/admin/students/list') return has('/admin/alert') || has('/admin/students/analysis')
  return has(menuKeyOf(path))
}

router.beforeEach(async (to) => {
  const token = getToken()

  if (to.path === '/login') {
    return token ? '/admin/dashboard' : true
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
  if (to.path.startsWith('/admin') && !isAllowed(to.path)) {
    return authStore.menus[0]?.path || '/login'
  }
  return true
})

export function initRouter(app: App<Element>): void { app.use(router) }
export const HOME_PAGE_PATH = '/admin/dashboard'

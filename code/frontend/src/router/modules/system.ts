// 系统管理路由：透明分组承接九个菜单，沿用后端授权使用的原 URL。
import type { RouteRecordRaw } from 'vue-router'

export const systemRoutes: RouteRecordRaw[] = [
  // 系统管理
  {
    path: 'system',
    redirect: '/admin/dashboard',
    children: [
      // 账号管理
      { path: 'accounts', component: () => import('@/views/admin/accounts/Accounts.vue') },
      // 菜单管理
      { path: 'menus', component: () => import('@/views/admin/menus/Menus.vue') },
      // 角色与功能权限
      { path: 'roles', component: () => import('@/views/admin/roles/Roles.vue') },
      // 数据权限
      { path: 'permissions', component: () => import('@/views/admin/permissions/Permissions.vue') },
      // 审计日志
      { path: 'audit', component: () => import('@/views/admin/audit/Audit.vue') },
      // 指标与口径管理
      { path: 'kpis', component: () => import('@/views/admin/kpis/Kpis.vue') },
      // 分析方案管理
      { path: 'schemes', component: () => import('@/views/admin/schemes/Schemes.vue') },
      // 数据采集监控
      { path: 'data-collection', component: () => import('@/views/admin/data-collection/DataCollection.vue') },
      // 系统参数
      { path: '/admin/settings', component: () => import('@/views/admin/parameters/Parameters.vue') },
      // 旧决策配置
      { path: 'decision-config', redirect: '/admin/system/schemes' },
    ],
  },
]

import type { AuthMenu, AuthUser } from '@/store/auth'

/** 业务子路由映射到实际授予权限的叶子菜单。 */
export function menuKeyOfPath(path: string, returnTo = ''): string {
  if (path.startsWith('/admin/student/')) {
    const source = returnTo ? menuKeyOfPath(returnTo) : ''
    return source === '/admin/alert' ? source : '/admin/students/analysis'
  }
  if (path.startsWith('/admin/college/')) return '/admin/dashboard'
  if (path.startsWith('/admin/major/')) return '/admin/dashboard'
  if (path.startsWith('/admin/course/')) return '/admin/dashboard'
  if (path.startsWith('/admin/alert/')) return '/admin/alert'
  if (path.startsWith('/admin/operation/')) return '/admin/operation/courses'
  if (path.startsWith('/admin/curriculum/')) return '/admin/curriculum'
  if (path.startsWith('/admin/faculty/')) return '/admin/faculty'
  if (path === '/admin/students/list') return '/admin/students/analysis'
  if (path.startsWith('/admin/students/')) return '/admin/students/analysis'

  if (path === '/admin/reports' || path === '/admin/reports/management-briefing') {
    return '/admin/reports/management-briefing'
  }
  if (path === '/admin/reports/decision-simulation') {
    return '/admin/reports/decision-simulation'
  }
  // 事实型旧专题保留兼容路由，但权限归回对应的预设业务模块。
  if (path === '/admin/reports/early-setback') return '/admin/alert'
  if (path === '/admin/reports/graduation-readiness') return '/admin/curriculum'
  if (path === '/admin/reports/course-quality') return '/admin/operation/courses'
  if (path === '/admin/reports/faculty-resource-risk') return '/admin/faculty'
  if (path === '/admin/reports/schedule-strategy') return '/admin/operation/courses'

  return path
}

export function leafMenus(menus: AuthMenu[]): AuthMenu[] {
  const parentIds = new Set(
    menus.map(menu => menu.parent_id).filter((id): id is string => !!id),
  )
  return menus
    .filter(menu => !parentIds.has(menu.menu_id))
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
}

export function homePathForUser(user: AuthUser | null, menus: AuthMenu[]): string {
  const allowed = new Set(leafMenus(menus).map(menu => menu.path))
  const preferred: string[] = []
  if (user?.username === 'admin') preferred.push('/admin/system/accounts')
  if (user?.role === 'counselor' || user?.role === 'teacher') {
    preferred.push('/admin/alert', '/admin/students/analysis')
  } else {
    preferred.push('/admin/dashboard')
  }
  preferred.push('/admin/reports/management-briefing', '/admin/system/accounts')
  return preferred.find(path => allowed.has(path)) || leafMenus(menus)[0]?.path || '/login'
}

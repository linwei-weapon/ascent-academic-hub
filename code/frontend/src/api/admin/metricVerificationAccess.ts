import { http } from '@/utils/http'
import type { AuthMenu } from '@/types/auth'

/** 核验原型服务复核现有身份后返回入口，失败时保留原环境菜单。 */
export async function appendVerificationMenu(menus: AuthMenu[]): Promise<AuthMenu[]> {
  if (import.meta.env.MODE !== 'test') return menus
  try {
    const access = await http.getSilent<{
      authorized: boolean; parent: AuthMenu; menu: AuthMenu
    }>('/admin/metric-verification/access')
    if (!access.authorized) return menus
    const merged = [...menus]
    for (const item of [access.parent, access.menu]) {
      if (!merged.some(m => m.menu_id === item.menu_id || m.path === item.path)) merged.push(item)
    }
    return merged
  } catch {
    return menus
  }
}

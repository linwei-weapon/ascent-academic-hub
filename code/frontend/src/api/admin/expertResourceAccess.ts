import { http } from '@/utils/http'
import type { AuthMenu } from '@/types/auth'

/** Optional resource service grants entries only after verifying the active identity. */
export async function appendExpertResourceMenus(menus: AuthMenu[]): Promise<AuthMenu[]> {
  if (import.meta.env.MODE !== 'test') return menus
  try {
    const result = await http.getSilent<{ authorized: boolean; menus: AuthMenu[] }>('/admin/expert-resources/access')
    if (!result.authorized) return menus
    const merged = menus.filter(item => item.path !== '/admin/system/expert-resources')
    for (const item of result.menus) {
      if (!merged.some(m => m.menu_id === item.menu_id || m.path === item.path)) merged.push(item)
    }
    return merged
  } catch { return menus }
}

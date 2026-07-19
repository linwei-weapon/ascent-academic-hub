import { computed } from 'vue'
import { authStore } from '@/store/auth'

/** 页面标题跟随已发布菜单标题，学校改名后无需二次修改业务页面。 */
export function useBusinessPageTitle(menuPath: string, fallback: string) {
  return computed(() => (
    authStore.menus.find(item => item.path === menuPath)?.title || fallback
  ))
}

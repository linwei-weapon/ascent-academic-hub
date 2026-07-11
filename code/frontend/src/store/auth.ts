/**
 * 认证状态：token / 当前用户 / 后端返回的可见菜单。
 * 登录后同步 roleStore.role（供既有页面的角色视角判断复用）。
 */
import { reactive, computed } from 'vue'
import { http, setToken, clearToken, getToken } from '@/utils/http'
import { roleStore, type RoleType, setCollege, setMajorId, setManagedClasses } from '@/store/role'

export interface AuthMenu {
  menu_id: string
  title: string
  path: string
  icon?: string | null
  sort_order?: number
  parent_id?: string | null
}

export interface AuthUser {
  username: string
  name: string
  role: string
  roleName: string
  scope?: { collegeId?: string; collegeName?: string; majorId?: string; classIds?: string[] }
}

interface AuthState {
  user: AuthUser | null
  menus: AuthMenu[]
}

export const authStore = reactive<AuthState>({
  user: null,
  menus: [],
})

export const isLoggedIn = computed(() => !!authStore.user)
export const visibleMenus = computed(() => authStore.menus)

function applyUser(user: AuthUser, menus: AuthMenu[]): void {
  authStore.user = user
  authStore.menus = [...menus].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  // 同步既有角色视角（校级/院级判断、数据大屏标题等仍读 roleStore）
  roleStore.role = user.role as RoleType
  // 同步数据范围（学院/专业/班级）
  const s = user.scope
  if (s?.collegeId) setCollege(s.collegeId, s.collegeName || s.collegeId)
  if (s?.majorId) setMajorId(s.majorId)
  if (s?.classIds) setManagedClasses(s.classIds)
}

/** 账号密码登录 */
export async function login(username: string, password: string): Promise<void> {
  const data = await http.post<{ token: string; user: AuthUser & { menus: AuthMenu[] } }>(
    '/auth/login', { username, password })
  setToken(data.token)
  applyUser(data.user, data.user.menus || [])
}

/** 刷新页面后用已存 token 恢复会话；失败抛错由守卫处理 */
export async function fetchMe(): Promise<void> {
  if (!getToken()) throw new Error('no token')
  const data = await http.get<AuthUser & { menus: AuthMenu[] }>('/auth/me')
  applyUser(data, data.menus || [])
}

/** 登出：清 token + 状态，跳登录页 */
export function logout(): void {
  clearToken()
  authStore.user = null
  authStore.menus = []
  location.hash = '#/login'
}

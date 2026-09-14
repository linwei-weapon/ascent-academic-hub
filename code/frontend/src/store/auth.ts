/**
 * 认证状态：token / 当前用户 / 后端返回的可见菜单。
 * 登录后同步 roleStore.role（供既有页面的角色视角判断复用）。
 */
import { reactive, computed } from 'vue'
import {
  setToken, clearToken, getToken, setActiveIdentity, clearActiveIdentity,
} from '@/utils/http'
import { roleStore, type RoleType, setCollege, setMajorId, setManagedClasses } from '@/store/role'
import { loginWithPassword, getCurrentUser, switchWorkIdentity, logoutSession } from '@/api/auth'
import type { AuthMenu, AuthUser } from '@/types/auth'

// 保留既有类型导入路径，页面与菜单工具可继续从 Store 导入。
export type { AuthMenu, AuthUser } from '@/types/auth'

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
  if (user.activeIdentityId) setActiveIdentity(user.activeIdentityId)
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
  const data = await loginWithPassword(username, password)
  setToken(data.token)
  applyUser(data.user, data.user.menus || [])
}

/** 刷新页面后用已存 token 恢复会话；失败抛错由守卫处理 */
export async function fetchMe(): Promise<void> {
  if (!getToken()) throw new Error('no token')
  const data = await getCurrentUser()
  applyUser(data, data.menus || [])
}

/** 切换当前工作身份；后端重新计算菜单、动作权限和数据范围。 */
export async function switchIdentity(identityId: string): Promise<void> {
  const data = await switchWorkIdentity(identityId)
  applyUser(data, data.menus || [])
}

/** 先请求撤销当前令牌；无论请求结果如何，均清除本地状态并返回登录页。 */
export async function logout(): Promise<void> {
  try {
    if (getToken()) await logoutSession()
  } finally {
    clearToken()
    clearActiveIdentity()
    authStore.user = null
    authStore.menus = []
    location.hash = '#/login'
  }
}

/** 认证接口：沿用现有 JSON 包络、Bearer 和工作身份请求头。 */
import { http } from '@/utils/http'
import type { AuthProfile, LoginResponse } from '@/types/auth'

export function loginWithPassword(username: string, password: string): Promise<LoginResponse> {
  return http.post<LoginResponse>('/auth/login', { username, password })
}

export function getCurrentUser(): Promise<AuthProfile> {
  return http.get<AuthProfile>('/auth/me')
}

export function switchWorkIdentity(identityId: string): Promise<AuthProfile> {
  return http.post<AuthProfile>('/auth/switch-identity', { identityId })
}

/** 限制注销等待时间，网络异常也能完成本地退出。 */
export async function logoutSession(): Promise<void> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 5000)
  try {
    await http.post<null>('/auth/logout', undefined, { signal: controller.signal })
  } finally {
    clearTimeout(timeout)
  }
}

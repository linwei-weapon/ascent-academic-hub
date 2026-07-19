/**
 * 轻量 fetch 封装：统一注入 Bearer token、解包 {code,msg,data}、401 跳登录。
 * 不引第三方 http 库。
 */
import { ElMessage } from 'element-plus'

const TOKEN_KEY = 'bi_token'
const ACTIVE_IDENTITY_KEY = 'bi_active_identity'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}
export function getActiveIdentity(): string {
  return localStorage.getItem(ACTIVE_IDENTITY_KEY) || ''
}
export function setActiveIdentity(identityId: string): void {
  if (identityId) localStorage.setItem(ACTIVE_IDENTITY_KEY, identityId)
  else localStorage.removeItem(ACTIVE_IDENTITY_KEY)
}
export function clearActiveIdentity(): void {
  localStorage.removeItem(ACTIVE_IDENTITY_KEY)
}

interface Envelope<T> { code: number; msg: string; data: T }

function toLogin(): void {
  clearToken()
  if (!location.hash.startsWith('#/login')) location.hash = '#/login'
}

async function request<T = any>(path: string, opts: RequestInit = {}, silent = false): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers as Record<string, string> | undefined),
  }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const activeIdentity = getActiveIdentity()
  if (token && activeIdentity) headers['X-Active-Identity'] = activeIdentity

  const res = await fetch(`/api${path}`, { ...opts, headers })

  let body: Envelope<T>
  try {
    body = await res.json()
  } catch {
    if (!silent) ElMessage.error('服务器无响应')
    throw new Error('invalid response')
  }

  if (res.status === 401) {
    ElMessage.error(body?.msg || '登录已过期，请重新登录')
    toLogin()
    throw new Error(body?.msg || 'unauthorized')
  }
  if (body.code !== 0) {
    if (!silent) ElMessage.error(body.msg || '请求失败')
    throw new Error(body.msg || 'request failed')
  }
  return body.data
}

export const http = {
  get: <T = any>(p: string) => request<T>(p),
  getSilent: <T = any>(p: string) => request<T>(p, {}, true),
  post: <T = any>(p: string, data?: unknown) =>
    request<T>(p, { method: 'POST', body: JSON.stringify(data ?? {}) }),
  put: <T = any>(p: string, data?: unknown) =>
    request<T>(p, { method: 'PUT', body: JSON.stringify(data ?? {}) }),
  del: <T = any>(p: string) => request<T>(p, { method: 'DELETE' }),
}

// 专家问策请求：专家、历史会话及 POST SSE，保留原认证和事件协议。
import { http, getToken, getActiveIdentity } from '@/utils/http'
import type { AdviceExpert, AdviceSession, AdviceSessionDetail } from '@/types/decision'
import type { AdviceStreamHandlers } from '@/types/advice'
export type { AdviceStreamHandlers } from '@/types/advice'

/* 旧「决策追问抽屉」链路（POST /chat + streamDecisionChat）已随 R4 退役：
   对话入口统一收口到专家问策（/ask/*）。后端 /chat 保留一个版本周期兼容。 */

/* ---- 专家问策（R4）：/admin/ai/decision/ask/* ---- */

export function getAdviceExperts() {
  return http.get<{ items: AdviceExpert[] }>('/admin/ai/decision/ask/experts')
}

export function getAdviceSessions(skillId: string) {
  return http.get<{ items: AdviceSession[] }>(
    `/admin/ai/decision/ask/sessions?skill_id=${encodeURIComponent(skillId)}`)
}

export function getAdviceSession(sessionId: string) {
  return http.get<AdviceSessionDetail>(
    `/admin/ai/decision/ask/sessions/${encodeURIComponent(sessionId)}`)
}

/** 专家问策（SSE）：与 streamDecisionChat 同模式，POST + ReadableStream，不走 envelope。 */
export async function streamAdviceAsk(
  skillId: string,
  body: { message: string; session_id?: string; signalId?: string },
  handlers: AdviceStreamHandlers,
): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const identity = getActiveIdentity()
  if (token && identity) headers['X-Active-Identity'] = identity

  const res = await fetch(`/api/admin/ai/decision/ask/${encodeURIComponent(skillId)}`, {
    method: 'POST', headers, body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    let msg = `问策服务异常（${res.status}）`
    try {
      const data = await res.json()
      if (data?.msg) msg = data.msg
    } catch { /* ignore */ }
    handlers.onError?.(msg)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      let event = '', data = ''
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim()
        else if (line.startsWith('data: ')) data = line.slice(6)
      }
      if (!event || !data) continue
      try {
        const parsed = JSON.parse(data)
        if (event === 'meta') handlers.onMeta?.(parsed)
        else if (event === 'delta') handlers.onDelta?.(parsed.text || '')
        else if (event === 'done') handlers.onDone?.(parsed)
        else if (event === 'error') handlers.onError?.(parsed.message || '问策服务异常')
      } catch { /* 忽略半包 */ }
    }
  }
}

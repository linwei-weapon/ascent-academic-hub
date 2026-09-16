// 信号证据与明细请求：共用原信号标识、事实标签和服务端权限校验。
import { http } from '@/utils/http'
import type { SignalDetail, SignalEvidencePack } from '@/types/decision'

/* ---- 查证窗口（R2：新开浏览器窗口的只读证据页） ---- */

export function getSignalEvidence(signalId: string) {
  return http.get<SignalEvidencePack>(
    `/admin/ai/decision/signals/${encodeURIComponent(signalId)}/evidence`)
}

/* ---- 明细清单（数据要素数字 → 该数字代表的业务明细，新开标签页） ---- */

export function getSignalDetail(signalId: string, fact: string) {
  return http.get<SignalDetail>(
    `/admin/ai/decision/signals/${encodeURIComponent(signalId)}/detail?fact=${encodeURIComponent(fact)}`)
}

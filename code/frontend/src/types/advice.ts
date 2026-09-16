// 专家问策流式事件回调类型，保留 meta、delta、done、error 约定。
import type { AdviceDoneEvent, AdviceMetaEvent } from './decision'

export interface AdviceStreamHandlers {
  onMeta?: (e: AdviceMetaEvent) => void
  onDelta?: (text: string) => void
  onDone?: (e: AdviceDoneEvent) => void
  onError?: (message: string) => void
}

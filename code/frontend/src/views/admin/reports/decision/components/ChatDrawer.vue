<template>
  <el-drawer :model-value="visible" size="500px" class="chat-drawer"
    @update:model-value="emit('update:visible', $event)" @open="onDrawerOpen">
    <template #header>
      <div class="drawer-head">
        <span class="title">决策追问</span>
        <el-tag size="small" :type="llmTagType" effect="plain">{{ llmLabel }}</el-tag>
      </div>
    </template>

    <div class="chat-body">
      <div ref="scrollEl" class="messages">
        <div v-if="!messages.length" class="empty-state">
          <p class="hello">围绕当前决策简报提问：查证直接走数据，归因按「事实/假设/行动」分层呈现。</p>
          <p v-if="!llmReady" class="rule-note">LLM增强未启用：回答全部来自规则与数据直查，数字与简报严格一致。</p>
          <template v-if="contextSignal">
            <p class="ctx-label">围绕信号「{{ contextSignal.headline }}」可问：</p>
            <el-button v-for="q in contextQuestions" :key="q" class="starter" size="small"
              @click="send(q)">{{ q }}</el-button>
          </template>
          <template v-else>
            <el-button v-for="q in genericStarters" :key="q" class="starter" size="small"
              @click="send(q)">{{ q }}</el-button>
          </template>
        </div>

        <template v-for="(msg, i) in messages" :key="i">
          <div v-if="msg.role === 'user'" class="msg user">
            <div class="bubble">{{ msg.text }}</div>
          </div>
          <div v-else class="msg assistant">
            <div class="a-head">
              <el-tag v-if="msg.intentLabel" size="small" type="primary" effect="plain">{{ msg.intentLabel }}</el-tag>
              <el-tag v-if="msg.llmStatus && !msg.streaming" size="small"
                :type="statusTagType(msg.llmStatus)" effect="plain">
                {{ statusLabel(msg.llmStatus) }}
              </el-tag>
            </div>

            <div v-if="msg.cited?.length" class="cited">
              <div v-for="c in msg.cited" :key="c.signal_id" class="cited-item">
                <el-tag size="small" :type="SEVERITY_META[c.severity]?.tag || 'info'" effect="dark">
                  {{ SEVERITY_META[c.severity]?.label || c.severity }}
                </el-tag>
                <span class="cited-headline">{{ c.headline }}</span>
                <span class="cited-facts">{{ factsLine(c) }}</span>
              </div>
            </div>

            <div class="bubble">
              <span>{{ msg.text }}</span><span v-if="msg.streaming" class="cursor">▍</span>
            </div>

            <div v-for="(blk, j) in msg.blocks || []" :key="j" class="block" :class="`layer-${blk.layer}`">
              <div class="block-title">
                {{ blk.title }}
                <el-tag v-if="blk.layer === 'hypothesis' && blk.text" size="small" type="warning" effect="plain">
                  待验证
                </el-tag>
              </div>
              <p v-if="blk.text" class="block-text">{{ blk.text }}</p>
              <p v-if="blk.verify" class="block-verify">验证路径：{{ blk.verify }}</p>
              <ul v-if="blk.items?.length" class="block-items">
                <li v-for="(item, k) in blk.items" :key="k">{{ item }}</li>
              </ul>
            </div>

            <div v-if="msg.followups?.length && !msg.streaming" class="followups">
              <el-button v-for="q in msg.followups" :key="q" link type="primary" size="small"
                @click="send(q)">{{ q }}</el-button>
            </div>
          </div>
        </template>
      </div>

      <div class="input-bar">
        <el-input v-model="input" type="textarea" :rows="2" resize="none"
          placeholder="输入问题，或点上方推荐问题（Enter 发送，Shift+Enter 换行）"
          @keydown.enter.exact.prevent="send(input)" />
        <el-button type="primary" :disabled="!input.trim() || sending" :loading="sending"
          @click="send(input)">发送</el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type {
  ChatBlock, ChatCitedSignal, DecisionSignal, LlmStatus, TagType,
} from '@/types/decision'
import { SEVERITY_META } from '@/types/decision'
import { getDecisionLlmStatus, streamDecisionChat } from '@/utils/decision'

interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  intentLabel?: string
  cited?: ChatCitedSignal[]
  blocks?: ChatBlock[]
  followups?: string[]
  llmStatus?: string
  streaming?: boolean
}

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ 'update:visible': [value: boolean] }>()

const messages = ref<ChatMessage[]>([])
const input = ref('')
const sending = ref(false)
const scrollEl = ref<HTMLElement | null>(null)
const llm = ref<LlmStatus | null>(null)
const contextSignal = ref<DecisionSignal | null>(null)

const llmReady = computed(() => Boolean(llm.value?.ready && llm.value?.chat_enabled))
const llmLabel = computed(() => (llmReady.value ? 'LLM增强已启用' : '规则生成模式'))
const llmTagType = computed((): TagType => (llmReady.value ? 'primary' : 'info'))

const genericStarters = [
  '今天有哪些需要处置的事项？',
  '哪些课程的未通过是结构性的？',
  '本周预警干预应该先给谁？',
  '当前首要事项为什么排最前？',
]
const contextQuestions = computed(() => contextSignal.value?.suggested_questions?.slice(0, 4) || [])

async function onDrawerOpen() {
  if (!llm.value) {
    try { llm.value = await getDecisionLlmStatus() } catch { /* 状态角标失败不影响对话 */ }
  }
}

/** 供父组件打开抽屉：可带信号上下文与预置问题（卡片追问按钮接入） */
function open(opts: { question?: string; signal?: DecisionSignal | null } = {}) {
  if (opts.signal !== undefined) contextSignal.value = opts.signal
  emit('update:visible', true)
  if (opts.question) send(opts.question)
}
defineExpose({ open })

function factsLine(c: ChatCitedSignal): string {
  return Object.entries(c.facts || {}).map(([k, v]) => `${k} ${v}`).join('；')
}

function statusLabel(status: string): string {
  if (status === 'ok') return 'LLM增强'
  if (status === 'not_used') return '数据直查'
  if (status === 'disabled') return '规则生成'
  return '规则生成·已回退'
}
function statusTagType(status: string): TagType {
  if (status === 'ok') return 'primary'
  if (status === 'not_used') return 'success'
  if (status === 'disabled') return 'info'
  return 'warning'
}

async function scrollBottom() {
  await nextTick()
  scrollEl.value?.scrollTo({ top: scrollEl.value.scrollHeight })
}

async function send(raw: string) {
  const text = (raw || '').trim()
  if (!text || sending.value) return
  input.value = ''
  messages.value.push({ role: 'user', text })
  const assistant: ChatMessage = { role: 'assistant', text: '', streaming: true }
  messages.value.push(assistant)
  sending.value = true
  scrollBottom()

  const history = messages.value
    .filter(m => !m.streaming && m.text)
    .slice(-6)
    .map(m => ({ role: m.role, content: m.text }))

  try {
    await streamDecisionChat(
      { message: text, signalId: contextSignal.value?.signal_id || '', history },
      {
        onMeta: e => {
          assistant.intentLabel = e.intent_label
          assistant.cited = e.cited
          scrollBottom()
        },
        onDelta: chunk => {
          assistant.text += chunk
          scrollBottom()
        },
        onDone: e => {
          assistant.blocks = e.blocks
          assistant.followups = e.followups
          assistant.llmStatus = e.llm_status
          assistant.streaming = false
          scrollBottom()
        },
        onError: message => {
          assistant.text = message
          assistant.llmStatus = 'failed'
          assistant.streaming = false
        },
      })
  } catch {
    assistant.text = '对话服务连接失败，请稍后重试。'
    assistant.llmStatus = 'failed'
    assistant.streaming = false
  } finally {
    assistant.streaming = false
    sending.value = false
    scrollBottom()
  }
}
</script>

<style scoped>
.drawer-head { display: flex; align-items: center; gap: 10px; }
.drawer-head .title { font-size: 16px; font-weight: 600; color: #303133; }
.chat-body { display: flex; flex-direction: column; height: 100%; }
.messages { flex: 1; overflow-y: auto; padding: 4px 2px 12px; }
.empty-state { padding: 18px 6px; }
.hello { margin: 0 0 8px; color: #606266; font-size: 13px; line-height: 1.7; }
.rule-note { margin: 0 0 12px; color: #909399; font-size: 12px; }
.ctx-label { margin: 10px 0 6px; color: #909399; font-size: 12px; }
.starter { display: block; margin: 6px 0; text-align: left; white-space: normal; height: auto; }
.msg { margin: 12px 0; }
.msg.user { display: flex; justify-content: flex-end; }
.msg.user .bubble { background: #4f46e5; color: #fff; border-radius: 10px 10px 2px 10px;
  padding: 8px 12px; max-width: 85%; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.msg.assistant .bubble { background: #f5f7fa; border-radius: 2px 10px 10px 10px; padding: 10px 12px;
  font-size: 13px; line-height: 1.7; color: #303133; white-space: pre-wrap; }
.a-head { display: flex; gap: 6px; margin-bottom: 6px; }
.cursor { display: inline-block; animation: blink 0.9s step-start infinite; color: #4f46e5; }
@keyframes blink { 50% { opacity: 0; } }
.cited { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.cited-item { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  border: 1px solid #e4e7ed; border-radius: 8px; padding: 6px 8px; background: #fff; }
.cited-headline { font-size: 12px; color: #303133; flex: 1; min-width: 60%; }
.cited-facts { font-size: 11px; color: #4f46e5; }
.block { margin-top: 8px; border-radius: 8px; padding: 8px 10px; font-size: 12px; }
.block-title { font-weight: 600; color: #475569; display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }
.block-text { margin: 0; color: #334155; line-height: 1.7; }
.block-verify { margin: 4px 0 0; color: #92400e; font-size: 11px; }
.block-items { margin: 4px 0 0; padding-left: 18px; color: #334155; line-height: 1.8; }
.layer-facts { background: #eff6ff; border-left: 3px solid #3b82f6; }
.layer-hypothesis { background: #fffbeb; border-left: 3px solid #f59e0b; }
.layer-action { background: #f0fdf4; border-left: 3px solid #22c55e; }
.layer-points { background: #f8fafc; border-left: 3px solid #94a3b8; }
.followups { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 2px 10px; }
.input-bar { display: flex; gap: 8px; align-items: flex-end; padding-top: 10px;
  border-top: 1px solid #ebeef5; }
</style>

<template>
  <div class="advice-layout">
    <!-- 左栏：专家切换 + 历史会话 -->
    <aside class="side">
      <div class="side-head">
        <b class="side-title">专家问策</b>
        <div class="side-links">
          <router-link to="/admin/reports/advice" class="back-link">‹ 专家库</router-link>
          <router-link to="/admin/reports/decision" class="back-link">‹ 决策简报</router-link>
        </div>
      </div>

      <p class="side-label">选择专家</p>
      <button v-for="ex in experts" :key="ex.skill_id" type="button" class="expert-row"
        :class="{ active: ex.skill_id === skillId }" @click="switchExpert(ex.skill_id)">
        <span class="expert-icon">{{ ex.icon || '策' }}</span>
        <span class="expert-row-name">{{ ex.name }}</span>
      </button>

      <div class="side-label row">
        <span>对话</span>
        <el-button link type="primary" size="small" @click="newChat">+ 新对话</el-button>
      </div>
      <div class="session-list">
        <button v-for="s in sessions" :key="s.session_id" type="button" class="session-row"
          :class="{ active: s.session_id === currentSessionId }" @click="loadSession(s)">
          <span class="session-title">· {{ s.title || '未命名对话' }}</span>
          <span class="session-time">{{ formatTime(s.updated_at) }}</span>
        </button>
        <p v-if="!sessions.length" class="session-empty">暂无历史对话</p>
      </div>
    </aside>

    <!-- 中栏：纯对话流 -->
    <main class="main">
      <div class="main-head">
        <h2 class="sa-page-title">{{ expert?.name || '专家问策' }}</h2>
        <p class="sa-page-sub">对话不产生任何办理动作 · 建议必附依据</p>
      </div>

      <div ref="scrollEl" class="chat-flow">
        <!-- 空态：居中输入 + 示例问法 -->
        <div v-if="!messages.length" class="empty-state">
          <h3 class="empty-title">{{ expert?.name || '' }}</h3>
          <p class="empty-q">{{ expert?.management_question }}</p>
          <div class="hero-input">
            <el-input v-model="input" placeholder="向专家提问…" size="large"
              @keydown.enter.exact.prevent="send(input)">
              <template #append>
                <el-button type="primary" :disabled="!input.trim() || sending" :loading="sending"
                  @click="send(input)">
                  <el-icon><Promotion /></el-icon>
                </el-button>
              </template>
            </el-input>
          </div>
          <div class="starter-chips">
            <el-button v-for="q in exampleChips" :key="q" round size="small" class="chip"
              @click="send(q)">{{ q }}</el-button>
          </div>
          <p class="empty-note">规则生成 · 回答中的每个数字都可核验</p>
        </div>

        <!-- 对话态 -->
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

            <!-- 越界拒答：指路到对应专家 -->
            <div v-if="msg.redirect && !msg.streaming" class="redirect-box">
              <span class="redirect-note">本问题超出本专家领域，建议改问：</span>
              <el-button type="primary" size="small" plain @click="goExpert(msg.redirect.skill_id)">
                去找{{ msg.redirect.name }} ›
              </el-button>
            </div>

            <div v-if="msg.boundary && !msg.streaming" class="boundary-line">
              适用边界：{{ msg.boundary }}
            </div>

            <div v-if="msg.evidenceRefs?.length && !msg.streaming" class="refs">
              <span class="refs-label">依据</span>
              <button v-for="r in msg.evidenceRefs" :key="r.n" type="button" class="ref-btn"
                :title="r.headline" @click="openEvidenceWindow(r.signal_id)">[{{ r.n }}]</button>
            </div>

            <div v-if="msg.suggested?.length && !msg.streaming" class="suggested">
              <el-button v-for="q in msg.suggested" :key="q" round size="small" class="chip"
                @click="onSuggested(msg, q)">{{ q }}</el-button>
            </div>
          </div>
        </template>
      </div>

      <div v-if="messages.length" class="input-bar">
        <el-input v-model="input" type="textarea" :rows="2" resize="none"
          placeholder="输入问题，或点推荐问法（Enter 发送，Shift+Enter 换行）"
          @keydown.enter.exact.prevent="send(input)" />
        <el-button type="primary" :disabled="!input.trim() || sending" :loading="sending"
          @click="send(input)">发送</el-button>
      </div>
    </main>

    <!-- 右栏：本轮依据 + 数据要素 / 空态今日信号 -->
    <aside class="rail">
      <template v-if="latestRefs.length">
        <div class="rail-section">
          <p class="rail-title">本轮依据</p>
          <p class="rail-sub">编号与对话中的 [n] 对应，点击核验</p>
          <button v-for="r in latestRefs" :key="r.n" type="button" class="ref-item"
            :style="{ borderLeftColor: SEVERITY_META[r.severity]?.color || '#909399' }"
            @click="openEvidenceWindow(r.signal_id)">
            <span class="ref-head">
              <span class="ref-n">{{ r.n }}</span>
              <b class="ref-headline">{{ r.headline }}</b>
            </span>
            <span class="ref-facts">{{ factsLine(r) }}</span>
          </button>
        </div>

        <div v-if="factTiles.length" class="rail-section">
          <p class="rail-title">数据要素 · 本专家速览</p>
          <p class="rail-sub">点击任一数字查证来源</p>
          <div class="fact-grid">
            <button v-for="t in factTiles" :key="t.k" type="button" class="fact-tile"
              :title="`查证来源信号：${t.headline}`"
              @click="openEvidenceWindow(t.signal_id)">
              <span class="fact-k">{{ t.k }}</span>
              <b class="fact-v">{{ t.v }}</b>
            </button>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="rail-section">
          <p class="rail-title">今日信号 · {{ expert?.name || '' }}</p>
          <button v-if="expert?.top_signal" type="button" class="ref-item"
            :style="{ borderLeftColor: SEVERITY_META[expert.top_signal.severity]?.color || '#909399' }"
            @click="askSignal(expert.top_signal.signal_id)">
            <span class="ref-head">
              <el-tag size="small" :type="SEVERITY_META[expert.top_signal.severity]?.tag || 'info'" effect="dark">
                {{ SEVERITY_META[expert.top_signal.severity]?.label || expert.top_signal.severity }}
              </el-tag>
              <b class="ref-headline">{{ expert.top_signal.headline }}</b>
            </span>
          </button>
          <p v-else class="rail-sub">今日无异常信号</p>
          <p class="rail-sub">点击信号即可就它提问</p>
        </div>
      </template>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Promotion } from '@element-plus/icons-vue'
import type {
  AdviceEvidenceRef, AdviceExpert, AdviceRedirect, AdviceSession, ChatBlock, TagType,
} from '@/types/decision'
import { SEVERITY_META } from '@/types/decision'
import {
  getAdviceExperts, getAdviceSession, getAdviceSessions, openEvidenceWindow, streamAdviceAsk,
} from '@/utils/decision'

interface AdviceMessage {
  role: 'user' | 'assistant'
  text: string
  intentLabel?: string
  evidenceRefs?: AdviceEvidenceRef[]
  blocks?: ChatBlock[]
  suggested?: string[]
  boundary?: string
  redirect?: AdviceRedirect | null
  llmStatus?: string
  streaming?: boolean
}

const route = useRoute()
const router = useRouter()

const skillId = computed(() => String(route.params.skillId || ''))
const experts = ref<AdviceExpert[]>([])
const expert = computed(() => experts.value.find(e => e.skill_id === skillId.value) || null)
const sessions = ref<AdviceSession[]>([])
const currentSessionId = ref('')
const messages = ref<AdviceMessage[]>([])
const input = ref('')
const sending = ref(false)
const scrollEl = ref<HTMLElement | null>(null)

const exampleChips = computed(() => (expert.value?.example_questions || []).slice(0, 4))

/** 右栏「本轮依据」：最近一条带引用的助手消息 */
const latestRefs = computed<AdviceEvidenceRef[]>(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const m = messages.value[i]
    if (m.role === 'assistant' && m.evidenceRefs?.length && !m.streaming) return m.evidenceRefs
  }
  return []
})

/** 数据要素速览：最近引用的 facts 键值，带来源信号（可点击查证），去重取前 6 */
const factTiles = computed(() => {
  const tiles: { k: string; v: string; signal_id: string; headline: string }[] = []
  const seen = new Set<string>()
  for (const r of latestRefs.value) {
    for (const [k, v] of Object.entries(r.facts || {})) {
      if (seen.has(k)) continue
      seen.add(k)
      tiles.push({ k, v, signal_id: r.signal_id, headline: r.headline })
      if (tiles.length >= 6) return tiles
    }
  }
  return tiles
})

function factsLine(r: AdviceEvidenceRef): string {
  return Object.entries(r.facts || {}).map(([k, v]) => `${k} ${v}`).join(' · ')
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

function formatTime(value: string): string {
  return (value || '').replace('T', ' ').slice(5, 16) || ''
}

async function scrollBottom() {
  await nextTick()
  scrollEl.value?.scrollTo({ top: scrollEl.value.scrollHeight })
}

function switchExpert(id: string) {
  if (id !== skillId.value) router.push(`/admin/reports/advice/${encodeURIComponent(id)}`)
}

function goExpert(id: string) {
  router.push(`/admin/reports/advice/${encodeURIComponent(id)}`)
}

/** 推荐问法：越界拒答的推荐问法跳转到对应专家并自动发问，其余在本会话追问 */
function onSuggested(msg: AdviceMessage, q: string) {
  if (msg.redirect) {
    router.push(`/admin/reports/advice/${encodeURIComponent(msg.redirect.skill_id)}?q=${encodeURIComponent(q)}`)
  } else {
    send(q)
  }
}

function askSignal(signalId: string) {
  send('请解读这条信号', { signalId })
}

async function refreshSessions() {
  try {
    const data = await getAdviceSessions(skillId.value)
    sessions.value = data.items || []
  } catch { sessions.value = [] }
}

async function loadSession(s: AdviceSession) {
  if (sending.value) return
  try {
    const detail = await getAdviceSession(s.session_id)
    currentSessionId.value = s.session_id
    messages.value = (detail.messages || []).map(m => {
      if (m.role === 'user') return { role: 'user', text: m.content } as AdviceMessage
      const p = m.payload || {}
      return {
        role: 'assistant',
        text: m.content,
        intentLabel: p.intent_label || p.intent || '',
        evidenceRefs: p.evidence_refs || [],
        blocks: p.blocks || [],
        suggested: p.suggested_questions || [],
        boundary: p.boundary || '',
        redirect: p.redirect || null,
        llmStatus: p.llm_status || '',
      } as AdviceMessage
    })
    scrollBottom()
  } catch { /* 信封层已提示 */ }
}

function newChat() {
  if (sending.value) return
  messages.value = []
  currentSessionId.value = ''
  input.value = ''
  if (route.query.signal || route.query.q) {
    router.replace(`/admin/reports/advice/${encodeURIComponent(skillId.value)}`)
  }
}

async function send(raw: string, opts: { signalId?: string } = {}) {
  const text = (raw || '').trim()
  if (!text || sending.value || !skillId.value) return
  input.value = ''
  messages.value.push({ role: 'user', text })
  // 注意：必须通过数组内的响应式代理修改消息字段，
  // 直接改原始对象不会触发 computed（右栏「本轮依据」会因此不刷新）
  messages.value.push({ role: 'assistant', text: '', streaming: true })
  const assistant = messages.value[messages.value.length - 1]
  sending.value = true
  scrollBottom()

  try {
    await streamAdviceAsk(
      skillId.value,
      {
        message: text,
        session_id: currentSessionId.value || undefined,
        signalId: opts.signalId || undefined,
      },
      {
        onMeta: e => {
          if (e.session_id) currentSessionId.value = e.session_id
          assistant.intentLabel = e.intent_label
          assistant.evidenceRefs = e.evidence_refs || []
          assistant.redirect = e.redirect || null
          scrollBottom()
        },
        onDelta: chunk => {
          assistant.text += chunk
          scrollBottom()
        },
        onDone: e => {
          if (e.session_id) currentSessionId.value = e.session_id
          assistant.blocks = e.blocks || []
          assistant.suggested = e.suggested_questions || []
          assistant.boundary = e.boundary || ''
          assistant.redirect = e.redirect || assistant.redirect || null
          assistant.llmStatus = e.llm_status
          assistant.streaming = false
          refreshSessions()
          scrollBottom()
        },
        onError: message => {
          assistant.text = message
          assistant.llmStatus = 'failed'
          assistant.streaming = false
        },
      })
  } catch {
    assistant.text = '问策服务连接失败，请稍后重试。'
    assistant.llmStatus = 'failed'
    assistant.streaming = false
  } finally {
    assistant.streaming = false
    sending.value = false
    scrollBottom()
  }
}

/** 进入/切换专家：重置会话，处理 ?signal= / ?q= 自动发问 */
async function init() {
  messages.value = []
  currentSessionId.value = ''
  input.value = ''
  if (!experts.value.length) {
    try {
      const data = await getAdviceExperts()
      experts.value = data.items || []
    } catch { experts.value = [] }
  }
  refreshSessions()
  const signal = String(route.query.signal || '')
  const q = String(route.query.q || '')
  if (signal) send('请解读这条信号', { signalId: signal })
  else if (q) send(q)
}

watch(() => route.fullPath, (to, from) => {
  // 仅路径或引导参数变化时重初始化；会话过程中不改 URL
  if (to !== from) init()
})
onMounted(init)
</script>

<style scoped>
.advice-layout { display: grid; grid-template-columns: 220px minmax(0, 1fr) 300px; gap: 14px;
  height: calc(100vh - 120px); min-height: 520px; }

/* 左栏 */
.side { display: flex; flex-direction: column; background: #fff; border: 1px solid #e4e7ed;
  border-radius: 10px; padding: 14px 12px; overflow-y: auto; }
.side-head { margin-bottom: 10px; }
.side-title { font-size: 15px; color: #0f172a; }
.side-links { display: flex; gap: 10px; margin-top: 4px; }
.back-link { font-size: 12px; color: #909399; text-decoration: none; }
.back-link:hover { color: #4f46e5; }
.side-label { margin: 12px 0 6px; font-size: 12px; color: #909399; }
.side-label.row { display: flex; justify-content: space-between; align-items: center; }
.expert-row { display: flex; align-items: center; gap: 8px; width: 100%; border: none;
  background: transparent; border-radius: 8px; padding: 7px 8px; cursor: pointer;
  font-size: 13px; color: #303133; text-align: left; }
.expert-row:hover { background: #f5f7fa; }
.expert-row.active { background: #eef2ff; color: #4f46e5; font-weight: 600; }
.expert-icon { width: 26px; height: 26px; border-radius: 8px; background: #4f46e5; color: #fff;
  font-size: 13px; display: grid; place-items: center; flex-shrink: 0; }
.expert-row-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-list { display: flex; flex-direction: column; gap: 2px; }
.session-row { display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  border: none; background: transparent; border-radius: 8px; padding: 6px 8px; cursor: pointer;
  text-align: left; }
.session-row:hover { background: #f5f7fa; }
.session-row.active { background: #eef2ff; }
.session-title { font-size: 12px; color: #303133; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; max-width: 100%; }
.session-time { font-size: 11px; color: #b0b6c0; }
.session-empty { margin: 4px 8px; font-size: 12px; color: #c0c4cc; }

/* 中栏 */
.main { display: flex; flex-direction: column; background: #fff; border: 1px solid #e4e7ed;
  border-radius: 10px; padding: 14px 18px; min-width: 0; }
.main-head { border-bottom: 1px solid #ebeef5; padding-bottom: 10px; }
.chat-flow { flex: 1; overflow-y: auto; padding: 14px 4px; }

.empty-state { max-width: 640px; margin: 8vh auto 0; text-align: center; }
.empty-title { margin: 0; font-size: 22px; color: #0f172a; }
.empty-q { margin: 10px 0 26px; font-size: 13px; color: #64748b; line-height: 1.8; }
.hero-input { max-width: 560px; margin: 0 auto; }
.starter-chips { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 18px; }
.chip { border-color: #c7d2fe; color: #4f46e5; background: #eef2ff; }
.chip:hover { background: #e0e7ff; }
.empty-note { margin-top: 22px; font-size: 12px; color: #b0b6c0; }

.msg { margin: 14px 0; }
.msg.user { display: flex; justify-content: flex-end; }
.msg.user .bubble { background: #4f46e5; color: #fff; border-radius: 10px 10px 2px 10px;
  padding: 9px 14px; max-width: 78%; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.msg.assistant .bubble { background: #f5f7fa; border-radius: 2px 10px 10px 10px; padding: 10px 14px;
  font-size: 13px; line-height: 1.8; color: #303133; white-space: pre-wrap; }
.a-head { display: flex; gap: 6px; margin-bottom: 6px; }
.cursor { display: inline-block; animation: blink 0.9s step-start infinite; color: #4f46e5; }
@keyframes blink { 50% { opacity: 0; } }

.block { margin-top: 8px; border-radius: 8px; padding: 8px 10px; font-size: 12px; }
.block-title { font-weight: 600; color: #475569; display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }
.block-text { margin: 0; color: #334155; line-height: 1.7; }
.block-verify { margin: 4px 0 0; color: #92400e; font-size: 11px; }
.block-items { margin: 4px 0 0; padding-left: 18px; color: #334155; line-height: 1.8; }
.layer-facts { background: #eff6ff; border-left: 3px solid #3b82f6; }
.layer-hypothesis { background: #fffbeb; border-left: 3px solid #f59e0b; }
.layer-action { background: #f0fdf4; border-left: 3px solid #22c55e; }
.layer-points { background: #f8fafc; border-left: 3px solid #94a3b8; }

.redirect-box { display: flex; align-items: center; gap: 10px; margin-top: 8px;
  border: 1px dashed #f59e0b; background: #fffbeb; border-radius: 8px; padding: 8px 10px; }
.redirect-note { font-size: 12px; color: #92400e; }
.boundary-line { margin-top: 8px; font-size: 11px; color: #909399; line-height: 1.6; }

.refs { display: flex; align-items: center; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.refs-label { font-size: 12px; color: #909399; }
.ref-btn { border: 1px solid #c7d2fe; background: #eef2ff; color: #4f46e5; border-radius: 6px;
  padding: 1px 7px; font-size: 12px; cursor: pointer; }
.ref-btn:hover { background: #e0e7ff; }
.suggested { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }

.input-bar { display: flex; gap: 8px; align-items: flex-end; padding-top: 10px;
  border-top: 1px solid #ebeef5; }

/* 右栏 */
.rail { display: flex; flex-direction: column; gap: 12px; background: #fff;
  border: 1px solid #e4e7ed; border-radius: 10px; padding: 14px 12px; overflow-y: auto; }
.rail-section { display: flex; flex-direction: column; gap: 8px; }
.rail-title { margin: 0; font-size: 14px; font-weight: 600; color: #0f172a; }
.rail-sub { margin: 0; font-size: 11px; color: #b0b6c0; }
.ref-item { display: flex; flex-direction: column; gap: 4px; border: 1px solid #ebeef5;
  border-left: 3px solid #909399; border-radius: 8px; background: #fff; padding: 8px 10px;
  cursor: pointer; text-align: left; }
.ref-item:hover { background: #fafbff; border-color: #c7d2fe; }
.ref-head { display: flex; align-items: center; gap: 6px; }
.ref-n { width: 18px; height: 18px; border-radius: 50%; border: 1px solid #c7d2fe; color: #4f46e5;
  font-size: 11px; display: grid; place-items: center; flex-shrink: 0; }
.ref-headline { font-size: 12px; color: #303133; line-height: 1.5; }
.ref-facts { font-size: 11px; color: #909399; line-height: 1.5; }
.fact-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.fact-tile { display: flex; flex-direction: column; gap: 2px; background: #f8fafc;
  border: 1px solid transparent; border-radius: 8px; padding: 8px 10px;
  cursor: pointer; text-align: left; transition: border-color .15s, background .15s; }
.fact-tile:hover { border-color: #c7d2fe; background: #eef2ff; }
.fact-k { font-size: 11px; color: #909399; }
.fact-v { font-size: 15px; color: #4f46e5; }

@media (max-width: 1200px) {
  .advice-layout { grid-template-columns: 200px minmax(0, 1fr); height: auto; }
  .rail { display: none; }
}
</style>

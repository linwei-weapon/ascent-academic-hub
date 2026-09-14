<template>
  <div>
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports/decision">AI管理决策</el-breadcrumb-item>
      <el-breadcrumb-item>决策简报</el-breadcrumb-item>
    </el-breadcrumb>

    <div class="page-head">
      <div>
        <h2 class="sa-page-title">AI决策简报</h2>
        <p class="sa-page-sub">首屏只有判断：全部数字由 Skill 确定性代码产出；数据未变化时复用快照。</p>
      </div>
      <div class="head-actions">
        <el-button type="success" plain @click="openChat()">决策追问</el-button>
        <el-button :loading="loading" @click="load(false)">刷新</el-button>
        <el-button type="primary" :loading="loading" @click="load(true)">重新生成</el-button>
      </div>
    </div>

    <!-- 冷启动分段进度：按 Skill 逐个呈现运行状态 -->
    <div v-if="loading && !briefing" class="sa-card coldstart">
      <div class="coldstart-head">
        <el-icon class="is-loading" :size="16"><Loading /></el-icon>
        <b>正在运行决策 Skills（{{ elapsed }}s）</b>
        <span class="muted">首次生成约需 1 分钟；之后数据未变化时秒级复用快照</span>
      </div>
      <div class="coldstart-steps">
        <span v-for="(name, i) in skillNames" :key="i" class="step"
          :class="{ done: i < doneSteps, active: i === doneSteps }">
          {{ name }}
        </span>
      </div>
    </div>

    <template v-if="briefing">
      <ToplineBar :briefing="briefing" />
      <p class="meta-line">
        {{ briefing.generation_method === 'llm_enhanced' ? 'LLM增强' : '规则生成' }}
        <template v-if="briefing.cache_hit"> · 快照复用</template>
        · 生成于 {{ formatTime(briefing.generated_at) }} · 数据学期 {{ briefing.semester }}
      </p>

      <!-- Top3：第 1 条展开，其余一行折叠；同信号单页只出现一次 -->
      <section v-if="top3.length" class="priority-section">
        <div class="section-heading">
          <h3>今日优先（{{ top3.length }}）</h3>
          <p>先处理第 1 项；点击其余行展开详情</p>
        </div>

        <div class="top1">
          <span class="rank">1</span>
          <ConclusionCard :signal="top3[0]" @ask="onCardAsk" />
        </div>

        <div v-for="(sig, i) in top3.slice(1)" :key="sig.signal_id" class="fold-item">
          <button class="fold-row" type="button" @click="toggleExpand(sig.signal_id)">
            <span class="rank small">{{ i + 2 }}</span>
            <el-tag size="small" :type="SEVERITY_META[sig.severity]?.tag || 'info'" effect="dark">
              {{ SEVERITY_META[sig.severity]?.label || sig.severity }}
            </el-tag>
            <span class="fold-headline">{{ sig.headline }}</span>
            <span class="fold-when">{{ sig.action.when }}</span>
            <el-icon><ArrowDown v-if="expandedId !== sig.signal_id" /><ArrowUp v-else /></el-icon>
          </button>
          <div v-if="expandedId === sig.signal_id" class="fold-body">
            <ConclusionCard :signal="sig" @ask="onCardAsk" />
          </div>
        </div>

        <button v-if="restPriority.length" class="more-row" type="button" @click="showRest = !showRest">
          {{ showRest ? '收起' : `还有 ${restPriority.length} 项重点` }}
          <el-icon><ArrowUp v-if="showRest" /><ArrowDown v-else /></el-icon>
        </button>
        <template v-if="showRest">
          <div v-for="sig in restPriority" :key="sig.signal_id" class="fold-item">
            <button class="fold-row" type="button" @click="toggleExpand(sig.signal_id)">
              <el-tag size="small" :type="SEVERITY_META[sig.severity]?.tag || 'info'" effect="plain">
                {{ SEVERITY_META[sig.severity]?.label || sig.severity }}
              </el-tag>
              <span class="fold-headline">{{ sig.headline }}</span>
              <span class="fold-when">{{ sig.action.when }}</span>
              <el-icon><ArrowDown v-if="expandedId !== sig.signal_id" /><ArrowUp v-else /></el-icon>
            </button>
            <div v-if="expandedId === sig.signal_id" class="fold-body">
              <ConclusionCard :signal="sig" @ask="onCardAsk" />
            </div>
          </div>
        </template>
      </section>

      <!-- 专题分区：默认折叠为计数行；Top3 信号已去重不再出现 -->
      <section class="sa-card sections-card">
        <div class="sa-card-title">专题信号分区
          <span class="extra">今日优先中的信号不再重复列出</span>
        </div>
        <div v-for="sec in dedupedSections" :key="sec.skill_id" class="sec-fold">
          <button class="sec-row" type="button" @click="toggleSection(sec.skill_id)">
            <b>{{ sec.skill_name }}</b>
            <span class="sec-q">{{ sec.management_question }}</span>
            <el-tag size="small" :type="sec.signals.length ? 'warning' : 'success'" effect="plain">
              {{ sec.signals.length ? `${sec.signals.length} 项信号` : '无异常' }}
            </el-tag>
            <el-icon><ArrowDown v-if="openSection !== sec.skill_id" /><ArrowUp v-else /></el-icon>
          </button>
          <div v-if="openSection === sec.skill_id" class="sec-body">
            <SkillSection :section="sec" @ask="onCardAsk" />
          </div>
        </div>
      </section>

      <!-- 观察项 / 积极变化 / 已消除：一行汇总，可展开 -->
      <section v-if="otherCount" class="sa-card">
        <button class="sec-row" type="button" @click="showOthers = !showOthers">
          <b>其他动态</b>
          <span class="sec-q">
            观察项 {{ briefing.watch_items.length }} · 积极变化 {{ briefing.positive_developments.length }}
            · 已消除 {{ briefing.resolved_since_last.length }}
          </span>
          <el-icon><ArrowDown v-if="!showOthers" /><ArrowUp v-else /></el-icon>
        </button>
        <div v-if="showOthers" class="others-body">
          <div v-if="briefing.watch_items.length" class="other-group">
            <p class="other-title">观察项 <span class="muted">低严重度，暂不占用处置资源</span></p>
            <RiskCard v-for="sig in briefing.watch_items" :key="sig.signal_id" :signal="sig"
              class="mini-card" @ask="onCardAsk" />
          </div>
          <div v-if="briefing.positive_developments.length" class="other-group">
            <p class="other-title">积极变化 <span class="muted">趋势向好，可在例会通报</span></p>
            <ConclusionCard v-for="sig in briefing.positive_developments" :key="sig.signal_id"
              :signal="sig" compact class="mini-card" @ask="onCardAsk" />
          </div>
          <div v-if="briefing.resolved_since_last.length" class="other-group">
            <p class="other-title">已消除 <span class="muted">相对上次快照不再成立</span></p>
            <div v-for="item in briefing.resolved_since_last" :key="item.signal_id" class="resolved-row">
              <el-tag size="small" type="success" effect="plain">已消除</el-tag>
              <span>{{ item.headline }}</span>
            </div>
          </div>
        </div>
      </section>
    </template>

    <el-skeleton v-else-if="loading" animated :rows="8" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Loading, ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import type { DecisionBriefing, DecisionSignal } from '@/types/decision'
import { SEVERITY_META } from '@/types/decision'
import { getDecisionBriefing, getDecisionSkills } from '@/utils/decision'
import ToplineBar from './components/ToplineBar.vue'
import ConclusionCard from './components/cards/ConclusionCard.vue'
import RiskCard from './components/cards/RiskCard.vue'
import SkillSection from './components/SkillSection.vue'

const router = useRouter()

const briefing = ref<DecisionBriefing | null>(null)
const loading = ref(false)
const expandedId = ref('')
const openSection = ref('')
const showRest = ref(false)
const showOthers = ref(false)

/** Top3：首屏主角；同信号单页只出现一次 */
const top3 = computed(() => (briefing.value?.priority_items || []).slice(0, 3))
const restPriority = computed(() => (briefing.value?.priority_items || []).slice(3))
const dedupedSections = computed(() => {
  const shown = new Set((briefing.value?.priority_items || []).map(s => s.signal_id))
  return (briefing.value?.skill_sections || []).map(sec => ({
    ...sec,
    signals: sec.signals.filter(s => !shown.has(s.signal_id)),
  }))
})
const otherCount = computed(() => {
  const b = briefing.value
  return b ? (b.watch_items.length + b.positive_developments.length + b.resolved_since_last.length) : 0
})

/* 冷启动分段进度（展示性）：按 Skill 名称逐个推进，完成后由真实数据接管 */
const skillNames = ref<string[]>([])
const doneSteps = ref(0)
const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

function startProgress() {
  elapsed.value = 0
  doneSteps.value = 0
  timer = setInterval(() => {
    elapsed.value += 1
    const n = skillNames.value.length
    if (n && doneSteps.value < n - 1 && elapsed.value % 6 === 0) doneSteps.value += 1
  }, 1000)
}
function stopProgress() {
  if (timer) { clearInterval(timer); timer = null }
}

async function load(force: boolean) {
  loading.value = true
  if (!briefing.value) startProgress()
  try {
    const data = await getDecisionBriefing(force)
    briefing.value = data
    expandedId.value = ''
    openSection.value = ''
  } finally {
    loading.value = false
    stopProgress()
  }
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? '' : id
}
function toggleSection(id: string) {
  openSection.value = openSection.value === id ? '' : id
}

function formatTime(value: string): string {
  return (value || '').replace('T', ' ').slice(0, 16) || '—'
}

/** 卡片「问专家」：直达对应专家的问策对话页，并带入信号上下文自动发问 */
function onCardAsk(signal: DecisionSignal) {
  router.push(`/admin/reports/advice/${encodeURIComponent(signal.skill_id)}?signal=${encodeURIComponent(signal.signal_id)}`)
}

function openChat() {
  router.push('/admin/reports/advice')
}

onMounted(async () => {
  getDecisionSkills()
    .then(d => { skillNames.value = (d.items || []).map((s: any) => s.name) })
    .catch(() => { skillNames.value = [] })
  await load(false)
})
onUnmounted(stopProgress)
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.head-actions { display: flex; gap: 10px; padding-top: 12px; }
.coldstart { margin: 12px 0; }
.coldstart-head { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #303133; }
.coldstart-head .muted { color: #909399; font-size: 12px; }
.coldstart-steps { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.step { font-size: 12px; color: #c0c4cc; background: #f5f7fa; border-radius: 6px; padding: 3px 10px; }
.step.active { color: #4f46e5; background: #eef2ff; }
.step.done { color: #67c23a; background: #f0f9eb; }
.meta-line { margin: 6px 2px 0; font-size: 12px; color: #a0a5b0; }
.priority-section { margin: 14px 0; }
.section-heading { margin: 4px 0 10px; display: flex; align-items: baseline; gap: 10px; }
.section-heading h3 { margin: 0; color: #0f172a; }
.section-heading p { margin: 0; color: #64748b; font-size: 12px; }
.top1 { position: relative; margin-bottom: 10px; }
.top1 > .rank { position: absolute; top: -8px; left: -8px; z-index: 1; width: 26px; height: 26px;
  border-radius: 8px; background: #c45656; color: #fff; font-size: 13px; font-weight: 700;
  display: grid; place-items: center; }
.rank.small { width: 20px; height: 20px; border-radius: 6px; background: #0f172a; color: #fff;
  font-size: 11px; font-weight: 700; display: grid; place-items: center; flex-shrink: 0; }
.fold-item { margin-bottom: 8px; }
.fold-row, .more-row, .sec-row { width: 100%; display: flex; align-items: center; gap: 10px;
  background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 9px 12px;
  font-size: 13px; color: #303133; cursor: pointer; text-align: left; }
.fold-row:hover, .more-row:hover, .sec-row:hover { border-color: #c7d2fe; background: #fafbff; }
.fold-headline { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fold-when { flex-shrink: 0; font-size: 12px; color: #b45309; }
.fold-body { margin-top: 8px; }
.more-row { justify-content: center; color: #4f46e5; border-style: dashed; margin-top: 4px; }
.sections-card { margin-bottom: 14px; }
.sec-fold { margin-bottom: 6px; }
.sec-row b { flex-shrink: 0; }
.sec-q { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: #909399; font-size: 12px; }
.sec-body { margin-top: 8px; }
.others-body { margin-top: 10px; }
.other-group { margin-bottom: 12px; }
.other-title { margin: 0 0 8px; font-size: 13px; color: #303133; font-weight: 600; }
.other-title .muted { font-weight: 400; color: #909399; font-size: 12px; margin-left: 6px; }
.mini-card { margin-bottom: 8px; }
.resolved-row { display: flex; gap: 8px; align-items: center; padding: 5px 0;
  border-bottom: 1px dashed #ebeef5; font-size: 13px; color: #606266; }
.resolved-row:last-child { border-bottom: none; }
@media (max-width: 1100px) {
  .page-head, .head-actions { display: block; }
}
</style>

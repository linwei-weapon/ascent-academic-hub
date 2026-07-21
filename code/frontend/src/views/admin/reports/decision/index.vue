<template>
  <div>
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports/decision">AI管理决策</el-breadcrumb-item>
      <el-breadcrumb-item>决策简报</el-breadcrumb-item>
    </el-breadcrumb>

    <div class="page-head">
      <div>
        <h2 class="sa-page-title">AI决策简报</h2>
        <p class="sa-page-sub">首屏只有判断：全部数字由 Skill 确定性代码产出；数据未变化时复用快照，不重复制造任务。</p>
      </div>
      <div class="head-actions">
        <el-button type="success" plain @click="openChat()">决策追问</el-button>
        <el-button :loading="loading" @click="load(false)">刷新</el-button>
        <el-button type="primary" :loading="loading" @click="load(true)">重新生成</el-button>
      </div>
    </div>

    <el-alert v-if="loading && !briefing" class="loading-alert" type="info" :closable="false" show-icon
      title="正在运行决策 Skills" description="正在汇总各专题信号、比对上次快照并装配简报。" />

    <template v-if="briefing">
      <ToplineBar :briefing="briefing" />

      <section v-if="briefing.priority_items.length" class="priority-section">
        <div class="section-heading">
          <div>
            <h3>优先处置</h3>
            <p>按严重度排序的跨专题热点信号，先处理第 1 项；点击数字可下钻证据。</p>
          </div>
        </div>
        <div class="priority-grid">
          <div v-for="(sig, i) in briefing.priority_items" :key="sig.signal_id" class="priority-item">
            <span class="rank">{{ i + 1 }}</span>
            <ConclusionCard :signal="sig" @evidence="openEvidence" @track="onTrack" @ask="onCardAsk" />
          </div>
        </div>
      </section>

      <FollowupPanel v-if="briefing.previous_followup.length"
        :items="briefing.previous_followup" @track="onTrack" />

      <section class="sa-card sections-card">
        <div class="sa-card-title">
          专题信号分区
          <span class="extra">每个 Skill 独立产出信号；进入专题工作区查看专属呈现</span>
        </div>
        <el-tabs v-model="activeSkill">
          <el-tab-pane v-for="sec in briefing.skill_sections" :key="sec.skill_id"
            :label="`${sec.skill_name}（${sec.signals.length}）`" :name="sec.skill_id" lazy>
            <SkillSection :section="sec" @evidence="openEvidence" @track="onTrack" @ask="onCardAsk" />
          </el-tab-pane>
        </el-tabs>
      </section>

      <div class="two-col">
        <section class="sa-card">
          <div class="sa-card-title">观察项 <span class="extra">低严重度，暂不占用处置资源</span></div>
          <el-empty v-if="!briefing.watch_items.length" description="当前无观察项" :image-size="60" />
          <RiskCard v-for="sig in briefing.watch_items" :key="sig.signal_id" :signal="sig"
            class="mini-card" @evidence="openEvidence" @ask="onCardAsk" />
        </section>
        <section class="sa-card">
          <div class="sa-card-title">积极变化 <span class="extra">趋势向好，可在例会通报</span></div>
          <el-empty v-if="!briefing.positive_developments.length" description="当前无积极变化" :image-size="60" />
          <ConclusionCard v-for="sig in briefing.positive_developments" :key="sig.signal_id"
            :signal="sig" compact :trackable="false" class="mini-card" @evidence="openEvidence" />
        </section>
      </div>

      <section v-if="briefing.resolved_since_last.length" class="sa-card">
        <div class="sa-card-title">已消除 <span class="extra">相对上次快照不再成立的信号</span></div>
        <div v-for="item in briefing.resolved_since_last" :key="item.signal_id" class="resolved-row">
          <el-tag size="small" type="success" effect="plain">已消除</el-tag>
          <el-tag size="small" :type="SEVERITY_META[item.severity as Severity]?.tag || 'info'" effect="plain">
            {{ SEVERITY_META[item.severity as Severity]?.label || item.severity }}
          </el-tag>
          <span>{{ item.headline }}</span>
        </div>
      </section>
    </template>

    <el-skeleton v-else-if="loading" animated :rows="8" />

    <EvidenceCard v-model:visible="evidenceVisible" :signal="evidenceSignal" @ask="onAsk" />
    <ChatDrawer ref="chatDrawerRef" v-model:visible="chatVisible" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { DecisionBriefing, DecisionSignal, Severity } from '@/types/decision'
import { SEVERITY_META } from '@/types/decision'
import { getDecisionBriefing, updateDecisionTracking } from '@/utils/decision'
import ToplineBar from './components/ToplineBar.vue'
import ConclusionCard from './components/cards/ConclusionCard.vue'
import RiskCard from './components/cards/RiskCard.vue'
import EvidenceCard from './components/cards/EvidenceCard.vue'
import FollowupPanel from './components/FollowupPanel.vue'
import SkillSection from './components/SkillSection.vue'
import ChatDrawer from './components/ChatDrawer.vue'

const briefing = ref<DecisionBriefing | null>(null)
const loading = ref(false)
const activeSkill = ref('')
const evidenceVisible = ref(false)
const evidenceSignal = ref<DecisionSignal | null>(null)
const chatVisible = ref(false)
const chatDrawerRef = ref<InstanceType<typeof ChatDrawer> | null>(null)

async function load(force: boolean) {
  loading.value = true
  try {
    const data = await getDecisionBriefing(force)
    briefing.value = data
    if (!activeSkill.value || !data.skill_sections.some(s => s.skill_id === activeSkill.value)) {
      activeSkill.value = data.skill_sections[0]?.skill_id || ''
    }
  } finally {
    loading.value = false
  }
}

function openEvidence(signal: DecisionSignal) {
  evidenceSignal.value = signal
  evidenceVisible.value = true
}

/** 证据卡追问：带预置问题直接发问（打字<30% 的关键路径） */
function onAsk(question: string, signal: DecisionSignal) {
  evidenceVisible.value = false
  chatDrawerRef.value?.open({ question, signal })
}

/** 卡片追问按钮：带信号上下文打开抽屉，推荐问题 chips 免输入 */
function onCardAsk(signal: DecisionSignal) {
  chatDrawerRef.value?.open({ signal })
}

function openChat() {
  chatDrawerRef.value?.open({ signal: null })
}

async function onTrack(status: string, note: string,
                       signal: DecisionSignal | import('@/types/decision').FollowupItem) {
  await updateDecisionTracking({
    signalId: signal.signal_id,
    skillId: signal.skill_id,
    headline: signal.headline,
    entity: signal.entity,
    action: signal.action,
    status: status as 'open' | 'in_progress' | 'done' | 'dismissed',
    note,
  })
  ElMessage.success('追踪状态已更新')
  await load(false)
}

onMounted(() => load(false))
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.head-actions { display: flex; gap: 10px; padding-top: 12px; }
.loading-alert { margin: 12px 0; }
.priority-section { margin: 16px 0; }
.section-heading { margin: 4px 0 12px; }
.section-heading h3 { margin: 0; color: #0f172a; }
.section-heading p { margin: 5px 0 0; color: #64748b; font-size: 12px; }
.priority-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.priority-item { position: relative; }
.priority-item .rank { position: absolute; top: -8px; left: -8px; z-index: 1; width: 24px; height: 24px;
  border-radius: 8px; background: #0f172a; color: #fff; font-size: 12px; font-weight: 700;
  display: grid; place-items: center; }
.sections-card { margin-bottom: 14px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
.mini-card { margin-bottom: 10px; }
.resolved-row { display: flex; gap: 8px; align-items: center; padding: 6px 0;
  border-bottom: 1px dashed #ebeef5; font-size: 13px; color: #606266; }
.resolved-row:last-child { border-bottom: none; }
@media (max-width: 1100px) {
  .page-head, .head-actions { display: block; }
  .priority-grid, .two-col { grid-template-columns: 1fr; }
}
</style>

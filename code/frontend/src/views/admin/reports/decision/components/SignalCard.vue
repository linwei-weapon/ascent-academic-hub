<template>
  <article class="signal-card" :class="[`sev-${signal.severity}`, { compact }]">
    <div class="sig-head">
      <el-tag size="small" :type="severityMeta.tag" effect="dark">{{ severityMeta.label }}</el-tag>
      <el-tag size="small" :type="changeMeta.tag" effect="plain">{{ changeMeta.label }}</el-tag>
      <el-tag v-if="signal.hotspot" size="small" type="danger" effect="plain">跨专题热点</el-tag>
      <el-tag v-if="signal.tracking" size="small" :type="trackingMeta.tag" effect="plain">
        {{ trackingMeta.label }}<template v-if="signal.tracking.assignee">·{{ signal.tracking.assignee }}</template>
      </el-tag>
      <span class="sig-type">{{ signal.skill_id }}</span>
    </div>

    <h4 class="headline">{{ signal.headline }}</h4>

    <div v-if="factEntries.length" class="facts">
      <span v-for="[k, v] in factEntries" :key="k" class="fact"><em>{{ k }}</em><b>{{ v }}</b></span>
    </div>

    <div class="action-box">
      <div><span>建议责任</span><b>{{ signal.action.owner || '—' }}</b></div>
      <div><span>建议时点</span><b>{{ signal.action.when || '—' }}</b></div>
      <p>{{ signal.action.what }}</p>
      <small v-if="signal.action.rationale">{{ signal.action.rationale }}</small>
    </div>

    <p class="consequence">暂不处理：{{ signal.consequence }}</p>

    <div v-if="!compact && signal.suggested_questions?.length" class="questions">
      <span class="q-label">可追问</span>
      <el-button v-for="q in signal.suggested_questions" :key="q" link type="primary" size="small"
        @click="ask(q)">{{ q }}</el-button>
    </div>

    <div class="sig-foot">
      <span class="evidence" :title="evidenceTitle">
        {{ signal.entity.name }} · 置信{{ confidenceLabel }} · {{ signal.evidence.freshness || signal.data_boundary }}
      </span>
      <div class="ops">
        <el-button v-if="signal.evidence.verify_route" link type="primary" size="small"
          @click="goEvidence">事实证据</el-button>
        <template v-if="trackable">
          <el-button v-if="status !== 'in_progress'" link size="small" @click="track('in_progress')">处理中</el-button>
          <el-button v-if="status !== 'done'" link size="small" type="success" @click="track('done')">完成</el-button>
          <el-button v-if="status !== 'dismissed'" link size="small" @click="track('dismissed')">忽略</el-button>
        </template>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import type { DecisionSignal } from '@/types/decision'
import { SEVERITY_META, CHANGE_META, TRACKING_META } from '@/types/decision'

const props = withDefaults(defineProps<{
  signal: DecisionSignal
  compact?: boolean
  trackable?: boolean
  semester?: string
}>(), { compact: false, trackable: true, semester: '' })

const emit = defineEmits<{ track: [status: string, note: string, signal: DecisionSignal] }>()
const router = useRouter()

const severityMeta = computed(() => SEVERITY_META[props.signal.severity] || SEVERITY_META.low)
const changeMeta = computed(() => CHANGE_META[props.signal.change] || CHANGE_META.ongoing)
const status = computed(() => props.signal.tracking?.status || '')
const trackingMeta = computed(() => TRACKING_META[status.value] || { label: status.value, tag: 'info' })
const factEntries = computed(() => Object.entries(props.signal.facts || {}).slice(0, 6))
const confidenceLabel = computed(() =>
  ({ high: '高', medium: '中', limited: '有限' }[props.signal.confidence] || props.signal.confidence))
const evidenceTitle = computed(() =>
  `数据表 ${props.signal.evidence.table} · 条件 ${props.signal.evidence.condition} · ${props.signal.data_boundary}`)

function goEvidence() {
  const route = props.signal.evidence.verify_route
  if (route) router.push(route)
}

function ask(question: string) {
  router.push({ path: '/admin/reports/decision-simulation',
    query: { question, semester: props.semester } })
}

async function track(next: string) {
  let note = ''
  if (next === 'done' || next === 'dismissed') {
    try {
      const { value } = await ElMessageBox.prompt(
        next === 'done' ? '补充处置结果（可留空）' : '说明忽略原因（可留空）',
        next === 'done' ? '标记完成' : '标记忽略',
        { confirmButtonText: '确定', cancelButtonText: '取消', inputPlaceholder: '选填' })
      note = value || ''
    } catch { return }
  }
  emit('track', next, note, props.signal)
}
</script>

<style scoped>
.signal-card { background: #fff; border: 1px solid #e4e7ed; border-left: 4px solid #909399;
  border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.signal-card.sev-critical { border-left-color: #c45656; }
.signal-card.sev-high { border-left-color: #e6a23c; }
.signal-card.sev-medium { border-left-color: #b88230; }
.sig-head { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.sig-type { margin-left: auto; color: #c0c4cc; font-size: 11px; }
.headline { margin: 0; font-size: 15px; line-height: 1.55; color: #303133; }
.facts { display: flex; flex-wrap: wrap; gap: 8px; }
.fact { background: #f5f7fa; border-radius: 6px; padding: 4px 10px; font-size: 12px; }
.fact em { font-style: normal; color: #909399; margin-right: 6px; }
.fact b { color: #303133; }
.action-box { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px;
  background: #eef2ff; border-radius: 8px; padding: 10px 12px; }
.action-box span { display: block; color: #94a3b8; font-size: 11px; }
.action-box b { font-size: 12px; color: #3730a3; }
.action-box p, .action-box small { grid-column: 1 / -1; margin: 2px 0 0; font-size: 12px;
  color: #334155; line-height: 1.6; }
.action-box small { color: #64748b; }
.consequence { margin: 0; font-size: 12px; color: #9f1239; line-height: 1.6; }
.questions { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; }
.q-label { color: #909399; font-size: 11px; }
.sig-foot { display: flex; justify-content: space-between; gap: 10px; align-items: center;
  border-top: 1px dashed #ebeef5; padding-top: 8px; }
.evidence { color: #909399; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops { flex-shrink: 0; display: flex; gap: 2px; }
.compact .action-box { display: none; }
.compact .consequence { display: none; }
</style>

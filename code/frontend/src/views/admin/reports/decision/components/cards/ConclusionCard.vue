<template>
  <!-- 结论卡：一个完整的管理判断。五要素顺序固定：判断→依据→动作→时限→代价 -->
  <article class="conclusion-card" :class="[`sev-${signal.severity}`, { compact }]">
    <div class="sig-head">
      <el-tag size="small" :type="severityMeta(signal).tag" effect="dark">{{ severityMeta(signal).label }}</el-tag>
      <el-tag size="small" :type="changeMeta(signal).tag" effect="plain">{{ changeMeta(signal).label }}</el-tag>
      <el-tag v-if="signal.hotspot" size="small" type="danger" effect="plain">跨专题热点</el-tag>
      <el-tag v-if="signal.tracking" size="small" :type="trackingMeta(signal).tag" effect="plain">
        {{ trackingMeta(signal).label }}<template v-if="signal.tracking.assignee">·{{ signal.tracking.assignee }}</template>
      </el-tag>
    </div>

    <!-- ① 判断 -->
    <h4 class="headline">{{ signal.headline }}</h4>

    <!-- ② 依据（可点击下钻证据卡） -->
    <div class="facts">
      <button v-for="[k, v] in factEntries(signal)" :key="k" class="fact" type="button"
        title="点击查看证据" @click="emit('evidence', signal)">
        <em>{{ k }}</em><b>{{ v }}</b>
      </button>
    </div>

    <!-- ③ 动作 + ④ 时限 -->
    <div v-if="!compact" class="action-box">
      <div><span>建议责任</span><b>{{ signal.action.owner || '—' }}</b></div>
      <div><span>时限</span><b class="when">{{ signal.action.when || '—' }}</b></div>
      <p>{{ signal.action.what }}</p>
      <small v-if="signal.action.rationale">{{ signal.action.rationale }}</small>
    </div>
    <div v-else class="compact-when">时限：{{ signal.action.when || '—' }}</div>

    <!-- ⑤ 代价 -->
    <p class="consequence">暂不处理：{{ signal.consequence }}</p>

    <div class="sig-foot">
      <span class="evidence" :title="evidenceTitle(signal)">
        {{ signal.entity.name }} · 置信{{ confidenceLabel(signal) }} · {{ signal.evidence.freshness || signal.data_boundary }}
      </span>
      <div class="ops">
        <el-button link type="primary" size="small" @click="emit('evidence', signal)">证据</el-button>
        <el-button v-if="signal.suggested_questions?.length" link size="small"
          @click="emit('ask', signal)">追问</el-button>
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
import { ElMessageBox } from 'element-plus'
import type { DecisionSignal } from '@/types/decision'
import {
  severityMeta, changeMeta, trackingMeta, confidenceLabel, factEntries, evidenceTitle,
} from './signalMeta'

const props = withDefaults(defineProps<{
  signal: DecisionSignal
  compact?: boolean
  trackable?: boolean
}>(), { compact: false, trackable: true })

const emit = defineEmits<{
  evidence: [signal: DecisionSignal]
  track: [status: string, note: string, signal: DecisionSignal]
  ask: [signal: DecisionSignal]
}>()

const status = computed(() => props.signal.tracking?.status || '')

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
.conclusion-card { background: #fff; border: 1px solid #e4e7ed; border-left: 4px solid #909399;
  border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.conclusion-card.sev-critical { border-left-color: #c45656; }
.conclusion-card.sev-high { border-left-color: #e6a23c; }
.conclusion-card.sev-medium { border-left-color: #b88230; }
.sig-head { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.headline { margin: 0; font-size: 15px; line-height: 1.55; color: #303133; }
.facts { display: flex; flex-wrap: wrap; gap: 8px; }
.fact { background: #f5f7fa; border: 1px solid transparent; border-radius: 6px; padding: 4px 10px;
  font-size: 12px; cursor: pointer; transition: border-color .15s; }
.fact:hover { border-color: #4f46e5; }
.fact em { font-style: normal; color: #909399; margin-right: 6px; }
.fact b { color: #4f46e5; }
.action-box { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px;
  background: #eef2ff; border-radius: 8px; padding: 10px 12px; }
.action-box span { display: block; color: #94a3b8; font-size: 11px; }
.action-box b { font-size: 12px; color: #3730a3; }
.action-box b.when { color: #b45309; }
.action-box p, .action-box small { grid-column: 1 / -1; margin: 2px 0 0; font-size: 12px;
  color: #334155; line-height: 1.6; }
.action-box small { color: #64748b; }
.compact-when { font-size: 12px; color: #b45309; }
.consequence { margin: 0; font-size: 12px; color: #9f1239; line-height: 1.6; }
.sig-foot { display: flex; justify-content: space-between; gap: 10px; align-items: center;
  border-top: 1px dashed #ebeef5; padding-top: 8px; }
.evidence { color: #909399; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops { flex-shrink: 0; display: flex; gap: 2px; }
.compact .consequence { display: none; }
</style>

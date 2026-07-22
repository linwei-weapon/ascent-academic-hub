<template>
  <!-- 结论卡：一个完整的管理判断。五要素顺序固定：判断→依据→动作→时限→代价。
       动作三件套：问专家 / 查证·新标签 / 核查清单（就地展开、可复制，不产生任何工单）。 -->
  <article class="conclusion-card" :class="[`sev-${signal.severity}`, { compact }]">
    <div class="sig-head">
      <el-tag size="small" :type="severityMeta(signal).tag" effect="dark">{{ severityMeta(signal).label }}</el-tag>
      <el-tag size="small" :type="changeMeta(signal).tag" effect="plain">{{ changeMeta(signal).label }}</el-tag>
      <el-tag v-if="signal.hotspot" size="small" type="danger" effect="plain">跨专题热点</el-tag>
    </div>

    <!-- ① 判断 -->
    <h4 class="headline">{{ signal.headline }}</h4>

    <!-- ② 依据（关键数字） -->
    <div class="facts">
      <span v-for="[k, v] in factEntries(signal)" :key="k" class="fact">
        <em>{{ k }}</em><b>{{ v }}</b>
      </span>
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

    <!-- 核查清单：就地展开，可复制 -->
    <div v-if="checklistOpen" class="checklist">
      <div class="checklist-head">
        <b>人工核查清单</b>
        <el-button link type="primary" size="small" @click="copyChecklist">
          {{ copied ? '已复制' : '复制' }}
        </el-button>
      </div>
      <p v-for="(item, i) in checklistItems" :key="i" class="check-item">□ {{ item }}</p>
      <p class="check-note">本平台只输出建议与核查依据，不创建工单；处置请走学校既有流程。</p>
    </div>

    <div class="sig-foot">
      <span class="evidence" :title="evidenceTitle(signal)">
        {{ signal.entity.name }} · 置信{{ confidenceLabel(signal) }} · {{ signal.evidence.freshness || signal.data_boundary }}
      </span>
      <div class="ops">
        <el-button link type="primary" size="small"
          @click="emit('ask', signal)">问专家</el-button>
        <el-button link type="primary" size="small" @click="openVerify">查证·新标签</el-button>
        <el-button link size="small" @click="checklistOpen = !checklistOpen">
          {{ checklistOpen ? '收起清单' : '核查清单' }}
        </el-button>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DecisionSignal } from '@/types/decision'
import { openEvidenceWindow } from '@/utils/decision'
import {
  severityMeta, changeMeta, confidenceLabel, factEntries, evidenceTitle,
} from './signalMeta'

const props = withDefaults(defineProps<{
  signal: DecisionSignal
  compact?: boolean
}>(), { compact: false })

const emit = defineEmits<{
  ask: [signal: DecisionSignal]
}>()

/** 查证·新标签（R2）：只读证据页在新浏览器标签页打开，主窗口状态不动。 */
function openVerify() {
  openEvidenceWindow(props.signal.signal_id)
}

/** 核查清单（R3）：由信号五要素确定性拼装，AI 输出的终点是清单，不是工单。 */
const checklistOpen = ref(false)
const copied = ref(false)
const checklistItems = computed(() => {
  const s = props.signal
  const items = [
    `核对数据：在「${s.evidence.table}」中按条件「${s.evidence.condition || '见查证窗口'}」复核 ${s.entity.name} 的关键数字`,
    `责任确认：与${s.action.owner || '责任方'}确认——${s.action.what}（建议时限：${s.action.when || '尽快'}）`,
  ]
  if (s.related?.length) items.push(`关联信号：本信号与 ${s.related.length} 项其他专题信号关联，建议一并核查`)
  items.push('证据复核：通过「查证·新标签」核对数据时效、口径边界与排除项后再定性')
  return items
})

async function copyChecklist() {
  const s = props.signal
  const text = [
    `【核查清单】${s.headline}`,
    `建议责任：${s.action.owner || '—'}；建议时限：${s.action.when || '—'}`,
    ...checklistItems.value.map((t, i) => `${i + 1}. ${t}`),
    '（本平台不形成办理闭环，请在学校既有流程中处置）',
  ].join('\n')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch { /* 剪贴板不可用时静默 */ }
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
.fact { background: #f5f7fa; border-radius: 6px; padding: 4px 10px; font-size: 12px; }
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
.checklist { background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 10px 12px; }
.checklist-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.checklist-head b { font-size: 12px; color: #334155; }
.check-item { margin: 4px 0; font-size: 12px; color: #475569; line-height: 1.6; }
.check-note { margin: 8px 0 0; font-size: 11px; color: #94a3b8; }
.sig-foot { display: flex; justify-content: space-between; gap: 10px; align-items: center;
  border-top: 1px dashed #ebeef5; padding-top: 8px; }
.evidence { color: #909399; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops { flex-shrink: 0; display: flex; gap: 2px; }
.compact .consequence { display: none; }
</style>

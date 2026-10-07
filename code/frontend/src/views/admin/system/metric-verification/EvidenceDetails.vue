<template>
  <div class="evidence-details">
    <div class="evidence-status">
      <el-tag size="small" :type="evidence.status === 'success' ? 'success' : 'danger'">{{ evidence.status === 'success' ? '查询成功' : '查询失败' }}</el-tag>
      <el-tag size="small" :type="evidence.current ? 'info' : 'warning'">{{ evidence.current ? '对应当前定义' : '定义已变化 · 证据已过期' }}</el-tag>
    </div>
    <el-alert v-if="isFactReference" class="reference-notice" title="从事实层复算的参考值" description="该证据来自事实层参考计算，不是应用层已保存结果，也不能代表应用页面实际值。" type="warning" :closable="false" show-icon />
    <p v-if="!evidence.current" class="expired-note">此证据保留当时的查询依据，可用于查看历史记录，不能作为本次“符合”的依据。</p>
    <dl>
      <dt>指标</dt><dd>{{ metricName }} <small>{{ evidence.metricId }}</small></dd>
      <dt>查询内容</dt><dd>{{ layerName }} · {{ kindName }}</dd>
      <template v-if="evidence.directSource"><dt>直接来源</dt><dd>{{ evidence.directSource }}</dd></template>
      <template v-if="evidence.metricResultReason"><dt>结果边界</dt><dd>{{ evidence.metricResultReason }}</dd></template>
      <dt>执行时间</dt><dd>{{ executedTime }} · {{ evidence.durationMs }} ms</dd>
      <dt>范围内记录数</dt><dd>{{ evidence.status === 'success' ? countText(evidence.recordCount) : '执行失败，未取得有效记录数' }}</dd>
      <dt>返回行数</dt><dd>{{ evidence.returnedRows }}{{ evidence.truncated ? '（达到展示上限）' : '' }}</dd>
      <dt>SQL 版本</dt><dd>{{ evidence.sqlVersion }}</dd>
      <dt>查询参数</dt><dd><dl v-if="Object.keys(evidence.parameters).length" class="parameter-values"><template v-for="(value, name) in evidence.parameters" :key="name"><dt>{{ name }}</dt><dd>{{ displayValue(value) }}</dd></template></dl><span v-else>无额外参数</span></dd>
      <template v-if="Object.keys(evidence.metrics).length"><dt>{{ isFactReference ? '参考计算结果' : '计算结果' }}</dt><dd><dl class="parameter-values"><template v-for="(value, name) in evidence.metrics" :key="name"><dt :title="String(name)">{{ resultFieldLabel(String(name)) }}</dt><dd>{{ displayValue(value) }}</dd></template></dl></dd></template>
      <template v-if="evidence.message"><dt>执行说明</dt><dd>{{ evidence.message }}</dd></template>
    </dl>
    <p v-if="!evidence.retainedEvidence" class="privacy-note">此执行只保存查询摘要与参数，没有可重算的原始输入。</p>
    <details v-else @toggle="openEvidence = ($event.target as HTMLDetailsElement).open"><summary>查看当次留存输入、独立核算与被测结果</summary><EvidenceReview :module-id="moduleId" v-if="openEvidence" :execution-id="evidence.id" :query-id="evidence.queryId" /></details>
    <details class="evidence-identifiers"><summary>证据标识</summary><dl><dt>证据编号</dt><dd>{{ evidence.id }}</dd><dt>查询编号</dt><dd>{{ evidence.queryId }}</dd><template v-if="evidence.queryChecksum"><dt>定义校验标识</dt><dd>{{ evidence.queryChecksum }}</dd></template></dl></details>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import EvidenceReview from './EvidenceReview.vue'
import type { VerificationModuleId, StoredVerificationEvidence } from '@/types/metricVerification'
import { resultFieldLabel } from './labels'
const props = defineProps<{ moduleId?: VerificationModuleId; evidence: StoredVerificationEvidence; metricName: string }>()
const openEvidence = ref(false)
const isFactReference = computed(() => props.evidence.mappingMode === 'reference_from_fact')
const layerName = computed(() => isFactReference.value ? '事实层复算参考' : { source: '贴源层', fact: '事实层', application: '应用层' }[props.evidence.layer])
const kindName = computed(() => ({ count: '记录数', detail: '数据明细', calculate: '指标复算' }[props.evidence.queryKind]))
const executedTime = computed(() => {
  const date = new Date(props.evidence.executedAt)
  return Number.isNaN(date.getTime()) ? props.evidence.executedAt : date.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' })
})
function countText(value: number | null) { return value === null || value === undefined ? '未取得' : value.toLocaleString('zh-CN') }
function displayValue(value: unknown): string { return value === null || value === undefined ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value) }
</script>

<style scoped>
.evidence-details { margin-top: 10px; padding: 12px; background: var(--el-fill-color-light); border-radius: 4px; font-size: 12px; min-width: 0; }
.evidence-status { display: flex; gap: 8px; flex-wrap: wrap; }
.reference-notice { margin-top: 12px; }
dl { display: grid; grid-template-columns: 108px minmax(0, 1fr); gap: 8px 12px; margin: 12px 0; }
dt { color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
dd { margin: 0; min-width: 0; overflow-wrap: anywhere; line-height: 1.6; }
dd small { display: block; color: var(--el-text-color-secondary); }
.parameter-values { grid-template-columns: minmax(90px, 1fr) minmax(0, 1fr); margin: 0; }
.expired-note { color: var(--el-color-warning-dark-2); line-height: 1.6; }
.privacy-note { color: var(--el-text-color-secondary); line-height: 1.6; }
.evidence-identifiers summary { cursor: pointer; color: var(--el-color-primary); }
@media (max-width: 700px) { dl { grid-template-columns: 92px minmax(0, 1fr); } .parameter-values { grid-template-columns: minmax(0, 1fr); gap: 3px; } .parameter-values dd { margin-bottom: 6px; } }
</style>

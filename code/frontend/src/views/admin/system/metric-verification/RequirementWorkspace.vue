<template>
  <section class="indicator-workspace" :aria-label="`${entry.name}核验内容`">
    <header class="workspace-heading"><div><el-button link type="primary" @click="emit('collapse')">← 返回指标清单</el-button><p class="muted">{{ pageName }} · {{ entry.group }}</p><h3 id="indicator-detail-heading" tabindex="-1">{{ entry.name }}</h3></div><el-tag :type="entry.status === 'pending' ? 'warning' : 'info'">{{ definitionStatus(entry.status) }}</el-tag></header>
    <div class="business-definition sa-card">
      <p v-if="entry.meaning !== entry.formula" class="meaning">{{ entry.meaning }}</p><dl><dt>计算口径</dt><dd>{{ entry.formula || '计算口径待明确' }}</dd><dt>组成值</dt><dd>{{ entry.components.join('、') || '以本指标结果为核对对象' }}</dd></dl>
      <p class="muted">{{ moduleId === 'ai-briefing' ? 'AI简报需求出处' : '106需求出处' }}：{{ entry.sourceSections.join('、') }} · {{ metric.unit || '单位见具体结果' }}</p>
      <details v-if="entry.pendingIssues.length || entry.status === 'pending'" class="condition-details"><summary>查看待确认口径{{ entry.pendingIssues.length ? `（${entry.pendingIssues.length}项）` : '' }}</summary><ul><li v-for="issue in entry.pendingIssues" :key="issue">{{ issue }}</li></ul><p v-if="!entry.pendingIssues.length">请先确认影响本次结果的计算条件，条件未齐时记录“条件不足”。</p></details>
      <details v-if="layerGapDetails.length" class="condition-details"><summary>其他数据条件（{{ layerGapDetails.length }}项，含完整阻断说明）</summary><ul><li v-for="gap in layerGapDetails" :key="gap">{{ gap }}</li></ul></details>
      <details class="source-details"><summary>查看需求原文、指标定义与验收依据</summary><p>{{ requirement.description }}</p><ol><li v-for="item in requirement.acceptanceCriteria" :key="item">{{ item }}</li></ol><p class="muted">{{ sourceDocument || (moduleId === 'ai-briefing' ? 'AI简报首修需求说明' : '106需求说明') }} · 第 {{ requirement.source.startLine }}–{{ requirement.source.endLine }} 行</p><p>{{ metric.definition }}</p><dl><dt>统计粒度</dt><dd>{{ metric.grain }}</dd><dt>空值规则</dt><dd>{{ metric.nullPolicy }}</dd><dt>范围</dt><dd>{{ metric.scope.join('；') }}</dd></dl><ul v-if="metric.issues.length"><li v-for="issue in metric.issues" :key="issue">{{ issue }}</li></ul><p class="muted">指标标识：{{ entry.metricId }} · 场景：{{ entry.id }}</p></details>
      <MappingContext :module-id="moduleId" v-if="effectiveMapping && mappingRevisionId" :mapping="effectiveMapping" :metric-id="entry.metricId" :mapping-revision-id="mappingRevisionId" />
    </div>
    <el-tabs v-model="activeTab" class="workspace-tabs">
      <el-tab-pane label="三层关系、SQL 与记录数" name="queries">
        <label v-if="queryMetrics.length > 1" class="evidence-object"><span>本指标的数据依据</span><el-select v-model="queryMetricId" aria-label="本指标的数据依据"><el-option v-for="item in queryMetrics" :key="item.id" :value="item.id" :label="item.id === entry.metricId ? `${entry.name}（主结果）` : item.name" /></el-select></label>
        <MetricQueryPanel :module-id="moduleId" v-if="queryMetric" :key="`${entry.id}:${queryMetric.id}`" :metric="queryMetric" :requirement-id="entry.requirementId" :scenario-id="entry.id" :capabilities="capabilities" :compact="true" :initial-parameters="queryParameters" :reset-revision="queryResetRevision" :mapping-revision-id="mappingRevisionId" :mapping="effectiveMapping" @evidence="rememberEvidence" @parameters="changeQueryParameters" @gaps="layerGaps = $event" @source-manifest="rememberSources" />
      </el-tab-pane>
      <el-tab-pane :label="`真实结果对照与记录${recordCount === null ? '' : `（${recordCount}）`}`" name="records" lazy>
        <VerificationRecords :module-id="moduleId" :requirement-id="entry.requirementId" :entry="entry" :metrics="queryMetrics" :capabilities="capabilities" :evidence="executions" :context-revision="contextRevision" :query-parameters="queryParameters" :mapping-revision-id="mappingRevisionId" @count="recordCount = $event" @saved="emit('saved', $event)" @conditions-change="invalidateQueries" />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { VerificationModuleId, VerificationCapabilities, VerificationExecution, VerificationIndicatorEntry, VerificationMetric, VerificationRecord, VerificationRequirement, MappingPackage, MappingSource } from '@/types/metricVerification'
import MetricQueryPanel from './MetricQueryPanel.vue'
import VerificationRecords from './VerificationRecords.vue'
import MappingContext from './MappingContext.vue'
import { definitionStatus } from './labels'
const props = defineProps<{ moduleId?: VerificationModuleId; entry: VerificationIndicatorEntry; metric: VerificationMetric; metrics: VerificationMetric[]; requirement: VerificationRequirement; capabilities: VerificationCapabilities; sourceDocument?: string; pageName: string; mappingRevisionId?: string; mapping?: MappingPackage }>()
const emit = defineEmits<{ collapse: []; saved: [record: VerificationRecord] }>()
const activeTab = ref('queries')
const queryMetricId = ref(props.entry.metricId)
const queryMetrics = computed(() => [...new Set([props.entry.metricId, ...(props.entry.evidenceMetricIds || [])])].flatMap(id => { const metric = props.metrics.find(item => item.id === id); return metric ? [metric] : [] }))
const queryMetric = computed(() => queryMetrics.value.find(item => item.id === queryMetricId.value))
const executions = ref<VerificationExecution[]>([])
const recordCount = ref<number | null>(null)
const contextRevision = ref(0)
const queryResetRevision = ref(0)
const queryParameters = ref<Record<string, string>>({})
const layerGaps = ref<string[]>([])
const layerGapDetails = computed(() => {
  const details = new Map<string, string>()
  // 仅整理重复的展示段落，原始条件仍由查询接口和业务校验使用。
  for (const gap of layerGaps.value) {
    for (const paragraph of gap.split(/[；\r\n]+/u)) {
      const text = paragraph.trim()
      const key = text.replace(/\s+/gu, ' ').replace(/[。；;]+$/u, '').trim()
      if (key && !details.has(key)) details.set(key, text)
    }
  }
  return [...details.values()]
})
const querySources = ref<MappingSource[]>([])
const effectiveMapping = computed(() => props.mapping ? { ...props.mapping, sourceManifest: mergeSources(props.mapping.sourceManifest || [], querySources.value) } : undefined)
function mergeSources(existing: MappingSource[], incoming: MappingSource[]) {
  const sources = new Map(existing.map(source => [source.id, source]))
  for (const source of incoming) {
    const previous = sources.get(source.id)
    const evidence = new Map([...(previous?.evidence || []), ...(source.evidence || [])].map(item => [item.id, item]))
    sources.set(source.id, { ...previous, ...source, evidence: [...evidence.values()] })
  }
  return [...sources.values()]
}
function rememberSources(sources: MappingSource[]) { querySources.value = mergeSources(querySources.value, sources) }
function rememberEvidence(result: VerificationExecution) {
  if (result.status === 'success' && result.evidenceSaved === true && result.id && result.scenarioId === props.entry.id) executions.value = [result, ...executions.value.filter(item => item.id !== result.id)]
}
function changeQueryParameters(parameters: Record<string, string>) { queryParameters.value = parameters; executions.value = []; contextRevision.value++ }
function invalidateQueries() { executions.value = []; queryResetRevision.value++ }
</script>

<style scoped>
.indicator-workspace { min-width:0; }
.workspace-heading { display:flex; justify-content:space-between; align-items:start; gap:12px; margin-bottom:14px; }
.workspace-heading h3 { margin:0; font-size:20px; scroll-margin-top:85px; } .workspace-heading p { margin:8px 0; }
.business-definition { padding:18px; } .meaning { line-height:1.7; margin:0 0 12px; font-size:14px; }
.muted { color:var(--el-text-color-secondary); font-size:12px; }
dl { display:grid; grid-template-columns:75px minmax(0,1fr); gap:8px 12px; margin:12px 0; font-size:13px; line-height:1.7; } dt { color:var(--el-text-color-secondary); } dd { margin:0; overflow-wrap:anywhere; }
.source-details { margin-top:12px; font-size:13px; line-height:1.7; } summary { cursor:pointer; color:var(--el-color-primary); } li { margin:5px 0; } .gap-notice { margin-top:10px; }
.condition-details { font-size:13px; line-height:1.7; margin-top:10px; }.condition-details summary { color:var(--el-color-warning-dark-2); }
.workspace-tabs { margin-top:16px; } .workspace-tabs :deep(.el-tabs__item) { font-size:14px; }
.evidence-object { display:flex; align-items:center; gap:12px; max-width:600px; margin:0 0 14px; font-size:13px; }.evidence-object .el-select { flex:1; min-width:0; }
@media(max-width:640px) { .business-definition { padding:14px; } .workspace-heading h3 { font-size:18px; } .evidence-object { flex-direction:column; align-items:stretch; } .workspace-tabs :deep(.el-tabs__item) { padding:0 12px; font-size:13px; } }
</style>

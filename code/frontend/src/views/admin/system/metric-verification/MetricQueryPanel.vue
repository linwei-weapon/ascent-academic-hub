<template>
  <div class="metric-query-panel">
    <details v-if="!compact" class="metric-definition" open>
      <summary>指标定义、加工步骤与原有分析说明</summary>
      <div><strong :title="metric.id">{{ metric.name }}</strong><el-tag size="small" effect="plain">{{ metricTypeLabel(metric.type) }}</el-tag></div>
      <p>{{ metric.definition }}</p>
      <p v-if="metric.managementUse"><strong>管理用途：</strong>{{ metric.managementUse }}</p>
      <dl><dt>计算公式</dt><dd>{{ metric.formula || '待确认' }}</dd><dt>统计粒度</dt><dd>{{ metric.grain }} · {{ metric.unit || '单位待确认' }}</dd></dl>
      <details><summary>分子分母、范围与空值规则</summary><dl>
        <template v-if="metric.numerator"><dt>分子</dt><dd>{{ metric.numerator }}</dd></template>
        <template v-if="metric.denominator"><dt>分母</dt><dd>{{ metric.denominator }}</dd></template>
        <dt>统计范围</dt><dd>{{ metric.scope.join('；') || '待确认' }}</dd>
        <dt>空值规则</dt><dd>{{ metric.nullPolicy || '待确认' }}</dd>
        <dt>需求依据</dt><dd>{{ metric.sourceSections.join('、') }}</dd>
      </dl></details>
      <details v-if="metric.calculationVariants?.length"><summary>不同页面场景的计算口径</summary>
        <section v-for="variant in metric.calculationVariants" :key="variant.id" class="calculation-variant">
          <strong>{{ variant.name }}</strong><dl><dt>公式与单位</dt><dd>{{ variant.formula }} · {{ variant.unit }}</dd><dt>需求章节</dt><dd>{{ variant.sourceSections.join('、') }}</dd><dt>适用边界</dt><dd>{{ variant.boundary }}</dd></dl>
        </section>
      </details>
      <details v-if="metric.mappingNote"><summary>数据库核对依据</summary><p>{{ metric.mappingNote }}</p></details>
      <details v-if="metric.calculationSteps?.length || metric.boundaryChecks?.length || metric.pageVerification"><summary>加工步骤与页面核对方法</summary>
        <ol v-if="metric.calculationSteps?.length"><li v-for="step in metric.calculationSteps" :key="step">{{ step }}</li></ol>
        <template v-if="metric.pageVerification">
          <p><strong>核对页面：</strong>{{ metric.pageVerification.path }}</p><p><strong>预期结果：</strong>{{ metric.pageVerification.expectedResult }}</p>
          <ol><li v-for="step in metric.pageVerification.steps" :key="step">{{ step }}</li></ol>
          <p>{{ metric.pageVerification.specificCheck }}</p>
        </template>
        <ul v-if="metric.boundaryChecks?.length"><li v-for="boundary in metric.boundaryChecks" :key="boundary">{{ boundary }}</li></ul>
      </details>
      <el-alert v-if="metric.issues.length" :title="metric.issues.join('；')" type="warning" :closable="false" show-icon />
    </details>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon><template #default><el-button size="small" @click="loadQueries">重试读取 SQL</el-button></template></el-alert>
    <div v-loading="loading" class="data-chain" aria-label="三层数据关系">
      <template v-for="(layer, index) in layers" :key="layer.id">
        <span v-if="index" class="chain-arrow" aria-hidden="true">→</span>
        <button type="button" class="layer-card" :class="{ selected: selectedLayerId === layer.id }"
          :aria-pressed="selectedLayerId === layer.id" :disabled="executing" @click="selectLayer(layer.id)">
          <span class="layer-title">{{ layer.name }}</span>
          <span v-if="layer.remainingGaps?.length" class="layer-gap">{{ layer.id === 'application' ? '应用结果对应关系待核对' : '数据条件需核对' }}</span>
          <span v-if="isFactReference(layer)" class="reference-badge">从事实层复算的参考值</span>
          <span v-else-if="layer.mappingMode === 'no_independent_source'" class="layer-grain">无独立源端结果对象</span>
          <span class="layer-tables">{{ layer.tables.join(' · ') || layer.directSource || (layer.mappingMode === 'no_independent_source' ? '请查看直接来源说明' : '数据表待配置') }}</span>
          <span class="layer-grain">{{ layer.grain || '粒度待确认' }}</span>
          <span class="layer-count">{{ isFactReference(layer) ? '参考查询记录数' : '记录数' }}：<strong>{{ layerCountText(layer) }}</strong></span>
        </button>
      </template>
    </div>
    <section v-if="selectedLayer" class="layer-detail">
      <div class="layer-heading"><h4 :title="metric.id">{{ selectedLayer.name }} · {{ metric.name }}</h4><span class="muted">{{ statusLabel(selectedLayer.status) }}</span><el-button v-if="selectedQuery" link type="primary" @click="sqlInput?.focus()">查看 SQL 与执行查询 ↓</el-button></div>
      <LayerMappingDetails v-if="mappingMetric" :metric="mappingMetric" :layer="selectedLayer" :query="selectedQuery" :sources="mapping?.sourceManifest || []" />
      <template v-else>
      <p v-if="isFactReference(selectedLayer)" class="reference-badge">本层是从事实层复算的参考值；应用实际结果需另行核对。</p>
      <p v-if="selectedLayer.mappingMode === 'no_independent_source'" class="muted">{{ selectedLayer.applicabilityReason || selectedLayer.directSource || '本层无独立源端结果，请核对直接来源。' }}</p>
      <dl v-if="selectedLayer.directSource || selectedLayer.closureReason || selectedLayer.applicabilityReason">
        <template v-if="selectedLayer.directSource"><dt>直接来源</dt><dd>{{ selectedLayer.directSource }}</dd></template>
        <template v-if="selectedLayer.applicabilityReason"><dt>适用说明</dt><dd>{{ selectedLayer.applicabilityReason }}</dd></template>
        <template v-if="selectedLayer.closureReason"><dt>映射说明</dt><dd>{{ selectedLayer.closureReason }}</dd></template>
      </dl>
      <div v-if="selectedLayer.transform.length" class="transform"><strong>数据关系与加工逻辑</strong><ol><li v-for="item in selectedLayer.transform" :key="item">{{ item }}</li></ol></div>
      </template>
      <details v-if="selectedLayerIssues.length"><summary>适用边界与待解决问题（{{ selectedLayerIssues.length }}项）</summary><ul><li v-for="issue in selectedLayerIssues" :key="issue">{{ issue }}</li></ul></details>
      <div class="query-kinds"><el-radio-group :model-value="selectedQueryKind" :disabled="executing" aria-label="查询类型" @change="changeQueryKind">
        <el-radio-button v-for="kind in queryKinds" :key="kind.id" :value="kind.id" :disabled="!selectedLayer.queries.some(item => item.kind === kind.id)">{{ kind.label }}</el-radio-button>
      </el-radio-group><span v-if="selectedQuery" class="muted">{{ selectedQuery.dialect }} · SQL {{ selectedQuery.version }}</span></div>
      <label v-if="queriesForKind.length > 1" class="query-choice"><span>查询方案</span><el-select v-model="selectedQueryId" :disabled="executing" aria-label="查询方案"><el-option v-for="query in queriesForKind" :key="query.id" :label="query.title || query.id" :value="query.id" /></el-select></label>
      <template v-if="selectedQuery">
        <p v-if="selectedQuery.title" class="muted"><strong>{{ selectedQuery.title }}</strong><br v-if="selectedQuery.scenarioPurpose" />{{ selectedQuery.scenarioPurpose }}</p>
        <section class="sql-details" aria-label="SQL 语句预览">
        <div class="sql-heading"><label :for="sqlElementId">{{ queryKindName(selectedQuery.kind) }} SQL</label><div class="sql-actions"><el-button size="small" :aria-expanded="sqlExpanded" :aria-controls="sqlElementId" @click="sqlExpanded = !sqlExpanded">{{ sqlExpanded ? '收起预览' : '展开 SQL' }}</el-button><el-button size="small" @click="copySql">复制完整 SQL</el-button></div></div>
        <textarea :id="sqlElementId" ref="sqlInput" class="sql-source" :class="{ expanded: sqlExpanded }" :value="selectedQuery.sql" :rows="sqlExpanded ? 22 : 7" readonly spellcheck="false" />
        </section>
        <form class="query-form" @submit.prevent="runQuery">
          <div class="parameter-heading"><h4>本次查询范围</h4><el-button v-if="selectedQuery.parameters.some(parameter => parameter.name !== 'student_id')" size="small" :loading="optionsLoading" :disabled="executing" @click="loadParameterOptions">读取可选值</el-button></div>
          <p v-if="selectedQuery.parameters.length" class="muted">可从数据库读取学期、批次等候选值，也可手工输入；请自行确认本次统计时点和业务口径。</p>
          <el-alert v-if="optionsError" :title="optionsError" type="warning" :closable="false" show-icon />
          <div v-if="selectedQuery.parameters.length" class="parameters">
            <label v-for="parameter in selectedQuery.parameters" :key="parameter.name">
              <span>{{ parameter.label || parameter.name }}<span v-if="parameter.required" class="required"> *</span></span>
              <el-select v-if="parameter.name !== 'student_id' && parameterOptions[parameter.name]?.items.length" v-model="parameterValues[parameter.name]" filterable allow-create clearable :aria-label="parameter.label || parameter.name" :placeholder="`选择或输入${parameter.label || parameter.name}`" :disabled="executing">
                <el-option v-for="option in parameterOptions[parameter.name].items" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
              <el-input v-else v-model="parameterValues[parameter.name]" :aria-label="parameter.label || parameter.name"
                :inputmode="parameter.type === 'integer' ? 'numeric' : parameter.type === 'number' ? 'decimal' : 'text'"
                :placeholder="parameter.name" :disabled="executing" />
              <small>{{ parameter.source ? parameterSourceLabel(parameter.source) : `${parameter.name} · ${parameter.type === 'integer' ? '整数' : parameter.type === 'number' ? '数值' : '文本'}` }}</small>
              <small v-if="parameter.name === 'student_id'">学生编号需按已授权核验对象手工填写。</small>
              <small v-else-if="parameterOptions[parameter.name]?.error" class="parameter-warning">{{ parameterOptions[parameter.name].error }}；可手工输入。</small>
              <small v-else-if="parameterOptions[parameter.name]">{{ parameterOptions[parameter.name].items.length ? `已读取 ${parameterOptions[parameter.name].items.length} 项可选值` : '未读取到可选值，可手工输入' }}{{ parameterOptions[parameter.name].truncated ? '；仅展示部分候选值，未列出的值可手工输入' : '' }}</small>
            </label>
          </div>
          <p v-else class="muted">此 SQL 无需额外参数，将按服务端登记的范围与权限查询。</p>
          <div v-if="parameterError" class="inline-error" role="alert">{{ parameterError }}</div>
          <section v-if="validationCases.length" class="validation-mode"><el-checkbox v-model="independentMode" :disabled="executing">独立核算此 SQL：留存本次输入，先核算后查看结果</el-checkbox><template v-if="independentMode"><label v-if="validationCases.length > 1" class="query-choice"><span>核算范围方案</span><el-select v-model="validationCaseId" :disabled="executing" aria-label="独立核算方案"><el-option v-for="item in validationCases" :key="item.id" :label="item.title" :value="item.id" /></el-select></label><p class="muted">{{ validationCase?.samplePlan?.requirement || '按本次参数留存完整输入与被测结果，完成独立核算后对照。' }}</p><p class="muted">请使用可完整保存的限定范围；截断或条件不足不能判定通过。</p></template></section>
          <div class="run-actions"><el-button type="primary" native-type="submit" :loading="executing" :disabled="!canExecute">{{ independentMode && validationCase ? '留存输入并开始独立核算' : `执行${queryKindName(selectedQuery.kind)}查询` }}</el-button><span class="muted">{{ independentMode && validationCase ? '记录数与留存完整性由核验服务校验。' : '明细最多展示 50 条；记录数以完整查询范围为准。' }}</span></div>
          <p v-if="!canExecute" class="blocked-reason">{{ blockedReason }}</p>
        </form>
        <section class="query-result" aria-live="polite" aria-atomic="false">
          <h4>{{ isFactReference(selectedLayer) ? '参考查询结果 · 从事实层复算' : '查询结果' }}</h4>
          <el-alert v-if="executionError" :title="executionError" type="error" :closable="false" show-icon />
          <template v-if="currentResult">
            <el-alert v-if="resultIsStale" title="参数已更改。下方保留的是上次查询结果，请重新执行后再核对。" type="warning" :closable="false" show-icon />
            <el-alert v-if="currentResult.status === 'error'" :title="currentResult.message || '查询执行失败，未取得有效结果'" type="error" :closable="false" show-icon />
            <template v-else>
              <el-alert v-if="!currentResult.evidenceSaved" title="查询已完成，但执行证据未保存；本次结果不能作为已存核验依据。" type="warning" :closable="false" show-icon />
              <el-alert v-if="currentResult.resultDisclosure === 'withheld'" title="本次输入与结果已留存。请先完成下方独立核算，再查看被测结果。" type="info" :closable="false" />
              <template v-else><div class="result-summary"><span v-if="currentResult.metrics.source_records != null">原始成绩记录数 <strong>{{ displayValue(currentResult.metrics.source_records) }}</strong></span><span v-if="currentResult.recordCount !== null">{{ currentResult.metrics.source_records != null ? '核算分组记录数' : '范围内记录数' }} <strong>{{ recordCountText(currentResult.recordCount) }}</strong></span><span v-if="selectedQuery.kind === 'calculate'">结果单位：{{ metric.unit || '见字段说明' }}</span><span>展示 {{ currentResult.rows.length }} 行</span><span>{{ formatTime(currentResult.executedAt) }} · {{ currentResult.durationMs }} ms</span></div>
              <p v-if="currentResult.metrics.source_records != null" class="muted">原始成绩按课程与状态合并展示，每组 attempts 保留原始人次；分组数量用于确认留存输入完整，不能替代原始记录数。</p>
              <dl v-if="Object.keys(currentResult.metrics).length" class="calculated-metrics"><template v-for="(value, key) in currentResult.metrics" :key="key"><dt :title="String(key)">{{ fieldLabel(String(key)) }}</dt><dd>{{ displayValue(value) }}</dd></template></dl>
              <div class="result-table-scroll"><AppTable :columns="resultColumns" :data="currentResult.rows" :storage-key="`metric-verification:results:${selectedQuery.id}`" :pagination="false" empty-text="查询成功，当前范围内无明细记录">
                <template v-for="column in resultColumns" :key="column.key" #[`col-${column.key}`]="{ row }">{{ displayValue(row[column.key]) }}</template>
              </AppTable></div>
              <p v-if="currentResult.truncated" class="muted">已达到明细展示上限。页面展示行数不能替代完整范围记录数。</p>
              </template>
              <p v-if="currentResult.message" class="muted">{{ currentResult.message }}</p>
              <EvidenceReview :module-id="moduleId" v-if="currentResult.retainedEvidence && currentResult.evidenceSaved" :key="currentResult.id" :execution-id="currentResult.id" :query-id="selectedQuery.id" :result-columns="resultContract?.columns" :result-shape="resultContract?.shape" />
              <details class="execution-evidence"><summary>本次执行依据 · {{ currentResult.id }}</summary><p>SQL 版本：{{ currentResult.sqlVersion }}</p><dl><template v-for="(value, name) in currentResult.parameters" :key="name"><dt>{{ name }}</dt><dd>{{ displayValue(value) }}</dd></template></dl></details>
            </template>
          </template>
          <p v-else-if="!executing && !executionError" class="not-queried">尚未查询。执行成功后显示真实记录数和结果。</p>
          <p v-if="executing" class="muted">正在查询，请稍候…</p>
        </section>
      </template>
      <el-empty v-else :description="selectedLayer.mappingMode === 'no_independent_source' ? '该指标不产生独立源端结果，请按直接来源说明核对依赖数据。' : selectedLayer.status === 'not_applicable' ? '本层不适用，请查看上方说明。' : '该层尚未登记可查询 SQL，请先补齐数据关系和查询定义。'" :image-size="65" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppTable from '@/components/AppTable.vue'
import EvidenceReview from './EvidenceReview.vue'
import LayerMappingDetails from './LayerMappingDetails.vue'
import { metricTypeLabel, parameterSourceLabel, resultFieldLabel, statusLabel } from './labels'
import { executeVerificationQuery, getMetricVerificationQueries, getVerificationQueryOptions } from '@/api/admin/metricVerification'
import type { AppTableColumn } from '@/types/table'
import type {
  VerificationModuleId, VerificationCapabilities, VerificationExecution, VerificationLayer, VerificationLayerId,
  VerificationMetric, VerificationParameterOptions, VerificationParameters, VerificationQuery, VerificationQueryKind,
  MappingPackage, MappingSource, MappingMetric,
} from '@/types/metricVerification'
const props = defineProps<{ moduleId?: VerificationModuleId; metric: VerificationMetric; requirementId: string; scenarioId?: string; capabilities: VerificationCapabilities; compact?: boolean; initialParameters?: Record<string, string>; resetRevision?: number; mappingRevisionId?: string; mapping?: MappingPackage }>()
const emit = defineEmits<{ evidence: [result: VerificationExecution]; parameters: [parameters: Record<string, string>]; gaps: [gaps: string[]]; sourceManifest: [sources: MappingSource[]] }>()
const layers = ref<VerificationLayer[]>([])
const loadedMappingMetric = ref<MappingMetric>()
const mappingMetric = computed(() => loadedMappingMetric.value || props.mapping?.metrics.find(item => item.id === props.metric.id))
const selectedLayerId = ref<VerificationLayerId>('source')
const selectedQueryKind = ref<VerificationQueryKind>('count')
const selectedQueryId = ref('')
const loading = ref(false)
const loadError = ref('')
const parameterValues = reactive<Record<string, string>>({ ...props.initialParameters })
const parameterError = ref('')
const optionsByQuery = reactive<Record<string, VerificationParameterOptions>>({})
const optionsErrors = reactive<Record<string, string>>({})
const loadingOptions = reactive(new Set<string>())
const executing = ref(false)
const queryErrors = reactive<Record<string, string>>({})
const results = reactive<Record<string, VerificationExecution>>({})
const sqlInput = ref<HTMLTextAreaElement>()
const sqlExpanded = ref(false)
const independentMode = ref(false)
const validationCaseId = ref('')
let controller: AbortController | undefined
let alive = true
let queryGeneration = 0
const queryKinds: { id: VerificationQueryKind; label: string }[] = [{ id: 'count', label: '记录数' }, { id: 'detail', label: '数据明细' }, { id: 'calculate', label: '指标复算' }]
const selectedLayer = computed(() => layers.value.find(layer => layer.id === selectedLayerId.value))
const selectedLayerIssues = computed(() => [...new Set([...(selectedLayer.value?.issues || []), ...(selectedLayer.value?.remainingGaps || [])].flatMap(text => text.split(/[；\r\n]+/u)).map(text => text.trim()).filter(Boolean))])
const queriesForKind = computed(() => selectedLayer.value?.queries.filter(query => query.kind === selectedQueryKind.value) || [])
const selectedQuery = computed(() => queriesForKind.value.find(query => query.id === selectedQueryId.value) || queriesForKind.value[0])
const validationCases = computed(() => (props.mapping?.validationCases || []).filter(item => item.metricId === props.metric.id && item.execution.queryId === selectedQuery.value?.id))
const validationCase = computed(() => validationCases.value.find(item => item.id === validationCaseId.value) || validationCases.value[0])
const resultContract = computed(() => props.mapping?.queries.find(item => item.id === selectedQuery.value?.id)?.resultContract)
const parameterOptions = computed(() => selectedQuery.value ? optionsByQuery[selectedQuery.value.id]?.parameters || {} : {})
const optionsLoading = computed(() => Boolean(selectedQuery.value && loadingOptions.has(selectedQuery.value.id)))
const optionsError = computed(() => selectedQuery.value ? optionsErrors[selectedQuery.value.id] || '' : '')
const sqlElementId = computed(() => `sql-${props.requirementId}-${props.metric.id}`)
const currentResult = computed(() => selectedQuery.value ? results[selectedQuery.value.id] : undefined)
const executionError = computed(() => selectedQuery.value ? queryErrors[selectedQuery.value.id] || '' : '')
const canExecute = computed(() => Boolean(props.capabilities.execute && selectedQuery.value?.executable && !executing.value))
const blockedReason = computed(() => selectedQuery.value?.blockedReason || (!props.capabilities.execute ? '当前环境未启用数据库查询，请先完成核验服务的数据源配置。' : executing.value ? '查询执行中。' : '此 SQL 的执行条件尚未满足。'))
const resultIsStale = computed(() => currentResult.value && selectedQuery.value ? !parametersMatch(currentResult.value, selectedQuery.value) : false)
function fieldLabel(name: string) { const declared = resultContract.value?.columns.find(column => column.key === name)?.label; return declared && declared !== name ? declared : resultFieldLabel(name) }
const resultColumns = computed<AppTableColumn[]>(() => (currentResult.value?.columns || []).map(name => ({ key: name, label: fieldLabel(name), minWidth: 140, align: 'left' })))

async function loadQueries() {
  loading.value = true; loadError.value = ''
  try {
    const response = await getMetricVerificationQueries(props.metric.id, props.mappingRevisionId, props.moduleId)
    if (!alive) return
    layers.value = response.layers
    loadedMappingMetric.value = response.mappingMetric
    emit('sourceManifest', response.sourceManifest || [])
    emit('gaps', [...new Set([...response.layers].sort((a, b) => Number(b.id === 'application') - Number(a.id === 'application')).flatMap(layer => [
      ...(layer.id === 'application' && layer.metricResultStatus === 'blocked' ? ['应用结果与页面的对应关系尚未确认，请记录真实页面值后再作对照。'] : []),
      ...(layer.remainingGaps || []),
    ]))])
    if (!layers.value.some(layer => layer.id === selectedLayerId.value)) selectedLayerId.value = layers.value[0]?.id || 'source'
    selectLayer(selectedLayerId.value)
  } catch (error) { if (alive) loadError.value = error instanceof Error ? error.message : '读取三层关系和 SQL 失败' }
  finally { if (alive) loading.value = false }
}
async function loadParameterOptions() {
  const query = selectedQuery.value
  if (!query || loadingOptions.has(query.id) || executing.value) return
  loadingOptions.add(query.id)
  delete optionsErrors[query.id]
  try {
    const response = await getVerificationQueryOptions(query.id, props.requirementId, props.mappingRevisionId, props.moduleId)
    if (alive) optionsByQuery[query.id] = response
  } catch (error) {
    if (alive) optionsErrors[query.id] = `${error instanceof Error ? error.message : '读取可选值失败'}；已填写参数保留，可继续手工输入。`
  } finally { if (alive) loadingOptions.delete(query.id) }
}
function isFactReference(layer: VerificationLayer) { return layer.id === 'application' && layer.mappingMode === 'reference_from_fact' }
function selectLayer(id: VerificationLayerId) {
  selectedLayerId.value = id
  const layer = layers.value.find(item => item.id === id)
  if (!layer?.queries.some(query => query.kind === selectedQueryKind.value)) selectedQueryKind.value = layer?.queries[0]?.kind || 'count'
  const candidates = layer?.queries.filter(query => query.kind === selectedQueryKind.value) || []
  selectedQueryId.value = (candidates.find(query => query.executable) || candidates[0])?.id || ''
  parameterError.value = ''
}
function changeQueryKind(value: string | number | boolean | undefined) {
  if (queryKinds.some(kind => kind.id === value)) selectedQueryKind.value = value as VerificationQueryKind
  selectedQueryId.value = (queriesForKind.value.find(query => query.executable) || queriesForKind.value[0])?.id || ''
  parameterError.value = ''
}
function queryKindName(kind: VerificationQueryKind) { return queryKinds.find(item => item.id === kind)?.label || kind }
function queryParameters(query: VerificationQuery): VerificationParameters {
  return Object.fromEntries(query.parameters.map(parameter => {
    const value = (parameterValues[parameter.name] || '').trim()
    return [parameter.name, value === '' ? null : parameter.type === 'string' ? value : Number(value)]
  }))
}
function parametersMatch(result: VerificationExecution, query: VerificationQuery) {
  const current = queryParameters(query)
  return query.parameters.every(parameter => String(current[parameter.name] ?? '') === String(result.parameters[parameter.name] ?? ''))
}
function layerCountText(layer: VerificationLayer) {
  const query = layer.queries.find(item => item.kind === 'count')
  if (!query) return '未配置'
  if (executing.value && selectedQuery.value?.id === query.id) return '查询中'
  if (queryErrors[query.id]) return '查询失败'
  const result = results[query.id]
  if (!result) return '未查询'
  if (result.status !== 'success') return '查询失败'
  if (!parametersMatch(result, query)) return '参数已更改'
  return recordCountText(result.recordCount)
}
function recordCountText(value: number | null) { return value === null || value === undefined ? '未取得' : value.toLocaleString('zh-CN') }
function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' })
}
async function copySql() {
  if (!selectedQuery.value) return
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')
    await navigator.clipboard.writeText(selectedQuery.value.sql)
    ElMessage.success('已复制完整 SQL')
  } catch {
    sqlInput.value?.focus(); sqlInput.value?.select()
    ElMessage.warning('自动复制不可用，已选中完整 SQL，请按 Ctrl+C 复制')
  }
}
async function runQuery() {
  const query = selectedQuery.value
  if (!query || !canExecute.value) return
  parameterError.value = ''; delete queryErrors[query.id]
  for (const parameter of query.parameters) {
    const text = (parameterValues[parameter.name] || '').trim()
    if (parameter.required && !text) { parameterError.value = `请填写${parameter.label || parameter.name}`; return }
    if (text && parameter.type !== 'string' && (!Number.isFinite(Number(text)) || (parameter.type === 'integer' && !Number.isSafeInteger(Number(text))))) {
      parameterError.value = `${parameter.label || parameter.name}必须为${parameter.type === 'integer' ? '有效整数' : '有效数值'}`; return
    }
  }
  executing.value = true
  const generation = ++queryGeneration
  delete results[query.id]
  controller = new AbortController()
  try {
    const result = await executeVerificationQuery(query.id, { requirementId: props.requirementId, scenarioId: props.scenarioId, parameters: queryParameters(query), limit: 50, sqlVersion: query.version, mappingRevisionId: props.mappingRevisionId, executionUse: independentMode.value && validationCase.value ? 'definition_validation' : 'verification', validationCaseId: independentMode.value ? validationCase.value?.id : undefined }, controller.signal, props.moduleId)
    if (!alive || generation !== queryGeneration) return
    results[query.id] = result
    if (result.status === 'success') emit('evidence', result)
  } catch (error) {
    if (alive && generation === queryGeneration) queryErrors[query.id] = error instanceof Error ? error.message : '查询失败，未取得有效结果'
  } finally { if (alive && generation === queryGeneration) executing.value = false }
}
function clearQueryResults() {
  ++queryGeneration; controller?.abort(); executing.value = false
  Object.keys(results).forEach(key => delete results[key])
  Object.keys(queryErrors).forEach(key => delete queryErrors[key])
}
watch(parameterValues, () => { clearQueryResults(); emit('parameters', { ...parameterValues }) }, { deep: true })
watch(() => props.resetRevision, clearQueryResults)
watch(independentMode, clearQueryResults)
watch(() => selectedQuery.value?.id, () => { sqlExpanded.value = false })
onMounted(loadQueries)
onBeforeUnmount(() => { alive = false; controller?.abort() })
</script>

<style scoped>
.metric-query-panel { min-width: 0; }
.metric-definition, .layer-detail { border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-bg-color); padding: 16px; min-width: 0; max-width: 100%; box-sizing: border-box; }
.metric-definition>div:first-child { display: flex; gap: 10px; align-items: center; }
.metric-definition p { margin: 10px 0; line-height: 1.65; }
dl { display: grid; grid-template-columns: 98px minmax(0, 1fr); gap: 8px 12px; margin: 12px 0; font-size: 13px; }
dt { color: var(--el-text-color-secondary); overflow-wrap: anywhere; } dd { margin: 0; overflow-wrap: anywhere; }
details { font-size: 13px; margin: 12px 0; } summary { cursor: pointer; color: var(--el-color-primary); }
.data-chain { display: grid; grid-template-columns: minmax(0,1fr) 20px minmax(0,1fr) 20px minmax(0,1fr); gap: 8px; align-items: stretch; margin: 18px 0; min-height: 60px; }
.chain-arrow { align-self: center; color: var(--el-text-color-secondary); text-align: center; }
.layer-card { display: flex; flex-direction: column; align-items: start; gap: 8px; border: 1px solid var(--el-border-color); border-radius: 6px; padding: 14px; background: var(--el-bg-color); color: var(--el-text-color-primary); font: inherit; cursor: pointer; text-align: left; min-width: 0; }
.layer-card.selected { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.layer-card:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.layer-title { font-weight: 600; color: var(--el-color-primary); }
.layer-tables { font: 12px/1.5 Consolas, monospace; overflow-wrap: anywhere; }
.layer-grain, .layer-count, .muted { font-size: 12px; color: var(--el-text-color-secondary); }
.layer-count { margin-top: auto; }
.layer-count strong { color: var(--el-text-color-primary); }
.reference-badge { font-size: 12px; font-weight: 600; line-height: 1.6; color: var(--el-color-warning-dark-2); background: var(--el-color-warning-light-9); padding: 3px 6px; border-radius: 4px; }
.layer-gap { font-size:12px; line-height:1.5; color:var(--el-color-warning-dark-2); overflow-wrap:anywhere; }
.query-choice { display:flex; align-items:center; gap:12px; font-size:13px; margin:12px 0; } .query-choice .el-select { flex:1; min-width:0; }
.sql-details .sql-heading { margin-top:12px; }
.mapping-notice { margin-top: 12px; }
.parameter-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.layer-heading, .sql-heading, .query-kinds { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h4 { font-size: 14px; margin: 0; }
.transform { font-size: 13px; margin: 12px 0; }
.transform ol { margin: 8px 0; padding-left: 20px; }
.transform li { margin: 5px 0; line-height: 1.6; }
.query-kinds { margin: 18px 0 14px; }
.sql-heading { margin-bottom: 8px; font-size: 13px; font-weight: 600; }
.sql-actions { display:flex; gap:8px; flex-wrap:wrap; }.sql-actions :deep(.el-button + .el-button) { margin-left:0; }
.sql-source { width: 100%; height:168px; min-height: 100px; max-height: 70vh; box-sizing: border-box; resize: vertical; border: 1px solid var(--el-border-color); border-radius: 4px; padding: 12px; background: var(--el-fill-color-lighter); color: var(--el-text-color-primary); font: 12px/1.7 Consolas, monospace; white-space: pre; overflow: auto; }.sql-source.expanded { height:480px; }
.query-form { margin-top: 18px; }
.parameters { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(190px, 100%), 1fr)); gap: 14px; margin: 12px 0; }
.parameters>label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; min-width: 0; }
.parameters small { font-size: 11px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.parameters small.parameter-warning { color: var(--el-color-warning-dark-2); }
.required, .inline-error { color: var(--el-color-danger); }
.inline-error { font-size: 13px; margin: 8px 0; }
.run-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.validation-mode { margin:14px 0; padding:12px; border:1px solid var(--el-border-color-light); border-radius:4px; }.validation-mode :deep(.el-checkbox) { height:auto; align-items:flex-start; }.validation-mode :deep(.el-checkbox__label) { white-space:normal; line-height:1.7; }.validation-mode :deep(.el-checkbox__input) { margin-top:5px; }
.blocked-reason { color: var(--el-color-warning-dark-2); font-size: 13px; line-height: 1.6; }
.query-result { border-top: 1px solid var(--el-border-color-lighter); padding-top: 16px; margin-top: 20px; }
.query-result h4 { margin-bottom: 12px; }
.result-summary { display: flex; flex-wrap: wrap; gap: 12px 22px; align-items: baseline; margin: 14px 0; font-size: 12px; color: var(--el-text-color-secondary); }
.result-summary strong { font-size: 20px; color: var(--el-text-color-primary); margin-left: 6px; }
.calculated-metrics { grid-template-columns: minmax(140px, 1fr) 2fr; background: var(--el-fill-color-light); padding: 12px; }
.not-queried { color: var(--el-text-color-secondary); padding: 14px 0; font-size: 13px; }
.execution-evidence dl { grid-template-columns: minmax(150px, 1fr) 2fr; }
.execution-evidence summary { overflow-wrap: anywhere; }
.result-table-scroll { max-width: 100%; overflow-x: auto; }
.query-kinds :deep(.el-radio-group) { max-width: 100%; flex-wrap: wrap; row-gap: 6px; }
@media (max-width: 880px) { .data-chain { grid-template-columns: 1fr; } .chain-arrow { transform: rotate(90deg); } .layer-card { gap: 6px; } }
</style>

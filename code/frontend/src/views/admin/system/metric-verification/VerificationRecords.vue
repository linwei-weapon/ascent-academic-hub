<template>
  <div class="verification-records">
    <p class="record-intro">当前核对：<strong>{{ entry.name }}</strong>。可根据真实页面观察和独立计算记录结果，也可引用本场景的 SQL 证据。查询成功不自动代表符合。</p>
    <form class="record-form" @submit.prevent="saveRecord">
      <section class="import-panel" aria-label="从查询带入复算值">
        <h4>从SQL带入需求复算值</h4>
        <p class="muted">选择本指标已保存的单值复算，可一起带入结果、组成值、条件与来源。此操作替换本次未保存的草稿；应用实际值需另行取得。</p>
        <div class="import-actions"><el-select v-model="importId" aria-label="选择复算证据" placeholder="选择已保存的复算结果" :disabled="saving || importing || !importableEvidence.length"><el-option v-for="item in importableEvidence" :key="item.id" :value="item.id" :label="`${layerName(item.layer)} · ${formatTime(item.executedAt)} · ${item.metrics.candidate_metric_value ?? '无有效值'}`" /></el-select><el-button :disabled="saving || !importId" :loading="importing" @click="importExpected">带入复算值</el-button></div>
        <p v-if="!loading && !importableEvidence.length" class="muted">暂无可带入结果。请在三层查询中执行本指标的贴源层或事实层“指标复算”；记录数不等于指标值，多行结果请按对象手工对照。</p>
        <el-alert v-if="importError" :title="importError" type="warning" :closable="false" />
      </section>
      <ComparisonEditor :module-id="moduleId" ref="comparisonEditor" :entry="entry" :unit="mainMetric?.unit || ''" :disabled="saving || importing" :context-revision="contextRevision" @conditions-change="conditionsChanged" />
      <details v-if="Object.keys(queryParameters).length" class="query-context"><summary>当前 SQL 参数（用于核对是否为同一范围）</summary><dl><template v-for="(value, key) in queryParameters" :key="key"><dt>{{ key }}</dt><dd>{{ value || '未填写' }}</dd></template></dl></details>
      <section class="evidence-picker">
        <div class="history-heading"><h4>引用真实查询证据（可选）</h4><el-button size="small" :loading="loading" :disabled="!capabilities.records || saving" @click="loadRecords">读取历史证据</el-button></div>
        <p class="muted">仅列本指标场景及其计算依据。手工核验可不引用内部SQL，但须记录双方真实来源、时间、条件与值。</p>
        <el-alert v-if="evidenceError" :title="evidenceError" type="warning" :closable="false" show-icon />
        <el-checkbox-group v-model="draft.evidenceIds" :disabled="saving" aria-label="关联查询证据">
          <div v-for="result in availableEvidence" :key="result.id" class="evidence-option">
            <el-checkbox :value="result.id" :disabled="!canSelectEvidence(result)"><span>{{ metricName(result.metricId) }} · {{ layerName(result.layer) }} · {{ kindName(result.queryKind) }} · {{ formatTime(result.executedAt) }}</span></el-checkbox>
            <div class="evidence-option-meta"><span>记录数：{{ countText(result.recordCount) }}</span><span v-if="result.executionUse === 'definition_validation'" class="expired-text">定义核算样本，另行执行同范围业务复算</span><span v-else-if="result.resultDisclosure === 'withheld'" class="expired-text">尚未完成独立核算</span><span v-else-if="!result.current" class="expired-text">定义已变化，不能用于新核验</span><span v-else-if="result.status !== 'success'" class="expired-text">查询失败</span><span v-else-if="!parametersMatch(result)" class="expired-text">与当前查询参数不一致</span><span v-else>对应当前定义，请确认业务范围</span></div>
            <p v-if="result.mappingMode === 'reference_from_fact'" class="evidence-reference">从事实层复算的参考值，不是应用实值。</p>
            <details><summary>查看参数、结果与 SQL 版本</summary><EvidenceDetails :module-id="moduleId" :evidence="result" :metric-name="metricName(result.metricId)" /></details>
          </div>
        </el-checkbox-group>
        <p v-if="!availableEvidence.length && !loading" class="muted">本场景暂无已保存的查询证据。不会将其他场景或旧版无场景证据自动带入。</p>
        <el-checkbox v-if="draft.evidenceIds.length" v-model="scopeConfirmed" :disabled="saving" class="scope-confirmation">已核对引用证据的对象、观察期和批次与本次条件一致</el-checkbox>
      </section>
      <div class="judgment-fields"><label><span>核验判断</span><el-select v-model="draft.judgment" :disabled="saving" aria-label="核验判断" placeholder="人工选择判断"><el-option v-for="judgment in judgments" :key="judgment" :label="judgment" :value="judgment" /></el-select></label><label class="comment-field"><span>观察与依据</span><el-input v-model="draft.comment" type="textarea" :rows="3" maxlength="4000" show-word-limit :disabled="saving" aria-label="观察与依据" placeholder="说明对照结果；条件不足时写明缺少的口径、数据或应用实值。" /></label></div>
      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
      <div class="save-actions"><el-button native-type="submit" type="primary" :loading="saving" :disabled="!capabilities.records">保存本次核对</el-button><span v-if="!capabilities.records" class="muted">核对记录存储未就绪。</span></div>
    </form>
    <section v-loading="loading" class="record-history" aria-label="本场景核对记录">
      <div class="history-heading"><h4>本指标场景的已保存记录</h4><el-button size="small" :loading="loading" :disabled="!capabilities.records || saving" @click="loadRecords">刷新</el-button></div>
      <p class="muted">记录保留各自范围和时点。历史符合不代表当前范围已经符合。</p>
      <el-alert v-if="!capabilities.records" title="核对记录存储尚未就绪，当前无法读取或保存记录。" type="info" :closable="false" show-icon />
      <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
      <el-empty v-if="capabilities.records && !loading && !loadError && !records.length" description="本场景暂无已保存记录" :image-size="60" />
      <article v-for="record in records" :key="record.id" class="saved-record">
        <header><el-tag :type="record.current === false ? 'info' : judgmentType(record.judgment)">{{ record.judgment }}</el-tag><strong>{{ entry.name }}</strong><span class="muted">{{ record.createdBy || '核验人员' }} · {{ formatTime(record.createdAt) }}</span></header>
        <el-alert v-if="record.current === false || record.evidenceIds.some(id => evidenceById.get(id)?.current === false)" title="定义或引用证据已变化，此记录仅供历史回看，不能作为本次符合结论。" type="warning" :closable="false" show-icon />
        <ComparisonDetails v-if="record.comparison" :comparison="record.comparison" /><p v-else class="expired-text">旧版记录没有结构化结果对照，不能按当前场景直接沿用。</p>
        <p>{{ record.comment }}</p>
        <details v-if="record.evidenceIds.length"><summary>查看 {{ record.evidenceIds.length }} 条引用证据</summary><div v-for="id in record.evidenceIds" :key="id" class="referenced-evidence"><EvidenceDetails :module-id="moduleId" v-if="evidenceById.has(id)" :evidence="evidenceById.get(id)!" :metric-name="metricName(evidenceById.get(id)!.metricId)" /><p v-else class="muted">暂未取得此执行摘要，不能确认其有效性。证据编号：{{ id }}</p></div></details><small class="muted">记录编号：{{ record.id }}</small>
      </article>
      <details v-if="legacyRecords.length" class="legacy-records"><summary>查看该指标的旧版无场景记录（{{ legacyRecords.length }}条）</summary><p class="muted">这些记录未登记场景，不计入本场景最近状态，也不自动作为本次依据。</p><article v-for="record in legacyRecords" :key="record.id" class="saved-record"><header><el-tag type="info">历史：{{ record.judgment }}</el-tag><span class="muted">{{ formatTime(record.createdAt) }}</span></header><p>{{ record.comment }}</p><ComparisonDetails v-if="record.comparison" :comparison="record.comparison" /><p v-else class="muted">旧版无结构化对照</p><small class="muted">{{ record.id }}</small></article></details>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getVerificationExecutions, getVerificationRecords, saveVerificationRecord, importVerificationExpected } from '@/api/admin/metricVerification'
import EvidenceDetails from './EvidenceDetails.vue'
import ComparisonEditor from './ComparisonEditor.vue'
import ComparisonDetails from './ComparisonDetails.vue'
import type { VerificationModuleId, StoredVerificationEvidence, VerificationCapabilities, VerificationExecution, VerificationIndicatorEntry, VerificationJudgment, VerificationLayerId, VerificationMetric, VerificationQueryKind, VerificationRecord } from '@/types/metricVerification'
const props = defineProps<{ moduleId?: VerificationModuleId; requirementId: string; entry: VerificationIndicatorEntry; metrics: VerificationMetric[]; capabilities: VerificationCapabilities; evidence: VerificationExecution[]; contextRevision: number; queryParameters: Record<string, string>; mappingRevisionId?: string }>()
const emit = defineEmits<{ count: [count: number]; saved: [record: VerificationRecord]; conditionsChange: [] }>()
const comparisonEditor = ref<InstanceType<typeof ComparisonEditor>>()
const judgments: VerificationJudgment[] = ['符合', '有差异', '条件不足']
const draft = reactive<{ judgment: VerificationJudgment | ''; comment: string; evidenceIds: string[] }>({ judgment: '', comment: '', evidenceIds: [] })
const allRecords = ref<VerificationRecord[]>([])
const storedEvidence = ref<StoredVerificationEvidence[]>([])
const evidenceError = ref('')
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const formError = ref('')
const scopeConfirmed = ref(false)
const importId = ref('')
const importing = ref(false)
const importError = ref('')
let importGeneration = 0
let loadGeneration = 0
let alive = true
const mainMetric = computed(() => props.metrics.find(metric => metric.id === props.entry.metricId))
const records = computed(() => allRecords.value.filter(record => record.metricId === props.entry.metricId && record.scenarioId === props.entry.id))
const legacyRecords = computed(() => allRecords.value.filter(record => record.metricId === props.entry.metricId && !record.scenarioId))
const allowedMetricIds = computed(() => new Set([props.entry.metricId, ...(props.entry.evidenceMetricIds || [])]))
const allEvidence = computed<StoredVerificationEvidence[]>(() => {
  const merged = new Map<string, StoredVerificationEvidence>()
  for (const result of props.evidence) {
    if (result.status !== 'success' || result.evidenceSaved !== true) continue
    const { rows, evidenceSaved: _saved, ...summary } = result
    merged.set(result.id, { ...summary, requirementId: props.requirementId, returnedRows: rows.length, queryChecksum: '', current: true })
  }
  for (const result of storedEvidence.value) merged.set(result.id, result)
  return [...merged.values()].sort((a, b) => b.executedAt.localeCompare(a.executedAt))
})
const availableEvidence = computed(() => allEvidence.value.filter(result => result.scenarioId === props.entry.id && allowedMetricIds.value.has(result.metricId)))
const importableEvidence = computed(() => availableEvidence.value.filter(result => canSelectEvidence(result) && result.metricId === props.entry.metricId && props.entry.comparisonKind === 'scalar' && ['source', 'fact'].includes(result.layer) && result.queryKind === 'calculate' && result.returnedRows === 1 && !result.truncated && Object.hasOwn(result.metrics || {}, 'candidate_metric_value')))
watch(importableEvidence, items => { if (!items.some(item => item.id === importId.value)) importId.value = items[0]?.id || '' }, { immediate: true })
const evidenceById = computed(() => new Map(allEvidence.value.map(result => [result.id, result])))
const selectedValidEvidence = computed(() => draft.evidenceIds.flatMap(id => { const result = evidenceById.value.get(id); return result && canSelectEvidence(result) ? [result] : [] }))
watch(availableEvidence, () => { draft.evidenceIds = draft.evidenceIds.filter(id => canSelectEvidence(evidenceById.value.get(id))) })
watch(() => props.contextRevision, () => { resetDecision(); ++importGeneration; importing.value = false })
watch(() => draft.evidenceIds.join(','), () => { scopeConfirmed.value = false })
function resetDecision() { draft.evidenceIds = []; draft.judgment = ''; draft.comment = ''; scopeConfirmed.value = false; formError.value = '' }
function conditionsChanged() { resetDecision(); emit('conditionsChange') }
async function importExpected() {
  if (saving.value || importing.value || !importId.value || !comparisonEditor.value) return
  const generation = ++importGeneration
  importing.value = true; importError.value = ''
  try {
    const data = await importVerificationExpected({ requirementId: props.requirementId, scenarioId: props.entry.id, executionId: importId.value, mappingRevisionId: props.mappingRevisionId }, props.moduleId)
    if (!alive || generation !== importGeneration) return
    resetDecision()
    await comparisonEditor.value.applyDraft(data)
    if (!alive || generation !== importGeneration) return
    draft.evidenceIds = [data.expectedExecutionId!]
    ElMessage.success('已带入真实复算值，请补充应用实际值和统计截至时点')
  } catch (error) { if (alive && generation === importGeneration) importError.value = error instanceof Error ? error.message : '带入失败，请重新查询' }
  finally { if (alive && generation === importGeneration) importing.value = false }
}
function parametersMatch(result: StoredVerificationEvidence) {
  return Object.entries(props.queryParameters).every(([name, value]) => !(name in result.parameters) || String(result.parameters[name] ?? '') === value.trim())
}
function canSelectEvidence(result: StoredVerificationEvidence | undefined) { return Boolean(result && result.status === 'success' && result.executionUse !== 'definition_validation' && result.resultDisclosure !== 'withheld' && result.current && result.scenarioId === props.entry.id && allowedMetricIds.value.has(result.metricId) && parametersMatch(result)) }
function countText(value: number | null) { return value === null || value === undefined ? '未取得' : value.toLocaleString('zh-CN') }
function layerName(layer: VerificationLayerId) { return { source: '贴源层', fact: '事实层', application: '应用层' }[layer] }
function metricName(id: string) { return props.metrics.find(metric => metric.id === id)?.name || '指标定义待补齐' }
function kindName(kind: VerificationQueryKind) { return { count: '记录数', detail: '明细', calculate: '指标复算' }[kind] }
function judgmentType(value: VerificationJudgment): 'success' | 'danger' | 'warning' { return value === '符合' ? 'success' : value === '有差异' ? 'danger' : 'warning' }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }) }
async function loadRecords() {
  if (!props.capabilities.records || saving.value) return
  const generation = ++loadGeneration
  loading.value = true; loadError.value = ''; evidenceError.value = ''
  const [recordResponse, executionResponse] = await Promise.allSettled([getVerificationRecords(props.requirementId, props.mappingRevisionId, props.moduleId), getVerificationExecutions(props.requirementId, props.mappingRevisionId, props.moduleId)])
  if (!alive || generation !== loadGeneration) return
  if (recordResponse.status === 'fulfilled') { allRecords.value = recordResponse.value.items; emit('count', records.value.length) }
  else loadError.value = recordResponse.reason instanceof Error ? recordResponse.reason.message : '读取核对记录失败'
  if (executionResponse.status === 'fulfilled') storedEvidence.value = executionResponse.value.items
  else evidenceError.value = executionResponse.reason instanceof Error ? executionResponse.reason.message : '读取历史查询证据失败'
  loading.value = false
}
async function saveRecord() {
  if (saving.value || importing.value || !props.capabilities.records || !comparisonEditor.value) return
  formError.value = ''
  if (!draft.judgment) { formError.value = '请选择人工核验判断'; return }
  if (!draft.comment.trim()) { formError.value = '请填写观察与依据'; return }
  const validation = comparisonEditor.value.validate(draft.judgment)
  if (validation) { formError.value = validation; return }
  const comparison = comparisonEditor.value.snapshot()
  if (comparison.expectedExecutionId && !draft.evidenceIds.includes(comparison.expectedExecutionId)) draft.evidenceIds.push(comparison.expectedExecutionId)
  if (draft.evidenceIds.length !== selectedValidEvidence.value.length) { formError.value = '所选证据已失效或不属于本次场景，请重新选择。'; return }
  if (draft.evidenceIds.length && !scopeConfirmed.value) { formError.value = '请先核对引用证据与本次范围、观察期和批次一致。'; return }
  saving.value = true; ++loadGeneration; loading.value = false
  try {
    const result = await saveVerificationRecord({ requirementId: props.requirementId, metricId: props.entry.metricId, scenarioId: props.entry.id, comparison, judgment: draft.judgment, comment: draft.comment.trim(), evidenceIds: selectedValidEvidence.value.map(item => item.id), mappingRevisionId: props.mappingRevisionId }, props.moduleId)
    if (!alive) return
    allRecords.value = [result, ...allRecords.value.filter(record => record.id !== result.id)]
    emit('count', records.value.length); emit('saved', result)
    resetDecision(); loadError.value = ''
    if (comparison.expectedExecutionId) draft.evidenceIds = [comparison.expectedExecutionId]
    ElMessage.success('本次核对记录已保存，差异以服务端计算结果为准')
  } catch (error) { if (alive) formError.value = error instanceof Error ? error.message : '保存失败，输入内容已保留' }
  finally { if (alive) saving.value = false }
}
onMounted(loadRecords)
onBeforeUnmount(() => { alive = false; ++loadGeneration; ++importGeneration })
</script>

<style scoped>
.verification-records { min-width:0; } .record-intro { font-size:13px; line-height:1.7; margin-bottom:14px; }
.import-panel { margin-bottom:20px; padding-bottom:16px; border-bottom:1px solid var(--el-border-color-light); } .import-panel h4 { margin:0; font-size:14px; } .import-actions { display:flex; flex-wrap:wrap; gap:10px; } .import-actions .el-select { flex:1 1 250px; min-width:0; }
.record-form { padding:16px; border:1px solid var(--el-border-color-light); border-radius:6px; background:var(--el-bg-color); }
.judgment-fields { display:flex; flex-wrap:wrap; gap:16px; margin:22px 0 16px; } .judgment-fields>label { display:flex; flex-direction:column; gap:7px; font-size:13px; flex:1 1 180px; min-width:0; } .judgment-fields>.comment-field { flex:3 1 320px; }
.form-error { color:var(--el-color-danger); font-size:13px; }.muted { font-size:12px; color:var(--el-text-color-secondary); line-height:1.7; }
.evidence-picker { margin-top:20px; padding-top:16px; border-top:1px solid var(--el-border-color-light); font-size:13px; }
.evidence-picker :deep(.el-checkbox-group) { display:flex; flex-direction:column; align-items:stretch; gap:7px; margin-top:10px; max-height:420px; overflow:auto; font-size:13px; line-height:1.6; }
.evidence-picker :deep(.el-checkbox) { display:flex; flex-direction:row; height:auto; align-items:flex-start; max-width:100%; margin-right:0; }.evidence-picker :deep(.el-checkbox__input) { margin-top:3px; flex:0 0 auto; }.evidence-picker :deep(.el-checkbox__label) { white-space:normal; font-size:12px; line-height:1.6; min-width:0; overflow-wrap:anywhere; }
.evidence-option { border:1px solid var(--el-border-color-lighter); border-radius:4px; padding:10px; min-width:0; flex:0 0 auto; }.evidence-option-meta { display:flex; flex-wrap:wrap; gap:8px 16px; margin:7px 0 8px 22px; font-size:12px; color:var(--el-text-color-secondary); }.evidence-option details { margin-left:22px; min-width:0; font-size:12px; } summary { color:var(--el-color-primary); cursor:pointer; }
.expired-text,.evidence-reference { color:var(--el-color-warning-dark-2); font-size:12px; line-height:1.6; }.evidence-reference { margin:6px 0 8px 22px; font-weight:600; }.scope-confirmation { margin-top:14px; }
.save-actions,.history-heading,.saved-record header { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }.record-history { margin-top:24px; }.history-heading { justify-content:space-between; }.history-heading h4 { margin:0; font-size:14px; }.saved-record { padding:18px 0; border-bottom:1px solid var(--el-border-color-lighter); }.saved-record header strong { font-size:13px; }.saved-record p { white-space:pre-wrap; line-height:1.7; font-size:13px; overflow-wrap:anywhere; }.saved-record details,.legacy-records,.query-context { margin:14px 0; font-size:12px; }.query-context dl { display:grid; grid-template-columns:minmax(80px,1fr) 2fr; gap:7px; }.query-context dd { margin:0; overflow-wrap:anywhere; }
@media(max-width:650px) { .record-form { padding:12px; } }
</style>

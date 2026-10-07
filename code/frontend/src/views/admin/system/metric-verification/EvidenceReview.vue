<template>
  <section class="evidence-review" aria-label="当次留存输入与独立核算">
    <div class="heading"><h4>当次留存输入与独立核算</h4><el-button size="small" :loading="loading" :disabled="saving" @click="load">{{ evidence ? '重新读取已存证据' : '读取留存证据' }}</el-button></div>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <template v-if="evidence">
      <p class="muted">这里读取核验当时保存的输入和结果，不重新查询历史批次。结论仅覆盖本次留存范围，不能直接代表应用业务符合。</p>
      <el-alert v-if="!evidence.integrity.readbackVerified" title="留存证据尚未完成完整性回读，当前不能确认其可复核性。" type="warning" :closable="false" />
      <p class="scope">留存时间：{{ time(evidence.integrity.persistedAt) }} · {{ evidence.integrity.readbackVerified ? '完整性回读已通过' : '完整性待确认' }}</p>
      <details><summary>留存范围、读取条件与版本</summary><dl><dt>范围</dt><dd>{{ describe(evidence.scope) }}</dd><dt>读取条件</dt><dd>{{ describe(evidence.capture) }}</dd><dt>映射版本</dt><dd>{{ evidence.mappingRevisionId || '未登记' }}</dd><dt>内容校验</dt><dd>{{ evidence.integrity.contentHash }}</dd></dl></details>
      <article v-for="(dataset, index) in evidence.datasets" :key="dataset.queryId" class="dataset">
        <h4>核算输入 {{ evidence.datasets.length > 1 ? index + 1 : '' }}</h4>
        <p class="muted">范围记录数：{{ dataset.matchedRecordCount ?? '未取得' }} · 保存 {{ dataset.returnedRecordCount }} 条 · {{ dataset.complete && !dataset.truncated ? '本次范围完整' : '输入不完整，不能判定通过' }}</p>
        <AppTable :columns="tableColumns(dataset.columns)" :data="dataset.rows" :pagination="false" :storage-key="`metric-evidence:${executionId}:${dataset.queryId}`" empty-text="本次留存输入为空"><template v-for="column in dataset.columns" :key="column.key" #[`col-${column.key}`]="{ row }">{{ display(row[column.key]) }}</template></AppTable>
        <details><summary>查看原始查询与参数</summary><pre>{{ dataset.sql }}</pre><dl><template v-for="(value,key) in dataset.parameters" :key="key"><dt>{{ key }}</dt><dd>{{ display(value) }}</dd></template></dl><p v-if="dataset.countSql">记录数查询：</p><pre v-if="dataset.countSql">{{ dataset.countSql }}</pre></details>
      </article>
      <form v-if="evidence.resultDisclosure === 'withheld'" class="expectation" @submit.prevent="submit">
        <h4>根据上方输入独立核算预期</h4><p class="muted">被测 SQL 结果已留存，提交独立核算依据后展示。请按需求口径核算，不参考待揭示的结果。</p>
        <label><span>核算方法</span><el-input v-model="method" :disabled="saving" aria-label="独立核算方法" placeholder="例如：逐条确认有效成绩后，分别按学生去重计数" /></label>
        <label><span>计算过程与依据</span><el-input v-model="derivation" :disabled="saving" type="textarea" :rows="3" aria-label="独立核算过程" placeholder="说明使用的需求口径、筛选、去重、分子分母和计算过程" /></label>
        <el-alert v-if="!columns.length" title="尚未取得被测查询的结果字段契约，无法提交预期。请重新读取，或补齐映射定义。" type="warning" :closable="false" />
        <el-checkbox v-if="shape !== 'scalar' && columns.length" v-model="expectedEmpty" :disabled="saving">按需求核算，预期结果为空集合</el-checkbox>
        <template v-if="!expectedEmpty"><article v-for="(row,index) in expectedRows" :key="index" class="expected-row"><div class="heading"><strong>预期结果{{ expectedRows.length > 1 ? ` ${index + 1}` : '' }}</strong><el-button v-if="expectedRows.length > 1" link type="danger" :disabled="saving" @click="expectedRows.splice(index,1)">移除此项</el-button></div><div class="expected-fields"><label v-for="column in columns" :key="column.key"><span>{{ column.label || column.key }}{{ column.unit ? `（${column.unit}）` : '' }}</span><el-input v-model="row[column.key]" :disabled="saving" :aria-label="`预期${index+1}项${column.label || column.key}`" placeholder="填写核算值；空值填 NULL" /></label></div></article>
        <el-button v-if="shape !== 'scalar' && columns.length" size="small" :disabled="saving" @click="addRow">添加预期结果项</el-button></template>
        <el-checkbox v-model="resultKnown" :disabled="saving" class="known-result">此前已通过其他途径知晓本次被测结果（如实登记，将影响独立核算结论）</el-checkbox>
        <p v-if="submissionError" class="error" role="alert">{{ submissionError }}</p>
        <el-button type="primary" native-type="submit" :loading="saving" :disabled="!columns.length || !evidence.integrity.readbackVerified">提交预期并查看 SQL 结果</el-button>
      </form>
      <section v-if="evidence.expected" class="recorded-expectation"><h4>已保存的独立核算</h4><p>{{ evidence.expected.method }}</p><p class="preserve">{{ evidence.expected.derivation }}</p><p v-if="evidence.expected.resultKnownBeforeCalculation" class="warning">核算前已知被测结果，不能作为盲算验证。</p><AppTable :columns="expectedTableColumns" :data="evidence.expected.rows" :pagination="false" :storage-key="`metric-evidence:expected:${executionId}`" /></section>
      <section v-if="evidence.resultDisclosure !== 'withheld' && evidence.testedResult" class="tested-result"><h4>{{ evidence.caseId ? '当次被测 SQL 结果' : '当次留存的应用结果' }}</h4><AppTable :columns="tableColumns(evidence.testedResult.columns)" :data="evidence.testedResult.rows" :pagination="false" :storage-key="`metric-evidence:tested:${executionId}`" /><el-alert v-if="evidence.caseId" :title="validationText" :type="evidence.validation.status === 'match' ? 'success' : 'warning'" :closable="false" show-icon /><ul v-if="evidence.validation.differences.length"><li v-for="(item,index) in evidence.validation.differences" :key="index">{{ describe(item) }}</li></ul><p class="muted">{{ evidence.caseId ? '本项检查需求复算 SQL 与独立核算是否一致；应用实际结果仍需在“真实结果对照与记录”中核对。' : '应用结果已留存，仍需与同条件的需求复算结果对照后记录人工判断。' }}</p><details><summary>查看当次 SQL</summary><pre>{{ evidence.testedResult.sql }}</pre></details></section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import { getRetainedVerificationEvidence, submitIndependentExpectation, getMappingRevision } from '@/api/admin/metricVerification'
import type { VerificationModuleId, MappingResultColumn, RetainedVerificationEvidence } from '@/types/metricVerification'
const props = defineProps<{ moduleId?: VerificationModuleId; executionId: string; queryId?: string; resultColumns?: MappingResultColumn[]; resultShape?: string }>()
const evidence = ref<RetainedVerificationEvidence>()
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const submissionError = ref('')
const method = ref('')
const derivation = ref('')
const resultKnown = ref(false)
const expectedEmpty = ref(false)
const columns = ref<MappingResultColumn[]>(props.resultColumns || [])
const shape = ref(props.resultShape || '')
const expectedRows = ref<Record<string, string>[]>([])
let alive = true
const expectedTableColumns = computed(() => tableColumns(evidence.value?.testedResult?.columns || columns.value))
const validationText = computed(() => ({ pending: '尚未完成独立核算', match: '本次留存范围内，独立核算与被测 SQL 一致', different: '独立核算与被测 SQL 存在差异，请核查口径和加工', inconclusive: '本次证据或核算条件不足，不能判定通过' }[evidence.value?.validation.status || 'pending']))
function tableColumns(items: MappingResultColumn[]): AppTableColumn[] { return items.map(item => ({ key: item.key, label: item.label || item.key, minWidth: 140, align: 'left' })) }
function display(value: unknown) { return value == null ? 'NULL' : typeof value === 'object' ? JSON.stringify(value) : String(value) }
function describe(value: unknown): string { if (value == null) return '未登记'; if (Array.isArray(value)) return value.map(describe).join('；'); if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}：${describe(item)}`).join('；'); return String(value) }
function time(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false }) }
function addRow() { expectedRows.value.push(Object.fromEntries(columns.value.map(column => [column.key, '']))) }
async function load() {
  loading.value = true; error.value = ''
  try {
    const data = await getRetainedVerificationEvidence(props.executionId, props.moduleId)
    if (!alive) return
    evidence.value = data
    if (!columns.value.length && data.mappingRevisionId) {
      const revision = await getMappingRevision(data.mappingRevisionId, props.moduleId)
      if (!alive) return
      const queryId = props.queryId || revision.package.validationCases?.find(item => item.id === data.caseId)?.execution.queryId
      const contract = revision.package.queries.find(query => query.id === queryId)?.resultContract
      columns.value = contract?.columns || []
      shape.value = contract?.shape || ''
    }
    if (!expectedRows.value.length && columns.value.length) addRow()
  } catch (err) { if (alive) error.value = err instanceof Error ? err.message : '留存证据读取失败' }
  finally { if (alive) loading.value = false }
}
async function submit() {
  if (!evidence.value || saving.value) return
  submissionError.value = ''
  if (!method.value.trim() || !derivation.value.trim()) { submissionError.value = '请填写独立核算方法和计算过程。'; return }
  if (!expectedEmpty.value && expectedRows.value.some(row => columns.value.some(column => !row[column.key]?.trim()))) { submissionError.value = '请填写每个预期字段；明确的空值填写 NULL。'; return }
  const rows: Record<string, unknown>[] = []
  for (const row of expectedEmpty.value ? [] : expectedRows.value) {
    const result: Record<string, unknown> = {}
    for (const column of columns.value) {
      const value = row[column.key].trim()
      if (value.toUpperCase() === 'NULL') result[column.key] = null
      else if (['integer', 'decimal', 'number', 'float', 'double'].includes(column.dataType || '')) {
        const numeric = Number(value)
        if (!Number.isFinite(numeric) || (column.dataType === 'integer' && !Number.isSafeInteger(numeric))) { submissionError.value = `${column.label || column.key}需要有效${column.dataType === 'integer' ? '整数' : '数值'}。`; return }
        result[column.key] = column.dataType === 'integer' ? numeric : value
      } else result[column.key] = value
    }
    rows.push(result)
  }
  saving.value = true
  try {
    const result = await submitIndependentExpectation(props.executionId, { method: method.value.trim(), derivation: derivation.value.trim(), rows, inputContentHash: evidence.value.integrity.contentHash, resultKnownBeforeCalculation: resultKnown.value }, props.moduleId)
    if (alive) evidence.value = result
  } catch (err) { if (alive) submissionError.value = err instanceof Error ? err.message : '提交失败，核算内容已保留' }
  finally { if (alive) saving.value = false }
}
onMounted(load)
onBeforeUnmount(() => { alive = false })
</script>

<style scoped>
.evidence-review { margin-top:16px; padding:16px; border:1px solid var(--el-border-color); border-radius:6px; min-width:0; font-size:13px; line-height:1.7; background:var(--el-bg-color); }.heading { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; } h4 { margin:0 0 10px; font-size:14px; }.muted,.scope { color:var(--el-text-color-secondary); font-size:12px; } details { margin:12px 0; } summary { cursor:pointer; color:var(--el-color-primary); } dl { display:grid; grid-template-columns:85px minmax(0,1fr); gap:8px; } dd { margin:0; overflow-wrap:anywhere; } pre { white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.7 Consolas,monospace; padding:12px; background:var(--el-fill-color-light); }.dataset,.expectation,.recorded-expectation,.tested-result { border-top:1px solid var(--el-border-color-light); padding-top:16px; margin-top:16px; }.expectation>label { display:flex; flex-direction:column; gap:6px; margin:12px 0; }.expected-row { border:1px solid var(--el-border-color-light); padding:12px; margin:12px 0; }.expected-fields { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr)); gap:12px; }.expected-fields label { display:flex; flex-direction:column; gap:6px; }.known-result { display:flex; height:auto; margin:16px 0; align-items:flex-start; }.known-result :deep(.el-checkbox__label) { white-space:normal; line-height:1.7; }.known-result :deep(.el-checkbox__input) { margin-top:5px; }.error { color:var(--el-color-danger); }.warning { color:var(--el-color-warning-dark-2); }.preserve { white-space:pre-wrap; }.tested-result .el-alert { margin-top:12px; }
</style>

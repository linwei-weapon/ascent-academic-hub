<template>
  <section class="comparison-editor" aria-label="真实结果对照">
    <h4>本次核对条件</h4>
    <p class="muted">填写实际核对的范围和时点。修改已有条件会清空之前的值和证据选择；首次补填空项不会清空。</p>
    <p v-if="comparison.expectedExecutionId" class="import-notice">复算值已从保存的SQL证据带入，保存时会再次核对。应用实际值仍需独立取得。<el-button link type="primary" :disabled="locked" @click="conditionsChanged">清除带入结果</el-button></p>
    <el-alert v-if="contextNotice" :title="contextNotice" type="info" :closable="false" />
    <div class="condition-grid">
      <label><span>组织 / 对象范围</span><el-input v-model="comparison.scope" :disabled="locked" aria-label="核对范围" placeholder="填写实际核验的组织、课程或学生范围" /></label>
      <label><span>观察期 / 学期</span><el-input v-model="comparison.period" :disabled="locked" aria-label="核对观察期" placeholder="填写实际学期；时点指标注明不适用" /></label>
      <label><span>统计截至时点</span><el-input v-model="comparison.asOf" :disabled="locked" aria-label="统计截至时点" placeholder="填写本次数据统计的截至时间" /></label>
      <label><span>数据批次 / 快照（适用时）</span><el-input v-model="comparison.dataVersion" :disabled="locked" aria-label="数据版本" placeholder="记录能够对应的数据批次或快照" /></label>
      <label><span>本次结论覆盖</span><el-select v-model="comparison.coverage" :disabled="locked" aria-label="本次结论覆盖"><el-option label="页面结果核对" value="display" /><el-option label="事实层至应用结果" value="fact_application" /><el-option label="完整三层关系" value="full_chain" /></el-select></label>
      <label><span>需求复算起点</span><el-select v-model="comparison.startLayer" :disabled="locked || !!comparison.expectedExecutionId" aria-label="需求复算起点"><el-option label="人工取得的独立依据" value="manual" /><el-option label="贴源层" value="source" /><el-option label="事实层" value="fact" /><el-option label="应用层" value="application" /></el-select></label>
    </div>
    <p class="coverage-note">{{ coverageNote }}</p>
    <div class="source-grid">
      <section><h4>应用实际值的来源</h4><label><span>真实页面 / 应用对象</span><el-input v-model="comparison.actualSource" type="textarea" :rows="2" :disabled="locked" aria-label="应用实际值来源" placeholder="记录观察页面或已证明映射的应用数据对象；事实参考查询不能作为应用实值" /></label><label><span>实际值获取时间</span><el-input v-model="comparison.actualObservedAt" :disabled="locked" aria-label="实际值获取时间" placeholder="填写真实观察时间" /></label></section>
      <section><h4>需求复算值的来源</h4><label><span>独立计算 / 查询依据</span><el-input v-model="comparison.expectedSource" type="textarea" :rows="2" :disabled="locked || !!comparison.expectedExecutionId" aria-label="需求复算来源" placeholder="记录按106及确认口径计算的来源，可引用下方真实SQL证据" /></label><label><span>复算值获取时间</span><el-input v-model="comparison.expectedObservedAt" :disabled="locked || !!comparison.expectedExecutionId" aria-label="复算值获取时间" placeholder="填写真实查询或计算时间" /></label></section>
    </div>
    <div class="section-heading"><h4>实际与需求复算对照</h4><el-button size="small" :disabled="locked" @click="addRow">添加组成值 / 比较项</el-button></div>
    <p class="muted">{{ comparisonHint }} 缺值请留空并记录“条件不足”，不填写演示值。</p>
    <article v-for="(row, index) in comparison.rows" :key="index" class="comparison-row">
      <div class="row-heading"><label><span>比较项 / 对象</span><el-input v-model="row.label" :disabled="locked || !!row.expectedKey" :aria-label="`第${index + 1}项名称`" /></label><label class="unit-field"><span>单位</span><el-input v-model="row.unit" :disabled="locked || !!row.expectedKey" :aria-label="`第${index + 1}项单位`" /></label><el-button v-if="comparison.rows.length > 1 && !row.expectedKey" link type="danger" :disabled="locked" @click="removeRow(index)">移除</el-button></div>
      <div class="value-grid"><label><span>应用实际</span><el-input v-model="row.actual" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" :disabled="locked" :aria-label="`第${index + 1}项应用实际`" placeholder="真实观察值或结果内容" /></label><label><span>需求复算</span><el-input v-model="row.expected" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" :disabled="locked || !!row.expectedKey" :aria-label="`第${index + 1}项需求复算`" placeholder="真实复算值或结果内容" /></label><div class="difference"><span>差异（实际－复算）</span><strong>{{ previewComplete ? row.difference ?? '未取得差异' : '待计算差异' }}</strong></div></div>
    </article>
    <label class="rule-field"><span>比较规则与显示精度</span><el-input v-model="comparison.comparisonRule" type="textarea" :rows="2" :disabled="locked" aria-label="比较规则" placeholder="说明单位、精度和比较方式；容差应有已确认依据" /></label>
    <div class="preview-actions"><el-button :loading="previewing" :disabled="disabled" @click="preview">计算差异</el-button><span class="muted">由核验服务计算差异，不自动生成验收判断。修改输入后需重新计算。</span></div>
    <el-alert v-if="previewError" :title="previewError" type="warning" :closable="false" show-icon />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { previewVerificationComparison } from '@/api/admin/metricVerification'
import type { VerificationModuleId, VerificationComparison, VerificationExpectedDraft, VerificationIndicatorEntry, VerificationJudgment } from '@/types/metricVerification'
const props = defineProps<{ moduleId?: VerificationModuleId; entry: VerificationIndicatorEntry; unit: string; disabled: boolean; contextRevision: number }>()
const emit = defineEmits<{ conditionsChange: [] }>()
const comparison = reactive<VerificationComparison>({ scope: '', period: '', asOf: '', dataVersion: '', coverage: 'display', startLayer: 'manual', actualSource: '', actualObservedAt: '', expectedSource: '', expectedObservedAt: '', comparisonRule: '精确一致', rows: [{ label: props.entry.name, unit: props.unit || (props.entry.comparisonKind === 'scalar' ? '' : '结果'), actual: '', expected: '' }] })
const previewing = ref(false)
const previewComplete = ref(false)
const previewError = ref('')
const contextNotice = ref('')
let previewGeneration = 0
let alive = true
let applyingDraft = false
const locked = computed(() => props.disabled || previewing.value)
const coverageNote = computed(() => comparison.coverage === 'full_chain' ? '完整三层结论须有对应层间的核对依据；没有独立来源的层说明不适用原因。' : comparison.coverage === 'fact_application' ? '本次仅核对事实输入至应用结果，不据此证明贴源到事实加工正确。' : '本次记录真实页面值与需求复算值的对照；结论仅适用于所填范围和时点。')
const comparisonHint = computed(() => ({ scalar: '必要分子、分母可分别添加为比较项，不能只核百分比。', distribution: '按档位分别填写人数、占比和总体。', ranking: '记录候选、成员及顺序，可按名次逐项填写。', series: '按真实学期逐项填写点值和变化。', collection: '记录完整成员或状态集合，不能用总数相等替代成员一致。' }[props.entry.comparisonKind]))
function snapshot(): VerificationComparison { return JSON.parse(JSON.stringify(comparison)) as VerificationComparison }
function clearDifferences() { previewComplete.value = false; previewError.value = ''; comparison.rows.forEach(row => { delete row.difference }); ++previewGeneration }
watch(() => JSON.stringify({ ...comparison, rows: comparison.rows.map(({ difference: _difference, ...row }) => row) }), clearDifferences)
function clearValues() { comparison.rows.forEach(row => { row.actual = ''; row.expected = ''; delete row.difference; delete row.expectedKey }); comparison.expectedExecutionId = null; comparison.actualSource = ''; comparison.expectedSource = ''; comparison.actualObservedAt = ''; comparison.expectedObservedAt = ''; clearDifferences() }
function conditionsChanged() { clearValues(); contextNotice.value = '核对条件已变更，请重新取得双方真实值并选择相符证据。'; emit('conditionsChange') }
watch(() => [comparison.scope, comparison.period, comparison.asOf, comparison.dataVersion], (values, previous) => {
  if (!applyingDraft && values.some((value, index) => previous[index]?.trim() && value !== previous[index])) conditionsChanged()
})
watch(() => props.contextRevision, () => { clearValues(); comparison.scope = ''; comparison.period = ''; comparison.asOf = ''; comparison.dataVersion = ''; contextNotice.value = 'SQL查询参数已变化。请重新确认核对范围、时点和双方结果。' })
function addRow() { comparison.rows.push({ label: '', unit: '', actual: '', expected: '' }) }
function removeRow(index: number) { if (!comparison.rows[index]?.expectedKey) comparison.rows.splice(index, 1) }
async function applyDraft(draft: VerificationExpectedDraft) {
  applyingDraft = true
  clearValues()
  const { parameters: _parameters, ...values } = draft
  Object.assign(comparison, values, { rows: draft.rows.map(row => ({ ...row })), asOf: '', coverage: 'display', actualSource: '', actualObservedAt: '' })
  contextNotice.value = '范围、学期、批次和复算值已带入。请补充真实统计截至时点及应用实际值；查询时间不等同业务统计截至时点。'
  await nextTick()
  applyingDraft = false
}
function validate(judgment: VerificationJudgment): string {
  if (judgment !== '符合') return ''
  const required: [string, string][] = [[comparison.scope, '核对范围'], [comparison.period, '观察期'], [comparison.asOf, '统计截至时点'], [comparison.actualSource, '应用实际来源'], [comparison.actualObservedAt, '实际值获取时间'], [comparison.expectedSource, '需求复算来源'], [comparison.expectedObservedAt, '复算值获取时间'], [comparison.comparisonRule, '比较规则']]
  const missing = required.filter(([value]) => !value.trim()).map(([, name]) => name)
  if (missing.length) return `判为符合前请补齐：${missing.join('、')}。`
  if (!comparison.rows.length || comparison.rows.some(row => !row.label.trim() || !row.unit.trim() || !row.actual.trim() || !row.expected.trim())) return '判为符合前，每个比较项均须填写名称、单位、真实应用值和需求复算值；未取得结果请记录条件不足。'
  return ''
}
async function preview() {
  previewError.value = ''
  if (!comparison.rows.length || comparison.rows.some(row => !row.label.trim() || !row.actual.trim() || !row.expected.trim())) { previewError.value = '请先填写比较项及双方真实值；未取得的数据可以保留为空并记录条件不足。'; return }
  const generation = ++previewGeneration
  previewing.value = true
  try {
    const response = await previewVerificationComparison(snapshot(), props.moduleId)
    if (!alive || generation !== previewGeneration) return
    comparison.rows.forEach((row, index) => { row.difference = response.rows[index]?.difference ?? null })
    previewComplete.value = true
  } catch (error) { if (alive && generation === previewGeneration) previewError.value = error instanceof Error ? error.message : '计算差异失败，输入内容已保留' }
  finally { if (alive) previewing.value = false }
}
defineExpose({ snapshot, validate, applyDraft })
onBeforeUnmount(() => { alive = false; ++previewGeneration })
</script>

<style scoped>
.comparison-editor { min-width:0; } h4 { font-size:14px; margin:0 0 10px; } .muted { font-size:12px; color:var(--el-text-color-secondary); line-height:1.7; }
.condition-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr)); gap:14px; margin:14px 0; }
label { display:flex; flex-direction:column; gap:6px; font-size:13px; min-width:0; } .coverage-note { font-size:12px; line-height:1.7; color:var(--el-color-warning-dark-2); }
.source-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin:20px 0; } .source-grid section { padding:14px; border:1px solid var(--el-border-color-light); border-radius:4px; } .source-grid label+label { margin-top:12px; }
.section-heading,.preview-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; } .preview-actions { justify-content:flex-start; margin:14px 0; }
.comparison-row { padding:14px; border:1px solid var(--el-border-color-light); border-radius:4px; margin:12px 0; }
.row-heading { display:flex; align-items:end; gap:12px; margin-bottom:12px; } .row-heading label:first-child { flex:1; } .unit-field { width:90px; }
.value-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(130px,.6fr); gap:12px; } .difference { display:flex; flex-direction:column; gap:10px; font-size:12px; min-width:0; } .difference strong { white-space:pre-wrap; overflow-wrap:anywhere; font-size:14px; line-height:1.7; }
.rule-field { margin-top:16px; }
@media(max-width:850px) { .source-grid,.value-grid { grid-template-columns:1fr; } .difference { padding-top:8px; } } @media(max-width:500px) { .row-heading { flex-wrap:wrap; } .row-heading label:first-child { flex:1 1 100%; } }
</style>

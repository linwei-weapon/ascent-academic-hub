<template>
  <section class="mapping-context" aria-label="映射口径与待确认问题">
    <details v-if="metric" class="mapping-details">
      <summary>查看已入库的指标口径、共用规则与加工依据</summary>
      <p v-if="metric.definition.businessPurpose">{{ metric.definition.businessPurpose }}</p>
      <dl><dt>业务含义</dt><dd>{{ metric.definition.meaning || '待明确' }}</dd><dt>计算公式</dt><dd>{{ metric.definition.formula || '待明确' }}</dd></dl>
      <ul v-if="metric.definition.components?.length"><li v-for="item in metric.definition.components" :key="item.key"><strong>{{ item.name }}</strong>：{{ item.expression || '表达式待明确' }}<span v-if="item.metricRef">（引用 {{ metricName(item.metricRef) }}）</span></li></ul>
      <section v-if="rules.length"><h4>本指标使用的共用口径</h4><article v-for="rule in rules" :key="rule.id"><strong>{{ rule.name }}</strong><ul><li v-for="(text, i) in describe(rule.definition)" :key="i">{{ text }}</li></ul></article></section>
      <p v-if="metric.definition.metricRefs?.length">依赖业务指标：{{ metric.definition.metricRefs.map(item => metricName(item.metricId)).join('、') }}</p>
      <section v-if="metric.processing?.steps.length"><h4>从输入到结果的加工</h4><ol><li v-for="step in metric.processing.steps" :key="step.id"><strong>{{ step.inputNodeIds.map(nodeName).join('、') }} → {{ nodeName(step.outputNodeId) }}</strong><p v-for="(text,index) in describe(step.description)" :key="index">{{ text }}</p><p v-if="step.physicalPredicate">筛选：{{ step.physicalPredicate }}</p><p v-if="step.join?.keys?.length">关联：{{ step.join.keys.map(item => `${item.left} = ${item.right}`).join('；') }}</p><p v-if="step.join?.snapshotCondition">{{ step.join.snapshotCondition }}</p><ul v-if="step.fieldMappings?.length"><li v-for="(field, index) in step.fieldMappings" :key="index">{{ field.from }} → {{ field.to }}<span v-if="field.expression">：{{ field.expression }}</span></li></ul></li></ol></section>
      <p v-if="metric.actualBinding?.reason" class="boundary"><strong>应用实值对应情况：</strong>{{ metric.actualBinding.reason }}</p>
      <section v-if="observations.length" class="application-observations" aria-label="已关联的应用观测">
        <h4>已保存的应用观测</h4>
        <article v-for="item in observations" :key="`${item.source.id}:${item.evidenceId}`" class="application-observation">
          <strong>{{ item.observation.metricLabel || metric.name }}</strong>
          <dl class="observation-fields">
            <dt>实值</dt><dd>{{ known(item.observation.value) }}</dd>
            <dt>单位</dt><dd>{{ known(item.observation.unit) }}</dd>
            <dt>数据性质</dt><dd>{{ dataNatureLabel(item.observation.dataNature) }}</dd>
            <dt>数据范围</dt><dd>{{ known(item.observation.filterContext?.scope) }}</dd>
            <dt>学期</dt><dd>{{ known(item.observation.filterContext?.semesterLabel) }}<span v-if="item.observation.filterContext?.semesterId">（标识：{{ item.observation.filterContext.semesterId }}）</span></dd>
            <dt>观察身份</dt><dd>{{ known(item.observation.identityContext?.activeIdentity) }} · 账号 {{ known(item.observation.identityContext?.user) }}</dd>
            <dt>观察时间</dt><dd>{{ item.observation.observedAt && item.observation.observedAtPrecision === 'approximately_minute' ? '约 ' : '' }}{{ capturedTime(item.observation.observedAt) }}</dd>
            <dt>页面载入</dt><dd>{{ capturedTime(item.observation.pageLoadedAt) }}</dd>
            <dt>业务时点</dt><dd>{{ capturedTime(item.observation.dataAsOf) }}</dd>
            <dt>页面位置</dt><dd>{{ known(item.observation.locator) }}</dd>
            <dt>来源</dt><dd><a v-if="sourceUrl(item.source.location)" :href="sourceUrl(item.source.location)" target="_blank" rel="noopener noreferrer">{{ item.source.title || item.source.location }} ↗</a><span v-else>{{ item.source.title || '未知' }}（来源链接未知）</span></dd>
          </dl>
          <div v-if="item.observation.supportingDisplay" class="supporting-display">
            <p v-if="item.observation.supportingDisplay.displayedValue != null">页面原始显示：{{ item.observation.supportingDisplay.displayedValue }}</p>
            <p v-if="item.observation.supportingDisplay.displayedCount != null">页面附带人数：{{ item.observation.supportingDisplay.displayedCount }}</p>
            <p v-if="item.observation.supportingDisplay.displayedAttemptCount != null">页面附带人次：{{ item.observation.supportingDisplay.displayedAttemptCount }}<span class="muted">（未作为计算分母）</span></p>
            <p v-if="item.observation.supportingDisplay.studentsWithGpa != null">页面显示有 GPA 学生数：{{ item.observation.supportingDisplay.studentsWithGpa }}</p>
            <table v-if="item.observation.supportingDisplay.displayedDistribution?.length" class="observation-distribution"><caption>页面显示的 GPA 分布</caption><thead><tr><th scope="col">GPA 区间</th><th scope="col">占比（%）</th></tr></thead><tbody><tr v-for="row in item.observation.supportingDisplay.displayedDistribution" :key="row.bucket"><td>{{ row.bucket }}</td><td>{{ known(row.sharePercent) }}</td></tr></tbody></table>
            <p v-if="item.observation.supportingDisplay.precision" class="muted">{{ item.observation.supportingDisplay.precision }}</p>
          </div>
          <ul v-if="item.observation.limitations?.length" class="muted"><li v-for="limit in item.observation.limitations" :key="limit">{{ limit }}</li></ul>
          <p class="muted">证据标识：{{ item.evidenceId }}</p>
        </article>
        <p class="muted">这里展示已保存的当次应用观测。范围、口径和业务时点需与 SQL 结果对应后，才能形成业务核验结论。</p>
      </section>
      <p v-else-if="metric.actualBinding?.evidenceRefs?.length" class="muted">本指标引用的应用观测尚未取得，实值与观察条件未知。</p>
      <p class="muted">定义已入库不代表本次业务核验已通过。结论以真实结果对照和保存记录为准。</p>
    </details>
    <details class="question-list"><summary>查看口径问题与答复{{ loading ? '（读取中）' : `（待确认 ${questions.filter(item => ['open','deferred'].includes(item.status)).length} 项）` }}</summary>
    <div class="question-heading"><h4>口径待确认与答复<span v-if="questions.length">（{{ questions.length }}）</span></h4><el-button size="small" :loading="loading" @click="loadQuestions">刷新问题</el-button></div>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <p v-if="!loading && !error && !questions.length" class="muted">当前指标没有登记待确认问题；这不代表数据核验已经通过。</p>
    <details v-for="question in questions" :key="question.id" class="question">
      <summary>{{ question.title }} <span class="question-status">{{ statusText(question.status) }}</span></summary>
      <p>{{ question.problem }}</p>
      <p v-if="question.affectedMetricIds?.length" class="muted">影响指标：{{ question.affectedMetricIds.map(metricName).join('、') }}</p>
      <div v-for="answer in question.answers || []" :key="answer.answerId || answer.recordedAt" class="saved-answer"><strong>已记录答复：</strong>{{ answer.rawAnswer }}<small v-if="answer.recordedAt">{{ answer.recordedAt }}</small></div>
      <form v-if="['open','deferred'].includes(question.status)" @submit.prevent="answerQuestion(question)">
        <el-radio-group v-if="question.options?.length" v-model="answers[question.id].choiceId" :disabled="savingId === question.id" :aria-label="question.title"><el-radio v-for="option in question.options" :key="option.id" :value="option.id"><strong>{{ option.label }}</strong><span v-if="option.effect"> — {{ option.effect }}</span></el-radio><el-radio v-if="question.customAnswerAllowed !== false" value="custom">填写其他意见</el-radio></el-radio-group>
        <label v-if="!question.options?.length || answers[question.id].choiceId === 'custom'"><span>口径答复</span><el-input v-model="answers[question.id].text" type="textarea" :rows="3" :disabled="savingId === question.id" aria-label="口径答复" placeholder="说明应采用的业务规则及适用范围" /></label>
        <p v-if="answers[question.id].error" class="error" role="alert">{{ answers[question.id].error }}</p>
        <el-button type="primary" native-type="submit" size="small" :loading="savingId === question.id">保存口径答复</el-button>
        <p class="muted">答复保存后，由映射 Skill 更新受影响的定义和 SQL；不会立即将指标标为已通过。</p>
      </form>
    </details>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getMappingQuestions, submitMappingAnswer } from '@/api/admin/metricVerification'
import type { VerificationModuleId, MappingPackage, MappingQuestion } from '@/types/metricVerification'
const props = defineProps<{ moduleId?: VerificationModuleId; mapping: MappingPackage; metricId: string; mappingRevisionId: string }>()
const metric = computed(() => props.mapping.metrics.find(item => item.id === props.metricId))
const rules = computed(() => (props.mapping.sharedRules || []).filter(rule => metric.value?.definition.ruleRefs?.includes(rule.id)))
const observations = computed(() => {
  const references = new Set(metric.value?.actualBinding?.evidenceRefs || [])
  return (props.mapping.sourceManifest || []).flatMap(source => (source.evidence || []).flatMap(evidence => {
    const observation = evidence.metricObservation
    return references.has(evidence.id) && observation?.metricId === props.metricId ? [{ source, evidenceId: evidence.id, observation }] : []
  }))
})
const questions = ref<MappingQuestion[]>([])
const answers = reactive<Record<string, { choiceId: string; text: string; error: string; submissionId: string; contextHash: string }>>({})
const loading = ref(false)
const error = ref('')
const savingId = ref('')
let alive = true
function metricName(id: string) { return props.mapping.metrics.find(item => item.id === id)?.name || id }
function nodeName(id: string) { return metric.value?.lineage?.nodes.find(node => node.id === id)?.logicalName || id }
function known(value: unknown): string {
  if (value == null || value === '') return '未知'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
function capturedTime(value?: string | null) { return value ? value.replace('T', ' ') : '未知' }
function dataNatureLabel(value?: string | null) { return ({ real: '真实系统观测', derived: '推导数据', demo: '演示数据', synthetic: '构造样例' } as Record<string, string>)[value || ''] || '未知' }
function sourceUrl(value?: string | null) {
  if (!value) return undefined
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined } catch { return undefined }
}
function statusText(status: string) { return ({ open: '待确认', answered: '已答复，待应用', deferred: '待补充条件', resolved: '已应用', superseded: '已被后续口径替代' } as Record<string, string>)[status] || status }
function newAnswer(question: MappingQuestion) { return { choiceId: '', text: '', error: '', submissionId: crypto.randomUUID(), contextHash: question.contextHash } }
function describe(value: unknown): string[] {
  if (value == null) return []
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return [String(value)]
  if (Array.isArray(value)) return value.flatMap(describe)
  return Object.values(value as Record<string, unknown>).flatMap(describe)
}
async function loadQuestions() {
  if (savingId.value) return
  loading.value = true; error.value = ''
  try {
    const result = await getMappingQuestions(props.mappingRevisionId, props.moduleId)
    if (!alive) return
    questions.value = result.items.filter(question => !question.affectedMetricIds?.length || question.affectedMetricIds.includes(props.metricId))
    for (const question of questions.value) if (answers[question.id]?.contextHash !== question.contextHash) answers[question.id] = newAnswer(question)
  } catch (err) { if (alive) error.value = err instanceof Error ? err.message : '读取问题失败' }
  finally { if (alive) loading.value = false }
}
async function answerQuestion(question: MappingQuestion) {
  const answer = answers[question.id]
  const option = question.options?.find(item => item.id === answer.choiceId)
  const rawAnswer = option ? option.label : answer.text.trim()
  answer.error = ''
  if (!rawAnswer) { answer.error = '请选择一个口径或填写答复。'; return }
  if (!question.contextHash) { answer.error = '问题版本尚未取得，请刷新后再答复。'; return }
  savingId.value = question.id
  try {
    await submitMappingAnswer(question.id, { submissionId: answer.submissionId, questionContextHash: question.contextHash, rawAnswer, choiceId: option?.id || null, customAnswer: option ? null : rawAnswer, scope: question.affectedMetricIds?.join(',') || props.metricId, opinionSourceRef: '指标核验：当前登录用户提交' }, props.moduleId)
    if (!alive) return
    savingId.value = ''
    answers[question.id] = newAnswer(question)
    ElMessage.success('答复已保存，待更新指标定义和 SQL 后生效')
    await loadQuestions()
  } catch (err) { if (alive) answer.error = err instanceof Error ? err.message : '答复保存失败，内容已保留' }
  finally { if (alive) savingId.value = '' }
}
onMounted(loadQuestions)
onBeforeUnmount(() => { alive = false })
</script>

<style scoped>
.application-observation { margin:8px 0; padding:12px; border:1px solid var(--el-border-color-lighter); border-radius:6px; background:var(--el-fill-color-blank); }
.observation-fields { grid-template-columns:85px minmax(0,1fr); }.observation-fields dt { color:var(--el-text-color-secondary); }.observation-fields a { color:var(--el-color-primary); }.supporting-display p { margin:6px 0; }.observation-distribution { width:100%; max-width:440px; border-collapse:collapse; margin:8px 0; }.observation-distribution caption { text-align:left; font-weight:600; padding-bottom:4px; }.observation-distribution th,.observation-distribution td { border:1px solid var(--el-border-color-lighter); padding:4px 10px; text-align:left; }
.mapping-context { margin-top:16px; border-top:1px solid var(--el-border-color-light); padding-top:12px; font-size:13px; line-height:1.7; } summary { cursor:pointer; color:var(--el-color-primary); } h4 { font-size:13px; margin:12px 0 8px; } .question-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; }.question { padding:12px 0; border-top:1px solid var(--el-border-color-lighter); } .question-status,.muted { color:var(--el-text-color-secondary); font-size:12px; }.question-status { margin-left:8px; }.boundary { color:var(--el-color-warning-dark-2); } dl { display:grid; grid-template-columns:75px minmax(0,1fr); gap:8px; } dd { margin:0; overflow-wrap:anywhere; } li { margin:6px 0; overflow-wrap:anywhere; }.question :deep(.el-radio-group) { display:flex; flex-direction:column; align-items:stretch; gap:8px; margin-bottom:14px; }.question :deep(.el-radio) { white-space:normal; height:auto; align-items:flex-start; margin:0; }.question :deep(.el-radio__input) { margin-top:5px; }.question :deep(.el-radio__label) { white-space:normal; line-height:1.7; }.question label { display:flex; flex-direction:column; gap:6px; margin-bottom:12px; }.saved-answer { padding:8px 12px; background:var(--el-fill-color-light); white-space:pre-wrap; margin:8px 0; }.saved-answer small { display:block; color:var(--el-text-color-secondary); }.error { color:var(--el-color-danger); }
</style>

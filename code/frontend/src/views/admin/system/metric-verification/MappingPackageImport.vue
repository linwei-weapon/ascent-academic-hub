<template>
  <el-dialog :model-value="true" title="导入指标映射包" width="760px" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="closeDialog">
    <p class="intro">当前模块：<strong>{{ moduleName }}</strong>。选择 Skill 输出的 JSON，核对摘要后保存草稿，再单独生效。</p>
    <label class="file-field"><span>映射包 JSON 文件</span><input type="file" accept=".json,application/json" :disabled="busy || !canManage" aria-label="选择指标映射包 JSON 文件" @change="chooseFile" /></label>
    <p v-if="fileName" class="muted">已选择：{{ fileName }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="!canManage" title="当前身份没有映射管理权限。" type="warning" :closable="false" />
    <div class="head-row"><span>当前生效版本：{{ head ? head.revisionId || '尚无生效映射' : '未读取' }}</span><el-button size="small" :disabled="busy" @click="refreshState">读取实际状态</el-button></div>
    <template v-if="candidate">
      <el-descriptions :column="2" border size="small" class="summary">
        <el-descriptions-item label="模块">{{ candidate.moduleName || moduleName }}（{{ candidate.moduleId }}）</el-descriptions-item>
        <el-descriptions-item label="项目 / 环境">{{ candidate.projectId }} / {{ candidate.environmentId }}</el-descriptions-item>
        <el-descriptions-item label="包 ID" :span="2">{{ candidate.packageId }}</el-descriptions-item>
        <el-descriptions-item label="业务指标">{{ candidate.metrics.length }} 个</el-descriptions-item>
        <el-descriptions-item label="SQL">{{ sqlCount }} 条（{{ candidate.queries.length }} 个查询项）</el-descriptions-item>
        <el-descriptions-item label="包的基线版本" :span="2">{{ candidate.baseRevisionId || '首次建立（无基线版本）' }}</el-descriptions-item>
      </el-descriptions>
      <div class="metric-tags" aria-label="包内业务指标"><el-tag v-for="metric in candidate.metrics" :key="metric.id" effect="plain">{{ metric.id }} · {{ metric.name }}</el-tag></div>
      <el-alert v-if="scopeProblem" :title="scopeProblem" type="error" :closable="false" />
      <el-alert v-else-if="baseConflict" title="包的基线与当前生效版本不同。保留原包，由服务检查是否已有相同草稿；不会覆盖其他更新。需要更新时请用 Skill 重新组包。" type="warning" :closable="false" />
      <p v-if="deliveryMode === 'analyze_only'" class="boundary">此包只供分析，不能保存或生效。请由 Skill 输出交付模式为 save_draft 或 activate 的完整包。</p>
      <p v-else-if="deliveryMode === 'save_draft'" class="boundary">此包只允许保存草稿。生效需由 Skill 输出交付模式为 activate 的包。</p>
      <p v-if="candidate.pendingAnswers?.length" class="boundary">有 {{ candidate.pendingAnswers.length }} 条离线答复尚未同步落实，可保存草稿，不能生效。请由 Skill 继续处理。</p>
    </template>
    <section v-if="savedRevision" class="stored-result" aria-label="数据库回读结果">
      <el-alert v-if="activeVerified" title="映射已生效，已回读确认当前版本。" :description="moduleId === 'ai-briefing' ? '指标定义与页面绑定也已由实际登记接口确认。' : '指标清单将使用此映射版本。'" type="success" :closable="false" show-icon />
      <el-alert v-else :title="activationNeedsCheck ? '生效状态尚未确认，请读取实际状态。' : '草稿已保存并回读确认，尚未确认生效。'" type="info" :closable="false" show-icon />
      <p>保存版本：<code>{{ savedRevision.revisionId }}</code><br />内容摘要：<code>{{ savedRevision.packageHash }}</code></p>
      <ul v-if="savedRevision.validation?.warnings?.length" class="boundary"><li v-for="(warning, index) in savedRevision.validation.warnings" :key="index">{{ warning.message }}{{ warning.blocksActivation ? '（阻止生效）' : '' }}</li></ul>
      <el-table v-if="registration" :data="registration.metrics" size="small" border aria-label="实际指标登记状态">
        <el-table-column prop="metricCode" label="指标" width="110" /><el-table-column prop="version" label="版本" min-width="120" /><el-table-column prop="definitionStatus" label="定义状态" width="115" />
        <el-table-column label="指标与页面绑定" min-width="150"><template #default="{ row }">{{ row.registered && row.enabled ? '已确认' : '未确认' }}</template></el-table-column>
      </el-table>
    </section>
    <p class="muted boundary">保存和生效只维护指标映射与登记，不执行包内 SQL。生效不代表业务核验通过，仍需在指标工作区核对数据与结果。</p>
    <template #footer>
      <div class="footer-actions"><el-button :disabled="busy" @click="closeDialog">{{ savedRevision ? '关闭' : '取消' }}</el-button><el-button :disabled="!canSave" :loading="operation === 'saving'" @click="saveDraft">保存草稿</el-button><el-button type="primary" :disabled="!canActivate" :loading="operation === 'activating'" @click="activateDraft">激活生效</el-button></div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { activateMappingRevision, getMappingHead, getMappingRegistration, getMappingRevision, saveMappingPackage } from '@/api/admin/metricVerification'
import type { MappingHead, MappingPackage, MappingRegistration, MappingRevision, VerificationModuleId } from '@/types/metricVerification'

const props = defineProps<{ moduleId: VerificationModuleId; canManage: boolean }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const candidate = ref<MappingPackage>()
const fileName = ref('')
const head = ref<MappingHead>()
const savedRevision = ref<MappingRevision>()
const registration = ref<MappingRegistration>()
const activeVerified = ref(false)
const activationNeedsCheck = ref(false)
const error = ref('')
const operation = ref<'reading' | 'saving' | 'activating' | null>(null)
const busy = computed(() => operation.value !== null)
const moduleName = computed(() => props.moduleId === 'ai-briefing' ? 'AI简报' : '教学数据总览')
const sqlCount = computed(() => candidate.value?.queries.filter(query => typeof query.sql === 'string' && query.sql.trim()).length || 0)
const deliveryMode = computed(() => candidate.value?.inputManifest?.delivery?.mode)
const scopeProblem = computed(() => {
  if (!head.value || !candidate.value) return ''
  if (head.value.projectId !== candidate.value.projectId || head.value.environmentId !== candidate.value.environmentId) return '包的项目或环境与服务配置不同，不能导入。请由 Skill 按实际环境重新组包。'
  if (head.value.legacyReason === 'database_not_configured' || head.value.legacyReason === 'explicit_legacy_mode') return '当前服务未启用数据库映射存储，不能保存或生效。'
  return ''
})
const baseConflict = computed(() => !!candidate.value && !!head.value && candidate.value.baseRevisionId !== head.value.revisionId && savedRevision.value?.revisionId !== head.value.revisionId)
const canSave = computed(() => props.canManage && !busy.value && !!candidate.value && !!head.value && !scopeProblem.value && !savedRevision.value && ['save_draft', 'activate'].includes(deliveryMode.value || ''))
const canActivate = computed(() => props.canManage && !busy.value && !!savedRevision.value && !!head.value && !scopeProblem.value && !baseConflict.value && !activeVerified.value && !activationNeedsCheck.value && deliveryMode.value === 'activate' && !candidate.value?.pendingAnswers?.length && !savedRevision.value.validation?.warnings?.some(warning => warning.blocksActivation))
let alive = true
let fileGeneration = 0
let savedRevisionId = ''

function message(value: unknown) { return value instanceof Error ? value.message : '请求未完成' }
function closeDialog() { if (!busy.value) emit('close') }
function object(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) }
function canonical(value: unknown): string {
  if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('映射包不能包含非有限数值。')
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (object(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`
  return JSON.stringify(value)
}
function parsePackage(content: string): MappingPackage {
  const value: unknown = JSON.parse(content.replace(/^\uFEFF/, ''))
  if (!object(value)) throw new Error('JSON 根节点必须是一个完整映射包对象。')
  if (value.moduleId !== props.moduleId) throw new Error(`包所属模块为 ${String(value.moduleId || '未填写')}，与当前 ${moduleName.value} 不一致。请关闭窗口后选择对应模块。`)
  if (value.schemaVersion !== '3.1.0' || value.template !== false) throw new Error('请导入 3.1.0 版本的完整输出包，不能导入模板。')
  for (const key of ['packageId', 'analysisId', 'projectId', 'environmentId']) if (typeof value[key] !== 'string' || !value[key].trim()) throw new Error(`映射包缺少 ${key}。`)
  if (value.baseRevisionId !== null && (typeof value.baseRevisionId !== 'string' || !value.baseRevisionId)) throw new Error('映射包必须明确 baseRevisionId，首次建立请使用 null。')
  if (!Array.isArray(value.metrics) || !value.metrics.length || value.metrics.some(metric => !object(metric) || typeof metric.id !== 'string' || typeof metric.name !== 'string')) throw new Error('映射包的业务指标清单不完整。')
  if (!Array.isArray(value.queries) || value.queries.some(query => !object(query) || typeof query.id !== 'string' || typeof query.metricId !== 'string')) throw new Error('映射包的查询清单不完整。')
  if (!object(value.inputManifest) || !object(value.inputManifest.delivery) || !['analyze_only', 'save_draft', 'activate'].includes(String(value.inputManifest.delivery.mode))) throw new Error('映射包缺少有效交付模式 inputManifest.delivery.mode。')
  if (value.pendingAnswers !== undefined && !Array.isArray(value.pendingAnswers)) throw new Error('pendingAnswers 必须是数组。')
  canonical(value) // Reject non-finite JSON numbers; keep the user's package unchanged.
  return value as unknown as MappingPackage
}
function assertHead(value: MappingHead) {
  if (value.moduleId !== props.moduleId) throw new Error('服务返回的模块作用域不一致，已停止操作。')
}
async function readHead() {
  const value = await getMappingHead(props.moduleId)
  assertHead(value)
  if (alive) head.value = value
}
async function chooseFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || busy.value || !props.canManage) return
  const generation = ++fileGeneration
  fileName.value = file.name; candidate.value = undefined; savedRevision.value = undefined; savedRevisionId = ''
  registration.value = undefined; activeVerified.value = false; activationNeedsCheck.value = false; error.value = ''; operation.value = 'reading'
  try {
    if (file.size > 12 * 1024 * 1024) throw new Error('文件超过 12MiB，请由 Skill 导出较小的完整包；样本应留在受控证据记录中。')
    const parsed = parsePackage(await file.text())
    if (!alive || generation !== fileGeneration) return
    candidate.value = parsed
    head.value = undefined
    await readHead()
  } catch (value) { if (alive && generation === fileGeneration) error.value = `文件尚未就绪：${message(value)}` }
  finally { if (alive && generation === fileGeneration) operation.value = null }
}
async function readStoredState() {
  if (!savedRevisionId || !candidate.value) { await readHead(); return }
  const [currentHead, revision] = await Promise.all([getMappingHead(props.moduleId), getMappingRevision(savedRevisionId, props.moduleId)])
  assertHead(currentHead)
  if (revision.revisionId !== savedRevisionId || !revision.packageHash || canonical(revision.package) !== canonical(candidate.value)) throw new Error('保存版本与所选包的内容回读不一致，不能继续生效。')
  if (!alive) return
  head.value = currentHead; savedRevision.value = revision; activeVerified.value = false
  registration.value = undefined
  if (currentHead.revisionId !== revision.revisionId || revision.current !== true) { activationNeedsCheck.value = false; return }
  activationNeedsCheck.value = true
  if (props.moduleId === 'ai-briefing') {
    const actual = await getMappingRegistration(revision.revisionId, props.moduleId)
    if (!alive) return
    registration.value = actual
    const ids = new Set(revision.package.metrics.map(metric => metric.id))
    if (!actual.registered || !actual.mappingRef.current || actual.mappingRef.moduleId !== props.moduleId || actual.mappingRef.revisionId !== revision.revisionId || actual.mappingRef.packageHash !== revision.packageHash || actual.metrics.length !== ids.size || actual.metrics.some(metric => !ids.delete(metric.metricCode) || !metric.registered || !metric.enabled) || ids.size) throw new Error('当前版本已更新，但指标定义与页面绑定尚未全部回读确认。')
  }
  activeVerified.value = true; activationNeedsCheck.value = false; emit('changed')
}
async function refreshState() {
  if (busy.value) return
  operation.value = 'reading'; error.value = ''
  try { await readStoredState() }
  catch (value) { if (alive) error.value = `实际状态未核实：${message(value)}` }
  finally { if (alive) operation.value = null }
}
async function saveDraft() {
  if (!canSave.value || !candidate.value) return
  operation.value = 'saving'; error.value = ''
  try {
    const saved = await saveMappingPackage(candidate.value, props.moduleId)
    if (!alive) return
    if (!saved.revisionId) throw new Error('服务未返回保存版本。')
    savedRevisionId = saved.revisionId
    await readStoredState()
  } catch (value) { if (alive) error.value = `${savedRevisionId ? '保存已返回版本，回读尚未确认' : '保存未确认'}：${message(value)}。所选文件与基线保留，可读取实际状态或重试。` }
  finally { if (alive) operation.value = null }
}
async function activateDraft() {
  if (!canActivate.value || !savedRevision.value || !candidate.value) return
  operation.value = 'activating'; error.value = ''; activationNeedsCheck.value = true
  try {
    const result = await activateMappingRevision({ revisionId: savedRevision.value.revisionId, expectedHeadRevisionId: candidate.value.baseRevisionId ?? null }, props.moduleId)
    if (!alive) return
    if (result.state !== 'active' || result.revisionId !== savedRevisionId) throw new Error('服务未返回所选草稿的生效结果。')
    await readStoredState()
    if (!activeVerified.value) throw new Error('回读时该草稿不是当前生效版本，可能已有其他更新。')
  } catch (value) { if (alive) error.value = `生效未确认：${message(value)}。请读取实际状态，草稿与原基线保留。` }
  finally { if (alive) operation.value = null }
}
onMounted(refreshState)
onBeforeUnmount(() => { alive = false; ++fileGeneration })
</script>

<style scoped>
.intro { margin:0 0 16px; line-height:1.6; }.file-field { display:flex; flex-direction:column; gap:8px; font-weight:500; }.file-field input { max-width:100%; font-weight:400; }
.muted { color:var(--el-text-color-secondary); font-size:12px; }.head-row { display:flex; justify-content:space-between; align-items:center; gap:12px; margin:16px 0; font-size:12px; overflow-wrap:anywhere; }
.summary { overflow-wrap:anywhere; }.metric-tags { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0; }.metric-tags .el-tag { height:auto; white-space:normal; line-height:1.7; }
.boundary { line-height:1.7; margin:12px 0; }.stored-result { margin-top:18px; }.stored-result p { font-size:12px; line-height:1.8; }code { overflow-wrap:anywhere; }.footer-actions { display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; }.footer-actions .el-button + .el-button { margin-left:0; }
@media(max-width:600px) { .head-row { align-items:flex-start; flex-direction:column; } }
</style>

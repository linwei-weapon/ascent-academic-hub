<template>
  <el-drawer
    :model-value="modelValue"
    :title="`${student.name || context?.studentName || ''}｜学生学业证据`"
    size="920px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="student-evidence">
      <el-alert v-if="loadError" type="error" :closable="false" show-icon title="学生学业证据加载失败">
        <template #default>
          <span>{{ loadError }}</span>
          <el-button link type="primary" @click="load">重新加载</el-button>
        </template>
      </el-alert>

      <div v-if="loading" class="drawer-loading" aria-live="polite">
        <el-skeleton :rows="9" animated />
        <p>正在加载成绩、课程有效结果、培养方案进度和预警记录，请稍候…</p>
      </div>

      <template v-else-if="student.code">
        <section class="attention-callout">
          <div>
            <span>为什么现在看</span>
            <b>{{ reasonText }}</b>
            <p>{{ contextSummary }}</p>
          </div>
          <el-tag v-if="context?.ruleVersion" size="small" effect="plain">
            规则 {{ context.ruleVersion }}
          </el-tag>
        </section>

        <el-descriptions :column="4" border size="small" class="identity-block">
          <el-descriptions-item label="学号">{{ student.code }}</el-descriptions-item>
          <el-descriptions-item label="学院">{{ student.collegeName || '—' }}</el-descriptions-item>
          <el-descriptions-item label="专业">{{ student.majorName || '—' }}</el-descriptions-item>
          <el-descriptions-item label="班级">{{ student.className || '—' }}</el-descriptions-item>
        </el-descriptions>

        <div class="evidence-kpis">
          <KpiCard label="当前GPA" :value="currentGpaText" hint="最新有成绩学期的学分加权GPA" :tone="currentGpaTone" />
          <KpiCard label="当前未解决课程" :value="`${currentFailures.length}门`"
            hint="历史曾未通过且最新有效修读结果仍未通过" :tone="currentFailures.length ? 'danger' : 'teal'" />
          <KpiCard label="重复未解决课程" :value="`${repeatedFailures.length}门`"
            hint="同一课程至少两次未通过且最新有效结果仍未通过" :tone="repeatedFailures.length ? 'danger' : 'teal'" />
          <KpiCard label="当前有效预警" :value="`${activeAlerts.length}件`"
            hint="当前仍有效的规则命中；核查状态与风险状态分别记录" :tone="activeAlerts.length ? 'amber' : 'teal'" />
        </div>

        <el-tabs v-model="activeTab" class="evidence-tabs">
          <el-tab-pane label="变化与方案进度" name="summary">
            <div v-if="hasContextChange" class="change-grid">
              <div>
                <span>GPA变化</span>
                <b>{{ valueText(context?.fromGpa) }} → {{ valueText(context?.toGpa) }}</b>
                <small :class="deltaClass(context?.gpaDelta)">{{ signed(context?.gpaDelta) }}</small>
              </div>
              <div>
                <span>未通过课程变化</span>
                <b>{{ valueText(context?.fromFailCount, 0) }} → {{ valueText(context?.toFailCount, 0) }}门</b>
                <small :class="failDeltaClass(context?.failDelta)">{{ signed(context?.failDelta) }}</small>
              </div>
            </div>

            <section class="section-card">
              <div class="section-head">
                <div>
                  <h4>相邻学期学业变化</h4>
                  <p>GPA和未通过课程均来自同一学期的有效成绩记录。</p>
                </div>
              </div>
              <DataTable
                :columns="semesterColumns"
                :data="semesterRows"
                storage-key="student-evidence:semesters"
                :max-business-columns="5"
                :config-version="1"
                size="small"
              />
              <el-empty v-if="!semesterRows.length" description="暂无可比较的学期成绩证据" :image-size="64" />
            </section>

            <section class="section-card">
              <div class="section-head">
                <div>
                  <h4>培养方案进度证据</h4>
                  <p>{{ curriculum.statusLabel }}</p>
                </div>
                <el-tag :type="curriculum.status === 'matched' ? 'success' : 'warning'" size="small">
                  {{ curriculum.planName || '方案待匹配' }}
                </el-tag>
              </div>
              <div v-if="curriculum.status === 'matched'" class="curriculum-grid">
                <div><span>完成模块</span><b>{{ curriculum.completedModules }}/{{ curriculum.assessableModules }}</b></div>
                <div><span>规则证据覆盖</span><b>{{ pctText(curriculum.ruleCoverageRate) }}</b></div>
                <div><span>明确缺口模块</span><b>{{ curriculum.explicitGapModules }}个</b></div>
                <div><span>待核验候选模块</span><b>{{ curriculum.candidateModules }}个</b></div>
              </div>
              <el-alert
                type="info"
                :closable="false"
                show-icon
                title="培养方案证据边界"
                :description="curriculum.boundary"
              />
            </section>
          </el-tab-pane>

          <el-tab-pane :label="`课程证据 (${failureTrace.length})`" name="courses">
            <div class="failure-switch">
              <button :class="{ active: failureView === 'current' }" @click="failureView = 'current'">
                当前未解决 <b>{{ currentFailures.length }}</b>
              </button>
              <button :class="{ active: failureView === 'repeated' }" @click="failureView = 'repeated'">
                重复未解决 <b>{{ repeatedFailures.length }}</b>
              </button>
              <button :class="{ active: failureView === 'resolved' }" @click="failureView = 'resolved'">
                历史已解决 <b>{{ resolvedFailures.length }}</b>
              </button>
            </div>
            <el-alert
              type="info" :closable="false" show-icon class="course-boundary"
              title="状态按课程最新有效修读结果判断"
              description="“历史已解决”只作为成长轨迹证据，不继续计入当前未解决风险；“重复未解决”是当前未解决课程的高优先子集。"
            />
            <DataTable
              :columns="failureColumns"
              :data="visibleFailures"
              storage-key="student-evidence:failures"
              :max-business-columns="5"
              :config-version="1"
              size="small"
            >
              <template #col-status="{ row }">
                <el-tag size="small" :type="row.repeatedUnresolved ? 'danger' : row.status === '历史已解决' ? 'success' : 'warning'">
                  {{ row.repeatedUnresolved ? '重复未解决' : row.status }}
                </el-tag>
              </template>
              <template #col-semesters="{ row }">{{ (row.semesters || []).join('、') }}</template>
            </DataTable>
            <el-empty v-if="!visibleFailures.length" :description="failureEmptyText" :image-size="64" />
          </el-tab-pane>

          <el-tab-pane :label="`预警与核查记录 (${alertHistory.length})`" name="alerts">
            <el-alert
              type="info" :closable="false" show-icon class="alert-boundary"
              title="预警状态与人工核查状态分别记录"
              description="当前规则不再命中，不会删除历史预警；已有核查记录，也不代表风险信号已经消失。"
            />
            <DataTable
              :columns="alertColumns"
              :data="alertHistory"
              storage-key="student-evidence:alerts"
              :max-business-columns="5"
              :config-version="1"
              size="small"
            >
              <template #col-active="{ row }">
                <el-tag size="small" :type="row.active ? 'danger' : 'info'">{{ row.active ? '当前有效' : '历史记录' }}</el-tag>
              </template>
            </DataTable>
            <el-empty v-if="!alertHistory.length" description="暂无预警记录" :image-size="64" />

            <div v-if="interventions.length" class="intervention-list">
              <h4>人工核查与跟进轨迹</h4>
              <div v-for="(item, index) in interventions" :key="`${item.kind}-${index}-${item.time}`">
                <b>{{ item.title }}</b>
                <span>{{ item.time || '—' }}</span>
                <p>{{ item.detail || '未填写说明' }}</p>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>

        <el-alert
          type="info" :closable="false" show-icon title="数据来源与适用边界"
          :description="evidenceDescription"
        />

        <div class="drawer-actions">
          <el-button v-if="aiEligible" type="primary" plain @click="emit('ai', student)">按需查看AI管理研判</el-button>
          <el-button type="primary" @click="openFullProfile">打开完整学生档案</el-button>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http } from '@/utils/http'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import KpiCard from '@/components/KpiCard.vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  studentId?: string
  context?: Record<string, any>
  aiEligible?: boolean
}>(), {
  studentId: '',
  context: () => ({}),
  aiEligible: false,
})
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'ai', student: any): void
}>()

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const loadError = ref('')
const student = ref<any>({})
const activeTab = ref('summary')
const failureView = ref<'current' | 'repeated' | 'resolved'>('current')
let requestSequence = 0

const semesterColumns: DataTableColumn[] = [
  { key: 'semester', label: '学期', width: 150, fixed: 'left', region: 'identity', required: true },
  { key: 'gpa', label: '学分加权GPA', width: 120, align: 'right', required: true },
  { key: 'gpaDeltaText', label: '较前一学期', width: 110, align: 'right' },
  { key: 'failCount', label: '未通过课程', width: 110, align: 'right', required: true },
  { key: 'failDeltaText', label: '较前一学期', width: 110, align: 'right' },
  { key: 'earnedCredits', label: '本学期获得学分', width: 130, align: 'right' },
]
const failureColumns: DataTableColumn[] = [
  { key: 'courseName', label: '课程', minWidth: 190, fixed: 'left', region: 'identity', required: true },
  { key: 'status', label: '当前状态', width: 112, required: true },
  { key: 'failCount', label: '未通过次数', width: 105, align: 'right', required: true },
  { key: 'semesters', label: '发生学期', minWidth: 180 },
  { key: 'teacherName', label: '授课教师', width: 110 },
  { key: 'college', label: '开课单位', minWidth: 150 },
]
const alertColumns: DataTableColumn[] = [
  { key: 'time', label: '生成时间', width: 150, fixed: 'left', region: 'identity', required: true },
  { key: 'active', label: '风险状态', width: 100, required: true },
  { key: 'level', label: '等级', width: 76 },
  { key: 'type', label: '预警类型', minWidth: 130 },
  { key: 'changeType', label: '与上次相比', width: 105 },
  { key: 'workflowStatusLabel', label: '核查状态', width: 110 },
  { key: 'detail', label: '触发证据', minWidth: 220, tooltip: true },
]

const failureTrace = computed(() => student.value.failTrace || [])
const currentFailures = computed(() => failureTrace.value.filter((row: any) => row.status === '当前未解决'))
const repeatedFailures = computed(() => currentFailures.value.filter((row: any) => row.repeatedUnresolved))
const resolvedFailures = computed(() => failureTrace.value.filter((row: any) => row.status === '历史已解决'))
const visibleFailures = computed(() => (
  failureView.value === 'current' ? currentFailures.value
    : failureView.value === 'repeated' ? repeatedFailures.value
      : resolvedFailures.value
))
const failureEmptyText = computed(() => (
  failureView.value === 'current' ? '当前没有未解决课程'
    : failureView.value === 'repeated' ? '当前没有重复未解决课程'
      : '暂无历史已解决课程'
))
const alertHistory = computed(() => student.value.alertHistory || [])
const activeAlerts = computed(() => alertHistory.value.filter((row: any) => row.active))
const curriculum = computed(() => student.value.curriculumProgress || {
  status: 'unavailable',
  statusLabel: '培养方案进度暂不可正式计算',
  boundary: '当前未接入可信的结构化培养方案进度摘要。',
})
const latestSemester = computed(() => {
  const rows = student.value.semesterSummary || []
  return rows[rows.length - 1] || null
})
const currentGpaText = computed(() => latestSemester.value?.gpa == null ? '—' : Number(latestSemester.value.gpa).toFixed(2))
const currentGpaTone = computed<'teal' | 'amber' | 'danger'>(() => {
  const gpa = latestSemester.value?.gpa
  if (gpa == null) return 'amber'
  return gpa >= 3 ? 'teal' : gpa < 2 ? 'danger' : 'amber'
})
const semesterRows = computed(() => {
  const rows = (student.value.semesterSummary || []).map((row: any, index: number, all: any[]) => {
    const previous = index ? all[index - 1] : null
    const gpaDelta = previous ? Number(row.gpa || 0) - Number(previous.gpa || 0) : null
    const failDelta = previous ? Number(row.failCount || 0) - Number(previous.failCount || 0) : null
    return {
      ...row,
      gpa: row.gpa == null ? '—' : Number(row.gpa).toFixed(2),
      gpaDeltaText: gpaDelta == null ? '—' : signed(Math.round(gpaDelta * 100) / 100),
      failDeltaText: failDelta == null ? '—' : signed(failDelta),
    }
  })
  return rows.reverse()
})
const interventions = computed(() => {
  const followups = (student.value.interventionHistory || []).map((row: any) => ({
    kind: 'followup',
    title: `${row.operator || '管理人员'} · ${row.action_type || '核查记录'}`,
    time: row.created_at,
    detail: row.content,
  }))
  const statuses = (student.value.alertStatusHistory || []).map((row: any) => ({
    kind: 'status',
    title: `${row.operator || '管理人员'} · ${row.fromStatusLabel || '—'} → ${row.toStatusLabel || '—'}`,
    time: row.changed_at,
    detail: row.reason,
  }))
  return [...followups, ...statuses].sort((a, b) => String(b.time || '').localeCompare(String(a.time || '')))
})
const reasonText = computed(() => {
  const reasons = props.context?.reasons || []
  return reasons.length ? reasons.join('、') : '当前管理范围内主动核查'
})
const contextSummary = computed(() => {
  const period = props.context?.period ? `证据周期 ${props.context.period}` : '使用当前可用学业证据'
  return `${period}；先核查事实，再形成管理判断。`
})
const hasContextChange = computed(() => (
  props.context?.fromGpa != null || props.context?.toGpa != null
  || props.context?.fromFailCount != null || props.context?.toFailCount != null
))
const sourceText = computed(() => {
  const sources = student.value.evidence?.sources || []
  return sources.length ? `数据来源：${sources.join('、')}` : '数据来源待披露'
})
const evidenceDescription = computed(() => {
  const version = props.context?.ruleVersion || student.value.evidence?.ruleVersion || '未标注'
  const calculatedAt = student.value.evidence?.calculatedAt || curriculum.value?.calculatedAt
  const freshness = calculatedAt
    ? `方案进度计算时间：${String(calculatedAt).replace('T', ' ').slice(0, 16)}`
    : '更新时间：随当前页面请求读取最新可用数据'
  return [
    sourceText.value,
    `规则版本：${version}`,
    freshness,
    student.value.evidence?.boundary || '',
    props.context?.boundary || '',
  ].filter(Boolean).join('；')
})

function valueText(value: any, fallback: any = '—') { return value == null ? fallback : value }
function signed(value: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}` }
function pctText(value: number | null) { return value == null ? '—' : `${value}%` }
function deltaClass(value: number | null) { return value == null ? '' : value <= -0.3 ? 'delta-bad' : value >= 0.3 ? 'delta-good' : '' }
function failDeltaClass(value: number | null) { return value == null ? '' : value > 0 ? 'delta-bad' : value < 0 ? 'delta-good' : '' }

async function load() {
  if (!props.modelValue || !props.studentId) return
  const sequence = ++requestSequence
  loading.value = true
  loadError.value = ''
  activeTab.value = 'summary'
  failureView.value = 'current'
  student.value = { code: props.studentId, name: props.context?.studentName || '' }
  try {
    const data = await http.get<any>(`/admin/student/${encodeURIComponent(props.studentId)}`)
    if (sequence === requestSequence) student.value = data || student.value
  } catch (error: any) {
    if (sequence === requestSequence) loadError.value = error?.message || '请稍后重试'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

function openFullProfile() {
  if (!student.value.code) return
  const returnQuery = {
    ...(props.context?.returnQuery || route.query),
    scrollY: String(Math.round(window.scrollY)),
  }
  const returnTo = router.resolve({
    path: route.path,
    query: returnQuery,
  }).fullPath
  router.push({
    path: `/admin/student/${student.value.code}`,
    query: {
      returnTo,
      returnLabel: props.context?.returnLabel || '学生成长与学业分析',
    },
  })
}

watch(
  () => [props.modelValue, props.studentId],
  () => { if (props.modelValue && props.studentId) void load() },
  { immediate: true },
)
</script>

<style scoped>
.student-evidence { min-height: 360px; }
.drawer-loading { min-height: 360px; display: grid; align-content: start; gap: 12px; }
.drawer-loading p { margin: 0; color: #64748b; text-align: center; }
.attention-callout { display: flex; justify-content: space-between; gap: 16px; padding: 14px 16px; border: 1px solid #fed7aa; background: #fff7ed; border-radius: 10px; }
.attention-callout > div { display: grid; gap: 4px; }
.attention-callout span { color: #9a3412; font-size: 12px; }
.attention-callout b { color: #7c2d12; font-size: 16px; }
.attention-callout p { margin: 0; color: #78716c; font-size: 13px; }
.identity-block { margin: 14px 0; }
.evidence-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.evidence-tabs { margin-bottom: 14px; }
.change-grid, .curriculum-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
.change-grid > div, .curriculum-grid > div { display: grid; gap: 5px; padding: 12px; border: 1px solid #e2e8f0; border-radius: 9px; background: #f8fafc; }
.change-grid span, .curriculum-grid span { color: #64748b; font-size: 12px; }
.change-grid b, .curriculum-grid b { color: #1e293b; font-size: 17px; }
.change-grid small { font-weight: 700; }
.delta-bad { color: #dc2626; }
.delta-good { color: #059669; }
.section-card { padding: 14px; border: 1px solid #e2e8f0; border-radius: 10px; margin-bottom: 12px; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.section-head h4, .intervention-list h4 { margin: 0; color: #1e293b; }
.section-head p { margin: 4px 0 0; color: #64748b; font-size: 12px; }
.failure-switch { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
.failure-switch button { border: 1px solid #e2e8f0; background: #fff; border-radius: 8px; padding: 10px; color: #475569; cursor: pointer; }
.failure-switch button.active { border-color: #818cf8; background: #eef2ff; color: #3730a3; }
.failure-switch b { margin-left: 5px; }
.course-boundary, .alert-boundary { margin-bottom: 10px; }
.intervention-list { margin-top: 14px; display: grid; gap: 8px; }
.intervention-list > div { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 8px; }
.intervention-list span { color: #64748b; font-size: 12px; }
.intervention-list p { grid-column: 1 / -1; margin: 0; color: #475569; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
@media (max-width: 900px) {
  .evidence-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .change-grid, .curriculum-grid { grid-template-columns: 1fr; }
}
</style>

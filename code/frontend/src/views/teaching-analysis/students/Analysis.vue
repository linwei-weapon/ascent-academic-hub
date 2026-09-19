<!-- 学生成长与学业分析：Analysis 页面或专用组件，保留原业务与权限行为。 -->
<template>
  <div
    v-loading="initialLoading"
    element-loading-text="正在计算最近两个学期的学业变化，请稍候…"
    element-loading-background="rgba(248,250,252,.86)"
  >
    <div class="sa-head-row">
      <h2 class="sa-page-title">{{ pageTitle }}</h2>
    </div>

    <div class="sa-card filter-card">
      <div class="filter-row sa-button-row">
        <el-select size="small" v-model="draft.fromSemester" style="width:166px" placeholder="起始学期">
          <el-option v-for="s in semesterOptions" :key="s.value" :label="`起始：${s.label}`" :value="s.value" />
        </el-select>
        <el-select size="small" v-model="draft.toSemester" style="width:166px" placeholder="目标学期">
          <el-option v-for="s in semesterOptions" :key="s.value" :label="`目标：${s.label}`" :value="s.value" />
        </el-select>
        <el-select size="small" v-model="draft.college" style="width:170px" clearable filterable placeholder="全部学院" :disabled="scopeType === 'college' || scopeType === 'major'" @change="onCollege">
          <el-option v-for="c in colleges" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-select size="small" v-model="draft.major" style="width:160px" clearable filterable placeholder="全部专业" :disabled="!draft.college || scopeType === 'major'" @change="onMajor">
          <el-option v-for="m in majorOptions" :key="m.value" :label="m.label" :value="m.value" />
        </el-select>
        <el-select size="small" v-model="draft.classId" style="width:160px" clearable filterable placeholder="全部行政班" :disabled="!draft.major">
          <el-option v-for="c in classOptions" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-button size="small" type="primary" :loading="refreshing" @click="queryScope">查询</el-button>
        <el-button size="small" @click="resetScope">重置</el-button>
      </div>
      <el-alert
        v-if="draft.fromSemester && draft.toSemester && draft.fromSemester >= draft.toSemester"
        type="warning" :closable="false" show-icon
        title="起始学期必须早于目标学期，当前条件尚未查询"
      />
    </div>

    <el-alert
      v-if="slowLoading"
      class="slow-alert"
      type="info"
      :closable="false"
      show-icon
      title="正在汇总成绩与未通过课程变化，已加载内容仍可查看"
    />
    <el-alert v-if="loadError" class="error-alert" type="error" :closable="false" show-icon>
      <template #title>成长概览加载失败，已保留上一次结果</template>
      <template #default>
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="loadOverview()">重新加载</el-button>
      </template>
    </el-alert>

    <div class="comparison-board" aria-label="可比较学生情况看板">
      <div class="comparison-board-item comparison-board-title">
        <strong>可比较学生情况看板</strong>
      </div>
      <div class="comparison-board-item">
        <span>参与比较学期</span>
        <strong class="tnum">{{ periodText }}</strong>
      </div>
      <el-tooltip content="两个参与学期均在籍的学生交集去重数" placement="top">
        <button
          type="button"
          class="comparison-board-item comparison-board-action"
          :disabled="comparisonBoardComparableCount == null"
          @click="showComparableStudents"
        >
          <span class="comparison-board-label">可比较学生数<el-icon aria-hidden="true"><QuestionFilled /></el-icon></span>
          <strong class="tnum">{{ countText(comparisonBoardComparableCount) }}</strong>
        </button>
      </el-tooltip>
      <div class="comparison-board-item">
        <span class="comparison-board-label">在籍学生总数
          <el-tooltip content="两个参与学期在籍学生并集去重数" placement="top">
            <el-icon tabindex="0" aria-label="查看在籍学生总数口径"><QuestionFilled /></el-icon>
          </el-tooltip>
        </span>
        <strong class="tnum">{{ countText(comparisonBoardStudentCount) }}</strong>
      </div>
      <div class="comparison-board-item">
        <span class="comparison-board-label">可比较学生占比
          <el-tooltip content="两个参与学期均在籍的学生交集去重数 ÷ 两个参与学期在籍学生并集去重数 × 100%" placement="top">
            <el-icon tabindex="0" aria-label="查看可比较学生占比计算公式"><QuestionFilled /></el-icon>
          </el-tooltip>
        </span>
        <strong class="tnum">{{ percentText(comparisonBoardRate) }}</strong>
      </div>
    </div>

    <div class="sa-kpi-row">
      <div
        v-for="metric in metricCards"
        :key="metric.key"
        class="drill-card"
        :class="{ active: activeGroup === metric.key }"
        @click="selectGroup(metric.key, metric.label)"
      >
        <KpiCard
          :label="metric.label"
          :value="metric.value"
          :sub="metric.sub"
          :hint="metricHint(metric)"
          :tone="metric.tone"
        />
        <span class="drill-hint">查看学生名单 →</span>
      </div>
    </div>

    <div class="sa-card organization-panel management-row">
      <div class="sa-card-title">{{ organizationTitle }}</div>
      <el-alert v-if="organizationError" class="list-rule" type="error" :closable="false" show-icon>
        <template #title>组织比较加载失败，其他区域仍可使用</template>
        <template #default>
          <span>{{ organizationError }}</span>
          <el-button link type="primary" @click="loadOrganizations">重新加载组织比较</el-button>
        </template>
      </el-alert>
      <AppTable
        :columns="organizationCols"
        :data="overview.organizations"
        storage-key="students:growth-organizations"
        :max-business-columns="7"
        :config-version="2"
        :show-density="true" :show-column-settings="true" :pagination="false"
        v-loading="organizationLoading"
      >
        <template #col-organizationName="{ row }"><b>{{ organizationDisplayName(row) }}</b></template>
        <template #col-coverageRate="{ row }">{{ ratioCell(row.comparableCount, row.studentCount, row.coverageRate) }}</template>
        <template #col-declinedRate="{ row }">{{ ratioCell(row.declinedCount, row.gradeEvidenceComparableCount ?? row.comparableCount, row.declinedRate) }}</template>
      </AppTable>
      <el-empty v-if="!initialLoading && !overview.organizations.length" description="当前查询范围没有可比较的组织数据" :image-size="62" />
    </div>

    <div class="sa-card list-panel" id="growth-priority-list">
      <div class="list-header">
        <div>
          <div class="sa-card-title">学生证据名单 · {{ activeGroupLabel }}</div>
          <p class="section-note">
            {{ selectedOrganizationName ? `当前组织：${selectedOrganizationName}；` : '' }}
            共 {{ list.total }} 人。默认排序：连续受挫且重复未解决 → 低年级首次受挫 → 明确恶化且未通过增加 → GPA明显下降 → 其他。
          </p>
        </div>
      </div>
      <el-alert v-if="listError" class="list-rule" type="error" :closable="false" show-icon>
        <template #title>学生名单加载失败，概览和现有名单仍可查看</template>
        <template #default>
          <span>{{ listError }}</span>
          <el-button link type="primary" @click="loadList(page)">重新加载名单</el-button>
        </template>
      </el-alert>
      <AppTable
        :columns="studentCols"
        :data="list.students"
        storage-key="students:growth-priority-list"
        :max-business-columns="8"
        :config-version="2"
        v-loading="listLoading"
        stripe :show-density="true" :show-column-settings="true" :pagination="true" :page="page" :page-size="pageSize" :total="list.total" @page-change="page = $event; loadList()" @page-size-change="pageSize = $event" :loading="listLoading">
        <template #toolbar>
          <div class="list-actions">
            <el-input size="small" v-model="keyword" clearable placeholder="搜索学号/姓名" style="width:190px" @keyup.enter="loadList(1)" />
            <el-button size="small" type="primary" plain @click="loadList(1)">查询</el-button>
          </div>
        </template>
        <template #col-sid="{ row }"><span class="tnum">{{ row.sid }}</span></template>
        <template #col-name="{ row }"><el-button link type="primary" @click="openEvidence(row)">{{ row.name }}</el-button></template>
        <template #col-organization="{ row }">{{ row.major }} · {{ row.className }}</template>
        <template #col-gpaChange="{ row }">
          <span class="tnum">{{ valueText(row.fromGpa) }} → {{ valueText(row.toGpa) }}</span>
          <small :class="deltaClass(row.gpaDelta)"> {{ signed(row.gpaDelta) }}</small>
        </template>
        <template #col-failChange="{ row }">
          <span class="tnum">{{ valueText(row.fromFailCount, 0) }} → {{ valueText(row.toFailCount, 0) }}门</span>
          <small :class="failDeltaClass(row.failDelta)"> {{ signed(row.failDelta) }}</small>
        </template>
        <template #col-triggers="{ row }">
          <div class="tag-wrap">
            <el-tag v-for="tag in triggerLabels(row)" :key="tag" size="small" :type="triggerType(tag)">{{ tag }}</el-tag>
          </div>
        </template>
        <template #col-unresolved="{ row }">
          <span v-if="row.unresolvedCourseCount">{{ row.unresolvedCourseCount }}门<span v-if="row.repeatedCourses?.length" class="danger-text"> · 重复{{ row.repeatedCourses.length }}门</span></span>
          <span v-else class="sa-faint">无</span>
        </template>
        <template #col-openAlerts="{ row }"><span :class="{ 'danger-text': row.openAlerts }">{{ row.openAlerts }}条</span></template>
        <template #col-actions="{ row }"><el-button size="small" type="primary" plain @click="openEvidence(row)">详情</el-button></template>
      </AppTable>
      <el-empty v-if="!listLoading && !list.students.length" :description="emptyDescription" :image-size="66" />

    </div>

    <StudentEvidenceDrawer
      v-model="evidenceVisible"
      :student-id="selected.sid"
      :context="evidenceContext"
    />
  </div>
</template>

<script setup lang="ts">
import * as studentsApi from '@/api/teachingAnalysis/students'

import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import { authStore } from '@/store/auth'

import { getFilterMeta, type ClassOpt, type MajorOpt, type SemesterOpt } from '@/api/shared/filterMeta'
import KpiCard from '@/components/KpiCard.vue'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import StudentEvidenceDrawer from '@/components/StudentEvidenceDrawer.vue'

const route = useRoute()
const router = useRouter()
const scopeType = computed(() => String(authStore.user?.permissionContext?.detailScope?.type || 'all'))
const pageTitle = computed(() => ({
  all: '全校学生成长与学业变化',
  college: '本学院学生成长与学业变化',
  major: '本专业学生成长与学业变化',
}[scopeType.value] || '当前授权范围学生成长与学业变化'))

const semesterOptions = ref<SemesterOpt[]>([])
const colleges = ref<{ value: string; label: string }[]>([])
const majors = ref<MajorOpt[]>([])
const classes = ref<ClassOpt[]>([])
const draft = reactive({ fromSemester: '', toSemester: '', college: '', major: '', classId: '' })
const applied = reactive({ fromSemester: '', toSemester: '', college: '', major: '', classId: '' })
const overview = reactive<any>({ metrics: [], groups: [], organizations: [], period: {}, comparisonBoard: {}, rule: {}, evidence: {} })
const list = reactive<any>({ total: 0, students: [] })
const initialLoading = ref(true)
const refreshing = ref(false)
const listLoading = ref(false)
const organizationLoading = ref(false)
const slowLoading = ref(false)
const loadError = ref('')
const listError = ref('')
const organizationError = ref('')
const activeGroup = ref('all')
const activeGroupLabel = ref('全部优先关注')
const selectedOrganizationId = ref('')
const selectedOrganizationName = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const evidenceVisible = ref(false)
const selected = ref<any>({})
let slowTimer: ReturnType<typeof setTimeout> | undefined

const majorOptions = computed(() => draft.college ? majors.value.filter(item => item.college === draft.college) : [])
const classOptions = computed(() => draft.major ? classes.value.filter(item => item.major === draft.major) : [])
const periodText = computed(() => overview.period?.fromSemester && overview.period?.toSemester
  ? `${overview.period.fromSemester} → ${overview.period.toSemester}`
  : '最近两个真实学期')
const comparableMetric = computed<any>(() => (overview.metrics || [])
  .find((item: any) => item.key === 'comparable') || {})
const comparableMetricUsesRosterCohort = computed(() =>
  overview.rule?.version === 'student-growth-v2')
const comparisonBoardComparableCount = computed<number | null>(() =>
  overview.comparisonBoard?.comparableCount
  ?? (comparableMetricUsesRosterCohort.value ? comparableMetric.value.count : null)
  ?? null)
const comparisonBoardStudentCount = computed<number | null>(() =>
  overview.comparisonBoard?.studentCount
  ?? (comparableMetricUsesRosterCohort.value ? comparableMetric.value.denominator : null)
  ?? null)
const comparisonBoardRate = computed<number | null>(() =>
  overview.comparisonBoard?.rate
  ?? (comparableMetricUsesRosterCohort.value ? comparableMetric.value.rate : null)
  ?? null)
const metricCards = computed<any[]>(() => {
  const metrics = [...(overview.metrics || [])]
    .filter((item: any) => item.key !== 'comparable')
  if (metrics.some((item: any) => item.key === 'repeated_unresolved')) return metrics
  if (!comparableMetricUsesRosterCohort.value) return metrics

  const group = (overview.groups || []).find((item: any) => item.key === 'repeated_unresolved')
  if (!group) return metrics
  const count = Number(group.count || 0)
  const denominator = comparisonBoardStudentCount.value
  const rate = denominator ? Math.round(count / denominator * 1000) / 10 : null
  const repeatedMetric = {
    key: "repeated_unresolved",
    label: '重复未解决',
    count,
    denominator,
    rate,
    value: `${count.toLocaleString('zh-CN')}人`,
    sub: `${count.toLocaleString('zh-CN')}/${denominator == null ? '—' : denominator.toLocaleString('zh-CN')}人 · ${rate == null ? '暂不可计算' : `${rate}%`}`,
    meaning: '同一课程至少两次未通过且最新有效结果仍未通过',
    tone: 'danger',
  }
  const firstSetbackIndex = metrics.findIndex((item: any) => item.key === 'first_setback')
  metrics.splice(firstSetbackIndex < 0 ? metrics.length : firstSetbackIndex + 1, 0, repeatedMetric)
  return metrics
})
const organizationTitle = computed(() => {
  if (applied.classId) return `${classOptionLabel(applied.classId)}变化与关注比较`
  if (applied.major) {
    return `${collegeOptionLabel(applied.college)}${majorOptionLabel(applied.major)}各行政班变化与关注比较`
  }
  if (applied.college) return `${collegeOptionLabel(applied.college)} 各专业变化与关注比较`
  return '学院变化与关注比较'
})
const organizationNameColumnLabel = computed(() => {
  if (applied.major || applied.classId) return '行政班名称'
  if (applied.college) return '专业名称'
  return '学院名称'
})
const emptyDescription = computed(() => activeGroup.value === 'all'
  ? '当前范围未识别到四类优先关注学生'
  : `当前范围没有命中“${activeGroupLabel.value}”的学生`)
const evidenceContext = computed(() => ({
  studentName: selected.value.name,
  reasons: triggerLabels(selected.value),
  period: periodText.value,
  fromGpa: selected.value.fromGpa,
  toGpa: selected.value.toGpa,
  gpaDelta: selected.value.gpaDelta,
  fromFailCount: selected.value.fromFailCount,
  toFailCount: selected.value.toFailCount,
  failDelta: selected.value.failDelta,
  returnLabel: pageTitle.value,
  returnQuery: currentViewQuery(),
}))

const organizationCols = computed<AppTableColumn[]>(() => [
  { key: 'organizationName', label: organizationNameColumnLabel.value, minWidth: 150, fixed: 'left', region: 'identity', required: true },
  { key: 'studentCount', label: '范围学生', minWidth: 92, align: 'center' },
  { key: 'coverageRate', label: '可比较覆盖', minWidth: 130, align: 'center', required: true },
  { key: 'declinedRate', label: '明确恶化', minWidth: 122, align: 'center' },
  { key: 'continuousCount', label: '连续受挫', minWidth: 96, align: 'center' },
  { key: 'firstSetbackCount', label: '首次受挫', minWidth: 96, align: 'center' },
  { key: 'repeatedUnresolvedCount', label: '重复未解决', minWidth: 110, align: 'center' },
  { key: 'openAlertCount', label: '有效预警', minWidth: 96, align: 'center', defaultVisible: false },
])
const studentCols: AppTableColumn[] = [
  { key: 'sid', label: '学号', minWidth: 132, fixed: 'left', region: 'identity', required: true },
  { key: 'name', label: '姓名', minWidth: 100, fixed: 'left', region: 'identity', required: true },
  { key: 'college', label: '院系', minWidth: 150, tooltip: true, region: 'identity', required: true },
  { key: 'organization', label: '专业 / 班级', minWidth: 190, tooltip: true },
  { key: 'gpaChange', label: 'GPA 起点→终点', minWidth: 150 },
  { key: 'failChange', label: '未通过 起点→终点', minWidth: 160 },
  { key: 'triggers', label: '触发原因', minWidth: 210, required: true },
  { key: 'unresolved', label: '当前未通过课程', minWidth: 150 },
  { key: 'openAlerts', label: '当前有效预警', minWidth: 110, align: 'center' },
  { key: 'grade', label: '年级', minWidth: 82, align: 'center', defaultVisible: false },
  { key: 'actions', label: '详情', width: 82, fixed: 'right', region: 'action', required: true },
]

function onCollege() { draft.major = ''; draft.classId = '' }
function onMajor() { draft.classId = '' }
function collegeOptionLabel(value: string) { return colleges.value.find(item => item.value === value)?.label || value }
function majorOptionLabel(value: string) { return majors.value.find(item => item.value === value)?.label || value }
function classOptionLabel(value: string) { return classes.value.find(item => item.value === value)?.label || value }
function organizationDisplayName(row: any) {
  const organizationId = String(row.organizationId || '')
  if (!organizationId || organizationId === 'UNASSIGNED') return '未分配'
  if (overview.organizationLabel === '行政班') {
    return classes.value.find(item => item.value === organizationId)?.label || organizationId
  }
  if (overview.organizationLabel === '专业') {
    return majors.value.find(item => item.value === organizationId)?.label || organizationId
  }
  return colleges.value.find(item => item.value === organizationId)?.label || organizationId
}
function organizationResponseMatchesQuery(data: any) {
  const expectedLabel = applied.major || applied.classId
    ? '行政班'
    : applied.college
      ? '专业'
      : scopeType.value === 'all' ? '学院' : String(data.organizationLabel || '')
  if (data.organizationLabel !== expectedLabel) return false
  const validIds = new Set(
    expectedLabel === '行政班'
      ? applied.classId ? [applied.classId] : classes.value
        .filter(item => !applied.major || item.major === applied.major)
        .map(item => item.value)
      : expectedLabel === '专业'
        ? majors.value
            .filter(item => !applied.college || item.college === applied.college)
            .map(item => item.value)
        : colleges.value.map(item => item.value),
  )
  return (data.organizations || []).every((row: any) => {
    const organizationId = String(row.organizationId || '')
    return (!applied.classId && organizationId === 'UNASSIGNED')
      || validIds.has(organizationId)
  })
}
function valueText(value: any, fallback: any = '—') { return value == null ? fallback : value }
function countText(value: number | null | undefined) { return value == null ? '—' : Number(value).toLocaleString('zh-CN') }
function percentText(value: number | null | undefined) { return value == null ? '—' : `${value}%` }
const metricHintDetails: Record<string, { indicator: string; formula: string; description: string; conditions?: string[] }> = {
  improved: {
    indicator: 'GPA明显上升且挂科未增加，或挂科减少且GPA未明显下降学生数',
    formula: '明确改善学生数 ÷ 两个学期均有有效成绩证据的学生数 × 100%',
    description: '学生在两个学期都有有效成绩记录，并且满足以下任一情况，即认定为“明确改善”：',
    conditions: [
      'GPA 明显上升，且未通过课程数量没有增加；',
      '未通过课程数量减少，且 GPA 没有明显下降。',
    ],
  },
  declined: {
    indicator: 'GPA明显下降且挂科未减少，或挂科增加且GPA未明显上升学生数',
    formula: '明确恶化学生数 ÷ 两个学期均有有效成绩证据的学生数 × 100%',
    description: '学生在两个学期都有有效成绩记录，并且满足以下任一情况，即认定为“明确恶化”：',
    conditions: [
      'GPA 明显下降，且未通过课程数量没有减少；',
      '未通过课程数量增加，且 GPA 没有明显上升。',
    ],
  },
  continuous: {
    indicator: '两个参与学期均在籍，且两个参与学期均至少有1门未通过课程的学生去重数',
    formula: '连续受挫学生数 ÷ 两个学期均有有效成绩证据的学生 × 100%',
    description: '学生在起始学期和目标学期均至少有1门未通过课程，即认定为“连续受挫”。分母是两个学期均有有效成绩证据的学生',
  },
  first_setback: {
    indicator: '当前两个低年级群体在目标学期首次出现可观测未通过记录的学生去重数。',
    formula: '低年级首次受挫学生数 ÷ 两个参与学期至少一个学期在籍的学生去重总数 × 100%',
    description: '学生属于当前范围最新两个年级，在目标学期至少有1门未通过课程，并且起始学期之前没有可观测的未通过课程记录，即纳入“低年级首次受挫”。分母为两个参与学期至少一个学期在籍的学生去重总数',
  },
  repeated_unresolved: {
    indicator: '同一课程至少两次未通过且最新有效结果仍未通过的学生去重数。',
    formula: '重复未解决学生数 ÷ 两个参与学期在籍学生并集去重数 × 100%',
    description: '同一学生只要存在至少1门课程“至少两次未通过，并且最新有效修读结果仍未通过”，即计入重复未解决学生；每名学生只计算一次',
  },
}
function metricHint(metric: any) {
  const detail = metricHintDetails[metric.key]
  if (!detail) return metric.meaning || ''
  const lines = [
    `1.指标说明：${detail.indicator}`,
    `2.时间范围：${periodText.value}`,
    `3.比例计算公式：${detail.formula}`,
    `4.中文说明：${detail.description}`,
  ]
  if (detail.conditions?.[0]) lines.push(`   i: ${detail.conditions[0]}`)
  if (detail.conditions?.[1]) lines.push(`  ii: ${detail.conditions[1]}`)
  return lines.join('\n')
}
function signed(value: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}` }
function ratioCell(count: number | null | undefined, denominator: number | null | undefined, rate: number | null | undefined) {
  return `${countText(count)}/${countText(denominator)} · ${percentText(rate)}`
}
function deltaClass(value: number | null) { return value == null ? '' : value <= -0.3 ? 'delta-bad' : value >= 0.3 ? 'delta-good' : '' }
function failDeltaClass(value: number | null) { return value == null ? '' : value > 0 ? 'delta-bad' : value < 0 ? 'delta-good' : '' }
function triggerLabels(row: any): string[] {
  if (row?.triggers?.length) return row.triggers
  if (row?.category === 'improved') return ['明确改善']
  if (row?.comparable) return ['两个学期均在籍']
  return []
}
function triggerType(label: string) {
  if (label.includes('改善')) return 'success'
  if (label.includes('重复') || label.includes('首次')) return 'danger'
  if (label.includes('连续') || label.includes('恶化')) return 'warning'
  return 'info'
}

// 收集当前查询上下文，保留原字段名和可选条件。
function queryParams(extra: Record<string, any> = {}) {
  const params: Record<string, any> = {
    from_semester: applied.fromSemester,
    to_semester: applied.toSemester,
    ...extra,
  }
  if (applied.college) params.college = applied.college
  if (applied.major) params.major = applied.major
  if (applied.classId) params.class_id = applied.classId
  return new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value != null) as [string, string][]).toString()
}
function currentViewQuery() {
  return {
    from_semester: applied.fromSemester || undefined,
    to_semester: applied.toSemester || undefined,
    college: applied.college || undefined,
    major: applied.major || undefined,
    class: applied.classId || undefined,
    group: activeGroup.value !== 'all' ? activeGroup.value : undefined,
    organization_id: selectedOrganizationId.value || undefined,
    organization_name: selectedOrganizationName.value || undefined,
    keyword: keyword.value || undefined,
    page: page.value > 1 ? String(page.value) : undefined,
    page_size: pageSize.value !== 20 ? String(pageSize.value) : undefined,
  }
}
async function syncViewState() {
  await router.replace({ query: currentViewQuery() })
}

function beginSlowTimer() {
  if (slowTimer) clearTimeout(slowTimer)
  slowLoading.value = false
  slowTimer = setTimeout(() => { slowLoading.value = true }, 2000)
}
function endSlowTimer() {
  if (slowTimer) clearTimeout(slowTimer)
  slowLoading.value = false
}

async function loadOverview(first = false) {
  if (first) initialLoading.value = true
  else refreshing.value = true
  loadError.value = ''
  beginSlowTimer()
  try {
    const data = await studentsApi.getStudentGrowthOverview<any>(queryParams())
    Object.assign(overview, data || {})
    if (activeGroup.value !== 'all') {
      const active = [...(overview.metrics || []), ...(overview.groups || [])]
        .find((item: any) => item.key === activeGroup.value)
      activeGroupLabel.value = active?.label || activeGroup.value
    }
    await Promise.all([
      loadOrganizations(),
      loadList(first ? page.value : 1),
    ])
  } catch (error: any) {
    loadError.value = error?.message || '学生成长数据加载失败，请稍后重试'
  } finally {
    initialLoading.value = false
    refreshing.value = false
    endSlowTimer()
  }
}

async function loadOrganizations() {
  organizationLoading.value = true
  organizationError.value = ''
  try {
    const data = await studentsApi.getStudentGrowthOrganizations<any>(queryParams())
    if (!organizationResponseMatchesQuery(data)) {
      overview.organizationLabel = ''
      overview.organizations = []
      throw new Error('组织比较返回层级与当前查询条件不一致，请重启后端服务后重新查询')
    }
    overview.organizationLabel = data.organizationLabel || ''
    overview.organizations = data.organizations || []
  } catch (error: any) {
    organizationError.value = error?.message || '组织比较加载失败，请稍后重试'
  } finally {
    organizationLoading.value = false
  }
}

async function loadList(targetPage = page.value) {
  listLoading.value = true
  listError.value = ''
  try {
    const extra: Record<string, any> = {
      group: activeGroup.value,
      page: targetPage,
      page_size: pageSize.value,
    }
    if (selectedOrganizationId.value) extra.organization_id = selectedOrganizationId.value
    if (keyword.value) extra.keyword = keyword.value
    const data = await studentsApi.getStudentGrowthList<any>(queryParams(extra))
    Object.assign(list, data || {})
    page.value = data.page || targetPage
    await syncViewState()
  } catch (error: any) {
    listError.value = error?.message || '学生名单加载失败，请稍后重试'
  } finally {
    listLoading.value = false
  }
}

async function queryScope() {
  if (!draft.fromSemester || !draft.toSemester || draft.fromSemester >= draft.toSemester) {
    ElMessage.warning('请选择有效的起始学期和目标学期')
    return
  }
  Object.assign(applied, draft)
  activeGroup.value = 'all'
  activeGroupLabel.value = '全部优先关注'
  selectedOrganizationId.value = ''
  selectedOrganizationName.value = ''
  keyword.value = ''
  page.value = 1
  await syncViewState()
  await loadOverview()
}

async function resetScope() {
  const newest = semesterOptions.value[0]?.value || ''
  const previous = semesterOptions.value[1]?.value || ''
  const defaults = scopedHierarchyDefaults()
  Object.assign(draft, {
    fromSemester: previous, toSemester: newest,
    college: defaults.college,
    major: defaults.major,
    classId: '',
  })
  await queryScope()
}

function scopedHierarchyDefaults() {
  const major = scopeType.value === 'major'
    ? String(authStore.user?.scope?.majorId || majors.value[0]?.value || '')
    : ''
  const college = scopeType.value === 'college' || scopeType.value === 'major'
    ? String(authStore.user?.scope?.collegeId || majors.value.find(item => item.value === major)?.college || '')
    : ''
  return { college, major }
}

function normalizeHierarchy(collegeValue: string, majorValue: string, classValue: string) {
  const defaults = scopedHierarchyDefaults()
  let college = defaults.college || collegeValue
  let major = defaults.major || majorValue
  let classId = classValue
  const selectedClass = classes.value.find(item => item.value === classId)
  if (classId && !major && selectedClass) major = selectedClass.major
  const selectedMajor = majors.value.find(item => item.value === major)
  if (major && !college && selectedMajor) college = selectedMajor.college
  if (!college || !selectedMajor || selectedMajor.college !== college) {
    major = ''
    classId = ''
  } else if (!selectedClass || selectedClass.major !== major) {
    classId = ''
  }
  return { college, major, classId }
}

async function showComparableStudents() {
  selectedOrganizationId.value = ''
  selectedOrganizationName.value = ''
  keyword.value = ''
  await selectGroup('comparable', '可比较学生')
}

async function selectGroup(key: string, label: string) {
  activeGroup.value = key
  activeGroupLabel.value = label
  page.value = 1
  await syncViewState()
  await loadList(1)
  document.getElementById('growth-priority-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function openEvidence(row: any) {
  selected.value = row
  evidenceVisible.value = true
}

// 按既有监听条件响应路由、筛选或身份变化，保留原重载与清理时机。
watch(pageSize, () => {
  if (!initialLoading.value) void loadList(1)
})

// 进入页面时执行原初始化流程，恢复路由条件与可用选项。
onMounted(async () => {
  const scrollY = Number(route.query.scrollY || 0)
  const meta = await getFilterMeta()
  semesterOptions.value = (meta.semesters || []).slice().reverse()
  colleges.value = meta.colleges || []
  majors.value = meta.majors || []
  classes.value = meta.classes || []
  const hierarchy = normalizeHierarchy(
    String(route.query.college || ''),
    String(route.query.major || ''),
    String(route.query.class || ''),
  )
  Object.assign(draft, {
    fromSemester: String(route.query.from_semester || semesterOptions.value[1]?.value || ''),
    toSemester: String(route.query.to_semester || semesterOptions.value[0]?.value || ''),
    ...hierarchy,
  })
  Object.assign(applied, draft)
  activeGroup.value = String(route.query.group || 'all')
  selectedOrganizationId.value = String(route.query.organization_id || '')
  selectedOrganizationName.value = String(route.query.organization_name || '')
  keyword.value = String(route.query.keyword || '')
  page.value = Math.max(1, Number(route.query.page || 1) || 1)
  pageSize.value = [10, 20, 50].includes(Number(route.query.page_size))
    ? Number(route.query.page_size) : 20
  await loadOverview(true)
  if (scrollY > 0) {
    await nextTick()
    window.scrollTo({ top: scrollY, behavior: 'auto' })
  }
})
</script>

<style scoped lang="scss">
// 按页面区域、后代元素和状态组织，保留原选择器顺序与作用范围。
.sa-head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.filter-card {
  margin-bottom: 14px;
  padding: 14px 16px;
}

.filter-title {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
  font-weight: 700;
  color: #1e293b;
  span:last-child {
    font-size: 12px;
    font-weight: 400;
    color: #64748b;
  }
}

.filter-row {
  display: flex;
  gap: var(--sa-button-gap);
  flex-wrap: wrap;
  align-items: center;
}

.slow-alert,.error-alert {
  margin-bottom: 12px;
}

.comparison-board {
  display:grid;
  grid-template-columns:minmax(240px,1.45fr) minmax(230px,1.35fr) repeat(3,minmax(160px,1fr));
  margin-bottom:14px;
  overflow:hidden;
  border:1px solid #dbeafe;
  border-radius:6px;
  background:#fff;
  box-shadow:0 3px 12px rgba(37,99,235,.06);

}

.comparison-board-item {
  min-width:0;
  min-height:58px;
  padding:0 16px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:14px;
  border:0;
  border-right:1px solid #e2e8f0;
  background:#fff;
  color:#475569;
  text-align:left;
  box-sizing:border-box;

}

.comparison-board-item:last-child {
  border-right:0;

}

.comparison-board-item span {
  flex:none;
  font-size:12px;
  color:#64748b;

}

.comparison-board-label {
  display:inline-flex;
  align-items:center;
  gap:4px;

}

.comparison-board-label .el-icon {
  color:#94a3b8;
  cursor:help;

}

.comparison-board-item strong {
  min-width:0;
  color:#172033;
  font-size:13px;
  text-align:right;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;

}

.comparison-board-title strong {
  color:#1e293b;

}

.comparison-board-action {
  cursor:pointer;
  font:inherit;

}

.comparison-board-action strong {
  color:#4f46e5;
  text-decoration:underline;
  text-underline-offset:3px;

}

.comparison-board-action:hover {
  background:#f5f3ff;

}

.comparison-board-action:focus-visible {
  position:relative;
  z-index:1;
  outline:2px solid #6366f1;
  outline-offset:-2px;

}

.comparison-board-action:disabled {
  cursor:default;

}

.comparison-board-action:disabled strong {
  color:#94a3b8;
  text-decoration:none;

}

.drill-card {
  position: relative;
  cursor: pointer;
  border-radius: 14px;
  transition: transform .15s ease, box-shadow .15s ease;
  :deep(.sa-kpi) {
    height: 100%;
    padding-bottom: 34px;
  }
  &:hover, &.active {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(79,70,229,.12);
  }
  &.active {
    outline: 2px solid rgba(79,70,229,.28);
  }
}

.drill-hint {
  position: absolute;
  right: 16px;
  bottom: 11px;
  font-size: 11px;
  line-height: 1.2;
  color: #6366f1;
}

.management-row {
  margin: 16px 0;
}

.organization-panel {
  width: 100%;
  box-sizing: border-box;
}

.section-note {
  margin: 4px 0 12px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.55;
}

.group-item {
  width: 100%;
  border: 1px solid #e2e8f0;
  background: #fff;
  border-radius: 10px;
  padding: 11px 12px;
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  text-align: left;
  cursor: pointer;
  &:hover, &.active {
    border-color: #818cf8;
    background: #f5f3ff;
  }
  span {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  b {
    color: #1e293b;
  }
  small {
    color: #64748b;
    line-height: 1.35;
  }
  strong {
    color: #4f46e5;
    white-space: nowrap;
  }
}

.title-note {
  margin-left: 8px;
  font-size: 11px;
  font-weight: 400;
  color: #64748b;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.list-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-start;
}

.list-rule {
  margin-bottom: 12px;
}

.tag-wrap {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.delta-good {
  color: #0d9488;
  font-weight: 700;
}

.delta-bad,.danger-text {
  color: #e11d48;
  font-weight: 700;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

@media (max-width: 1100px) {
  .comparison-board { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .comparison-board-item { border-bottom:1px solid #e2e8f0; }
  .comparison-board-item:nth-child(2n) { border-right:0; }
  .comparison-board-item:last-child { border-bottom:0; }

  .management-row {
    :deep(.el-col) {
      max-width: 100%;
      flex: 0 0 100%;
      margin-bottom: 14px;
    }
  }

  .list-header {
    flex-direction: column;
  }

}
</style>

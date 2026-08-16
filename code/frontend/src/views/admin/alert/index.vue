<template>
  <div class="alert-monitor">
    <div v-if="!embedded" class="monitor-head">
      <div class="monitor-title-line">
        <h2 class="sa-page-title">学业预警监控</h2>
        <span>最新预警统计时间：{{ latestGeneratedDate || '—' }}</span>
      </div>
    </div>

    <div v-if="initialLoading" class="initial-loading" aria-live="polite">
      <div class="loading-title">正在建立当前预警快照</div>
      <p>正在加载去重学生摘要、第一页核查名单和组织分布，预计需要数秒…</p>
      <el-skeleton :rows="9" animated />
    </div>

    <template v-else>
      <el-alert
        v-if="loadError"
        class="state-alert"
        type="error"
        :closable="false"
        show-icon
        title="预警监控数据加载失败"
      >
        <template #default>
          <span>{{ loadError }}</span>
          <el-button link type="primary" @click="loadAll">重新加载</el-button>
        </template>
      </el-alert>

      <div class="monitor-context">
        <b>当前快照</b>
        <div class="filter-grid">
          <el-select
            v-model="draft.college"
            clearable
            placeholder="学院"
            @change="handleCascadeChange('college')"
          >
            <el-option
              v-for="item in organizationOptions.college || []"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <el-select
            v-model="draft.major"
            clearable
            placeholder="专业"
            @change="handleCascadeChange('major')"
          >
            <el-option
              v-for="item in organizationOptions.major || []"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <el-select
            v-model="draft.grade"
            clearable
            placeholder="年级"
            @change="handleCascadeChange('grade')"
          >
            <el-option
              v-for="item in organizationOptions.grade || []"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <el-select
            v-model="draft.classId"
            clearable
            placeholder="行政班"
            @change="handleCascadeChange('class')"
          >
            <el-option
              v-for="item in organizationOptions.class || []"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <el-select v-model="draft.type" clearable placeholder="预警类型">
            <el-option
              v-for="item in filterOptions.types || []"
              :key="item.value"
              :label="item.value"
              :value="item.value"
            />
          </el-select>
          <el-select v-model="draft.level" clearable placeholder="风险等级">
            <el-option
              v-for="item in filterOptions.levels || []"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <div class="filter-actions">
            <el-button type="primary" :loading="refreshing" @click="applyFilters">
              查询
            </el-button>
            <el-button @click="resetAnalysisFilters">重置</el-button>
          </div>
        </div>
        <span v-if="appliedDescription" class="applied-summary">
          已查询：{{ appliedDescription }}
        </span>
      </div>

      <div v-if="refreshing" class="refresh-feedback" aria-live="polite">
        <span>正在按新条件更新摘要、图表和学生名单，当前结果暂时保留…</span>
      </div>

      <section class="kpi-grid">
        <button
          v-for="card in kpiCards"
          :key="card.key"
          type="button"
          class="kpi-card"
          :class="{ active: activePreset === card.key, static: !card.filter }"
          :aria-pressed="card.filter ? activePreset === card.key : undefined"
          @click="card.filter && applyPreset(card)"
        >
          <span class="kpi-value" :style="{ color: card.color }">{{ card.value }}</span>
          <span class="kpi-label">
            <KpiLabel :label="card.label" :formula="card.formula" />
          </span>
          <span class="kpi-note">{{ card.note }}</span>
        </button>
      </section>

      <section class="priority-section">
        <div class="section-head">
          <div>
            <h3>本轮优先核查队列</h3>
            <p>综合最高风险、核查状态、规则叠加和持续时长排序；分数只用于安排核查先后。</p>
          </div>
          <el-button
            v-if="priorityRows.length"
            type="primary"
            plain
            size="small"
            @click="openGroupInsight"
          >AI管理研判</el-button>
        </div>
        <div v-if="priorityRows.length" class="priority-grid">
          <button
            v-for="item in priorityRows.slice(0, 4)"
            :key="item.studentId"
            type="button"
            class="priority-card"
            @click="showStudent(item)"
          >
            <div>
              <b>{{ item.studentName }}</b>
              <span>优先分 {{ item.priorityScore }}</span>
            </div>
            <p>{{ item.priorityReasons?.join('；') }}</p>
            <small>
              {{ organizationText(item) }} · {{ item.className }}
            </small>
          </button>
        </div>
        <el-empty
          v-else
          description="当前范围没有严重且待核查的学生"
          :image-size="70"
        />
      </section>

      <el-row :gutter="16" class="chart-row">
        <el-col :span="12">
          <section class="sa-card chart-card">
            <div class="section-head compact">
              <div>
                <h3>当前预警时间分布</h3>
              </div>
              <KpiLabel label="" :formula="timeData.definition?.boundary || ''" />
            </div>
            <EChart
              v-if="timeData.items?.length"
              :option="timeOption"
              :height="230"
            />
            <el-empty
              v-else
              description="当前范围暂无活动预警时间分布"
              :image-size="70"
            />
          </section>
        </el-col>
        <el-col :span="12">
          <section class="sa-card chart-card">
            <div class="section-head compact">
              <div>
                <h3>{{ distributionTitle }}</h3>
              </div>
              <KpiLabel label="" :formula="distribution.definition?.formula || ''" />
            </div>
            <EChart
              v-if="distribution.items?.length"
              :option="distributionOption"
              :height="230"
            />
            <el-empty
              v-else
              description="当前范围暂无可比较的组织分布"
              :image-size="70"
            />
          </section>
        </el-col>
      </el-row>

      <section ref="studentListSection" class="sa-card list-card">
        <div class="section-head compact">
          <div>
            <h3>当前预警学生</h3>
            <p>共 {{ pagination.total }} 名去重学生；多条规则命中在核查抽屉中查看。</p>
          </div>
          <div class="list-head-actions">
            <span v-if="listAppliedDescription" class="applied-summary">
              名单筛选：{{ listAppliedDescription }}
            </span>
            <el-button :loading="exporting" @click="exportCurrentList">导出</el-button>
          </div>
        </div>

        <div class="list-filter-bar">
          <span class="list-filter-label">名单内筛选</span>
          <el-input
            v-model="listDraft.q"
            clearable
            placeholder="学生姓名或学号"
            @keyup.enter="applyListFilters"
          />
          <el-select v-model="listDraft.management" clearable placeholder="核查状态">
            <el-option
              v-for="item in filterOptions.managementStates || []"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <el-checkbox
            v-if="['class', 'staff_relation'].includes(meta.scope?.type)"
            v-model="listDraft.mine"
          >只看我的待办</el-checkbox>
          <el-button type="primary" plain :loading="refreshing" @click="applyListFilters">
            筛选名单
          </el-button>
          <el-button v-if="hasListFilters" link @click="resetListFilters">清除名单筛选</el-button>
          <span class="list-filter-hint">不改变上方管理指标和组织图表</span>
        </div>

        <DataTable
          :columns="studentColumns"
          :data="rows"
          storage-key="alert:student-list"
          config-version="2"
          :max-business-columns="6"
          :page-size="pagination.pageSize"
          :page-sizes="[10, 20, 50]"
          size="small"
          empty-text="当前条件下没有预警学生"
          row-class-name="row-clickable"
          @row-click="showStudent"
          @update:page-size="changePageSize"
        >
          <template #header-primaryReason>
            <KpiLabel
              label="主要触发证据"
              formula="显示最严重的最近一次触发的证据名称和证据内容结果"
            />
          </template>
          <template #col-student="{ row }">
            <div class="student-cell">
              <button type="button" @click.stop="showStudent(row)">{{ row.studentName }}</button>
              <span>{{ row.studentId }}</span>
            </div>
          </template>
          <template #col-highestLevel="{ row }">
            <el-tag :type="levelType(row.highestLevel)" size="small">
              {{ row.highestLevel }}
            </el-tag>
          </template>
          <template #col-primaryReason="{ row }">
            <div class="reason-cell">
              <b>{{ row.primaryType }}</b>
              <span>{{ row.primaryReason }}</span>
            </div>
          </template>
          <template #col-alertCount="{ row }">
            <span class="count-cell">{{ row.alertCount }}条</span>
          </template>
          <template #col-managementLabel="{ row }">
            <el-tag :type="managementType(row.managementState)" effect="plain" size="small">
              {{ row.managementLabel }}
            </el-tag>
          </template>
          <template #col-latestAt="{ row }">{{ formatDate(row.latestAt) }}</template>
          <template #col-action="{ row }">
            <el-button link type="primary" @click.stop="showStudent(row)">核查</el-button>
          </template>
          <template #empty>
            <div class="table-empty">
              <p v-if="hasAppliedFilters">当前筛选条件下没有匹配学生。</p>
              <p v-else>当前规则快照在本权限范围内没有命中学生。</p>
              <el-button v-if="hasAppliedFilters" link type="primary" @click="resetFilters">
                清除筛选
              </el-button>
            </div>
          </template>
        </DataTable>

        <div class="external-pager">
          <el-pagination
            v-model:current-page="pagination.page"
            :page-size="pagination.pageSize"
            :total="pagination.total"
            layout="total, prev, pager, next"
            small
            @current-change="loadStudentPage"
          />
        </div>
      </section>
    </template>

    <AlertStudentDrawer
      v-model="drawerVisible"
      :row="selectedStudent"
      @ai="openStudentInsight"
      @changed="loadAll"
    />
    <AIInsightDrawer
      v-model="aiDrawerVisible"
      :insight="aiInsight"
      :loading="aiLoading"
      title="AI管理研判"
      @focus-item-click="openStudentFromFocus"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getActiveIdentity, getToken, http } from '@/utils/http'
import { getAlertSummaryAIInsight, getStudentAIInsight } from '@/utils/ai'
import EChart from '@/components/EChart.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import AlertStudentDrawer from './AlertStudentDrawer.vue'

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
const emit = defineEmits<{ (event: 'latest-date', value: string): void }>()

const route = useRoute()
const router = useRouter()
const initialLoading = ref(true)
const refreshing = ref(false)
const loadError = ref('')
const requestSequence = ref(0)
const summary = reactive<Record<string, any>>({})
const definitions = reactive<Record<string, any>>({})
const meta = reactive<Record<string, any>>({})
const rows = ref<any[]>([])
const priorityRows = ref<any[]>([])
const distribution = reactive<Record<string, any>>({ items: [] })
const timeData = reactive<Record<string, any>>({ items: [] })
const filterOptions = reactive<Record<string, any>>({
  levels: [], types: [], managementStates: [], organizations: {},
})
const pagination = reactive({ page: 1, pageSize: 20, total: 0, pages: 0 })
const drawerVisible = ref(false)
const selectedStudent = ref<any>(null)
const aiDrawerVisible = ref(false)
const aiLoading = ref(false)
const aiInsight = ref<any>(null)
const activePreset = ref('')
const cardPreset = reactive({ highestLevel: '', management: '', mine: false })
const exporting = ref(false)
const studentListSection = ref<HTMLElement | null>(null)
const optionsSequence = ref(0)

const emptyFilter = () => ({
  college: '', major: '', grade: '', classId: '', type: '', level: '',
})
const emptyListFilter = () => ({ q: '', management: '', mine: false })
const draft = reactive(emptyFilter())
const applied = reactive(emptyFilter())
const listDraft = reactive(emptyListFilter())
const listApplied = reactive(emptyListFilter())

const organizationOptions = computed(() => filterOptions.organizations || {})
const hasAppliedFilters = computed(() =>
  Object.values(applied).some(Boolean) || Object.values(listApplied).some(Boolean),
)
const hasListFilters = computed(() => Object.values(listApplied).some(Boolean))
const appliedDescription = computed(() => {
  const labels: string[] = []
  const findLabel = (dimension: string, value: string) =>
    organizationOptions.value[dimension]?.find((item: any) => item.value === value)?.label || value
  if (applied.college) labels.push(`学院=${findLabel('college', applied.college)}`)
  if (applied.major) labels.push(`专业=${findLabel('major', applied.major)}`)
  if (applied.grade) labels.push(`年级=${findLabel('grade', applied.grade)}`)
  if (applied.classId) labels.push(`班级=${findLabel('class', applied.classId)}`)
  if (applied.type) labels.push(`类型=${applied.type}`)
  if (applied.level) labels.push(`等级=${applied.level}`)
  return labels.join('、')
})
const listAppliedDescription = computed(() => {
  const labels: string[] = []
  if (listApplied.q) labels.push(`学生=${listApplied.q}`)
  if (listApplied.management) {
    const label = filterOptions.managementStates?.find((item: any) =>
      item.value === listApplied.management)?.label || listApplied.management
    labels.push(`核查状态=${label}`)
  }
  if (listApplied.mine) labels.push('我的待办')
  return labels.join('、')
})

const kpiCards = computed(() => {
  const cards: any[] = [
    {
      key: 'current', label: '当前预警学生',
      value: `${summary.current_students || 0}人`, color: '#4f46e5',
      formula: definitionText('current_students'),
      note: `${summary.current_alert_records || 0}次规则触发 · 点击查看全部`,
      filter: {},
    },
    {
      key: 'critical', label: '当前严重学生',
      value: `${summary.critical_students || 0}人`, color: '#e11d48',
      formula: '按学生当前命中的最高风险等级去重统计；一名学生只计一次。',
      note: '点击筛选严重风险',
      filter: { highestLevel: '严重' },
    },
    {
      key: 'criticalPending', label: '严重且待核查',
      value: `${summary.critical_pending_students || 0}人`, color: '#be123c',
      formula: definitionText('critical_pending_students'),
      note: '严重风险且仍有规则待核查',
      filter: { highestLevel: '严重', management: 'pending_review' },
    },
    {
      key: 'pending', label: '待核查学生',
      value: `${summary.pending_students || 0}人`, color: '#d97706',
      formula: definitionText('pending_students'),
      note: '点击查看仍有规则待核查的学生',
      filter: { management: 'pending_review' },
    },
  ]
  if (['class', 'staff_relation'].includes(meta.scope?.type)) {
    cards.push({
      key: 'inbox', label: '我的待核查',
      value: `${summary.inbox_students || 0}人`, color: '#0f766e',
      formula: '分派给当前用户且至少存在1条尚未关闭的当前预警学生数。',
      note: '点击查看本人责任范围',
      filter: { mine: true },
    })
  } else {
    cards.push({
      key: 'rate', label: '当前预警学生率',
      value: summary.alert_student_rate == null ? '—' : `${summary.alert_student_rate}%`,
      color: '#0f766e',
      formula: definitionText('alert_student_rate'),
      note: `${summary.current_students || 0}/${summary.eligible_students || 0}人`,
      filter: null,
    })
  }
  return cards
})

const studentColumns = computed<DataTableColumn[]>(() => {
  const columns: DataTableColumn[] = [
    {
      key: 'student', label: '学生', width: 126, fixed: 'left',
      required: true, region: 'identity',
    },
  ]
  if (meta.scope?.type === 'all') {
    columns.push({
      key: 'collegeName', label: '学院', width: 150,
      region: 'business', tooltip: true,
    })
  }
  if (['all', 'college', 'major'].includes(meta.scope?.type)) {
    columns.push({
      key: 'majorName', label: '专业', width: 145,
      region: 'business', tooltip: true,
    })
  }
  columns.push(
    {
      key: 'className', label: '班级', width: 145, region: 'business',
      tooltip: true, defaultVisible: meta.scope?.type !== 'all',
    },
    {
      key: 'highestLevel', label: '最高风险', width: 84,
      required: true, region: 'business',
    },
    {
      key: 'primaryReason', label: '主要触发证据', minWidth: 245,
      required: true, region: 'business', tooltip: true,
    },
    { key: 'alertCount', label: '规则命中', width: 84, region: 'business' },
    {
      key: 'managementLabel', label: '核查状态', width: 110,
      required: true, region: 'business',
    },
    {
      key: 'latestAt', label: '最近变化', width: 138,
      region: 'business', defaultVisible: false,
    },
    {
      key: 'action', label: '操作', width: 64, fixed: 'right',
      required: true, region: 'action',
    },
  )
  return columns
})

const distributionTitle = computed(() => {
  if (applied.classId) {
    const label = organizationOptions.value.class?.find(
      (item: any) => item.value === applied.classId,
    )?.label || applied.classId
    return `${label}-当前预警学生率`
  }
  if (applied.major) return '各班级当前预警学生率'
  if (applied.college) return '各专业当前预警学生率'
  return '各学院当前预警学生率'
})

const latestGeneratedDate = computed(() => timeData.latestGeneratedDate || '')

const distributionOption = computed(() => {
  const items = [...(distribution.items || [])].slice(0, 10).reverse()
  const benchmark = distribution.benchmark?.alertStudentRate
  return {
    grid: { left: 8, right: 45, top: 10, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        const item = items[params[0]?.dataIndex]
        return `${item?.name || ''}<br/>预警学生率：${item?.alertStudentRate ?? '—'}%`
          + `<br/>预警学生：${item?.alertStudents || 0}人`
          + `<br/>在籍学生：${item?.eligibleStudents || 0}人`
      },
    },
    xAxis: {
      type: 'value', axisLabel: { formatter: '{value}%', color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    yAxis: {
      type: 'category', data: items.map((item: any) => item.name),
      axisLabel: { color: '#475569', fontSize: 11, width: 105, overflow: 'truncate' },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      data: items.map((item: any) => item.alertStudentRate || 0),
      barWidth: '48%',
      itemStyle: { color: '#4f46e5', borderRadius: [0, 5, 5, 0] },
      label: { show: true, position: 'right', formatter: '{c}%', color: '#475569' },
      markLine: benchmark == null ? undefined : {
        symbol: 'none',
        lineStyle: { color: '#f59e0b', type: 'dashed' },
        label: { formatter: `范围平均 ${benchmark}%`, color: '#b45309' },
        data: [{ xAxis: benchmark }],
      },
    }],
  }
})

const timeOption = computed(() => {
  const items = timeData.items || []
  return {
    grid: { left: 8, right: 18, top: 18, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        const item = items[params[0]?.dataIndex]
        return `${item?.month || ''}<br/>当前仍命中学生：${item?.alertStudents || 0}人`
          + `<br/>规则命中记录：${item?.alertRecords || 0}条`
      },
    },
    xAxis: {
      type: 'category', data: items.map((item: any) => item.month),
      axisLabel: { color: '#64748b', fontSize: 11 },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value', name: '学生数',
      axisLabel: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    series: [{
      type: 'bar',
      data: items.map((item: any) => item.alertStudents),
      barWidth: '45%',
      itemStyle: { color: '#6366f1', borderRadius: [5, 5, 0, 0] },
      label: { show: true, position: 'top', color: '#475569' },
    }],
  }
})

function definitionText(key: string) {
  const item = definitions[key]
  return item
    ? `${item.formula}。管理用途：${item.managementUse}。`
    : '指标口径由当前预警学生口径接口返回。'
}
function levelType(level: string) {
  return level === '严重' ? 'danger' : level === '警告' ? 'warning' : 'info'
}
function managementType(state: string) {
  if (state === 'pending_review') return 'danger'
  if (state === 'in_review') return 'warning'
  if (state === 'recorded') return 'success'
  return 'info'
}
function formatDate(value: string) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}
function organizationText(row: any) {
  if (meta.scope?.type === 'all') return row.collegeName
  if (meta.scope?.type === 'college') return row.majorName
  return row.className
}
function commonParams(source = applied) {
  const params = new URLSearchParams()
  if (source.level) params.set('level', source.level)
  if (source.type) params.set('type', source.type)
  if (source.college) params.set('college', source.college)
  if (source.major) params.set('major', source.major)
  if (source.grade) params.set('grade', source.grade)
  if (source.classId) params.set('class_id', source.classId)
  return params
}
function studentParams() {
  const params = commonParams()
  params.set('page', String(pagination.page))
  params.set('page_size', String(pagination.pageSize))
  if (listApplied.q) params.set('q', listApplied.q)
  if (listApplied.management) params.set('management', listApplied.management)
  if (listApplied.mine) params.set('assigned_to_me', 'true')
  if (cardPreset.highestLevel) params.set('highest_level', cardPreset.highestLevel)
  if (cardPreset.management) params.set('management', cardPreset.management)
  if (cardPreset.mine) params.set('assigned_to_me', 'true')
  return params
}
function query(path: string, params: URLSearchParams) {
  const suffix = params.toString()
  return `${path}${suffix ? `?${suffix}` : ''}`
}
function assignObject(target: Record<string, any>, source: any) {
  Object.keys(target).forEach(key => delete target[key])
  Object.assign(target, source || {})
}

async function loadOptions(source = draft) {
  const sequence = ++optionsSequence.value
  const params = new URLSearchParams()
  if (source.college) params.set('college', source.college)
  if (source.major) params.set('major', source.major)
  if (source.grade) params.set('grade', source.grade)
  if (source.classId) params.set('class_id', source.classId)
  const data: any = await http.get(query('/admin/alerts/options', params))
  if (sequence !== optionsSequence.value) return
  assignObject(filterOptions, data)
  let removedInvalidValue = false
  const fields: Record<string, string> = {
    college: 'college', major: 'major', grade: 'grade', class: 'classId',
  }
  Object.entries(fields).forEach(([dimension, field]) => {
    const value = source[field]
    if (!value) return
    const valid = data.organizations?.[dimension]?.some(
      (item: any) => item.value === value,
    )
    if (!valid) {
      source[field] = ''
      removedInvalidValue = true
    }
  })
  if (source.type && !data.types?.some((item: any) => item.value === source.type)) {
    source.type = ''
    removedInvalidValue = true
  }
  if (removedInvalidValue) await loadOptions(source)
}
async function handleCascadeChange(dimension: string) {
  if (dimension === 'college') {
    draft.major = ''
    draft.classId = ''
  } else if (dimension === 'major' || dimension === 'grade') {
    draft.classId = ''
  }
  try {
    await loadOptions(draft)
  } catch (error: any) {
    loadError.value = error?.message || '查询条件加载失败'
  }
}
async function loadAll() {
  const sequence = ++requestSequence.value
  refreshing.value = !initialLoading.value
  loadError.value = ''
  try {
    const params = commonParams()
    const distributionParams = commonParams()
    distributionParams.set(
      'dimension',
      applied.major || applied.classId ? 'class' : applied.college ? 'major' : 'college',
    )
    const priorityParams = commonParams()
    priorityParams.set('limit', '10')
    const [summaryData, studentData, distributionData, timeResult, priorityData] =
      await Promise.all([
        http.get<any>(query('/admin/alerts/summary', params)),
        http.get<any>(query('/admin/alerts/students', studentParams())),
        http.get<any>(query('/admin/alerts/distribution', distributionParams)),
        http.get<any>(query('/admin/alerts/time-distribution', params)),
        http.get<any>(query('/admin/alerts/priority', priorityParams)),
      ])
    if (sequence !== requestSequence.value) return
    assignObject(summary, summaryData.summary)
    assignObject(definitions, summaryData.definitions)
    assignObject(meta, summaryData.meta)
    rows.value = studentData.items || []
    Object.assign(pagination, studentData.pagination || {})
    assignObject(distribution, distributionData)
    assignObject(timeData, timeResult)
    emit('latest-date', timeResult.latestGeneratedDate || '')
    priorityRows.value = priorityData.items || []
  } catch (error: any) {
    if (sequence !== requestSequence.value) return
    loadError.value = error?.message || '请稍后重试'
  } finally {
    if (sequence === requestSequence.value) {
      initialLoading.value = false
      refreshing.value = false
    }
  }
}
async function loadStudentPage() {
  const sequence = ++requestSequence.value
  refreshing.value = true
  try {
    const data: any = await http.get(query('/admin/alerts/students', studentParams()))
    if (sequence !== requestSequence.value) return
    rows.value = data.items || []
    Object.assign(pagination, data.pagination || {})
  } catch (error: any) {
    if (sequence === requestSequence.value) loadError.value = error?.message || '学生名单加载失败'
  } finally {
    if (sequence === requestSequence.value) refreshing.value = false
  }
}
function applyFilters() {
  Object.assign(applied, { ...draft })
  pagination.page = 1
  clearCardPreset()
  syncRoute()
  loadAll()
}
async function resetAnalysisFilters() {
  Object.assign(draft, emptyFilter())
  Object.assign(applied, emptyFilter())
  pagination.page = 1
  clearCardPreset()
  syncRoute()
  await loadOptions(draft)
  loadAll()
}
async function resetFilters() {
  Object.assign(draft, emptyFilter())
  Object.assign(applied, emptyFilter())
  Object.assign(listDraft, emptyListFilter())
  Object.assign(listApplied, emptyListFilter())
  pagination.page = 1
  clearCardPreset()
  syncRoute()
  await loadOptions(draft)
  loadAll()
}
function applyListFilters() {
  Object.assign(listApplied, { ...listDraft })
  pagination.page = 1
  clearCardPreset()
  syncRoute()
  loadStudentPage()
}
function resetListFilters() {
  Object.assign(listDraft, emptyListFilter())
  Object.assign(listApplied, emptyListFilter())
  pagination.page = 1
  clearCardPreset()
  syncRoute()
  loadStudentPage()
}
function clearCardPreset() {
  activePreset.value = ''
  Object.assign(cardPreset, { highestLevel: '', management: '', mine: false })
}
async function applyPreset(card: any) {
  Object.assign(listDraft, emptyListFilter())
  Object.assign(listApplied, emptyListFilter())
  Object.assign(cardPreset, {
    highestLevel: card.filter?.highestLevel || '',
    management: card.filter?.management || '',
    mine: Boolean(card.filter?.mine),
  })
  activePreset.value = card.key
  pagination.page = 1
  syncRoute()
  await loadStudentPage()
  await nextTick()
  studentListSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function changePageSize(value: number) {
  if (value === pagination.pageSize) return
  pagination.pageSize = value
  pagination.page = 1
  loadStudentPage()
}
function syncRoute() {
  const queryValue: Record<string, string> = {}
  if (route.query.tab) queryValue.tab = String(route.query.tab)
  if (applied.level) queryValue.level = applied.level
  if (applied.type) queryValue.type = applied.type
  if (applied.college) queryValue.college = applied.college
  if (applied.major) queryValue.major = applied.major
  if (applied.grade) queryValue.grade = applied.grade
  if (applied.classId) queryValue.class_id = applied.classId
  if (listApplied.management) queryValue.management = listApplied.management
  if (listApplied.q) queryValue.q = listApplied.q
  if (listApplied.mine) queryValue.mine = '1'
  router.replace({ path: '/admin/alert', query: queryValue })
}
function restoreRoute() {
  Object.assign(draft, {
    college: String(route.query.college || ''),
    major: String(route.query.major || ''),
    grade: String(route.query.grade || ''),
    classId: String(route.query.class_id || ''),
    type: String(route.query.type || ''),
    level: String(route.query.level || ''),
  })
  Object.assign(applied, { ...draft })
  Object.assign(listDraft, {
    q: String(route.query.q || ''),
    management: String(route.query.management || ''),
    mine: String(route.query.mine || '') === '1',
  })
  Object.assign(listApplied, { ...listDraft })
}
function showStudent(row: any) {
  selectedStudent.value = row
  drawerVisible.value = true
}
async function openStudentInsight(row: any) {
  if (!row?.studentId) return
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try {
    aiInsight.value = await getStudentAIInsight(row.studentId, 'alert')
  } finally {
    aiLoading.value = false
  }
}
async function openGroupInsight() {
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try {
    aiInsight.value = await getAlertSummaryAIInsight({
      level: applied.level,
      type: applied.type,
      status: listApplied.management,
      college: applied.college,
    })
  } finally {
    aiLoading.value = false
  }
}
function openStudentFromFocus(item: any) {
  const id = item.student_id || item.studentId || item.sid || item.code
  const row = rows.value.find(current => current.studentId === id)
    || priorityRows.value.find(current => current.studentId === id)
  if (!row) return
  aiDrawerVisible.value = false
  showStudent(row)
}
async function exportCurrentList() {
  exporting.value = true
  try {
    const params = studentParams()
    params.delete('page')
    params.delete('page_size')
    const headers: Record<string, string> = {}
    const token = getToken()
    const activeIdentity = getActiveIdentity()
    if (token) headers.Authorization = `Bearer ${token}`
    if (token && activeIdentity) headers['X-Active-Identity'] = activeIdentity
    const response = await fetch(
      `/api${query('/admin/alerts/students.csv', params)}`,
      { headers },
    )
    if (!response.ok) {
      let message = '导出失败'
      try {
        const body = await response.json()
        message = body?.msg || message
      } catch {
        // 非JSON错误响应使用通用提示。
      }
      throw new Error(message)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `当前预警学生_${new Date().toISOString().slice(0, 10)}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出${response.headers.get('X-Export-Count') || ''}名学生`)
  } catch (error: any) {
    ElMessage.error(error?.message || '导出失败，请稍后重试')
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  restoreRoute()
  try {
    await loadOptions()
    Object.assign(applied, { ...draft })
  } catch (error: any) {
    loadError.value = error?.message || '筛选条件加载失败'
  }
  await loadAll()
})
</script>

<style scoped>
.monitor-head { margin-bottom: 12px; }
.monitor-title-line { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.monitor-title-line > span { color: #64748b; font-size: 12px; }
.initial-loading {
  padding: 18px; border: 1px solid var(--sa-border); border-radius: 12px; background: #fff;
}
.loading-title { color: var(--sa-text); font-size: 15px; font-weight: 700; }
.initial-loading > p { margin: 5px 0 18px; color: var(--sa-muted); font-size: 12px; }
.state-alert { margin-bottom: 12px; }
.monitor-context {
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center; gap: 12px;
  margin-bottom: 12px; padding: 10px 12px; border: 1px solid #dbeafe;
  border-radius: 9px; background: #f8fbff; color: #475569; font-size: 12px;
}
.monitor-context b { color: #1e3a8a; }
.monitor-context .filter-grid {
  display: grid; grid-template-columns: repeat(6, minmax(105px, 1fr)) auto;
  gap: 8px; min-width: 0;
}
.refresh-feedback {
  margin-bottom: 12px; padding: 8px 12px; border-radius: 8px;
  background: #eef2ff; color: #4338ca; font-size: 12px;
}
.kpi-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 16px; }
.kpi-card {
  min-width: 0; padding: 14px; text-align: left; border: 1px solid var(--sa-border);
  border-radius: 12px; background: #fff; cursor: pointer; transition: .18s ease;
}
.kpi-card:not(.static):hover { border-color: #a5b4fc; transform: translateY(-1px); }
.kpi-card.active { border-color: #6366f1; box-shadow: 0 0 0 3px #eef2ff; }
.kpi-card.static { cursor: default; }
.kpi-value { display: block; font-size: 25px; font-weight: 750; line-height: 1.1; }
.kpi-label { display: block; margin-top: 7px; color: var(--sa-text); font-size: 12px; font-weight: 600; }
.kpi-note { display: block; margin-top: 4px; overflow: hidden; color: #94a3b8; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.priority-section {
  margin-bottom: 16px; padding: 15px; border: 1px solid #fed7aa;
  border-radius: 12px; background: linear-gradient(135deg, #fffaf5, #fff);
}
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.section-head.compact { align-items: center; }
.section-head h3 { margin: 0; color: var(--sa-text); font-size: 15px; }
.section-head p { margin: 4px 0 0; color: var(--sa-muted); font-size: 11px; line-height: 1.55; }
.priority-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.priority-card {
  min-width: 0; padding: 11px; text-align: left; border: 1px solid #fed7aa;
  border-left: 3px solid #e11d48; border-radius: 9px; background: #fff;
  cursor: pointer; transition: .18s ease;
}
.priority-card:hover { box-shadow: 0 5px 16px rgba(190, 24, 93, .1); }
.priority-card > div { display: flex; justify-content: space-between; gap: 8px; }
.priority-card b { color: var(--sa-text); font-size: 13px; }
.priority-card span {
  flex: none; padding: 1px 6px; border-radius: 9px; background: #fff1f2;
  color: #be123c; font-size: 10px; font-weight: 700;
}
.priority-card p {
  display: -webkit-box; min-height: 32px; margin: 6px 0 4px; overflow: hidden;
  color: #9f1239; font-size: 11px; line-height: 16px;
  -webkit-box-orient: vertical; -webkit-line-clamp: 2;
}
.priority-card small { color: #94a3b8; }
.chart-row { margin-bottom: 16px; }
.chart-card { height: 330px; }
.list-card { margin-bottom: 16px; scroll-margin-top: 16px; }
.filter-actions { display: flex; gap: 8px; white-space: nowrap; }
.applied-summary {
  max-width: 50%; overflow: hidden; color: #4338ca; font-size: 11px;
  text-overflow: ellipsis; white-space: nowrap;
}
.list-head-actions { display: flex; align-items: center; gap: 8px; }
.list-filter-bar {
  display: flex; align-items: center; gap: 8px; margin: 2px 0 12px; padding: 9px 10px;
  border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc;
}
.list-filter-bar .el-input { width: 210px; }
.list-filter-bar .el-select { width: 150px; }
.list-filter-label { flex: none; color: #334155; font-size: 12px; font-weight: 700; }
.list-filter-hint { margin-left: auto; color: #94a3b8; font-size: 11px; }
.student-cell button {
  display: block; padding: 0; border: 0; background: transparent;
  color: var(--sa-primary); cursor: pointer; font-size: 12px; font-weight: 650;
}
.student-cell span { display: block; margin-top: 2px; color: #94a3b8; font-size: 10px; }
.reason-cell { min-width: 0; }
.reason-cell b { display: block; color: var(--sa-text); font-size: 12px; }
.reason-cell span { display: block; margin-top: 2px; overflow: hidden; color: #64748b; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.count-cell { color: #475569; font-weight: 600; }
.external-pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.table-empty { padding: 18px; color: #64748b; font-size: 12px; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover td.el-table__cell) { background: #f5f7ff !important; }
@media (max-width: 1200px) {
  .kpi-grid { grid-template-columns: repeat(3, 1fr); }
  .priority-grid { grid-template-columns: repeat(2, 1fr); }
  .monitor-context { grid-template-columns: 1fr; }
  .monitor-context .filter-grid { grid-template-columns: repeat(4, minmax(130px, 1fr)); }
  .list-filter-hint { display: none; }
}
@media (max-width: 760px) {
  .kpi-grid, .priority-grid, .monitor-context .filter-grid { grid-template-columns: 1fr; }
  .chart-row :deep(.el-col) { max-width: 100%; flex: 0 0 100%; }
  .monitor-context, .section-head { align-items: flex-start; flex-direction: column; }
  .list-head-actions, .list-filter-bar {
    align-items: stretch; flex-direction: column; width: 100%;
  }
  .list-filter-bar .el-input, .list-filter-bar .el-select { width: 100%; }
}
</style>

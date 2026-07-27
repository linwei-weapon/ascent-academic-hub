<template>
  <el-dialog
    :model-value="modelValue"
    :title="dialogTitle"
    width="min(1040px, 94vw)"
    append-to-body
    destroy-on-close
    class="metric-history-dialog"
    @update:model-value="emit('update:modelValue', $event)"
    @closed="restoreFocus"
  >
    <div class="history-scope">
      <div>
        <span>统计范围</span>
        <b>{{ scopeLabel || data.scope?.label || '当前身份授权范围' }}</b>
      </div>
      <p>{{ data.metric?.formula || metricConfig?.label || '按现有统一指标口径计算' }}</p>
    </div>

    <div class="history-filters" aria-label="历史指标查询条件">
      <label>
        <span>起始学期</span>
        <el-select v-model="draftStart" style="width: 190px">
          <el-option v-for="semester in semesters" :key="semester"
            :label="semesterLabel(semester)" :value="semester" />
        </el-select>
      </label>
      <label>
        <span>结束学期</span>
        <el-select v-model="draftEnd" style="width: 190px">
          <el-option v-for="semester in semesters" :key="semester"
            :label="semesterLabel(semester)" :value="semester" />
        </el-select>
      </label>
      <el-button type="primary" :loading="refreshing" @click="applyQuery">查询</el-button>
      <el-button :disabled="refreshing" @click="resetQuery">重置</el-button>
      <small v-if="filtersDirty">筛选条件尚未应用</small>
    </div>

    <el-alert v-if="loadError" type="error" :closable="false" show-icon
      title="历史指标加载失败" class="history-alert">
      <template #default>
        {{ loadError }} <el-button link type="primary" @click="load">重新加载</el-button>
      </template>
    </el-alert>
    <el-alert v-else-if="hasUnavailable" type="warning" :closable="false" show-icon
      title="部分学期数据不可用" description="图表以断点展示；明细表保留不可用原因，不按 0 处理。" class="history-alert" />

    <div v-if="loading && !data.periods?.length" class="history-loading">
      <el-skeleton :rows="10" animated />
      <p>正在按当前身份和统计范围读取历史数据…</p>
    </div>
    <template v-else>
      <section class="sa-card history-chart-card">
        <div class="sa-card-title">
          <span>{{ data.metric?.label || metricConfig?.label }}历年学期变化</span>
          <span class="extra">{{ appliedPeriodText }}</span>
        </div>
        <p class="history-purpose">用于纵向观察变化和识别需要核查的异常学期；空点表示数据不足或不适用。</p>
        <EChart v-if="chartableRows.length" :option="chartOption" :height="330" />
        <el-empty v-else description="当前范围暂无可绘制的历史数据" :image-size="72" />
        <div v-if="refreshing" class="history-refreshing">正在按新条件更新，当前结果暂时保留…</div>
      </section>

      <section class="sa-card history-table-card">
        <div class="sa-card-title">
          <span>历年学期明细</span>
          <span class="extra">{{ tableRows.length }} 个学期</span>
        </div>
        <DataTable
          :columns="tableColumns"
          :data="tableRows"
          :storage-key="`dashboard:metric-history:${metricId}`"
          :max-business-columns="6"
          :config-version="1"
          :pagination="true"
          :page-size="10"
          size="small"
        >
          <template #col-status="{ row }">
            <el-tooltip v-if="row.unavailableReason" :content="row.unavailableReason" placement="top">
              <el-tag size="small" :type="row.statusType">{{ row.statusLabel }}</el-tag>
            </el-tooltip>
            <el-tag v-else size="small" :type="row.statusType">{{ row.statusLabel }}</el-tag>
          </template>
        </DataTable>
      </section>

      <el-alert type="info" :closable="false" show-icon title="数据来源与使用边界"
        :description="boundaryText" />
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import EChart from '@/components/EChart.vue'
import { http } from '@/utils/http'
import {
  DASHBOARD_HISTORY_METRICS,
  DASHBOARD_SEMESTERS,
  semesterLabel,
} from '@/utils/dashboardHistory'

const props = withDefaults(defineProps<{
  modelValue: boolean
  metricId: string
  scopeType?: 'school' | 'college' | 'major'
  scopeId?: string
  scopeLabel?: string
  endSemester?: string
}>(), {
  scopeType: 'school',
  scopeId: '',
  scopeLabel: '',
  endSemester: '',
})
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const data = ref<any>({ periods: [], metric: {}, scope: {} })
const loading = ref(false)
const refreshing = ref(false)
const loadError = ref('')
const draftStart = ref(DASHBOARD_SEMESTERS[0])
const draftEnd = ref(DASHBOARD_SEMESTERS[DASHBOARD_SEMESTERS.length - 1])
const appliedStart = ref(draftStart.value)
const appliedEnd = ref(draftEnd.value)
let requestSequence = 0
let focusTarget: HTMLElement | null = null

const semesters = computed(() => data.value.availableSemesters?.length
  ? data.value.availableSemesters : [...DASHBOARD_SEMESTERS])
const metricConfig = computed(() => DASHBOARD_HISTORY_METRICS[props.metricId])
const dialogTitle = computed(() => `${props.scopeLabel || data.value.scope?.label || '当前范围'} · ${data.value.metric?.label || metricConfig.value?.label || '历史指标'}`)
const filtersDirty = computed(() => draftStart.value !== appliedStart.value || draftEnd.value !== appliedEnd.value)
const hasUnavailable = computed(() => (data.value.periods || []).some((row: any) => row.status !== 'available'))
const chartableRows = computed(() => (data.value.periods || []).filter((row: any) => row.value != null))
const appliedPeriodText = computed(() => `${semesterLabel(appliedStart.value)} 至 ${semesterLabel(appliedEnd.value)}`)
const boundaryText = computed(() => [
  data.value.metric?.source ? `数据来源：${data.value.metric.source}` : '',
  data.value.boundary || '',
].filter(Boolean).join('；'))

const tableColumns = computed<DataTableColumn[]>(() => {
  const base: DataTableColumn[] = [
    { key: 'semesterLabel', label: '学年学期', minWidth: 180, fixed: 'left', region: 'identity', required: true },
    { key: 'valueText', label: data.value.metric?.label || metricConfig.value?.label || '指标值', width: 140, align: 'right', required: true },
    { key: 'changeText', label: '较上学期', width: 120, align: 'right' },
  ]
  if (data.value.metric?.chart === 'gpa' || metricConfig.value?.chart === 'gpa') {
    base.push({ key: 'numerator', label: '有 GPA 学生数', width: 135, align: 'right' })
  } else {
    base.push(
      { key: 'numerator', label: data.value.metric?.numeratorLabel || '分子', width: 140, align: 'right' },
      { key: 'denominator', label: data.value.metric?.denominatorLabel || '分母', width: 140, align: 'right' },
    )
  }
  base.push({ key: 'status', label: '数据状态', width: 112, region: 'action', required: true })
  return base
})

const tableRows = computed(() => (data.value.periods || []).map((row: any) => {
  const unit = data.value.metric?.unit ?? metricConfig.value?.unit ?? ''
  const status = {
    available: { label: '可用', type: 'success' },
    insufficient: { label: '数据不足', type: 'warning' },
    unavailable: { label: '不可用', type: 'info' },
  }[row.status as 'available' | 'insufficient' | 'unavailable'] || { label: '待核验', type: 'warning' }
  return {
    ...row,
    valueText: row.value == null ? '—' : `${Number(row.value).toFixed(unit === '%' ? 1 : 2)}${unit}`,
    changeText: row.change == null ? '—' : `${row.change > 0 ? '+' : ''}${Number(row.change).toFixed(unit === '%' ? 1 : 2)}${unit === '%' ? '个百分点' : ''}`,
    statusLabel: status.label,
    statusType: status.type,
  }
}))

const chartOption = computed(() => {
  const rows = data.value.periods || []
  const labels = rows.map((row: any) => row.semesterLabel)
  const unit = data.value.metric?.unit ?? metricConfig.value?.unit ?? ''
  const color = metricConfig.value?.color || '#4f46e5'
  if ((data.value.metric?.chart || metricConfig.value?.chart) === 'gpa') {
    return {
      tooltip: { trigger: 'axis', valueFormatter: (value: any) => value == null ? '不可用' : Number(value).toFixed(2) },
      legend: { data: ['学生平均 GPA'], bottom: 0 },
      grid: { left: 48, right: 24, top: 28, bottom: 64 },
      xAxis: { type: 'category', data: labels, axisLabel: { rotate: 24 } },
      yAxis: { type: 'value', name: 'GPA', min: 0, max: 5 },
      series: [{
        name: '学生平均 GPA', type: 'line', smooth: true, connectNulls: false,
        data: rows.map((row: any) => row.value), itemStyle: { color }, lineStyle: { color, width: 3 }, symbolSize: 7,
      }],
    }
  }
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: [data.value.metric?.numeratorLabel || '分子', '其余', data.value.metric?.label || '比率'], bottom: 0 },
    grid: { left: 54, right: 54, top: 28, bottom: 64 },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 24 } },
    yAxis: [
      { type: 'value', name: '人数/人次', min: 0 },
      { type: 'value', name: unit || '%', min: 0, max: unit === '%' ? 100 : undefined },
    ],
    series: [
      {
        name: data.value.metric?.numeratorLabel || '分子', type: 'bar', stack: 'total',
        data: rows.map((row: any) => row.numerator), itemStyle: { color },
      },
      {
        name: '其余', type: 'bar', stack: 'total',
        data: rows.map((row: any) => row.denominator == null || row.numerator == null ? null : Math.max(row.denominator - row.numerator, 0)),
        itemStyle: { color: '#e2e8f0' },
      },
      {
        name: data.value.metric?.label || '比率', type: 'line', yAxisIndex: 1, smooth: true,
        connectNulls: false, data: rows.map((row: any) => row.value),
        itemStyle: { color }, lineStyle: { color, width: 3 }, symbolSize: 7,
      },
    ],
  }
})

async function load() {
  if (!props.metricId) return
  const sequence = ++requestSequence
  const hasRows = !!data.value.periods?.length
  loading.value = !hasRows
  refreshing.value = hasRows
  loadError.value = ''
  const params = new URLSearchParams({
    metricId: props.metricId,
    scopeType: props.scopeType,
    startSemester: appliedStart.value,
    endSemester: appliedEnd.value,
  })
  if (props.scopeId) params.set('scopeId', props.scopeId)
  try {
    const result = await http.get<any>(`/admin/dashboard/metric-history?${params.toString()}`)
    if (sequence === requestSequence) data.value = result || { periods: [] }
  } catch (error: any) {
    if (sequence === requestSequence) loadError.value = error?.message || '请稍后重试'
  } finally {
    if (sequence === requestSequence) {
      loading.value = false
      refreshing.value = false
    }
  }
}

function applyQuery() {
  const startIndex = semesters.value.indexOf(draftStart.value)
  const endIndex = semesters.value.indexOf(draftEnd.value)
  if (startIndex < 0 || endIndex < 0 || startIndex > endIndex) {
    ElMessage.warning('起始学期不能晚于结束学期')
    return
  }
  appliedStart.value = draftStart.value
  appliedEnd.value = draftEnd.value
  void load()
}

function resetQuery() {
  draftStart.value = semesters.value[0]
  draftEnd.value = props.endSemester && semesters.value.includes(props.endSemester)
    ? props.endSemester : semesters.value[semesters.value.length - 1]
  appliedStart.value = draftStart.value
  appliedEnd.value = draftEnd.value
  void load()
}

function restoreFocus() {
  void nextTick(() => focusTarget?.focus())
}

watch(
  () => [props.modelValue, props.metricId, props.scopeType, props.scopeId, props.endSemester],
  ([open]) => {
    if (!open) return
    focusTarget = document.activeElement instanceof HTMLElement ? document.activeElement : null
    data.value = { periods: [], metric: {}, scope: {} }
    draftStart.value = DASHBOARD_SEMESTERS[0]
    draftEnd.value = props.endSemester && DASHBOARD_SEMESTERS.includes(props.endSemester as any)
      ? props.endSemester as typeof draftEnd.value : DASHBOARD_SEMESTERS[DASHBOARD_SEMESTERS.length - 1]
    appliedStart.value = draftStart.value
    appliedEnd.value = draftEnd.value
    void load()
  },
  { immediate: true },
)
</script>

<style scoped>
.history-scope {
  display: grid;
  grid-template-columns: minmax(180px, auto) 1fr;
  align-items: center;
  gap: 18px;
  padding: 12px 14px;
  border: 1px solid var(--sa-border);
  border-radius: 10px;
  background: var(--sa-bg);
}
.history-scope > div { display: grid; gap: 3px; }
.history-scope span { color: var(--sa-muted); font-size: 12px; }
.history-scope b { color: var(--sa-text); }
.history-scope p { margin: 0; color: var(--sa-muted); font-size: 12px; line-height: 1.6; }
.history-filters { display: flex; align-items: end; flex-wrap: wrap; gap: 10px; margin: 14px 0; }
.history-filters label { display: grid; gap: 5px; color: var(--sa-muted); font-size: 12px; }
.history-filters small { color: var(--sa-amber); align-self: center; }
.history-alert { margin-bottom: 12px; }
.history-loading { min-height: 420px; display: grid; align-content: start; gap: 12px; }
.history-loading p, .history-purpose { color: var(--sa-muted); font-size: 12px; }
.history-loading p { text-align: center; }
.history-chart-card, .history-table-card { margin-bottom: 14px; position: relative; }
.history-purpose { margin: -7px 0 8px; }
.history-refreshing { position: absolute; inset: 0; display: grid; place-items: center; background: color-mix(in srgb, #fff 82%, transparent); color: var(--sa-primary); font-size: 13px; }
@media (max-width: 720px) {
  .history-scope { grid-template-columns: 1fr; }
  .history-filters { align-items: stretch; }
  .history-filters label, .history-filters :deep(.el-select) { width: 100% !important; }
}
</style>

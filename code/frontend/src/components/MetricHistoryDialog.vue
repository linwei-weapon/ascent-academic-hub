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
          <el-option v-for="option in semesters" :key="option.value"
            :label="option.label" :value="option.value" />
        </el-select>
      </label>
      <label>
        <span>结束学期</span>
        <el-select v-model="draftEnd" style="width: 190px">
          <el-option v-for="option in semesters" :key="option.value"
            :label="option.label" :value="option.value" />
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
      title="“-”：表示学年学期对应内容无数据或无计算结果。" class="history-alert" />

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
        <template v-if="chartableRows.length">
          <EChart :option="chartOption" :height="330" />
          <div v-if="isRatioChart" class="history-chart-legend" aria-label="历史比率图图例">
            <span>
              <i class="legend-swatch bar" :style="{ backgroundColor: historyColor }"></i>
              {{ numeratorLegendLabel }}
            </span>
            <span>
              <i class="legend-swatch outline"></i>
              {{ denominatorLegendLabel }}（柱总高）
            </span>
            <span>
              <i class="legend-swatch line"
                :style="{ borderTopColor: historyColor, color: historyColor }"></i>
              {{ rateLegendLabel }}
            </span>
          </div>
        </template>
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
          :max-business-columns="5"
          :config-version="2"
          :pagination="true"
          :page-size="10"
          size="small"
        />
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
import { DASHBOARD_HISTORY_METRICS } from '@/utils/dashboardHistory'
import type { SemesterOpt } from '@/utils/meta'

const props = withDefaults(defineProps<{
  modelValue: boolean
  metricId: string
  scopeType?: 'school' | 'college' | 'major'
  scopeId?: string
  scopeLabel?: string
  endSemester?: string
  semesterOptions?: SemesterOpt[]
}>(), {
  scopeType: 'school',
  scopeId: '',
  scopeLabel: '',
  endSemester: '',
  semesterOptions: () => [],
})
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const data = ref<any>({ periods: [], metric: {}, scope: {} })
const loading = ref(false)
const refreshing = ref(false)
const loadError = ref('')
const draftStart = ref('')
const draftEnd = ref('')
const appliedStart = ref(draftStart.value)
const appliedEnd = ref(draftEnd.value)
let requestSequence = 0
let focusTarget: HTMLElement | null = null

const semesters = computed<SemesterOpt[]>(() => props.semesterOptions.length
  ? props.semesterOptions
  : (data.value.availableSemesters || []).map((value: string) => ({
      value,
      label: value,
      current: value === props.endSemester,
    })))
const semesterValues = computed(() => semesters.value.map(option => option.value))
const historyPeriods = computed(() => data.value.periods || [])
const metricConfig = computed(() => DASHBOARD_HISTORY_METRICS[props.metricId])
const isRatioChart = computed(() =>
  (data.value.metric?.chart || metricConfig.value?.chart) === 'ratio')
const historyColor = computed(() => metricConfig.value?.color || '#4f46e5')
const numeratorLegendLabel = computed(() => data.value.metric?.numeratorLabel || '分子')
const denominatorLegendLabel = computed(() => data.value.metric?.denominatorLabel || '分母')
const rateLegendLabel = computed(() => data.value.metric?.label || '比率')
const dialogTitle = computed(() => `${props.scopeLabel || data.value.scope?.label || '当前范围'} · ${data.value.metric?.label || metricConfig.value?.label || '历史指标'}`)
const filtersDirty = computed(() => draftStart.value !== appliedStart.value || draftEnd.value !== appliedEnd.value)
const hasUnavailable = computed(() => historyPeriods.value.some((row: any) => row.status !== 'available'))
const chartableRows = computed(() => historyPeriods.value.filter((row: any) => row.value != null))
const displaySemester = (value: string) =>
  semesters.value.find(option => option.value === value)?.label || value || '—'
const appliedPeriodText = computed(() => `${displaySemester(appliedStart.value)} 至 ${displaySemester(appliedEnd.value)}`)
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
  return base
})

const tableRows = computed(() => historyPeriods.value.map((row: any) => {
  const unit = data.value.metric?.unit ?? metricConfig.value?.unit ?? ''
  return {
    ...row,
    semesterLabel: displaySemester(row.semester),
    valueText: row.value == null ? '-' : `${Number(row.value).toFixed(unit === '%' ? 1 : 2)}${unit}`,
    changeText: row.change == null ? '-' : `${row.change > 0 ? '+' : ''}${Number(row.change).toFixed(unit === '%' ? 1 : 2)}${unit === '%' ? '个百分点' : ''}`,
  }
}))

const chartOption = computed(() => {
  const rows = historyPeriods.value
  const labels = rows.map((row: any) => displaySemester(row.semester))
  const unit = data.value.metric?.unit ?? metricConfig.value?.unit ?? ''
  const color = metricConfig.value?.color || '#4f46e5'
  if ((data.value.metric?.chart || metricConfig.value?.chart) === 'gpa') {
    return {
      tooltip: { trigger: 'axis', valueFormatter: (value: any) => value == null ? '-' : Number(value).toFixed(2) },
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
  const numeratorLabel = data.value.metric?.numeratorLabel || '分子'
  const denominatorLabel = data.value.metric?.denominatorLabel || '分母'
  const rateLabel = data.value.metric?.label || '比率'
  const countUnit = `${numeratorLabel}${denominatorLabel}`.includes('人次') ? '人次' : '人'
  const countValueFormatter = (value: any) => value == null
    ? '-' : `${Number(value).toLocaleString('zh-CN')}${countUnit}`
  return {
    tooltip: { trigger: 'axis' },
    legend: { show: false },
    grid: { left: 68, right: 60, top: 28, bottom: 52 },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 24 } },
    yAxis: [
      {
        type: 'value',
        min: 0,
        axisLabel: {
          formatter: (value: any) => `${Number(value).toLocaleString('zh-CN')}${countUnit}`,
        },
      },
      {
        type: 'value',
        min: 0,
        max: unit === '%' ? 100 : undefined,
        axisLabel: { formatter: (value: any) => `${value}%` },
      },
    ],
    series: [
      {
        name: numeratorLabel, type: 'bar', z: 2, barWidth: '52%',
        data: rows.map((row: any) => row.numerator),
        itemStyle: { color },
        tooltip: { valueFormatter: countValueFormatter },
      },
      {
        name: denominatorLabel, type: 'bar', z: 3, barWidth: '52%', barGap: '-100%',
        data: rows.map((row: any) => row.denominator),
        itemStyle: {
          color: 'transparent',
          borderColor: '#94a3b8',
          borderWidth: 1.5,
          borderType: 'dashed',
        },
        tooltip: { valueFormatter: countValueFormatter },
      },
      {
        name: rateLabel, type: 'line', yAxisIndex: 1, smooth: true,
        connectNulls: false, data: rows.map((row: any) => row.value),
        itemStyle: { color }, lineStyle: { color, width: 3 }, symbolSize: 7,
        tooltip: {
          valueFormatter: (value: any) => value == null ? '-' : `${Number(value).toFixed(1)}%`,
        },
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
  const startIndex = semesterValues.value.indexOf(draftStart.value)
  const endIndex = semesterValues.value.indexOf(draftEnd.value)
  if (startIndex < 0 || endIndex < 0 || startIndex < endIndex) {
    ElMessage.warning('起始学期不能晚于结束学期')
    return
  }
  appliedStart.value = draftStart.value
  appliedEnd.value = draftEnd.value
  void load()
}

function resetQuery() {
  draftStart.value = semesterValues.value[semesterValues.value.length - 1] || ''
  draftEnd.value = props.endSemester && semesterValues.value.includes(props.endSemester)
    ? props.endSemester : (semesterValues.value[0] || '')
  appliedStart.value = draftStart.value
  appliedEnd.value = draftEnd.value
  void load()
}

function restoreFocus() {
  void nextTick(() => focusTarget?.focus())
}

watch(
  () => [
    props.modelValue,
    props.metricId,
    props.scopeType,
    props.scopeId,
    props.endSemester,
    props.semesterOptions,
  ],
  ([open]) => {
    if (!open) return
    focusTarget = document.activeElement instanceof HTMLElement ? document.activeElement : null
    data.value = { periods: [], metric: {}, scope: {} }
    draftStart.value = semesterValues.value[semesterValues.value.length - 1] || ''
    draftEnd.value = props.endSemester && semesterValues.value.includes(props.endSemester)
      ? props.endSemester : (semesterValues.value[0] || '')
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
.history-chart-legend {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 18px;
  min-height: 22px;
  color: var(--sa-muted);
  font-size: 12px;
}
.history-chart-legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend-swatch { display: inline-block; width: 20px; height: 10px; flex: none; }
.legend-swatch.bar { border-radius: 2px; }
.legend-swatch.outline {
  border: 1.5px dashed #94a3b8;
  border-radius: 2px;
  background: transparent;
}
.legend-swatch.line {
  position: relative;
  height: 0;
  border-top: 3px solid;
}
.legend-swatch.line::after {
  content: '';
  position: absolute;
  top: -5px;
  left: 7px;
  width: 5px;
  height: 5px;
  border: 2px solid currentColor;
  border-radius: 50%;
  background: #fff;
}
.history-refreshing { position: absolute; inset: 0; display: grid; place-items: center; background: color-mix(in srgb, #fff 82%, transparent); color: var(--sa-primary); font-size: 13px; }
@media (max-width: 720px) {
  .history-scope { grid-template-columns: 1fr; }
  .history-filters { align-items: stretch; }
  .history-filters label, .history-filters :deep(.el-select) { width: 100% !important; }
}
</style>

<!-- 教学运行分析：ScheduleChanges 页面或专用组件，保留原业务与权限行为。 -->
<template>
  <div v-loading="loading && !!kpis.length" element-loading-text="正在按新条件更新调停课分析，当前结果暂时保留…">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">调停课趋势分析</h2>
      </div>
      <el-select v-model="fCollege" size="small" clearable placeholder="全部学院" style="width:160px" @change="load">
        <el-option v-for="college in colleges" :key="college.value" :label="college.label" :value="college.value" />
      </el-select>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon title="调停课分析加载失败"
      :description="loadError" style="margin-bottom:12px"><template #default><el-button link type="primary" @click="load">重新加载</el-button></template></el-alert>
    <div v-else-if="loading && !kpis.length" class="sa-card" style="margin-bottom:12px"><el-skeleton :rows="8" animated /></div>

    <div class="sa-kpi-row">
      <KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="kpiTone(k.label)" />
    </div>
    <div class="ai-toolbar">
      <el-button size="small" type="primary" plain @click="openScheduleAi()">生成当前调课重点</el-button>
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">按学院调停课率排名</div>
          <AppTable :columns="deptRankCols" :data="data.deptRanks" storage-key="operation:schedule-changes-dept"  config-version="2" :show-density="true" :show-column-settings="true" :pagination="false">
            <template #header-changeCount><KpiLabel label="调停课次数" formula="该学院下所有开课教学任务调停课记录总数" /></template>
            <template #header-pct><KpiLabel label="调停课率" formula="该学院下所有开课教学任务调停课去重记录数 ÷ 该学院下所有的教学任务数（教学任务就是教学班）" /></template>
            <template #col-attention="{row,$index}"><el-tag size="small" :type="$index<3?'danger':row.pct>=3?'warning':'info'">{{$index<3?'优先关注':row.pct>=3?'需关注':'常规'}}</el-tag></template>
            <template #col-pct="{row}">
              <div style="display:flex;align-items:center;gap:8px">
                <el-progress :percentage="Math.min(row.pct*20,100)" :show-text="false" :stroke-width="8" :color="row.pct>4?'#E11D48':'#D97706'" style="flex:1" />
                <span class="tnum" :style="{color:row.pct>4?'#E11D48':'#D97706',fontWeight:600,minWidth:'42px',textAlign:'right'}">{{ row.pct }}%</span>
              </div>
            </template>
          </AppTable>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="schedule-side-stack">
          <div class="sa-card">
            <div class="sa-card-title">调课原因语义分类 <KpiLabel label="" :formula="data.classification.explanation" /></div>
            <EChart v-if="data.semanticReasonDist.length" :option="reasonOption" :height="180" />
            <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          </div>
          <div class="sa-card">
            <div class="sa-card-title">教师调停课 TOP10 <KpiLabel label="" formula="统计每位教师的调停课事件总次数，进入列表条件为总次数 `≥3`；最多 10 人" /></div>
            <AppTable :columns="teacherTopCols" :data="data.frequentTeachers" storage-key="operation:schedule-changes-teachers"  @row-click="inspectTeacher" row-class-name="row-clickable" :show-density="true" :show-column-settings="true" :pagination="false">
              <template #col-name="{row}"><span class="link">{{ row.name }}</span></template>
              <template #col-attention="{row}"><el-tag size="small" :type="teacherNeedsAi(row)?'danger':'warning'">{{teacherNeedsAi(row)?'重点关注':'需关注'}}</el-tag></template>
            </AppTable>
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">月度调停课趋势 <KpiLabel label="" formula="按月统计调停课次数变化" /></div>
      <EChart v-if="data.monthlyTrend.length" :option="monthlyOption" :height="220" />
      <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
    </div>

    <el-drawer v-model="teacherDrawer" :title="`${selectedTeacher.name || ''}｜调课原因信息`" size="620px">
      <div class="teacher-summary"><b>{{ selectedTeacher.count || 0 }}</b><span>调停课记录</span><b>{{ selectedTeacher.reasonBreakdown?.length || 0 }}</b><span>原始原因类型</span></div>
      <AppTable :data="selectedTeacher.reasonBreakdown || []"  stripe :columns="[]" storage-key="teaching-analysis:operation:schedulechanges:3" :pagination="false">
        <template #columns>
        <el-table-column prop="reason" label="原始原因文本" min-width="180" align="center" header-align="center"/>
        <el-table-column prop="semanticCategory" label="语义分类" min-width="150" align="center" header-align="center"/>
        <el-table-column prop="count" label="次数" min-width="80" align="center" header-align="center"/>
              </template>
      </AppTable>
      <div class="drawer-actions">
        <span v-if="!teacherNeedsAi(selectedTeacher)" class="sa-faint">当前未列入重点关注范围，核对原始原因即可。</span>
        <el-button v-else type="primary" plain @click="openTeacherAi(selectedTeacher)">查看调课研判</el-button>
      </div>
    </el-drawer>
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="调课治理研判"
      hide-intervention-tag hide-decision-meta hide-baseline hide-consequence hide-expected-result
      hide-no-comparison-tag hide-trace hide-trace-shortcut hide-evidence-help hide-evidence-source show-all-evidence />
  </div>
</template>

<script setup lang="ts">
import * as operationApi from '@/api/teachingAnalysis/operation'


import { reactive, ref, computed, watch, onMounted, inject, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import { getFilterMeta } from '@/api/shared/filterMeta'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import { getScheduleChangesAIInsight, getScheduleTeacherAIInsight } from '@/api/teachingAnalysis/insights'
const route = useRoute()

// 按学院调停课率排名 / 教师调停课 TOP10 表列定义（AppTable）
const deptRankCols: AppTableColumn[] = [
  { key: 'name', label: '学院', minWidth: 130, required:true, region:'identity', fixed:'left' },
  { key: 'totalLessons', label: '教学班数', minWidth: 84, align: 'center', required:true },
  { key: 'changeCount', label: '调停课次数', minWidth: 110, align: 'center', required:true },
  { key: 'attention', label: '管理关注', minWidth: 100, required:true },
  { key: 'pct', label: '调停课率', minWidth: 170, required:true },
]
const teacherTopCols: AppTableColumn[] = [
  { key: 'name', label: '教师', minWidth: 80, required:true, region:'identity', fixed:'left' },
  { key: 'dept', label: '学院', minWidth: 120 },
  { key: 'count', label: '次数', minWidth: 60, align: 'center', required:true },
  { key: 'attention', label: '管理关注', minWidth: 100, required:true },
  { key: 'reason', label: '主要原因', minWidth: 110 },
]
const fSemester = inject<Ref<string>>('operationSemester', ref(''))
const fCollege = ref('')
const colleges = ref<{value:string;label:string}[]>([])

const kpis = ref<any[]>([])
const loading = ref(false)
const loadError = ref('')
const data = reactive<any>({
  deptRanks: [], reasonDist: [], semanticReasonDist: [], frequentTeachers: [], monthlyTrend: [], classification: {}, dataLimitation: '',
})
const teacherDrawer = ref(false)
const selectedTeacher = ref<any>({})
const aiDrawerVisible = ref(false)
const aiLoading = ref(false)
const aiInsight = ref<any>(null)
function inspectTeacher(row:any) { selectedTeacher.value = row; teacherDrawer.value = true }
const teacherAiIds = computed(() => new Set((data.frequentTeachers || []).slice(0, 3).map((row:any) => row.id || row.teacher_id || row.teacherId)))
function teacherNeedsAi(row:any) { return teacherAiIds.value.has(row?.id || row?.teacher_id || row?.teacherId) }

async function openScheduleAi(row?: any) {
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try {
    aiInsight.value = await getScheduleChangesAIInsight({
      semester: fSemester.value,
      college: row?.id || fCollege.value || undefined,
    })
  } finally { aiLoading.value = false }
}

async function openTeacherAi(row: any) {
  const teacherId = row?.id || row?.teacher_id || row?.teacherId
  if (!teacherId) return
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try { aiInsight.value = await getScheduleTeacherAIInsight(teacherId, fSemester.value) }
  finally { aiLoading.value = false }
}

// 按当前页面上下文读取数据，沿用原加载状态和异常处理。
async function load() {
  loading.value = true
  loadError.value = ''
  try {
  const params = new URLSearchParams()
  if (fCollege.value) params.set('college', fCollege.value)
  if (fSemester.value) params.set('semester', fSemester.value)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const d = await operationApi.getScheduleChanges(qs)
  kpis.value = (d && d.kpis) || []
  Object.assign(data, { deptRanks: [], reasonDist: [], semanticReasonDist: [], frequentTeachers: [], monthlyTrend: [], classification: {}, dataLimitation: '' }, d || {})
  } catch (error:any) {
    loadError.value = error?.message || '调停课分析加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}
// 进入页面时执行原初始化流程，恢复路由条件与可用选项。
onMounted(async () => {
  const meta = await getFilterMeta()
  colleges.value = meta.colleges || []
  const routeCollege = String(route.query.college || '')
  if (colleges.value.some(item => item.value === routeCollege)) fCollege.value = routeCollege
  if (!fSemester.value) fSemester.value = meta.current
  await load()
})
// 按既有监听条件响应路由、筛选或身份变化，保留原重载与清理时机。
watch(fSemester, (value, oldValue) => {
  if (oldValue && value !== oldValue) load()
})

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('停课') || label.includes('受影响')) return 'danger'
  if (label.includes('覆盖率')) return 'teal'
  return 'primary'
}

const reasonOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c} 次（{d}%）' },
  legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748B', fontSize: 11 } },
  series: [{
    type: 'pie', radius: ['46%', '72%'], center: ['34%', '50%'], avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 }, label: { show: false },
    data: (data.semanticReasonDist || []).map((r: any) => ({ name: r.name, value: r.count, itemStyle: { color: r.color } })),
  }],
}))

const monthlyOption = computed(() => {
  const m = data.monthlyTrend || []
  return {
    grid: { left: 6, right: 12, top: 24, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: m.map((x: any) => x.month), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    series: [{
      type: 'line', smooth: true, data: m.map((x: any) => x.count), symbolSize: 8,
      lineStyle: { width: 3, color: '#D97706' }, itemStyle: { color: '#D97706' },
      areaStyle: { color: 'rgba(217,119,6,0.10)' },
      label: { show: true, position: 'top', formatter: '{c}', color: '#64748B', fontSize: 11 },
    }],
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

.ai-toolbar {
  display: flex;
  justify-content: flex-end;
  margin: -4px 0 12px;
}

.schedule-side-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.link {
  color: var(--sa-primary);
  cursor: pointer;
  font-weight: 500;
  &:hover {
    text-decoration: underline;
  }
}

:deep(.row-clickable) {
  cursor: pointer;
}

:deep(.row-clickable:hover) {
  background: #eef2ff !important;
}

.teacher-summary {
  display: grid;
  grid-template-columns: auto 1fr auto 1fr;
  align-items: end;
  gap: 5px 8px;
  padding: 14px 0;
  b {
    color: #1e3a5f;
    font-size: 24px;
  }
  span {
    color: #64748b;
    font-size: 12px;
    padding-bottom: 3px;
  }
}

.drawer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
  .sa-faint {
    margin-right: auto;
  }
}
</style>

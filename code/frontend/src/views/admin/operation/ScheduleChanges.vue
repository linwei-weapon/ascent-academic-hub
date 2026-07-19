<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">调停课趋势分析</h2>
        <p class="sa-page-sub">数据来源：调停课记录表(CL_ROOM_APPLIES) · {{ selectedSemesterLabel }}</p>
      </div>
      <el-select v-model="fSemester" size="small" style="width:200px" @change="load">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
    </div>

    <div v-if="collegeFilter" class="filter-banner">
      <span>当前学院视图：<b>{{ collegeFilter.name }}</b></span>
      <el-button size="small" type="primary" text @click="clearCollegeFilter">← 返回全院视图</el-button>
    </div>

    <el-alert type="warning" :closable="false" show-icon style="margin-bottom:12px"
      title="当前为调课分析交互原型"
      :description="data.dataLimitation || '生产系统需接入真实调课申请和原始原因文本。'" />

    <div class="sa-kpi-row">
      <KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="kpiTone(k.label)" />
    </div>
    <div class="ai-toolbar">
      <el-button size="small" type="primary" plain @click="openScheduleAi()">生成当前调课重点</el-button>
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">按学院调课率排名 <KpiLabel label="" formula="调课率=调课次数÷该院教学班数×100%" /></div>
          <el-table :data="data.deptRanks" size="small" @row-click="goCollege" row-class-name="row-clickable">
            <el-table-column prop="name" label="学院" width="130"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
            <el-table-column prop="totalLessons" label="教学班数" width="84" align="right" />
            <el-table-column prop="changeCount" label="调课次数" width="84" align="right" />
            <el-table-column label="管理关注" width="100"><template #default="{row,$index}"><el-tag size="small" :type="$index<3?'danger':row.pct>=3?'warning':'info'">{{$index<3?'优先核查':row.pct>=3?'需关注':'常规'}}</el-tag></template></el-table-column>
            <el-table-column label="调课率" min-width="150"><template #default="{row}">
              <div style="display:flex;align-items:center;gap:8px">
                <el-progress :percentage="Math.min(row.pct*20,100)" :show-text="false" :stroke-width="8" :color="row.pct>4?'#E11D48':'#D97706'" style="flex:1" />
                <span class="tnum" :style="{color:row.pct>4?'#E11D48':'#D97706',fontWeight:600,minWidth:'42px',textAlign:'right'}">{{ row.pct }}%</span>
              </div>
            </template></el-table-column>
          </el-table>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card" style="margin-bottom:12px">
          <div class="sa-card-title">调课原因语义分类 <KpiLabel label="" :formula="data.classification.explanation" /></div>
          <EChart v-if="data.semanticReasonDist.length" :option="reasonOption" :height="180" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          <div class="classification-note">规则已分类 {{ data.classification.classifiedRecords || 0 }} 条 · 待核验 {{ data.classification.unclassifiedRecords || 0 }} 条 · 未启用外部AI</div>
        </div>
        <div class="sa-card">
          <div class="sa-card-title">教师调课 TOP10 <span class="extra">本学期 ≥ 3 次 · 点击核查原因</span></div>
          <el-table :data="data.frequentTeachers" size="small" @row-click="inspectTeacher" row-class-name="row-clickable">
            <el-table-column prop="name" label="教师" width="80"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
            <el-table-column prop="dept" label="学院" width="120" />
            <el-table-column prop="count" label="次数" width="60" align="right" />
            <el-table-column label="管理关注" width="100"><template #default="{row}"><el-tag size="small" :type="teacherNeedsAi(row)?'danger':'warning'">{{teacherNeedsAi(row)?'AI重点':'需核查'}}</el-tag></template></el-table-column>
            <el-table-column prop="reason" label="主要原因" min-width="110" />
          </el-table>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">月度调课趋势 <KpiLabel label="" formula="按月统计调课次数变化" /></div>
      <EChart v-if="data.monthlyTrend.length" :option="monthlyOption" :height="220" />
      <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
    </div>

    <el-drawer v-model="teacherDrawer" :title="`${selectedTeacher.name || ''}｜调课原因核查`" size="620px">
      <el-alert type="info" :closable="false" show-icon title="语义分类仅用于汇总管理原因，核查时必须查看原始原因文本。" />
      <div class="teacher-summary"><b>{{ selectedTeacher.count || 0 }}</b><span>调停课记录</span><b>{{ selectedTeacher.reasonBreakdown?.length || 0 }}</b><span>原始原因类型</span></div>
      <el-table :data="selectedTeacher.reasonBreakdown || []" size="small" stripe>
        <el-table-column prop="reason" label="原始原因文本" min-width="180" />
        <el-table-column prop="semanticCategory" label="语义分类" width="150" />
        <el-table-column prop="count" label="次数" width="80" align="right" />
      </el-table>
      <div class="drawer-actions">
        <span v-if="!teacherNeedsAi(selectedTeacher)" class="sa-faint">当前频次未达到 AI 重点阈值，核对原始原因即可。</span>
        <el-button v-else type="primary" plain @click="openTeacherAi(selectedTeacher)">查看 AI 调课研判</el-button>
        <el-button type="primary" plain @click="goTeacher(selectedTeacher)">查看教师教学档案</el-button>
      </div>
    </el-drawer>
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="调课治理AI研判" />
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, ref, computed, watch, onMounted, inject, type Ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import { COLLEGE_MAP } from '@/constants/colleges'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import { getScheduleChangesAIInsight, getScheduleTeacherAIInsight } from '@/utils/ai'
const router = useRouter(); const route = useRoute()
const collegeFilter = ref<{id:string;name:string}|null>(null)
const collegeMap = COLLEGE_MAP
function applyCollegeFilter() { const cid = route.query.college as string; collegeFilter.value = (cid && collegeMap[cid]) ? { id: cid, name: collegeMap[cid] } : null }
applyCollegeFilter(); watch(() => route.query.college, () => { applyCollegeFilter(); load() })
function clearCollegeFilter() { collegeFilter.value = null; router.replace({ query: {} }) }
function goCollege(row: any) { router.push({ query: { college: row.id } }) }
function goTeacher(row: any) { router.push({ path: '/admin/faculty/' + row.id, query: fSemester.value ? { semester: fSemester.value } : {} }) }

const fSemester = inject<Ref<string>>('operationSemester', ref(''))
const semesters = ref<SemesterOpt[]>([])
const selectedSemesterLabel = computed(() => semesters.value.find(s => s.value === fSemester.value)?.label || '')

const kpis = ref<any[]>([])
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
      college: row?.id || (route.query.college as string) || undefined,
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

async function load() {
  const cid = route.query.college as string
  const params = new URLSearchParams()
  if (cid && collegeMap[cid]) params.set('college', cid)
  if (fSemester.value) params.set('semester', fSemester.value)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const d = await http.get('/admin/operation/schedule-changes' + qs)
  kpis.value = (d && d.kpis) || []
  Object.assign(data, { deptRanks: [], reasonDist: [], semanticReasonDist: [], frequentTeachers: [], monthlyTrend: [], classification: {}, dataLimitation: '' }, d || {})
}
onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  if (!fSemester.value) fSemester.value = meta.current
  await load()
})

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('停课') || label.includes('受影响')) return 'danger'
  if (label.includes('自动审核')) return 'teal'
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

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.ai-toolbar { display:flex; justify-content:flex-end; margin:-4px 0 12px; }
.filter-banner { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 10px; padding: 8px 14px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--sa-primary); }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
.classification-note { padding-top:8px; border-top:1px solid var(--sa-border); color:#64748b; font-size:11px; }
.teacher-summary { display:grid; grid-template-columns:auto 1fr auto 1fr; align-items:end; gap:5px 8px; padding:14px 0; }
.teacher-summary b { color:#1e3a5f; font-size:24px; }
.teacher-summary span { color:#64748b; font-size:12px; padding-bottom:3px; }
.drawer-actions { display:flex; align-items:center; justify-content:flex-end; gap:8px; margin-top:14px; }.drawer-actions .sa-faint{margin-right:auto}
</style>

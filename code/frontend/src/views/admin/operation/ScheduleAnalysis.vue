<template>
  <div>
    <!-- 筛选行 -->
    <div style="display:flex;gap:12px;margin-bottom:16px;align-items:center">
      <el-select v-model="fSemester" placeholder="选择学期" clearable size="small" style="width:160px" @change="load">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-button size="small" @click="load" type="primary">查询</el-button>
      <span class="sa-faint" style="font-size:12px">数据来源：agg_course_category_term 预聚合表</span>
    </div>

    <!-- KPI 卡片 -->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="6" v-for="(k, i) in kpis" :key="i">
        <div class="kpi-card">
          <div class="kpi-val tnum">{{ k.value }}</div>
          <div class="kpi-label">{{ k.label }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- ====== 模块1+2：类别分布 + 年级交叉 ====== -->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="14">
        <div class="sa-card">
          <div class="sa-card-title">
            <span>课程类别分布</span>
            <span class="sa-faint" style="font-size:11px;margin-left:8px">
              集中度：前3类占比 <b>{{ uniformity.top3Pct }}%</b> · 变异系数 <b>{{ uniformity.cv }}</b>
              <span v-if="uniformity.cv > 0.8" style="color:#DC2626">（偏集中）</span>
              <span v-else style="color:#0D9488">（较均衡）</span>
            </span>
          </div>
          <el-table :data="categoryDist" size="small" stripe max-height="360">
            <el-table-column prop="category" label="类别" width="110" />
            <el-table-column prop="courseCount" label="课程门数" width="80" align="right" />
            <el-table-column prop="lessonCount" label="教学班" width="80" align="right" />
            <el-table-column label="班额分布" min-width="180">
              <template #default="{row}">
                <div style="display:flex;gap:4px;align-items:center;height:20px">
                  <span v-if="row.smallCount" class="size-tag size-s" :style="{flex:row.smallCount}">{{row.smallCount}}<span class="size-hint">小</span></span>
                  <span v-if="row.mediumCount" class="size-tag size-m" :style="{flex:row.mediumCount}">{{row.mediumCount}}<span class="size-hint">中</span></span>
                  <span v-if="row.largeCount" class="size-tag size-l" :style="{flex:row.largeCount}">{{row.largeCount}}<span class="size-hint">大</span></span>
                  <span v-if="row.xlargeCount" class="size-tag size-xl" :style="{flex:row.xlargeCount}">{{row.xlargeCount}}<span class="size-hint">超大</span></span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="学时(总/理/实)" width="140">
              <template #default="{row}">
                <span class="tnum" style="font-size:12px">{{ row.totalHours }}h</span>
                <span class="sa-faint" style="font-size:10px;margin-left:4px">{{ row.theoryHours }}/{{ row.practiceHours }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="sa-card" style="height:100%">
          <div class="sa-card-title">年级 × 类别 排课热力图</div>
          <EChart v-if="gradeCross.categories && gradeCross.categories.length" :option="gradeHeatOption" :height="340" />
          <div v-else class="sa-faint" style="font-size:12px;padding:20px">暂无年级交叉数据</div>
        </div>
      </el-col>
    </el-row>

    <!-- ====== 模块3：体育/思政专项 ====== -->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">🏃 体育课 · 教室热力图</div>
          <EChart v-if="heatmaps.pe.length" :option="peHeatOption" :height="240" />
          <div v-else class="sa-faint" style="font-size:12px;padding:20px">暂无体育场地数据</div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">📖 思政课 · 教学楼热力图</div>
          <EChart v-if="heatmaps.normal.length" :option="normalHeatOption" :height="240" />
          <div v-else class="sa-faint" style="font-size:12px;padding:20px">暂无教学楼数据</div>
        </div>
      </el-col>
    </el-row>

    <!-- 体育/思政指标对比 -->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">体育课 · 概览</div>
          <div class="pe-pol-grid">
            <div class="pp-item"><span class="pp-label">课程门数</span><b class="tnum">{{ pePolitics.pe.courseCount }}</b></div>
            <div class="pp-item"><span class="pp-label">教学班数</span><b class="tnum">{{ pePolitics.pe.lessonCount }}</b></div>
            <div class="pp-item"><span class="pp-label">总学时</span><b class="tnum">{{ pePolitics.pe.totalHours }}h</b></div>
            <div class="pp-item"><span class="pp-label">实践学时</span><b class="tnum">{{ pePolitics.pe.practiceHours }}h</b></div>
            <div class="pp-item"><span class="pp-label">平均班额</span><b class="tnum">{{ pePolitics.pe.avgEnrolled }}人</b></div>
          </div>
          <EChart :option="peSizeOption" :height="160" />
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">思政课 · 概览</div>
          <div class="pe-pol-grid">
            <div class="pp-item"><span class="pp-label">课程门数</span><b class="tnum">{{ pePolitics.politics.courseCount }}</b></div>
            <div class="pp-item"><span class="pp-label">教学班数</span><b class="tnum">{{ pePolitics.politics.lessonCount }}</b></div>
            <div class="pp-item"><span class="pp-label">总学时</span><b class="tnum">{{ pePolitics.politics.totalHours }}h</b></div>
            <div class="pp-item"><span class="pp-label">理论学时</span><b class="tnum">{{ pePolitics.politics.theoryHours }}h</b></div>
            <div class="pp-item"><span class="pp-label">平均班额</span><b class="tnum">{{ pePolitics.politics.avgEnrolled }}人</b></div>
          </div>
          <EChart :option="polSizeOption" :height="160" />
        </div>
      </el-col>
    </el-row>

    <!-- ====== 模块4：教学楼负载 + 均匀度 ====== -->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="14">
        <div class="sa-card">
          <div class="sa-card-title">教学楼负载（利用率）</div>
          <EChart v-if="buildingLoad.length" :option="buildingOption" :height="280" />
          <div v-else class="sa-faint" style="font-size:12px;padding:20px">暂无数据</div>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="sa-card" style="height:100%">
          <div class="sa-card-title">课程类别学时构成</div>
          <EChart v-if="categoryDist.length" :option="hoursStackOption" :height="280" />
          <div v-else class="sa-faint" style="font-size:12px;padding:20px">暂无数据</div>
        </div>
      </el-col>
    </el-row>

    <!-- ====== 模块5：时序趋势 ====== -->
    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">各类别教学班数趋势（9学期）</div>
      <EChart v-if="trendCategories.length" :option="trendOption" :height="300" />
      <div v-else class="sa-faint" style="font-size:12px;padding:20px">暂无趋势数据</div>
    </div>

    <el-row :gutter="16">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">体育课趋势</div>
          <EChart v-if="peTrends.length" :option="peTrendOption" :height="240" />
          <div v-else class="sa-faint" style="font-size:12px;padding:20px">暂无数据</div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">思政课趋势</div>
          <EChart v-if="politicsTrends.length" :option="polTrendOption" :height="240" />
          <div v-else class="sa-faint" style="font-size:12px;padding:20px">暂无数据</div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { ref, reactive, computed, onMounted } from 'vue'
import EChart from '@/components/EChart.vue'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'

const fSemester = ref('')
const semesters = ref<SemesterOpt[]>([])

const kpis = ref<any[]>([])
const categoryDist = ref<any[]>([])
const uniformity = ref({ top3Pct: 0, cv: 0 })
const gradeCross = ref<{ categories: string[], grades: string[], data: any[] }>({ categories: [], grades: [], data: [] })
const pePolitics = ref<any>({ pe: {}, politics: {} })
const heatmaps = ref<{ pe: any[], normal: any[] }>({ pe: [], normal: [] })
const buildingLoad = ref<any[]>([])
const trends = ref<any[]>([])
const peTrends = ref<any[]>([])
const politicsTrends = ref<any[]>([])

const CAT_COLORS = ['#2563EB', '#16A34A', '#EA580C', '#F59E0B', '#9333EA', '#DC2626', '#0891B2', '#65A30D']

async function load() {
  const params = new URLSearchParams()
  if (fSemester.value) params.set('semester', fSemester.value)
  const qs = params.toString() ? '?' + params.toString() : ''
  const d = await http.get('/admin/operation/schedule-analysis' + qs)
  if (!d) return
  kpis.value = d.kpis || []
  categoryDist.value = d.categoryDist || []
  uniformity.value = d.uniformity || { top3Pct: 0, cv: 0 }
  gradeCross.value = d.gradeCross || { categories: [], grades: [], data: [] }
  pePolitics.value = d.pePolitics || { pe: {}, politics: {} }
  heatmaps.value = d.heatmaps || { pe: [], normal: [] }
  buildingLoad.value = d.buildingLoad || []
  trends.value = d.trends || []
  peTrends.value = d.peTrends || []
  politicsTrends.value = d.politicsTrends || []
}

// ---- 年级×类别热力图 ----
const gradeHeatOption = computed(() => {
  const gc = gradeCross.value
  const catMap = new Map(gc.categories.map((c, i) => [c, i]))
  const gradeMap = new Map(gc.grades.map((g, i) => [g, i]))
  const maxV = Math.max(1, ...gc.data.map((d: any) => d.count))
  const data = gc.data.map((d: any) => [catMap.get(d.category)!, gradeMap.get(d.grade)!, d.count || 0])
  return {
    tooltip: {
      formatter: (p: any) => {
        const cat = gc.categories[p.data[0]]
        const grd = gc.grades[p.data[1]]
        return `${cat} × ${grd}级<br/>教学班: <b>${p.data[2]}</b>`
      },
    },
    grid: { left: 110, right: 20, top: 10, bottom: 40 },
    xAxis: { type: 'category', data: gc.categories, axisLabel: { rotate: 30, fontSize: 10, color: '#64748B' }, splitArea: { show: true } },
    yAxis: { type: 'category', data: gc.grades.map((g: string) => g + '级'), axisLabel: { fontSize: 11, color: '#475569' }, splitArea: { show: true } },
    visualMap: { min: 0, max: maxV, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#EEF2FF', '#DBEAFE', '#93C5FD', '#3B82F6', '#1D4ED8'] } },
    series: [{ type: 'heatmap', data, label: { show: true, fontSize: 10 }, emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.25)' } } }],
  }
})

// ---- 热力图（体育场地 / 教学楼） ----
function _hmOpt(data: any[], title: string) {
  const days = ['周一', '周二', '周三', '周四', '周五']
  const periods = ['1-2节', '3-4节', '5-6节', '7-8节']
  const hmData = data.map((d: any) => [d.day - 1, periods.indexOf(d.periodLabel), d.utilization])
  const maxV = Math.max(0.01, ...data.map((d: any) => d.utilization))
  return {
    tooltip: { formatter: (p: any) => `${days[p.data[0]]} ${periods[p.data[1]]}<br/>利用率: <b>${(p.data[2] * 100).toFixed(1)}%</b>` },
    grid: { left: 80, right: 30, top: 10, bottom: 30 },
    xAxis: { type: 'category', data: days, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'category', data: periods, axisLabel: { fontSize: 11 } },
    visualMap: { min: 0, max: maxV, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#F0FDF4', '#BBF7D0', '#4ADE80', '#F59E0B', '#DC2626'] } },
    series: [{ type: 'heatmap', data: hmData, label: { show: true, formatter: (p: any) => (p.data[2] * 100).toFixed(0) + '%', fontSize: 10 } }],
  }
}
const peHeatOption = computed(() => _hmOpt(heatmaps.value.pe, '体育'))
const normalHeatOption = computed(() => _hmOpt(heatmaps.value.normal, '教学'))

// ---- 班额分布饼图 ----
function _sizePie(pe: any) {
  const b = pe.sizeBuckets || {}
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 班 ({d}%)' },
    legend: { orient: 'vertical', left: 0, top: 6, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 10 } },
    series: [{
      type: 'pie', radius: ['40%', '66%'], center: ['62%', '50%'],
      label: { formatter: '{b}\n{d}%', fontSize: 10 },
      data: [
        { name: '小班(<30)', value: b.small || 0, itemStyle: { color: '#16A34A' } },
        { name: '中班(30-60)', value: b.medium || 0, itemStyle: { color: '#2563EB' } },
        { name: '大班(60-120)', value: b.large || 0, itemStyle: { color: '#F59E0B' } },
        { name: '超大班(>120)', value: b.xlarge || 0, itemStyle: { color: '#DC2626' } },
      ].filter(d => d.value > 0),
    }],
  }
}
const peSizeOption = computed(() => _sizePie(pePolitics.value.pe))
const polSizeOption = computed(() => _sizePie(pePolitics.value.politics))

// ---- 教学楼负载条形图 ----
const buildingOption = computed(() => {
  const data = [...buildingLoad.value]
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any) => `${ps[0].name}<br/>利用率: <b>${(ps[0].value * 100).toFixed(1)}%</b>` },
    grid: { left: 120, right: 50, top: 6, bottom: 4 },
    xAxis: { type: 'value', max: 1, axisLabel: { formatter: (v: number) => (v * 100).toFixed(0) + '%', color: '#94A3B8' } },
    yAxis: { type: 'category', data: data.map((d: any) => d.building + ' ' + d.roomType).reverse(), axisLabel: { fontSize: 10, color: '#475569' }, inverse: true },
    series: [{
      type: 'bar', barWidth: '60%',
      data: data.map((d: any) => ({
        value: d.utilization,
        itemStyle: { color: d.utilization > 0.3 ? '#DC2626' : d.utilization > 0.15 ? '#F59E0B' : '#16A34A' },
      })).reverse(),
      label: { show: true, position: 'right', formatter: (p: any) => (p.value * 100).toFixed(0) + '%', fontSize: 9 },
    }],
  }
})

// ---- 学时构成堆叠柱状图 ----
const hoursStackOption = computed(() => {
  const cats = categoryDist.value.map((c: any) => c.category)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 10 } },
    grid: { left: 10, right: 10, top: 30, bottom: 4 },
    xAxis: { type: 'category', data: cats, axisLabel: { rotate: 35, fontSize: 9, color: '#64748B' } },
    yAxis: { type: 'value', name: '学时(h)', axisLabel: { fontSize: 10 } },
    series: [
      { name: '理论', type: 'bar', stack: 'total', data: categoryDist.value.map((c: any) => c.theoryHours), itemStyle: { color: '#2563EB' }, barWidth: '50%' },
      { name: '实验', type: 'bar', stack: 'total', data: categoryDist.value.map((c: any) => c.expHours), itemStyle: { color: '#0D9488' } },
      { name: '实践', type: 'bar', stack: 'total', data: categoryDist.value.map((c: any) => c.practiceHours), itemStyle: { color: '#F59E0B' } },
      { name: '上机', type: 'bar', stack: 'total', data: categoryDist.value.map((c: any) => c.labHours), itemStyle: { color: '#9333EA' } },
    ],
  }
})

// ---- 趋势折线图 ----
const trendCategories = computed(() => {
  const set = new Set(trends.value.map((t: any) => t.category))
  return [...set]
})
const trendOption = computed(() => {
  const semesters = [...new Set(trends.value.map((t: any) => t.semester))].sort() as string[]
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 10 } },
    grid: { left: 10, right: 10, top: 30, bottom: 6, containLabel: true },
    xAxis: { type: 'category', data: semesters, axisLabel: { rotate: 30, fontSize: 9 } },
    yAxis: { type: 'value', name: '教学班数', axisLabel: { fontSize: 10 } },
    series: trendCategories.value.map((cat, i) => ({
      name: cat, type: 'line',
      data: semesters.map(s => {
        const t = trends.value.find((x: any) => x.category === cat && x.semester === s)
        return t ? t.lessonCount : null
      }),
      itemStyle: { color: CAT_COLORS[i % CAT_COLORS.length] },
      smooth: true,
    })),
  }
})

function _trendLine(data: any[], fields: string[]) {
  const semesters = data.map((d: any) => d.semester)
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 10 } },
    grid: { left: 10, right: 50, top: 28, bottom: 6, containLabel: true },
    xAxis: { type: 'category', data: semesters, axisLabel: { rotate: 30, fontSize: 9 } },
    yAxis: [
      { type: 'value', name: '班数/学时', axisLabel: { fontSize: 10 } },
      { type: 'value', name: '班额', axisLabel: { fontSize: 10 } },
    ],
    series: [
      { name: '教学班数', type: 'bar', data: data.map((d: any) => d.lessonCount), itemStyle: { color: '#2563EB' }, barWidth: '40%' },
      { name: '总学时', type: 'line', data: data.map((d: any) => d.totalHours), itemStyle: { color: '#16A34A' }, smooth: true },
      { name: '平均班额', type: 'line', yAxisIndex: 1, data: data.map((d: any) => d.avgEnrolled), itemStyle: { color: '#EA580C' }, smooth: true },
    ],
  }
}
const peTrendOption = computed(() => _trendLine(peTrends.value, ['lessonCount', 'totalHours', 'avgEnrolled']))
const polTrendOption = computed(() => _trendLine(politicsTrends.value, ['lessonCount', 'totalHours', 'avgEnrolled']))

onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  await load()
})
</script>

<style scoped>
.kpi-card {
  background: #fff; border: 1px solid #E2E8F0; border-radius: 8px;
  padding: 14px 16px; text-align: center;
}
.kpi-val { font-size: 22px; font-weight: 700; color: #1E3A5F; }
.kpi-label { font-size: 12px; color: #94A3B8; margin-top: 4px; }

.size-tag {
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600; border-radius: 3px; min-width: 28px;
  padding: 1px 3px; color: #fff;
}
.size-s { background: #16A34A; }
.size-m { background: #2563EB; }
.size-l { background: #F59E0B; }
.size-xl { background: #DC2626; }
.size-hint { font-size: 8px; opacity: 0.7; margin-left: 1px; }

.pe-pol-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;
}
.pp-item {
  background: #F8FAFC; border-radius: 6px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.pp-label { font-size: 11px; color: #94A3B8; }
</style>

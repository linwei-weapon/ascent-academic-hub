<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">教师教学负荷分析</h2>
        <p class="sa-page-sub">数据来源：教学任务表(T_LESSONS) + 教职工信息表(C_TEACHERS) · {{ selectedSemesterLabel }}</p>
      </div>
      <div style="display:flex;gap:8px">
        <el-select v-model="fTitle" size="small" style="width:120px" clearable placeholder="全部职称" @change="load">
          <el-option v-for="t in titles" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="fSemester" size="small" style="width:200px" @change="load">
          <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </div>
    </div>

    <div v-if="collegeFilter" class="filter-banner">
      <span>当前学院视图：<b>{{ collegeFilter.name }}</b></span>
      <el-button size="small" type="primary" text @click="clearCollegeFilter">← 返回全院视图</el-button>
    </div>

    <div class="sa-kpi-row">
      <KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="kpiTone(k.label, k.value)" />
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="14">
        <div class="sa-card">
          <div class="sa-card-title">按职称人均学时 <KpiLabel label="" formula="按职称分组统计人均学时与上课率。教授上课率≥85%为教育部要求" /></div>
          <EChart v-if="data.titleLoad.length" :option="titleOption" :height="200" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          <el-table :data="data.titleLoad" size="small" style="margin-top:8px">
            <el-table-column prop="title" label="职称" width="80" />
            <el-table-column prop="count" label="人数" width="60" align="right" />
            <el-table-column prop="avgHours" label="人均学时" width="84" align="right" />
            <el-table-column prop="avgCourses" label="人均课程" width="84" align="right" />
            <el-table-column label="上课率" width="84" align="right"><template #default="{row}"><b class="tnum" :style="{color:row.teachingRate>=85?'#0D9488':'#E11D48'}">{{ row.teachingRate }}%</b></template></el-table-column>
            <el-table-column label="评估" min-width="100"><template #default="{row}"><el-tag :type="row.status==='ok'?'success':row.status==='warn'?'warning':'danger'" size="small">{{ row.note }}</el-tag></template></el-table-column>
          </el-table>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="sa-card" style="margin-bottom:12px">
          <div class="sa-card-title">负荷分布 <KpiLabel label="" formula="按总学时分组：低<80·正常80-180·高180-280·过载>280" /></div>
          <EChart v-if="data.loadDist.length" :option="loadOption" :height="170" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
        </div>
        <div class="sa-card">
          <div class="sa-card-title">过载教师 <span class="extra">学时>280 或 课程>5门</span></div>
          <div v-if="data.overloaded.length">
            <div v-for="o in data.overloaded" :key="o.id" class="overload-row" @click="goTeacher(o)">
              <span><span class="link">{{ o.name }}</span> <span class="sa-faint">· {{ o.title }} · {{ o.dept }}</span></span>
              <span style="color:#E11D48;font-weight:600" class="tnum">{{ o.hours }}学时·{{ o.courses }}门</span>
            </div>
          </div>
          <div v-else class="sa-faint" style="font-size:12px">无过载教师</div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">各学院教学负荷对比 <KpiLabel label="" formula="按学院分组统计教师平均教学负荷" /></div>
      <el-table :data="data.deptLoad" size="small" @row-click="goCollege" row-class-name="row-clickable">
        <el-table-column prop="dept" label="学院" width="150"><template #default="{row}"><span class="link">{{ row.dept }}</span></template></el-table-column>
        <el-table-column prop="teacherCount" label="教师数" width="80" align="right" />
        <el-table-column prop="avgHours" label="人均学时" width="90" align="right" />
        <el-table-column prop="avgCourses" label="人均课程" width="90" align="right" />
        <el-table-column label="负荷水平" min-width="200"><template #default="{row}">
          <el-progress :percentage="row.loadLevel" :stroke-width="10" :color="row.loadLevel>80?'#E11D48':row.loadLevel>60?'#D97706':'#0D9488'" />
        </template></el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import { COLLEGE_MAP } from '@/constants/colleges'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
const router = useRouter(); const route = useRoute()
const collegeFilter = ref<{id:string;name:string}|null>(null)
const collegeMap = COLLEGE_MAP
function applyCollegeFilter() { const cid = route.query.college as string; collegeFilter.value = (cid && collegeMap[cid]) ? { id: cid, name: collegeMap[cid] } : null }
applyCollegeFilter(); watch(() => route.query.college, () => { applyCollegeFilter(); load() })
function clearCollegeFilter() { collegeFilter.value = null; router.replace({ query: {} }) }
function goCollege(row: any) { router.push({ query: { college: row.id } }) }
function goTeacher(row: any) { router.push({ path: '/admin/faculty/' + row.id, query: fSemester.value ? { semester: fSemester.value } : {} }) }

const fSemester = ref('')
const fTitle = ref('')
const semesters = ref<SemesterOpt[]>([])
const titles = ref<string[]>([])
const selectedSemesterLabel = computed(() => semesters.value.find(s => s.value === fSemester.value)?.label || '')

const kpis = ref<any[]>([])
const data = reactive<{titleLoad:any[];loadDist:any[];overloaded:any[];deptLoad:any[]}>({
  titleLoad: [], loadDist: [], overloaded: [], deptLoad: [],
})

async function load() {
  const cid = route.query.college as string
  const params = new URLSearchParams()
  if (cid && collegeMap[cid]) params.set('college', cid)
  if (fSemester.value) params.set('semester', fSemester.value)
  if (fTitle.value) params.set('title', fTitle.value)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const d = await http.get('/admin/operation/teacher-load' + qs)
  if (d) { kpis.value = d.kpis || []; Object.assign(data, d) }
}
onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  titles.value = meta.titles || []
  fSemester.value = meta.current
  await load()
})

function kpiTone(label: string, value: any): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('过载')) return 'danger'
  if (label.includes('上课率')) return parseFloat(String(value)) >= 85 ? 'teal' : 'danger'
  return 'primary'
}

const titleOption = computed(() => {
  const t = data.titleLoad || []
  return {
    grid: { left: 6, right: 36, top: 30, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['人均学时', '上课率'], top: 0, textStyle: { color: '#64748B', fontSize: 12 }, itemWidth: 14, itemHeight: 8 },
    xAxis: { type: 'category', data: t.map((x: any) => x.title), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', name: '学时', nameTextStyle: { color: '#94A3B8', fontSize: 11 }, axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
      { type: 'value', name: '上课率%', max: 100, nameTextStyle: { color: '#94A3B8', fontSize: 11 }, axisLabel: { color: '#94A3B8', formatter: '{value}%' }, splitLine: { show: false } },
    ],
    series: [
      { name: '人均学时', type: 'bar', data: t.map((x: any) => x.avgHours), itemStyle: { color: '#4F46E5', borderRadius: [4, 4, 0, 0] }, barWidth: '40%' },
      { name: '上课率', type: 'line', yAxisIndex: 1, smooth: true, data: t.map((x: any) => x.teachingRate), itemStyle: { color: '#0D9488' }, lineStyle: { width: 3 }, symbolSize: 7,
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: 85 }], lineStyle: { color: '#E11D48', type: 'dashed' }, label: { formatter: '达标线 85%', color: '#E11D48', fontSize: 10 } } },
    ],
  }
})

const loadOption = computed(() => {
  const l = [...(data.loadDist || [])].reverse()
  return {
    grid: { left: 6, right: 40, top: 6, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any) => { const d = l[ps[0].dataIndex]; return `${d.label}<br/>${d.count} 人 · ${d.pct}%` } },
    xAxis: { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: l.map((x: any) => x.label), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [{
      type: 'bar', barWidth: '54%', itemStyle: { borderRadius: [0, 4, 4, 0] },
      data: l.map((x: any) => ({ value: x.count, itemStyle: { color: x.color } })),
      label: { show: true, position: 'right', formatter: (p: any) => `${l[p.dataIndex].count}人 ${l[p.dataIndex].pct}%`, color: '#64748B', fontSize: 11 },
    }],
  }
})
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.filter-banner { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 10px; padding: 8px 14px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--sa-primary); }
.overload-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--sa-border); font-size: 12px; cursor: pointer; }
.overload-row:last-child { border-bottom: none; }
.overload-row:hover { background: #f8fafc; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
</style>

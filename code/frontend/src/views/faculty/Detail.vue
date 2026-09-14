<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/faculty'}">师资保障分析</el-breadcrumb-item>
      <el-breadcrumb-item>{{ data.name || '教师详情' }}</el-breadcrumb-item>
    </el-breadcrumb>

    <h2 class="sa-page-title">{{ data.name || '加载中…' }} · 教师教学档案</h2>
    <div class="info-bar">
      <span>职工号：{{ data.code || '—' }}</span><el-divider direction="vertical" />
      <span>{{ data.deptName || '—' }}</span><el-divider direction="vertical" />
      <span>{{ data.title || '—' }}</span><el-divider direction="vertical" />
      <span>{{ data.education || '—' }} · {{ data.degree || '—' }}</span><el-divider direction="vertical" />
      <span>毕业学校：{{ data.school || '—' }}</span>
      <template v-if="semLabel"><el-divider direction="vertical" /><span style="color:#4F46E5">数据周期：{{ semLabel }}</span></template>
    </div>
    <el-alert v-if="data.evidence?.limitation" type="warning" :closable="false" show-icon style="margin-bottom:12px"
      title="画像字段说明：学历学位、年龄、学缘、毕业院校和教龄为模拟数据"
      :description="data.evidence.limitation" />
    <el-alert v-if="data.dataQuality" type="error" :closable="false" show-icon style="margin-bottom:12px"
      title="该教师当前学期教学任务存在未关闭的数据质量问题，课程数、学时和历史偏好仅供核验"
      :description="`${data.dataQuality.detail}；${data.dataQuality.recommendation}`" />

    <div class="sa-kpi-row">
      <KpiCard v-for="k in data.kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" tone="primary" />
    </div>

    <el-row :gutter="16" style="margin:4px 0 16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">授课成绩趋势 <span class="extra">逐学期学生平均分</span></div>
          <EChart v-if="data.scoreTrend && data.scoreTrend.length" :option="scoreOption" :height="180" />
          <div v-else class="sa-faint" style="font-size:12px">暂无成绩数据</div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">本学期教学班明细 <span class="extra">展示 {{ data.currentCourses.length }}/{{ data.currentCourseTotal }} 条，最多100条</span></div>
          <el-table v-if="data.currentCourses && data.currentCourses.length" :data="data.currentCourses" size="small" @row-click="goCourse" row-class-name="row-clickable">
            <el-table-column prop="courseName" label="课程" width="140"><template #default="{row}"><span class="link">{{ row.courseName }}</span></template></el-table-column>
            <el-table-column prop="className" label="教学班" min-width="130" />
            <el-table-column prop="students" label="学生数" width="74" align="right" />
            <el-table-column prop="hours" label="学时" width="64" align="right" />
          </el-table>
          <div v-else class="sa-faint" style="font-size:12px">本学期暂无授课</div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">近年授课历史</div>
      <el-table v-if="data.teachingHistory && data.teachingHistory.length" :data="data.teachingHistory" size="small">
        <el-table-column prop="semester" label="学期" width="130" />
        <el-table-column prop="courseName" label="课程" min-width="150" />
        <el-table-column prop="students" label="修读人数" width="90" align="right" />
        <el-table-column prop="avgScore" label="平均分" width="84" align="right"><template #default="{row}"><b class="tnum">{{ row.avgScore }}</b></template></el-table-column>
        <el-table-column prop="passRate" label="通过率" width="84" align="right"><template #default="{row}"><span class="tnum">{{ row.passRate }}</span></template></el-table-column>
      </el-table>
      <div v-else class="sa-faint" style="font-size:12px">暂无授课历史</div>
    </div>

    <div class="sa-card" style="margin-top:16px">
      <div class="sa-card-title">历史排课偏好分析 <span class="extra">基于真实排课行为推断</span></div>
      <el-alert type="info" :closable="false" show-icon :title="data.schedulePattern.limitation" style="margin-bottom:12px" />
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="历史教学班样本">{{ data.schedulePattern.sampleCount }} 条</el-descriptions-item>
        <el-descriptions-item label="覆盖学期">{{ data.schedulePattern.semesterCount }} 个</el-descriptions-item>
        <el-descriptions-item label="倾向置信度">{{ data.schedulePattern.confidence }}</el-descriptions-item>
        <el-descriptions-item label="参考状态">{{ data.schedulePattern.readiness }}</el-descriptions-item>
        <el-descriptions-item label="常用校区">{{ patternText(data.schedulePattern.campuses) }}</el-descriptions-item>
        <el-descriptions-item label="常用教室">{{ patternText(data.schedulePattern.classrooms) }}</el-descriptions-item>
        <el-descriptions-item label="课程性质">{{ patternText(data.schedulePattern.courseNatures) }}</el-descriptions-item>
        <el-descriptions-item label="典型班额">{{ data.schedulePattern.classSizeTendency }}<template v-if="data.schedulePattern.avgClassSize !== null">（均值 {{ data.schedulePattern.avgClassSize }}）</template></el-descriptions-item>
      </el-descriptions>
    </div>

    <div v-if="v2Preference.loaded" class="sa-card" style="margin-top:16px">
      <div class="sa-card-title">V2 历史实际排课时间分布 <span class="extra">{{ v2Preference.semester }} · 非教师主动填报</span></div>
      <el-alert type="success" :closable="false" show-icon :title="v2Preference.scope" style="margin-bottom:12px" />
      <el-table :data="preferenceRows" size="small" stripe>
        <el-table-column prop="day" label="星期" width="100" />
        <el-table-column prop="morning" label="上午排课次数" align="right" />
        <el-table-column prop="afternoon" label="下午排课次数" align="right" />
        <el-table-column prop="evening" label="晚间排课次数" align="right" />
        <el-table-column prop="total" label="合计" align="right" />
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import { getV2TeachingSemester } from '@/utils/v2meta'
const route = useRoute(); const router = useRouter()
const semLabel = computed(() => (route.query.semester as string) || '')
const data = reactive<any>({ name: '', code: '', deptName: '', title: '', education: '', degree: '', school: '', kpis: [], semesters: [], scoreTrend: [], currentCourses: [], currentCourseTotal:0, currentCourseDisplayLimit:100, dataQuality:null, teachingHistory: [], evidence: {}, schedulePattern: { sampleCount:0, semesterCount:0, campuses:[], classrooms:[], courseNatures:[], avgClassSize:null, classSizeTendency:'暂无', confidence:'低', readiness:'暂无数据', limitation:'' } })
const v2Preference = reactive<any>({ loaded: false, semester: '', cells: [], scope: '' })
async function load() {
  const qs = semLabel.value ? '?semester=' + encodeURIComponent(semLabel.value) : ''
  try {
    const d = await http.get('/admin/faculty/' + route.params.id + qs)
    if (d) Object.assign(data, d)
  } catch { /* V2教师可能尚未进入旧画像库，继续加载真实排课证据 */ }
  try {
    const semester = await getV2TeachingSemester()
    if (!semester) throw new Error('no real teaching semester')
    const real = await http.get<any>(`/v2/teachers/${encodeURIComponent(String(route.params.id))}/schedule-preference?semester=${encodeURIComponent(semester)}`)
    Object.assign(v2Preference, real || {}, { loaded: true })
  } catch {
    Object.assign(v2Preference, { loaded: false, semester: '', cells: [], scope: '' })
  }
}
onMounted(load)
watch(() => [route.params.id, route.query.semester], load)
function goCourse(row: any) { router.push({ path: '/admin/course/' + row.id, query: semLabel.value ? { semester: semLabel.value } : {} }) }
function patternText(items:any[]) { return items?.length ? items.map(x => `${x.label} ${x.pct}%`).join('、') : '暂无数据' }
const preferenceRows = computed(() => {
  const labels:Record<number,string> = {1:'周一',2:'周二',3:'周三',4:'周四',5:'周五',6:'周六',7:'周日'}
  return Array.from({length:7}, (_,i) => {
    const cells = (v2Preference.cells || []).filter((x:any) => x.weekday === i + 1)
    const count = (part:string) => cells.filter((x:any) => x.day_part === part).reduce((s:number,x:any) => s + x.meeting_count, 0)
    const morning=count('morning'), afternoon=count('afternoon'), evening=count('evening')
    return { day:labels[i+1], morning, afternoon, evening, total:morning+afternoon+evening }
  }).filter(x => x.total > 0)
})

const scoreOption = computed(() => {
  const s = data.scoreTrend || []
  return {
    grid: { left: 4, right: 12, top: 18, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: data.semesters || [], axisLabel: { color: '#94A3B8', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: { type: 'value', min: 50, max: 100, axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    series: [{
      type: 'line', smooth: true, data: s, symbolSize: 8, lineStyle: { width: 3, color: '#4F46E5' }, itemStyle: { color: '#4F46E5' },
      areaStyle: { color: 'rgba(79,70,229,0.08)' },
      label: { show: true, position: 'top', formatter: '{c}', color: '#64748B', fontSize: 11 },
    }],
  }
})
</script>

<style scoped>
.info-bar { font-size: 12px; color: var(--sa-muted); margin: 8px 0 16px; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
</style>

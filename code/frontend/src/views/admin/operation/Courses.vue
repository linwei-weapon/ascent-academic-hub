<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">开课与排课结果统计</h2>
        <p class="sa-page-sub">数据来源：教学任务表(T_LESSONS) + 排课结果表 · {{ selectedSemesterLabel }}</p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
        <el-input v-model="fKeyword" size="small" clearable placeholder="课程代码/名称" style="width:170px" @keyup.enter="load" @clear="load" />
        <el-select v-model="fCampus" size="small" style="width:120px" clearable placeholder="全部校区" @change="load">
          <el-option v-for="c in campuses" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="fNature" size="small" style="width:130px" clearable placeholder="课程性质" @change="load">
          <el-option v-for="n in courseNatures" :key="n" :label="n" :value="n" />
        </el-select>
        <el-select v-model="fCategory" size="small" style="width:130px" clearable placeholder="课程类别" @change="load">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="fSize" size="small" style="width:140px" clearable placeholder="班额档" @change="load">
          <el-option v-for="s in sizeBuckets" :key="s" :label="s" :value="s" />
        </el-select>
        <el-select v-model="fSemester" size="small" style="width:170px" clearable placeholder="全部学期" @change="onSemesterChange">
          <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-model="fYear" size="small" style="width:130px" clearable placeholder="全部学年" @change="onYearChange">
          <el-option v-for="y in years" :key="y" :label="y + '学年'" :value="y" />
        </el-select>
      </div>
    </div>

    <el-alert v-if="data.dataQuality.excludedLessons" type="warning" :closable="false" show-icon style="margin-bottom:12px"
      :title="`数据质量排除：${data.dataQuality.excludedTeachers} 名异常教师、${data.dataQuality.excludedLessons} 条排课记录未计入统计`"
      :description="`${data.dataQuality.reason}（阈值>${data.dataQuality.threshold}）`" />
    <el-collapse v-if="qualityIssues.length" style="margin-bottom:12px">
      <el-collapse-item :title="`查看 ${qualityIssues.length} 条数据质量问题明细`" name="quality">
        <el-table :data="qualityIssues" size="small" stripe max-height="300">
          <el-table-column prop="semester_id" label="学期" width="120" />
          <el-table-column label="教师" width="150"><template #default="{row}">{{ row.entity_name || row.entity_id }}（{{ row.entity_id }}）</template></el-table-column>
          <el-table-column prop="affected_rows" label="影响记录" width="90" align="right" />
          <el-table-column prop="detail" label="问题说明" min-width="210" />
          <el-table-column prop="recommendation" label="处置建议" min-width="250" />
          <el-table-column label="状态" width="90"><template #default="{row}"><el-tag size="small" :type="qualityStatusType(row.status)">{{ qualityStatusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="处置" width="220"><template #default="{row}">
            <el-button link @click="showQualityAudit(row)">处置轨迹</el-button>
            <template v-if="qualityManage">
            <el-button v-if="row.status==='open'" link type="primary" @click="changeQuality(row,'reviewing')">开始复核</el-button>
            <template v-if="row.status==='reviewing'"><el-button link type="success" @click="changeQuality(row,'closed')">确认关闭</el-button><el-button link @click="changeQuality(row,'open')">退回</el-button></template>
            <el-button v-if="row.status==='closed'" link type="warning" @click="changeQuality(row,'open')">重新打开</el-button>
            </template>
          </template></el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>
    <el-dialog v-model="auditVisible" title="数据质量问题处置轨迹" width="680px">
      <el-empty v-if="!qualityAudit.length" description="暂无处置记录" />
      <el-timeline v-else>
        <el-timeline-item v-for="(item,index) in qualityAudit" :key="index" :timestamp="item.operated_at" placement="top">
          <div><b>{{ qualityStatusLabel(item.from_status) }} → {{ qualityStatusLabel(item.to_status) }}</b></div>
          <div class="sa-faint">操作人：{{ item.operator }}</div>
          <div>{{ item.comment }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-dialog>

    <div v-if="collegeFilter" class="filter-banner">
      <span>当前学院视图：<b>{{ collegeFilter.name }}</b>（仅显示该学院数据）</span>
      <el-button size="small" type="primary" text @click="clearCollegeFilter">← 返回全院视图</el-button>
    </div>

    <el-alert type="success" :closable="false" show-icon style="margin-bottom:12px"
      title="V2 真实教学任务证据"
      :description="`已关联 ${v2Offering.total} 门课程的真实教学任务；下表固定展示 ${v2Offering.semester} 学期，避免与原型模拟趋势混用。`" />
    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">单门课程开课情况 <span class="extra">V2 · 教学任务聚合，最多展示100门</span></div>
      <el-table :data="v2Offering.items" size="small" stripe max-height="360">
        <el-table-column prop="course_id" label="课程代码" width="140" />
        <el-table-column prop="course_name" label="课程名称" min-width="190" />
        <el-table-column prop="category" label="课程类别" width="120" />
        <el-table-column prop="nature" label="课程性质" width="120" />
        <el-table-column prop="lesson_count" label="教学班" width="85" align="right" />
        <el-table-column prop="teacher_count" label="教师数" width="80" align="right" />
        <el-table-column prop="enrolled" label="选课人次" width="90" align="right" />
      </el-table>
    </div>

    <div class="sa-kpi-row">
      <KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="k.label.includes('合班')?'amber':'primary'" />
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="14">
        <div class="sa-card">
          <div class="sa-card-title">按学院开课门数 <span class="extra">全校共 {{ totalCourses }} 门 · 点击学院下钻</span></div>
          <el-table :data="data.deptCourses" size="small" @row-click="goCollege" row-class-name="row-clickable">
            <el-table-column prop="name" label="学院" width="150"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
            <el-table-column label="开课门数" width="130"><template #default="{row}">
              <div class="tnum" style="font-weight:700;font-size:14px;color:#1E293B">{{ row.courseCount }} <span style="font-size:12px;font-weight:400">门</span></div>
              <div class="sa-faint" style="font-size:11px">{{ row.lessonCount }} 个教学班</div>
            </template></el-table-column>
            <el-table-column label="占全校比例" min-width="240"><template #default="{row}">
              <div style="display:flex;align-items:center;gap:10px">
                <el-progress :percentage="row.pct" :stroke-width="10" :color="pctColor(row.pct)" style="flex:1" />
                <span class="tnum" style="font-weight:700;font-size:13px;min-width:34px;text-align:right">{{ row.pct }}%</span>
                <span class="lvl-tag" :style="{background:lvlBg(row.pct),color:lvlFg(row.pct)}">{{ row.level }}</span>
              </div>
            </template></el-table-column>
          </el-table>
          <div class="table-foot">
            <span style="width:150px">合计</span>
            <span style="width:130px;font-weight:700;color:#1E293B" class="tnum">{{ totalCourses }} 门</span>
            <span style="flex:1;font-weight:700;color:#1E293B">100%</span>
          </div>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="right-stack">
          <div class="sa-card" style="margin-bottom:16px">
            <div class="sa-card-title">课程类别分布 <KpiLabel label="" formula="按课程性质统计（去重课程计数）" /></div>
            <EChart v-if="data.typeDist.length" :option="typeOption" :height="200" />
            <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          </div>
          <div class="sa-card">
            <div class="sa-card-title">班额分布 <KpiLabel label="" formula="按教学班选课人数分组：小班<30·中班30-60·大班60-120·超大班>120" /></div>
            <EChart v-if="data.sizeDist.length" :option="sizeOption" :height="180" />
            <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">近年开课趋势 <KpiLabel label="" formula="按学期统计开课门数、教学班数、平均班额变化" /></div>
      <EChart v-if="data.trend.length" :option="trendOption" :height="240" />
      <div v-else class="sa-faint" style="font-size:12px">暂无趋势数据</div>
    </div>
    <div class="sa-card" style="margin-top:16px">
      <div class="sa-card-title">课程明细 <span class="extra">当前筛选最多展示100门，可按课程代码或名称定位</span></div>
      <el-table :data="data.courseList" size="small" stripe>
        <el-table-column prop="courseId" label="课程代码" width="140" />
        <el-table-column prop="courseName" label="课程名称" min-width="190" />
        <el-table-column prop="dept" label="开课单位" min-width="160" />
        <el-table-column prop="courseNature" label="性质" width="90" />
        <el-table-column prop="lessonCount" label="教学班" width="80" align="right" />
        <el-table-column prop="avgEnrolled" label="平均班额" width="90" align="right" />
        <el-table-column prop="studentCount" label="选课人次" width="90" align="right" />
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
import { ElMessageBox } from 'element-plus'
import { getV2TeachingSemester } from '@/utils/v2meta'
const router = useRouter()
const route = useRoute()

const fSemester = ref('')
const fYear = ref('')
const fCampus = ref('')
const fNature = ref('')
const fCategory = ref('')
const fSize = ref('')
const fKeyword = ref('')
const collegeFilter = ref<{id:string;name:string}|null>(null)
const collegeMap = COLLEGE_MAP
function applyCollegeFilter() {
  const cid = route.query.college as string
  collegeFilter.value = (cid && collegeMap[cid]) ? { id: cid, name: collegeMap[cid] } : null
}
applyCollegeFilter()
watch(() => route.query.college, () => { applyCollegeFilter(); load() })
function clearCollegeFilter() { router.replace({ query: {} }) }
function goCollege(row: any) { router.push({ query: { college: row.id } }) }

const semesters = ref<SemesterOpt[]>([])
const years = ref<string[]>([])
const campuses = ref<string[]>([])
const courseNatures = ref<string[]>([])
const categories = ref<string[]>([])
const sizeBuckets = ref<string[]>([])
const selectedSemesterLabel = computed(() => semesters.value.find(s => s.value === fSemester.value)?.label || (fYear.value ? fYear.value + '学年' : '全部学期'))
function onSemesterChange() { if (fSemester.value) fYear.value = ''; load() }
function onYearChange() { if (fYear.value) fSemester.value = ''; load() }

const kpis = ref<any[]>([])
const data = reactive<{deptCourses:any[];typeDist:any[];sizeDist:any[];trend:any[];totalCourses:number;courseList:any[];dataQuality:any}>({
  deptCourses: [], typeDist: [], sizeDist: [], trend: [], totalCourses: 0, courseList: [], dataQuality: {},
})
const qualityIssues = ref<any[]>([])
const qualityManage = ref(false)
const auditVisible = ref(false)
const qualityAudit = ref<any[]>([])
const v2Offering = reactive<any>({ items: [], total: 0, semester: '' })
const qualityStatusLabel = (status:string) => ({open:'待处理',reviewing:'复核中',closed:'已关闭'} as Record<string,string>)[status] || status
const qualityStatusType = (status:string) => ({open:'danger',reviewing:'warning',closed:'success'} as Record<string,any>)[status] || 'info'
async function showQualityAudit(row:any) {
  qualityAudit.value = await http.get(`/admin/operation/data-quality/${encodeURIComponent(row.issue_id)}/audit`) || []
  auditVisible.value = true
}
async function changeQuality(row:any,status:string) {
  const action:any={reviewing:'开始复核',closed:'确认关闭',open:'重新打开/退回'}
  const r=await ElMessageBox.prompt('请填写处置说明',action[status]||'更新状态',{inputPlaceholder:'说明核查结果或处置依据'})
  await http.put(`/admin/operation/data-quality/${encodeURIComponent(row.issue_id)}/status`,{status,comment:r.value})
  await load()
}
const totalCourses = computed(() => data.totalCourses)

async function load() {
  const cid = route.query.college as string
  const params = new URLSearchParams()
  if (cid && collegeMap[cid]) params.set('college', cid)
  if (fSemester.value) params.set('semester', fSemester.value)
  else if (fYear.value) params.set('year', fYear.value)
  if (fCampus.value) params.set('campus', fCampus.value)
  if (fNature.value) params.set('course_nature', fNature.value)
  if (fCategory.value) params.set('category', fCategory.value)
  if (fSize.value) params.set('size', fSize.value)
  if (fKeyword.value.trim()) params.set('keyword', fKeyword.value.trim())
  const qs = params.toString() ? `?${params.toString()}` : ''
  const d = await http.get('/admin/operation/courses' + qs)
  if (d) { kpis.value = d.kpis || []; Object.assign(data, d) }
  const qParams = new URLSearchParams()
  if (fSemester.value) qParams.set('semester', fSemester.value)
  const q = await http.get<any>('/admin/operation/data-quality?' + qParams.toString())
  qualityIssues.value = q?.list || []
  qualityManage.value = !!q?.permissions?.manage
  const realSemester = await getV2TeachingSemester()
  if (realSemester) {
    const v2 = await http.get<any>(`/v2/courses/offerings?semester=${encodeURIComponent(realSemester)}&limit=100`)
    if (v2) Object.assign(v2Offering, v2)
  } else Object.assign(v2Offering, { items: [], total: 0, semester: '暂无真实教学任务学期' })
}
onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()  // 最新在前
  campuses.value = meta.campuses || []
  courseNatures.value = meta.courseNature || []
  categories.value = meta.categories || []
  sizeBuckets.value = meta.sizeBuckets || []
  years.value = (meta.years || []).slice().reverse()
  fSemester.value = meta.current
  await load()
})

function pctColor(p: number) { return p >= 12 ? '#4F46E5' : p >= 6 ? '#6366F1' : '#0D9488' }
function lvlBg(p: number) { return p >= 12 ? '#eef2ff' : p >= 6 ? '#f1f5f9' : '#ecfdf5' }
function lvlFg(p: number) { return p >= 12 ? '#4F46E5' : p >= 6 ? '#64748B' : '#0D9488' }

const TYPE_COLORS = ['#4F46E5', '#0D9488', '#D97706', '#6366F1', '#0EA5E9', '#94A3B8', '#A855F7', '#E11D48']
const typeOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c} 门（{d}%）' },
  legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748B', fontSize: 11 } },
  series: [{
    type: 'pie', radius: ['48%', '74%'], center: ['34%', '50%'], avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 }, label: { show: false },
    data: (data.typeDist || []).map((t: any, i: number) => ({ name: t.name, value: t.count, itemStyle: { color: TYPE_COLORS[i % TYPE_COLORS.length] } })),
  }],
}))

const sizeOption = computed(() => {
  const sd = data.sizeDist || []
  return {
    grid: { left: 6, right: 16, top: 10, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any) => { const s = sd[ps[0].dataIndex]; return `${s.label}<br/>${s.count} 班 · ${s.pct}%` } },
    xAxis: { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: sd.map((s: any) => s.label), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [{
      type: 'bar', barWidth: '54%', itemStyle: { borderRadius: [0, 4, 4, 0] },
      data: sd.map((s: any) => ({ value: s.count, itemStyle: { color: s.color } })),
      label: { show: true, position: 'right', formatter: '{c}', color: '#64748B', fontSize: 11 },
    }],
  }
})

const trendOption = computed(() => {
  const t = data.trend || []
  return {
    grid: { left: 6, right: 24, top: 36, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    legend: { data: ['开课门数', '教学班数', '平均班额'], top: 0, textStyle: { color: '#64748B', fontSize: 12 }, itemWidth: 14, itemHeight: 8 },
    xAxis: { type: 'category', data: t.map((x: any) => x.semester), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
      { type: 'value', name: '平均班额', nameTextStyle: { color: '#94A3B8', fontSize: 11 }, axisLabel: { color: '#94A3B8' }, splitLine: { show: false } },
    ],
    series: [
      { name: '开课门数', type: 'bar', data: t.map((x: any) => x.courseCount), itemStyle: { color: '#4F46E5', borderRadius: [4, 4, 0, 0] }, barWidth: '28%' },
      { name: '教学班数', type: 'bar', data: t.map((x: any) => x.lessonCount), itemStyle: { color: '#A5B4FC', borderRadius: [4, 4, 0, 0] }, barWidth: '28%' },
      { name: '平均班额', type: 'line', yAxisIndex: 1, smooth: true, data: t.map((x: any) => x.avgSize), itemStyle: { color: '#D97706' }, lineStyle: { width: 3 }, symbolSize: 7 },
    ],
  }
})
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.filter-banner {
  background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 10px; padding: 8px 14px;
  margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;
  font-size: 12px; color: var(--sa-primary);
}
.lvl-tag { font-size: 10px; padding: 2px 8px; border-radius: 99px; min-width: 56px; text-align: center; }
.table-foot { display: flex; align-items: center; padding: 10px 12px; background: #f8fafc; border-top: 2px solid var(--sa-border-2); font-size: 12px; color: #475569; font-weight: 600; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
</style>

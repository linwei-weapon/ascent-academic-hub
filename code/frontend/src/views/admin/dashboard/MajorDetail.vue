<template>
  <div v-loading="pageLoading && !!data.name" element-loading-text="正在更新专业分析，当前结果暂时保留…" :aria-busy="pageLoading">
    <el-breadcrumb separator="›">
      <el-breadcrumb-item :to="{path:'/admin/dashboard',query:semLabel?{semester:semLabel}:{}}">教学数据总览</el-breadcrumb-item>
      <el-breadcrumb-item v-if="data.collegeId" :to="{path:'/admin/college/'+data.collegeId,query:semLabel?{semester:semLabel}:{}}">{{ data.college || '学院详情' }}</el-breadcrumb-item>
      <el-breadcrumb-item>{{ data.name || '专业详情' }}</el-breadcrumb-item>
    </el-breadcrumb>

    <h2 class="sa-page-title" style="margin-top:14px">{{ data.name || '加载中…' }} · 专业详情</h2>
    <p class="sa-page-sub">{{ data.college }} · {{ semLabel || '默认学期' }} · {{ data.scope?.restricted ? '当前角色授权范围' : '本专业全量' }}</p>

    <el-alert v-if="loadError" type="error" :closable="false" show-icon title="专业数据加载失败" :description="loadError">
      <template #default><el-button size="small" @click="loadData">重新加载</el-button></template>
    </el-alert>
    <div v-if="pageLoading && !data.name" class="sa-card">
      <el-skeleton :rows="10" animated />
    </div>

    <template v-if="data.name">
      <div class="sa-kpi-row">
        <KpiCard v-for="k in data.kpi" :key="k.id || k.label" :label="k.label" :value="k.value"
          :tone="kpiTone(k.label)" :hint="k.formula" :sub="k.detail"
          :interactive="kpiInteractive(k.id)" :action-text="kpiAction(k.id)"
          @drilldown="handleKpi(k.id)" />
      </div>

      <div class="sa-card">
        <div class="sa-card-title">
          年级风险核查
          <span class="extra">按入学年级倒序固定排列；风险排名和颜色仅用于提示核查优先级</span>
        </div>
        <div v-if="!data.gradeDetail.length" class="sa-faint">暂无年级数据</div>
        <el-collapse v-else v-model="activeGrade" accordion class="grade-collapse">
          <el-collapse-item v-for="g in data.gradeDetail" :key="g.grade" :name="g.grade">
            <template #title>
              <div class="grade-title">
                <span class="rank" :class="{hot:g.failedStudents || g.alertCount}" :title="`风险核查排序第${g.riskRank}`">{{ g.riskRank }}</span>
                <b>{{ g.grade }}</b>
                <span class="priority-reason">{{ g.priorityReason }}</span>
                <span class="grade-stat">有效成绩 {{ g.studentsWithResults }}/{{ g.students }}人</span>
                <span class="grade-stat risk">挂科学生率 {{ g.failRate }}</span>
                <span class="grade-stat">GPA {{ g.gpaAvg ?? '—' }}</span>
              </div>
            </template>

            <div class="grade-evidence">
              <div>
                <span>本学期课程学分通过占比</span>
                <el-progress v-if="g.creditDone != null" :percentage="g.creditDone" :stroke-width="8"
                  :color="g.creditDone>75?'#0D9488':'#D97706'" style="width:170px" />
                <b v-else>—</b>
              </div>
              <div><span>有效成绩覆盖率</span><b>{{ g.resultCoverageRate == null ? '—' : `${g.resultCoverageRate}%` }}</b></div>
              <div><span>当前挂科学生</span><b class="risk-text">{{ g.failedStudents }}人</b></div>
              <div><span>有效预警</span><b class="risk-text">{{ g.alertCount }}人</b></div>
            </div>

            <div class="course-caption">该年级当前未通过率较高课程 TOP3，点击课程查看趋势和行政班证据</div>
            <DataTable v-if="g.courses && g.courses.length" :columns="gradeCourseCols"
              :data="g.courses" :storage-key="`dashboard:major-grade-courses:${g.grade}`"
              :max-business-columns="3" :config-version="2" size="small"
              @row-click="row => goCourse(row, g)" row-class-name="course-row-clickable">
              <template #col-name="{row}"><span class="course-link">{{ row.name }}</span></template>
              <template #col-failRate="{row}"><b class="tnum risk-text">{{ row.failRate }}%</b></template>
              <template #col-drill><span class="sa-faint">›</span></template>
            </DataTable>
            <div v-else class="sa-faint">该年级没有达到展示阈值的集中未通过课程</div>
            <div class="more-courses">
              <el-button size="small" type="primary" plain @click="openGradeCourses(g)">
                更多课程（{{ g.courseCount || 0 }}）
              </el-button>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <div class="actions">
        <el-button type="primary" @click="goStudents">查看{{ data.scope?.restricted ? '授权范围' : '本专业全部' }}学生 →</el-button>
      </div>

      <el-collapse v-if="data.evidence?.limitation" class="evidence-collapse">
        <el-collapse-item title="数据证据与适用边界" name="evidence">
          <p class="sa-page-sub">{{ data.evidence.limitation }}</p>
        </el-collapse-item>
      </el-collapse>
      <MetricHistoryDialog v-model="historyVisible" :metric-id="historyMetricId"
        scope-type="major" :scope-id="String(route.params.id)" :scope-label="data.name"
        :end-semester="semLabel" :semester-options="semesters" />
      <MajorAlertStudentsDialog v-model="alertVisible" :major-id="String(route.params.id)"
        :major-name="data.name" :college-name="data.college" />
      <GradeCoursesDrawer v-model="gradeCoursesVisible" :major-id="String(route.params.id)"
        :major-name="data.name" :college-id="data.collegeId" :college-name="data.college"
        :grade="selectedGrade" :semester="semLabel" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import KpiCard from '@/components/KpiCard.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import MetricHistoryDialog from '@/components/MetricHistoryDialog.vue'
import MajorAlertStudentsDialog from '@/components/MajorAlertStudentsDialog.vue'
import GradeCoursesDrawer from '@/components/GradeCoursesDrawer.vue'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'

const route = useRoute()
const router = useRouter()
const semLabel = (route.query.semester as string) || ''
const pageLoading = ref(false)
const loadError = ref('')
const activeGrade = ref('')
const historyVisible = ref(false)
const historyMetricId = ref('')
const alertVisible = ref(false)
const gradeCoursesVisible = ref(false)
const selectedGrade = ref('')
const semesters = ref<SemesterOpt[]>([])
const data = reactive<any>({
  name:'', college:'', collegeId:'', kpi:[], gradeDetail:[],
  scope:{restricted:false}, evidence:{},
})

const gradeCourseCols: DataTableColumn[] = [
  { key: 'name', label: '重点课程', width: 200, fixed: 'left', region: 'identity', required: true },
  { key: 'failCount', label: '未通过人次', width: 100, align: 'right' },
  { key: 'totalCount', label: '有效成绩人次', width: 112, align: 'right' },
  { key: 'failRate', label: '未通过人次率', width: 118, align: 'right', required: true },
  { key: 'drill', label: '详情', width: 52, fixed: 'right', region: 'action', required: true },
]

async function loadData() {
  pageLoading.value = true
  loadError.value = ''
  try {
    const qs = semLabel ? '?semester=' + encodeURIComponent(semLabel) : ''
    const d = await http.get('/admin/major/' + (route.params.id || 'M051') + qs)
    if (d) {
      Object.assign(data, d)
      activeGrade.value = d.gradeDetail?.length ? d.gradeDetail[0].grade : ''
    }
  } catch (error:any) {
    loadError.value = error?.message || '数据加载失败，请稍后重试'
  } finally {
    pageLoading.value = false
  }
}

onMounted(async () => {
  await Promise.allSettled([
    loadData(),
    getFilterMeta().then((meta) => {
      semesters.value = meta.semesters.slice().reverse()
    }),
  ])
})

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('预警')) return 'danger'
  if (label.includes('挂科')) return 'amber'
  if (label.includes('覆盖')) return 'teal'
  return 'primary'
}
function kpiInteractive(id:string) {
  return [
    'roster_students',
    'active_alert_students',
    'valid_result_coverage_rate',
    'current_fail_student_rate',
    'average_student_gpa',
  ].includes(id)
}
function kpiAction(id:string) {
  if (id === 'roster_students') return '查看本专业学生'
  if (id === 'active_alert_students') return '查看预警学生名单'
  return '查看历年学期变化'
}
function handleKpi(id:string) {
  if (id === 'roster_students') return goStudents()
  if (id === 'active_alert_students') {
    alertVisible.value = true
    return
  }
  historyMetricId.value = id
  historyVisible.value = true
}
function openGradeCourses(row:any) {
  selectedGrade.value = String(row.grade || '').replace(/级$/, '')
  gradeCoursesVisible.value = true
}
function goStudents() {
  const majorId = route.params.id as string
  router.push({
    path:'/admin/students/list',
    query:{
      college:data.collegeId, collegeName:data.college,
      major:majorId, majorName:data.name,
      returnTo:route.fullPath, returnLabel:'返回专业详情',
      ...(semLabel?{semester:semLabel}:{}),
    },
  })
}
function goCourse(row: any, gradeRow: any) {
  const grade = String(gradeRow?.grade || '').replace(/级$/, '')
  router.push({
    path:'/admin/course/'+row.id,
    query:{
      collegeId:data.collegeId, collegeName:data.college,
      majorId:String(route.params.id), majorName:data.name,
      ...(grade ? { grade } : {}),
      ...(semLabel?{semester:semLabel}:{}),
    },
  })
}
</script>

<style scoped>
.grade-collapse { border-top:0; }
.grade-title { display:flex;align-items:center;gap:10px;width:100%;padding-right:12px;min-width:0; }
.rank { display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:7px;background:#f1f5f9;color:#64748b;font-weight:700;flex:none; }
.rank.hot { background:#fff1f2;color:#be123c; }
.priority-reason { flex:1;min-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#64748b;font-size:12px; }
.grade-stat { white-space:nowrap;color:#475569;font-size:12px;background:#f8fafc;border-radius:10px;padding:2px 8px; }
.grade-stat.risk,.risk-text { color:#dc2626;font-weight:600; }
.grade-evidence { display:grid;grid-template-columns:1.5fr repeat(3,1fr);gap:10px;margin:4px 0 14px;padding:12px;background:#f8fafc;border-radius:10px; }
.grade-evidence>div { display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;color:#64748b; }
.course-caption { font-size:12px;color:#64748b;margin-bottom:8px; }
.more-courses { margin-top:10px; text-align:right; }
.actions { margin-top:16px;text-align:right; }
.evidence-collapse { margin-top:16px; }
:deep(.course-row-clickable) { cursor:pointer; }
.course-link { color:var(--sa-primary);font-weight:500; }
@media (max-width: 1200px) {
  .grade-stat { display:none; }
  .grade-evidence { grid-template-columns:1fr 1fr; }
}
</style>

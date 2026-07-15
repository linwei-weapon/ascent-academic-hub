<template>
  <div>
    <div class="sa-head-row">
      <div>
        <el-breadcrumb separator="›" style="margin-bottom:4px">
          <el-breadcrumb-item :to="backTarget">{{ backLabel }}</el-breadcrumb-item>
          <el-breadcrumb-item>学生学业画像</el-breadcrumb-item>
        </el-breadcrumb>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">数据来源：学籍表 + 成绩表 · 快照+趋势+模式，从群体统计下钻到个体追踪</p>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
      <el-select v-model="fCollege" size="small" style="width:150px" clearable filterable placeholder="全部学院" @change="onCollege">
        <el-option v-for="c in colleges" :key="c.value" :label="c.label" :value="c.value" />
      </el-select>
      <el-select v-model="fMajor" size="small" style="width:140px" clearable filterable placeholder="全部专业" @change="onMajor">
        <el-option v-for="m in majorOptions" :key="m.value" :label="m.label" :value="m.value" />
      </el-select>
      <el-select v-model="fGrade" size="small" style="width:100px" clearable placeholder="全部年级">
        <el-option v-for="g in grades" :key="g" :label="g + '级'" :value="g" />
      </el-select>
      <el-select v-model="fClass" size="small" style="width:140px" clearable filterable placeholder="全部班级">
        <el-option v-for="c in classOptions" :key="c.value" :label="c.label" :value="c.value" />
      </el-select>
      <el-select v-model="fSemester" size="small" style="width:160px" clearable placeholder="全部学期" @change="onSemester">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-select v-model="fYear" size="small" style="width:120px" clearable placeholder="全部学年" @change="onYear">
        <el-option v-for="y in years" :key="y" :label="y + '学年'" :value="y" />
      </el-select>
      <el-select v-model="fRetake" size="small" style="width:100px" clearable placeholder="重修/非">
        <el-option label="重修" value="重修" /><el-option label="非重修" value="非重修" />
      </el-select>
      <el-select v-model="fRequired" size="small" style="width:100px" clearable placeholder="课程性质">
        <el-option label="必修" value="必修" /><el-option label="选修" value="选修" />
      </el-select>
      <el-input v-model="keyword" size="small" style="width:180px" placeholder="搜索学号/姓名" clearable @keyup.enter="search" />
      <el-button size="small" type="primary" @click="search">查询</el-button>
      <el-button size="small" @click="reset">重置</el-button>
    </div>

    <!-- 群体画像下钻与课程过滤标签 -->
    <div v-if="courseName || patternKey || migrationKey" class="drill-tags">
      <el-tag v-if="courseName" closable type="warning" @close="removeCourse">当前课程：{{ courseName }}</el-tag>
      <el-tag v-if="patternKey" closable type="danger" @close="removePattern">挂科模式：{{ patternLabel }}</el-tag>
      <el-tag v-if="migrationKey" closable type="primary" @close="removeMigration">
        画像迁移：{{ migrationLabel }}（{{ fromSemester }} → {{ toSemester }}）
      </el-tag>
    </div>

    <!-- 摘要行 -->
    <div class="sa-summary" style="margin-bottom:12px;font-size:13px;color:var(--sa-faint)">
      共 <b class="tnum">{{ total }}</b> 名学生<span v-if="avgGpa !== null">，平均 GPA <b class="tnum" :style="{color: avgGpa >= 3.0 ? '#16A34A' : '#DC2626'}">{{ avgGpa }}</b></span>
    </div>

    <!-- 学生表格 -->
    <div class="sa-card student-table-card">
      <div class="sa-card-title list-title"><span>学生明细</span><span class="extra">点击姓名或“详情”在当前页面核查，筛选条件不会丢失</span></div>
      <el-table :data="students" stripe v-loading="loading" class="student-table">
        <el-table-column prop="sid" label="学号" width="130"><template #default="{row}"><span class="tnum sid">{{ row.sid }}</span></template></el-table-column>
        <el-table-column prop="name" label="姓名" width="100"><template #default="{row}"><el-button link type="primary" class="name-link" @click.stop="openReview(row)">{{ row.name }}</el-button></template></el-table-column>
        <el-table-column prop="college" label="学院" min-width="160" show-overflow-tooltip />
        <el-table-column label="专业" min-width="140" show-overflow-tooltip>
          <template #default="{row}"><span>{{ row.majorName || row.major }}</span></template>
        </el-table-column>
        <el-table-column label="班级" min-width="120" show-overflow-tooltip>
          <template #default="{row}"><span>{{ row.className || row.class }}</span></template>
        </el-table-column>
        <el-table-column prop="grade" label="年级" width="82" align="center" />
        <el-table-column label="GPA" width="72" align="right">
          <template #default="{row}">
            <span class="tnum" :style="{color: gpaColor(row.gpa), fontWeight:700}">{{ row.gpa != null ? row.gpa.toFixed(2) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="挂科门数" width="80" align="right">
          <template #default="{row}">
            <span class="tnum" :style="{color: row.failCount > 0 ? '#DC2626' : '#6B7280', fontWeight: row.failCount > 0 ? 700 : 400}">{{ row.failCount }}</span>
          </template>
        </el-table-column>
        <el-table-column label="预警" width="100">
          <template #default="{row}">
            <el-tag v-if="row.alertLevel && row.alertLevel !== '—'" size="small" :type="alertTagType(row.alertLevel)">{{ row.alertLevel }}</el-tag>
            <span v-else class="sa-faint">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right" align="center">
          <template #default="{row}">
            <el-button size="small" type="primary" plain @click.stop="openReview(row)">详情</el-button>
            <el-button size="small" type="primary" text @click.stop="openStudentInsight(row)">AI研判</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!loading && students.length === 0" class="sa-faint" style="text-align:center;padding:40px">未找到匹配学生</div>

      <div style="display:flex;justify-content:flex-end;margin-top:12px" v-if="total > 0">
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next, jumper" small @current-change="loadPage" />
      </div>
    </div>

    <el-drawer v-model="reviewVisible" :title="`${review.name || ''}｜学业画像核查`" size="920px">
      <div v-loading="reviewLoading" style="min-height:300px">
        <el-alert type="info" :closable="false" show-icon title="本抽屉汇总当前学生的成绩、挂科和历史预警证据；管理判断仍需结合培养方案和实际沟通。" />
        <el-descriptions :column="4" border size="small" style="margin:14px 0">
          <el-descriptions-item label="学号">{{ review.code || '—' }}</el-descriptions-item><el-descriptions-item label="学院">{{ review.collegeName || '—' }}</el-descriptions-item><el-descriptions-item label="专业">{{ review.majorName || '—' }}</el-descriptions-item><el-descriptions-item label="班级">{{ review.className || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div class="review-kpis"><KpiCard v-for="k in review.kpis || []" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="reviewTone(k.label,k.value)" /></div>
        <el-tabs v-model="reviewTab" class="review-tabs">
          <el-tab-pane label="学期变化" name="semester">
            <el-table :data="review.semesterSummary || []" size="small"><el-table-column prop="semester" label="学期" width="150" /><el-table-column prop="gpa" label="GPA" width="90" align="right" /><el-table-column label="GPA变化" width="100" align="right"><template #default="{row,$index}">{{ deltaText(review.semesterSummary,$index,'gpa') }}</template></el-table-column><el-table-column prop="failCount" label="挂科门次" width="100" align="right" /><el-table-column label="挂科变化" width="100" align="right"><template #default="{row,$index}">{{ deltaText(review.semesterSummary,$index,'failCount') }}</template></el-table-column><el-table-column prop="earnedCredits" label="获得学分" width="100" align="right" /></el-table>
          </el-tab-pane>
          <el-tab-pane :label="`挂科分析 (${(review.failTrace || []).length})`" name="failure">
            <el-table :data="review.failTrace || []" size="small"><el-table-column prop="courseName" label="课程" min-width="190" /><el-table-column prop="failCount" label="挂科次数" width="90" align="right" /><el-table-column label="发生学期" min-width="180"><template #default="{row}">{{ (row.semesters || []).join('、') }}</template></el-table-column><el-table-column prop="teacherName" label="授课教师" width="110" /><el-table-column prop="college" label="开课单位" min-width="150" /></el-table>
          </el-tab-pane>
          <el-tab-pane :label="`预警记录 (${(review.alertHistory || []).length})`" name="alert">
            <el-table :data="review.alertHistory || []" size="small"><el-table-column prop="time" label="时间" width="150" /><el-table-column prop="level" label="等级" width="76" /><el-table-column prop="type" label="预警类型" width="130" /><el-table-column prop="changeType" label="与上次相比" width="100" /><el-table-column prop="workflowStatusLabel" label="处置状态" width="100" /><el-table-column prop="detail" label="触发证据" min-width="210" show-overflow-tooltip /></el-table>
          </el-tab-pane>
        </el-tabs>
        <div class="drawer-actions">
          <el-button type="primary" plain @click="openStudentInsight({ sid: review.code })">AI研判</el-button>
          <el-button type="primary" @click="goStudent({sid:review.code})">打开完整学生档案</el-button>
        </div>
      </div>
    </el-drawer>
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="AI学业研判" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http } from '@/utils/http'
import { getStudentAIInsight } from '@/utils/ai'
import { getFilterMeta, type SemesterOpt, type MajorOpt, type ClassOpt } from '@/utils/meta'
import KpiCard from '@/components/KpiCard.vue'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'

const route = useRoute()
const router = useRouter()

// ── 筛选状态 ──
const fCollege = ref('')
const fMajor = ref('')
const fGrade = ref('')
const fClass = ref('')
const fSemester = ref('')
const fYear = ref('')
const fRetake = ref('')
const fRequired = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = 20

// ── URL 参数预填 ──
const courseName = ref(route.query.courseName as string || '')
const courseId = ref(route.query.course as string || '')
const patternKey = ref(route.query.pattern as string || '')
const patternLabel = ref(route.query.patternLabel as string || '')
const migrationKey = ref(route.query.migration as string || '')
const migrationLabel = ref(route.query.migrationLabel as string || '')
const fromSemester = ref(route.query.from_semester as string || '')
const toSemester = ref(route.query.to_semester as string || '')
const backTarget = computed(() => {
  const path = route.query.returnTo as string
  return path ? path : '/admin/students/analysis'
})
const backLabel = computed(() => (route.query.returnLabel as string) || '学生学业')

// ── 数据 ──
const loading = ref(false)
const students = ref<any[]>([])
const total = ref(0)
const avgGpa = ref<number | null>(null)
const reviewVisible = ref(false)
const reviewLoading = ref(false)
const reviewTab = ref('semester')
const review = ref<any>({})
const aiDrawerVisible = ref(false)
const aiLoading = ref(false)
const aiInsight = ref<any>(null)

// ── 筛选器选项 ──
const semesters = ref<SemesterOpt[]>([])
const years = ref<string[]>([])
const grades = ref<string[]>([])
const colleges = ref<{value:string;label:string}[]>([])
const majors = ref<MajorOpt[]>([])
const classes = ref<ClassOpt[]>([])

const majorOptions = computed(() => fCollege.value
  ? majors.value.filter(m => m.college === fCollege.value)
  : majors.value)
const classOptions = computed(() => fMajor.value
  ? classes.value.filter(c => c.major === fMajor.value)
  : classes.value)

// ── 页面标题 ──
const pageTitle = computed(() => {
  const parts: string[] = []
  if (courseName.value) parts.push(courseName.value)
  if (patternKey.value) parts.push(patternLabel.value || '挂科模式')
  if (migrationKey.value) parts.push((migrationLabel.value || '画像迁移') + '学生')
  if (route.query.collegeName) parts.push(route.query.collegeName as string)
  else if (route.query.majorName) parts.push(route.query.majorName as string)
  parts.push('学生学业画像')
  return parts.join(' · ')
})

// ── URL 参数初始化 ──
onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  years.value = (meta.years || []).slice().reverse()
  grades.value = meta.grades || []
  colleges.value = meta.colleges || []
  majors.value = meta.majors || []
  classes.value = meta.classes || []

  if (route.query.college) fCollege.value = route.query.college as string
  if (route.query.major) fMajor.value = route.query.major as string
  if (route.query.grade) fGrade.value = route.query.grade as string
  if (route.query.class) fClass.value = route.query.class as string
  if (route.query.semester) fSemester.value = route.query.semester as string
  if (route.query.year) fYear.value = route.query.year as string
  if (route.query.retake) fRetake.value = route.query.retake as string
  if (route.query.required) fRequired.value = route.query.required as string
  if (route.query.course) courseId.value = route.query.course as string
  if (route.query.courseName) courseName.value = route.query.courseName as string
  loadPage(1)
})

// ── 筛选联动 ──
function onCollege() { fMajor.value = ''; fClass.value = '' }
function onMajor() { fClass.value = '' }
function onSemester() { if (fSemester.value) fYear.value = '' }
function onYear() { if (fYear.value) fSemester.value = '' }

// ── 数据加载 ──
async function loadPage(p: number) {
  loading.value = true
  try {
    const params: Record<string, any> = { page: p, page_size: pageSize }
    if (fCollege.value) params.college = fCollege.value
    if (fMajor.value) params.major = fMajor.value
    if (fGrade.value) params.grade = fGrade.value
    if (fClass.value) params.class_id = fClass.value
    if (fSemester.value) params.semester = fSemester.value
    else if (fYear.value) params.year = fYear.value
    if (fRetake.value) params.retake = fRetake.value
    if (fRequired.value) params.required = fRequired.value
    if (keyword.value) params.keyword = keyword.value
    if (courseId.value) params.course = courseId.value
    if (patternKey.value) params.pattern = patternKey.value
    if (migrationKey.value) {
      params.migration = migrationKey.value
      params.from_semester = fromSemester.value
      params.to_semester = toSemester.value
    }
    // 排序
    params.sort = 'gpa'
    params.order = 'desc'

    const qs = Object.entries(params).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')
    const data = await http.get<any>(`/admin/students/list?${qs}`)

    students.value = data.students || []
    total.value = data.total || 0
    page.value = data.page || p

    // 使用后端对完整筛选群体计算的均值，不能只计算当前分页。
    avgGpa.value = data.summary?.avgGpa ?? null
  } catch { /* http 工具已 toast */ }
  finally { loading.value = false }
}

// ── 操作 ──
async function openReview(row: any) {
  reviewVisible.value = true; reviewLoading.value = true; reviewTab.value = 'semester'; review.value = { name: row.name, code: row.sid }
  try { const d = await http.get<any>(`/admin/student/${encodeURIComponent(row.sid)}`); if (d) review.value = d }
  finally { reviewLoading.value = false }
}
async function openStudentInsight(row: any) {
  const sid = row.sid || row.code || row.student_id
  if (!sid) return
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try {
    aiInsight.value = await getStudentAIInsight(sid, 'student_list')
  } finally {
    aiLoading.value = false
  }
}
function search() { page.value = 1; loadPage(1) }
function reset() {
  fCollege.value = ''; fMajor.value = ''; fGrade.value = ''
  fClass.value = ''; fSemester.value = ''; fYear.value = ''; fRetake.value = ''
  fRequired.value = ''; keyword.value = ''
  courseId.value = ''; courseName.value = ''
  patternKey.value = ''; patternLabel.value = ''
  migrationKey.value = ''; migrationLabel.value = ''; fromSemester.value = ''; toSemester.value = ''
  router.replace({ path: route.path, query: {} })
  page.value = 1; loadPage(1)
}
function clearRouteKeys(keys: string[]) {
  const query: Record<string, any> = { ...route.query }
  keys.forEach(key => delete query[key])
  router.replace({ path: route.path, query })
}
function removeCourse() {
  courseId.value = ''; courseName.value = ''; clearRouteKeys(['course', 'courseName']); search()
}
function removePattern() {
  patternKey.value = ''; patternLabel.value = ''; clearRouteKeys(['pattern', 'patternLabel']); search()
}
function removeMigration() {
  migrationKey.value = ''; migrationLabel.value = ''; fromSemester.value = ''; toSemester.value = ''
  clearRouteKeys(['migration', 'migrationLabel', 'from_semester', 'to_semester']); search()
}
function goStudent(row: any) {
  const qs = new URLSearchParams({ from: 'list' })
  Object.entries(route.query).forEach(([k,v]) => { if (v != null) qs.set(k, String(v)) })
  if (fCollege.value) qs.set('college', fCollege.value)
  if (fMajor.value) qs.set('major', fMajor.value)
  if (fGrade.value) qs.set('grade', fGrade.value)
  if (fClass.value) qs.set('class', fClass.value)
  if (fSemester.value) qs.set('semester', fSemester.value)
  if (courseId.value) qs.set('course', courseId.value)
  if (courseName.value) qs.set('courseName', courseName.value)
  router.push(`/admin/student/${row.sid}?${qs.toString()}`)
}

// ── 辅助 ──
function gpaColor(g: number | null): string {
  if (g == null) return '#6B7280'
  if (g >= 3.5) return '#16A34A'
  if (g >= 3.0) return '#2563EB'
  if (g >= 2.0) return '#EA580C'
  return '#DC2626'
}
function alertTagType(level: string): string {
  if (level.includes('严重')) return 'danger'
  if (level.includes('警告')) return 'warning'
  return 'info'
}
function reviewTone(label:string,value:any):'primary'|'teal'|'danger'|'amber'{if(label.includes('预警'))return String(value).includes('正常')?'teal':'danger';if(label.includes('GPA'))return Number(value)>=3?'teal':Number(value)<2?'danger':'amber';return'primary'}
function deltaText(rows:any[],index:number,key:string){if(index===0)return'—';const d=Number(rows[index]?.[key]||0)-Number(rows[index-1]?.[key]||0);return`${d>0?'+':''}${Math.round(d*100)/100}`}
</script>

<style scoped>
.drill-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.student-table-card { padding: 0; overflow: hidden; }
.list-title { padding: 14px 16px 10px; display:flex; justify-content:space-between; }
.student-table { width: 100%; }
.sid { color:#475569; font-size:12px; }
.name-link { font-weight:600; padding:0; }
:deep(.student-table th.el-table__cell) { background:#F8FAFC; color:#475569; font-weight:600; height:44px; }
:deep(.student-table td.el-table__cell) { padding:10px 0; }
:deep(.student-table .el-table__row:hover > td.el-table__cell) { background:#F5F7FF; }
.review-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.review-tabs { margin-top:14px; }
.drawer-actions { display:flex; justify-content:flex-end; margin-top:16px; }
</style>

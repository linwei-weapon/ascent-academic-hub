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

    <el-alert class="ai-focus-alert" type="info" :closable="false" show-icon>
      <template #title>
        当前页识别出 <b>{{ currentPageAiFocus.length }}</b> 名 AI 重点学生
      </template>
      <template #default>
        AI 只用于解释“低 GPA、较多挂科与严重预警同时出现”的复合风险，不对每名学生逐一生成评价。请先打开“详情”核查学期变化、挂科和历史预警，达到介入条件时再查看 AI 研判。
      </template>
    </el-alert>
    <el-alert v-if="loadError" class="ai-focus-alert" type="error" :closable="false" show-icon>
      <template #title>学生名单加载失败，已保留当前页面内容</template>
      <template #default>
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="loadPage(page)">重新加载</el-button>
      </template>
    </el-alert>

    <!-- 学生表格 -->
    <div class="sa-card student-table-card">
      <div class="sa-card-title list-title"><span>学生明细</span><span class="extra">点击姓名或“详情”在当前页面核查，筛选条件不会丢失</span></div>
      <DataTable :columns="studentCols" :data="students" storage-key="students:list"
        :max-business-columns="8" :config-version="2" stripe v-loading="loading"
        class="student-table" v-model:page-size="pageSize">
        <template #col-sid="{row}"><span class="tnum sid">{{ row.sid }}</span></template>
        <template #col-name="{row}"><el-button link type="primary" class="name-link" @click.stop="openReview(row)">{{ row.name }}</el-button></template>
        <template #col-major="{row}"><span>{{ row.majorName || row.major }}</span></template>
        <template #col-class="{row}"><span>{{ row.className || row.class }}</span></template>
        <template #col-gpa="{row}">
          <span class="tnum" :style="{color: gpaColor(row.gpa), fontWeight:700}">{{ row.gpa != null ? row.gpa.toFixed(2) : '—' }}</span>
        </template>
        <template #col-failCount="{row}">
          <span class="tnum" :style="{color: row.failCount > 0 ? '#DC2626' : '#6B7280', fontWeight: row.failCount > 0 ? 700 : 400}">{{ row.failCount }}</span>
        </template>
        <template #col-alertLevel="{row}">
          <el-tag v-if="row.alertLevel && row.alertLevel !== '—'" size="small" :type="alertTagType(row.alertLevel)">{{ row.alertLevel }}</el-tag>
          <span v-else class="sa-faint">—</span>
        </template>
        <template #col-attention="{row}">
          <el-tag size="small" :type="studentAttention(row).type">{{ studentAttention(row).label }}</el-tag>
        </template>
        <template #col-actions="{row}">
          <el-button size="small" type="primary" plain @click.stop="openReview(row)">详情</el-button>
        </template>
      </DataTable>

      <div v-if="!loading && students.length === 0" class="sa-faint" style="text-align:center;padding:40px">未找到匹配学生</div>

      <div style="display:flex;justify-content:flex-end;margin-top:12px" v-if="total > 0">
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next, jumper" size="small" @current-change="loadPage" />
      </div>
    </div>

    <StudentEvidenceDrawer
      v-model="reviewVisible"
      :student-id="selectedStudentRow?.sid"
      :context="listEvidenceContext"
      :ai-eligible="selectedStudentNeedsAi"
      @ai="openStudentInsight({ sid: selectedStudentRow?.sid })"
    />
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="AI学业研判" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http } from '@/utils/http'
import { getStudentAIInsight } from '@/utils/ai'
import { getFilterMeta, type SemesterOpt, type MajorOpt, type ClassOpt } from '@/utils/meta'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import StudentEvidenceDrawer from '@/components/StudentEvidenceDrawer.vue'

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
// M6：每页行数由 DataTable 偏好驱动（v-model:page-size），变化时回到第一页重查
const pageSize = ref(20)
const initialized = ref(false)
let requestSeq = 0
watch(pageSize, () => {
  if (!initialized.value) return
  page.value = 1
  loadPage(1)
})

// 学生明细表列定义（M6 DataTable）
const studentCols: DataTableColumn[] = [
  { key: 'sid', label: '学号', width: 130, fixed: 'left', region: 'identity', required: true },
  { key: 'name', label: '姓名', width: 100, fixed: 'left', region: 'identity', required: true },
  { key: 'college', label: '学院', minWidth: 160, tooltip: true },
  { key: 'major', label: '专业', minWidth: 140, tooltip: true },
  { key: 'class', label: '班级', minWidth: 120, tooltip: true },
  { key: 'grade', label: '年级', width: 82, align: 'center' },
  { key: 'gpa', label: '筛选期GPA', width: 96, align: 'right', required: true },
  { key: 'failCount', label: '筛选期未通过', width: 104, align: 'right' },
  { key: 'alertLevel', label: '预警', width: 100 },
  { key: 'attention', label: '管理关注', width: 105, align: 'center' },
  { key: 'actions', label: '操作', width: 88, align: 'center', fixed: 'right', region: 'action', required: true },
]
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
const loadError = ref('')
const students = ref<any[]>([])
const total = ref(0)
const avgGpa = ref<number | null>(null)
const appliedFilters = ref<Record<string, any>>({})
const reviewVisible = ref(false)
const selectedStudentRow = ref<any>(null)
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
const currentPageAiFocus = computed(() => students.value.filter(row => studentAttention(row).level === 'ai'))
const selectedStudentNeedsAi = computed(() => selectedStudentRow.value && studentAttention(selectedStudentRow.value).level === 'ai')
function currentListQuery() {
  return {
    returnTo: route.query.returnTo || undefined,
    returnLabel: route.query.returnLabel || undefined,
    collegeName: route.query.collegeName || undefined,
    majorName: route.query.majorName || undefined,
    college: fCollege.value || undefined,
    major: fMajor.value || undefined,
    grade: fGrade.value || undefined,
    class: fClass.value || undefined,
    semester: fSemester.value || undefined,
    year: fYear.value || undefined,
    retake: fRetake.value || undefined,
    required: fRequired.value || undefined,
    keyword: keyword.value || undefined,
    course: courseId.value || undefined,
    courseName: courseName.value || undefined,
    pattern: patternKey.value || undefined,
    patternLabel: patternLabel.value || undefined,
    migration: migrationKey.value || undefined,
    migrationLabel: migrationLabel.value || undefined,
    from_semester: fromSemester.value || undefined,
    to_semester: toSemester.value || undefined,
    page: page.value > 1 ? String(page.value) : undefined,
    page_size: pageSize.value !== 20 ? String(pageSize.value) : undefined,
  }
}
async function syncListState() {
  await router.replace({ path: route.path, query: currentListQuery() })
}
const listEvidenceContext = computed(() => {
  const row = selectedStudentRow.value || {}
  const reasons = []
  if (migrationKey.value) reasons.push(`${migrationLabel.value || '画像迁移'}名单命中`)
  if (patternKey.value) reasons.push(`${patternLabel.value || '挂科模式'}命中`)
  if (row.failCount > 0) reasons.push(`筛选期有${row.failCount}门未通过课程`)
  if (row.alertLevel && row.alertLevel !== '—') reasons.push(`当前最高预警为${row.alertLevel}`)
  if (!reasons.length) reasons.push('当前名单主动核查')
  const period = fromSemester.value && toSemester.value
    ? `${fromSemester.value} → ${toSemester.value}`
    : fSemester.value || (fYear.value ? `${fYear.value}学年` : '当前筛选周期')
  return {
    studentName: row.name,
    reasons,
    period,
    ruleVersion: migrationKey.value ? 'student-growth-v1' : 'academic-metrics-v1',
    returnLabel: pageTitle.value,
    returnQuery: currentListQuery(),
    boundary: '当前筛选条件只用于定位学生；抽屉内课程状态按完整历史有效修读结果核查。',
  }
})

// ── 页面标题 ──
const pageTitle = computed(() => {
  const parts: string[] = []
  if (courseName.value) parts.push(courseName.value)
  if (patternKey.value) parts.push(patternLabel.value || '挂科模式')
  if (migrationKey.value) parts.push((migrationLabel.value || '画像迁移') + '学生')
  if (route.query.collegeName) parts.push(route.query.collegeName as string)
  if (route.query.majorName) parts.push(route.query.majorName as string)
  parts.push('学生学业画像')
  return parts.join(' · ')
})

// ── URL 参数初始化 ──
onMounted(async () => {
  const restoredScroll = Math.max(0, Number(route.query.scrollY || 0) || 0)
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
  if (route.query.keyword) keyword.value = route.query.keyword as string
  if (route.query.course) courseId.value = route.query.course as string
  if (route.query.courseName) courseName.value = route.query.courseName as string
  const restoredPageSize = Number(route.query.page_size || 20)
  pageSize.value = [10, 20, 50].includes(restoredPageSize) ? restoredPageSize : 20
  const restoredPage = Math.max(1, Number(route.query.page || 1) || 1)
  page.value = restoredPage
  initialized.value = true
  await loadPage(restoredPage)
  if (restoredScroll) {
    await nextTick()
    window.scrollTo({ top: restoredScroll, behavior: 'auto' })
  }
})

// ── 筛选联动 ──
function onCollege() { fMajor.value = ''; fClass.value = '' }
function onMajor() { fClass.value = '' }
function onSemester() { if (fSemester.value) fYear.value = '' }
function onYear() { if (fYear.value) fSemester.value = '' }

// ── 数据加载 ──
async function loadPage(p: number) {
  const currentRequest = ++requestSeq
  loading.value = true
  loadError.value = ''
  try {
    const params: Record<string, any> = { page: p, page_size: pageSize.value }
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
    if (currentRequest !== requestSeq) return

    students.value = data.students || []
    total.value = data.total || 0
    page.value = data.page || p
    appliedFilters.value = data.appliedFilters || {}
    await syncListState()

    // 使用后端对完整筛选群体计算的均值，不能只计算当前分页。
    avgGpa.value = data.summary?.avgGpa ?? null
  } catch (error: any) {
    if (currentRequest === requestSeq) {
      loadError.value = error?.message || '学生名单加载失败，请稍后重试'
    }
  }
  finally {
    if (currentRequest === requestSeq) loading.value = false
  }
}

// ── 操作 ──
function openReview(row: any) {
  selectedStudentRow.value = row
  reviewVisible.value = true
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
function studentAttention(row: any): { level: 'ai' | 'verify' | 'routine'; label: string; type: 'danger' | 'warning' | 'info' } {
  const level = String(row?.alertLevel || '')
  const failCount = Number(row?.failCount || 0)
  const gpa = row?.gpa == null ? null : Number(row.gpa)
  const severeComposite = level.includes('严重') && (failCount >= 2 || (gpa != null && gpa < 2.0))
  if (severeComposite || failCount >= 3 || (gpa != null && gpa < 1.8 && failCount > 0)) {
    return { level: 'ai', label: 'AI重点', type: 'danger' }
  }
  if ((level.includes('警告') || level.includes('严重')) && (failCount > 0 || (gpa != null && gpa < 2.3))) {
    return { level: 'verify', label: '需核查', type: 'warning' }
  }
  return { level: 'routine', label: '常规查看', type: 'info' }
}
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
.ai-focus-alert { margin-bottom:12px; }
</style>

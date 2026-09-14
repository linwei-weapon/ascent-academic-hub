<template>
  <div
    v-loading="initialLoading"
    element-loading-text="正在计算最近两个学期的学业变化，请稍候…"
    element-loading-background="rgba(248,250,252,.86)"
  >
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">识别真实变化、组织管理注意力，并提供可核查的学生证据；不使用未披露的综合风险分。</p>
      </div>
    </div>

    <BusinessPageContext
      :period="periodText"
      source="学籍、真实成绩、课程有效结果与当前预警事件"
      :loading="initialLoading || refreshing"
      :error="loadError"
      :updated-at="updatedAt"
    />

    <div class="sa-card filter-card">
      <div class="filter-title">
        <span>分析范围</span>
        <span>调整条件后点击“应用范围”，页面保留当前结果直到新数据返回</span>
      </div>
      <div class="filter-row">
        <el-select v-model="draft.fromSemester" style="width:166px" placeholder="起始学期">
          <el-option v-for="s in semesterOptions" :key="s.value" :label="`起始：${s.label}`" :value="s.value" />
        </el-select>
        <el-select v-model="draft.toSemester" style="width:166px" placeholder="目标学期">
          <el-option v-for="s in semesterOptions" :key="s.value" :label="`目标：${s.label}`" :value="s.value" />
        </el-select>
        <el-select v-model="draft.college" style="width:170px" clearable filterable placeholder="全部学院" :disabled="scopeType === 'college'" @change="onCollege">
          <el-option v-for="c in colleges" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-select v-model="draft.major" style="width:160px" clearable filterable placeholder="全部专业" :disabled="scopeType === 'major'" @change="onMajor">
          <el-option v-for="m in majorOptions" :key="m.value" :label="m.label" :value="m.value" />
        </el-select>
        <el-select v-model="draft.grade" style="width:116px" clearable placeholder="全部年级">
          <el-option v-for="g in grades" :key="g" :label="`${g}级`" :value="g" />
        </el-select>
        <el-select v-model="draft.classId" style="width:160px" clearable filterable placeholder="全部行政班">
          <el-option v-for="c in classOptions" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-button type="primary" :loading="refreshing" @click="applyScope">应用范围</el-button>
        <el-button @click="resetScope">重置</el-button>
      </div>
      <el-alert
        v-if="draft.fromSemester && draft.toSemester && draft.fromSemester >= draft.toSemester"
        type="warning" :closable="false" show-icon
        title="起始学期必须早于目标学期，当前条件尚未应用"
      />
    </div>

    <el-alert
      v-if="slowLoading"
      class="slow-alert"
      type="info"
      :closable="false"
      show-icon
      title="正在汇总成绩与未通过课程变化，已加载内容仍可查看"
    />
    <el-alert v-if="loadError" class="error-alert" type="error" :closable="false" show-icon>
      <template #title>成长概览加载失败，已保留上一次结果</template>
      <template #default>
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="loadOverview()">重新加载</el-button>
      </template>
    </el-alert>

    <div class="sa-kpi-row">
      <div
        v-for="metric in overview.metrics"
        :key="metric.key"
        class="drill-card"
        :class="{ active: activeGroup === metric.key }"
        @click="selectGroup(metric.key, metric.label)"
      >
        <KpiCard
          :label="metric.label"
          :value="metric.value"
          :sub="metric.sub"
          :hint="`${metric.meaning} 时间范围：${periodText}；当前全页筛选生效。`"
          :tone="metric.tone"
        />
        <span class="drill-hint">查看学生名单 →</span>
      </div>
    </div>

    <el-row :gutter="16" class="management-row">
      <el-col :span="9">
        <div class="sa-card group-panel">
          <div class="sa-card-title">管理关注分组</div>
          <p class="section-note">{{ overview.evidence?.overlapNotice || '关注分组允许重叠。' }}</p>
          <button
            v-for="group in overview.groups"
            :key="group.key"
            type="button"
            class="group-item"
            :class="{ active: activeGroup === group.key }"
            @click="selectGroup(group.key, group.label)"
          >
            <span><b>{{ group.label }}</b><small>{{ group.description }}</small></span>
            <strong class="tnum">{{ group.count }}人</strong>
          </button>
        </div>
      </el-col>
      <el-col :span="15">
        <div class="sa-card organization-panel">
          <div class="sa-card-title">
            {{ overview.organizationLabel || '组织' }}变化与关注比较
            <span class="title-note">点击“查看名单”仅收窄当前授权范围，不扩大明细权限</span>
          </div>
          <el-alert v-if="organizationError" class="list-rule" type="error" :closable="false" show-icon>
            <template #title>组织比较加载失败，其他区域仍可使用</template>
            <template #default>
              <span>{{ organizationError }}</span>
              <el-button link type="primary" @click="loadOrganizations">重新加载组织比较</el-button>
            </template>
          </el-alert>
          <DataTable
            :columns="organizationCols"
            :data="overview.organizations"
            storage-key="students:growth-organizations"
            :max-business-columns="7"
            :config-version="1"
            size="small"
            v-loading="organizationLoading"
          >
            <template #col-organizationName="{ row }"><b>{{ row.organizationName }}</b></template>
            <template #col-coverageRate="{ row }">{{ ratioCell(row.comparableCount, row.studentCount, row.coverageRate) }}</template>
            <template #col-declinedRate="{ row }">{{ ratioCell(row.declinedCount, row.comparableCount, row.declinedRate) }}</template>
            <template #col-actions="{ row }">
              <el-button size="small" type="primary" plain @click="selectOrganization(row)">查看名单</el-button>
            </template>
          </DataTable>
          <el-empty v-if="!initialLoading && !overview.organizations.length" description="当前授权范围没有可比较的下级组织" :image-size="62" />
        </div>
      </el-col>
    </el-row>

    <div class="sa-card list-panel" id="growth-priority-list">
      <div class="list-header">
        <div>
          <div class="sa-card-title">学生证据名单 · {{ activeGroupLabel }}</div>
          <p class="section-note">
            {{ selectedOrganizationName ? `当前组织：${selectedOrganizationName}；` : '' }}
            共 {{ list.total }} 人。默认排序：连续受挫且重复未解决 → 低年级首次受挫 → 明确恶化且未通过增加 → GPA明显下降 → 其他。
          </p>
        </div>
        <div class="list-actions">
          <el-input v-model="keyword" clearable placeholder="搜索学号/姓名" style="width:190px" @keyup.enter="loadList(1)" />
          <el-button type="primary" plain @click="loadList(1)">查询</el-button>
          <el-button v-if="selectedOrganizationId" @click="clearOrganization">返回全部组织</el-button>
        </div>
      </div>
      <el-alert
        type="info" :closable="false" show-icon class="list-rule"
        :title="`规则版本 ${overview.rule?.version || '—'}：GPA明显变化阈值为 ${overview.rule?.gpaThreshold ?? '—'}；关注分组允许重叠。`"
      />
      <el-alert v-if="listError" class="list-rule" type="error" :closable="false" show-icon>
        <template #title>学生名单加载失败，概览和现有名单仍可查看</template>
        <template #default>
          <span>{{ listError }}</span>
          <el-button link type="primary" @click="loadList(page)">重新加载名单</el-button>
        </template>
      </el-alert>
      <DataTable
        :columns="studentCols"
        :data="list.students"
        storage-key="students:growth-priority-list"
        :max-business-columns="8"
        :config-version="1"
        v-model:page-size="pageSize"
        v-loading="listLoading"
        stripe
      >
        <template #col-sid="{ row }"><span class="tnum">{{ row.sid }}</span></template>
        <template #col-name="{ row }"><el-button link type="primary" @click="openEvidence(row)">{{ row.name }}</el-button></template>
        <template #col-organization="{ row }">{{ row.major }} · {{ row.className }}</template>
        <template #col-gpaChange="{ row }">
          <span class="tnum">{{ valueText(row.fromGpa) }} → {{ valueText(row.toGpa) }}</span>
          <small :class="deltaClass(row.gpaDelta)"> {{ signed(row.gpaDelta) }}</small>
        </template>
        <template #col-failChange="{ row }">
          <span class="tnum">{{ valueText(row.fromFailCount, 0) }} → {{ valueText(row.toFailCount, 0) }}门</span>
          <small :class="failDeltaClass(row.failDelta)"> {{ signed(row.failDelta) }}</small>
        </template>
        <template #col-triggers="{ row }">
          <div class="tag-wrap">
            <el-tag v-for="tag in triggerLabels(row)" :key="tag" size="small" :type="triggerType(tag)">{{ tag }}</el-tag>
          </div>
        </template>
        <template #col-unresolved="{ row }">
          <span v-if="row.unresolvedCourseCount">{{ row.unresolvedCourseCount }}门<span v-if="row.repeatedCourses?.length" class="danger-text"> · 重复{{ row.repeatedCourses.length }}门</span></span>
          <span v-else class="sa-faint">无</span>
        </template>
        <template #col-openAlerts="{ row }"><span :class="{ 'danger-text': row.openAlerts }">{{ row.openAlerts }}件</span></template>
        <template #col-actions="{ row }"><el-button size="small" type="primary" plain @click="openEvidence(row)">详情</el-button></template>
      </DataTable>
      <el-empty v-if="!listLoading && !list.students.length" :description="emptyDescription" :image-size="66" />
      <div class="pager" v-if="list.total">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="list.total"
          layout="total, prev, pager, next, jumper"
          size="small"
          @current-change="loadList"
        />
      </div>
    </div>

    <StudentEvidenceDrawer
      v-model="evidenceVisible"
      :student-id="selected.sid"
      :context="evidenceContext"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authStore } from '@/store/auth'
import { http } from '@/utils/http'
import { getFilterMeta, type ClassOpt, type MajorOpt, type SemesterOpt } from '@/utils/meta'
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import KpiCard from '@/components/KpiCard.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import StudentEvidenceDrawer from '@/components/StudentEvidenceDrawer.vue'

const route = useRoute()
const router = useRouter()
const scopeType = computed(() => String(authStore.user?.permissionContext?.detailScope?.type || 'all'))
const pageTitle = computed(() => ({
  all: '全校学生成长与学业变化',
  college: '本学院学生成长与学业变化',
  major: '本专业学生成长与学业变化',
}[scopeType.value] || '当前授权范围学生成长与学业变化'))

const semesterOptions = ref<SemesterOpt[]>([])
const colleges = ref<{ value: string; label: string }[]>([])
const majors = ref<MajorOpt[]>([])
const classes = ref<ClassOpt[]>([])
const grades = ref<string[]>([])
const draft = reactive({ fromSemester: '', toSemester: '', college: '', major: '', grade: '', classId: '' })
const applied = reactive({ fromSemester: '', toSemester: '', college: '', major: '', grade: '', classId: '' })
const overview = reactive<any>({ metrics: [], groups: [], organizations: [], period: {}, rule: {}, evidence: {} })
const list = reactive<any>({ total: 0, students: [] })
const initialLoading = ref(true)
const refreshing = ref(false)
const listLoading = ref(false)
const organizationLoading = ref(false)
const slowLoading = ref(false)
const loadError = ref('')
const listError = ref('')
const organizationError = ref('')
const updatedAt = ref('')
const activeGroup = ref('all')
const activeGroupLabel = ref('全部优先关注')
const selectedOrganizationId = ref('')
const selectedOrganizationName = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const evidenceVisible = ref(false)
const selected = ref<any>({})
let slowTimer: ReturnType<typeof setTimeout> | undefined

const majorOptions = computed(() => draft.college ? majors.value.filter(item => item.college === draft.college) : majors.value)
const classOptions = computed(() => draft.major ? classes.value.filter(item => item.major === draft.major) : classes.value)
const periodText = computed(() => overview.period?.fromSemester && overview.period?.toSemester
  ? `${overview.period.fromSemester} → ${overview.period.toSemester}`
  : '最近两个真实学期')
const emptyDescription = computed(() => activeGroup.value === 'all'
  ? '当前范围未识别到四类优先关注学生'
  : `当前范围没有命中“${activeGroupLabel.value}”的学生`)
const evidenceContext = computed(() => ({
  studentName: selected.value.name,
  reasons: triggerLabels(selected.value),
  period: periodText.value,
  ruleVersion: overview.rule?.version,
  fromGpa: selected.value.fromGpa,
  toGpa: selected.value.toGpa,
  gpaDelta: selected.value.gpaDelta,
  fromFailCount: selected.value.fromFailCount,
  toFailCount: selected.value.toFailCount,
  failDelta: selected.value.failDelta,
  boundary: overview.evidence?.courseOutcomeBoundary,
  returnLabel: pageTitle.value,
  returnQuery: currentViewQuery(),
}))

const organizationCols: DataTableColumn[] = [
  { key: 'organizationName', label: '组织名称', minWidth: 150, fixed: 'left', region: 'identity', required: true },
  { key: 'studentCount', label: '范围学生', width: 92, align: 'right' },
  { key: 'coverageRate', label: '可比较覆盖', minWidth: 130, align: 'right', required: true },
  { key: 'declinedRate', label: '明确恶化', minWidth: 122, align: 'right' },
  { key: 'continuousCount', label: '连续受挫', width: 96, align: 'right' },
  { key: 'firstSetbackCount', label: '首次受挫', width: 96, align: 'right' },
  { key: 'repeatedUnresolvedCount', label: '重复未解决', width: 110, align: 'right' },
  { key: 'openAlertCount', label: '有效预警', width: 96, align: 'right', defaultVisible: false },
  { key: 'actions', label: '操作', width: 96, fixed: 'right', region: 'action', required: true },
]
const studentCols: DataTableColumn[] = [
  { key: 'sid', label: '学号', width: 132, fixed: 'left', region: 'identity', required: true },
  { key: 'name', label: '姓名', width: 100, fixed: 'left', region: 'identity', required: true },
  { key: 'organization', label: '专业 / 班级', minWidth: 190, tooltip: true },
  { key: 'gpaChange', label: 'GPA 起点→终点', minWidth: 150 },
  { key: 'failChange', label: '未通过 起点→终点', minWidth: 160 },
  { key: 'triggers', label: '触发原因', minWidth: 210, required: true },
  { key: 'unresolved', label: '当前未解决', minWidth: 130 },
  { key: 'openAlerts', label: '当前预警', width: 90, align: 'right' },
  { key: 'grade', label: '年级', width: 82, align: 'center', defaultVisible: false },
  { key: 'college', label: '学院', minWidth: 150, tooltip: true, defaultVisible: false },
  { key: 'actions', label: '详情', width: 82, fixed: 'right', region: 'action', required: true },
]

function onCollege() { draft.major = ''; draft.classId = '' }
function onMajor() { draft.classId = '' }
function valueText(value: any, fallback: any = '—') { return value == null ? fallback : value }
function signed(value: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}` }
function ratioCell(count: number, denominator: number, rate: number | null) {
  return rate == null ? `${count}/${denominator} · —` : `${count}/${denominator} · ${rate}%`
}
function deltaClass(value: number | null) { return value == null ? '' : value <= -0.3 ? 'delta-bad' : value >= 0.3 ? 'delta-good' : '' }
function failDeltaClass(value: number | null) { return value == null ? '' : value > 0 ? 'delta-bad' : value < 0 ? 'delta-good' : '' }
function triggerLabels(row: any): string[] {
  if (row?.triggers?.length) return row.triggers
  if (row?.category === 'improved') return ['明确改善']
  if (row?.comparable) return ['具备可比较证据']
  return []
}
function triggerType(label: string) {
  if (label.includes('改善')) return 'success'
  if (label.includes('重复') || label.includes('首次')) return 'danger'
  if (label.includes('连续') || label.includes('恶化')) return 'warning'
  return 'info'
}

function queryParams(extra: Record<string, any> = {}) {
  const params: Record<string, any> = {
    from_semester: applied.fromSemester,
    to_semester: applied.toSemester,
    ...extra,
  }
  if (applied.college) params.college = applied.college
  if (applied.major) params.major = applied.major
  if (applied.grade) params.grade = applied.grade
  if (applied.classId) params.class_id = applied.classId
  return new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value != null) as [string, string][]).toString()
}
function currentViewQuery() {
  return {
    from_semester: applied.fromSemester || undefined,
    to_semester: applied.toSemester || undefined,
    college: applied.college || undefined,
    major: applied.major || undefined,
    grade: applied.grade || undefined,
    class: applied.classId || undefined,
    group: activeGroup.value !== 'all' ? activeGroup.value : undefined,
    organization_id: selectedOrganizationId.value || undefined,
    organization_name: selectedOrganizationName.value || undefined,
    keyword: keyword.value || undefined,
    page: page.value > 1 ? String(page.value) : undefined,
    page_size: pageSize.value !== 20 ? String(pageSize.value) : undefined,
  }
}
async function syncViewState() {
  await router.replace({ query: currentViewQuery() })
}

function beginSlowTimer() {
  if (slowTimer) clearTimeout(slowTimer)
  slowLoading.value = false
  slowTimer = setTimeout(() => { slowLoading.value = true }, 2000)
}
function endSlowTimer() {
  if (slowTimer) clearTimeout(slowTimer)
  slowLoading.value = false
}

async function loadOverview(first = false) {
  if (first) initialLoading.value = true
  else refreshing.value = true
  loadError.value = ''
  beginSlowTimer()
  try {
    const data = await http.get<any>(`/admin/students/growth/overview?${queryParams()}`)
    Object.assign(overview, data || {})
    if (activeGroup.value !== 'all') {
      const active = [...(overview.metrics || []), ...(overview.groups || [])]
        .find((item: any) => item.key === activeGroup.value)
      activeGroupLabel.value = active?.label || activeGroup.value
    }
    updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    await Promise.all([
      loadOrganizations(),
      loadList(first ? page.value : 1),
    ])
  } catch (error: any) {
    loadError.value = error?.message || '学生成长数据加载失败，请稍后重试'
  } finally {
    initialLoading.value = false
    refreshing.value = false
    endSlowTimer()
  }
}

async function loadOrganizations() {
  organizationLoading.value = true
  organizationError.value = ''
  try {
    const data = await http.get<any>(`/admin/students/growth/organizations?${queryParams()}`)
    overview.organizationLabel = data.organizationLabel || ''
    overview.organizations = data.organizations || []
  } catch (error: any) {
    organizationError.value = error?.message || '组织比较加载失败，请稍后重试'
  } finally {
    organizationLoading.value = false
  }
}

async function loadList(targetPage = page.value) {
  listLoading.value = true
  listError.value = ''
  try {
    const extra: Record<string, any> = {
      group: activeGroup.value,
      page: targetPage,
      page_size: pageSize.value,
    }
    if (selectedOrganizationId.value) extra.organization_id = selectedOrganizationId.value
    if (keyword.value) extra.keyword = keyword.value
    const data = await http.get<any>(`/admin/students/growth/list?${queryParams(extra)}`)
    Object.assign(list, data || {})
    page.value = data.page || targetPage
    await syncViewState()
  } catch (error: any) {
    listError.value = error?.message || '学生名单加载失败，请稍后重试'
  } finally {
    listLoading.value = false
  }
}

async function applyScope() {
  if (!draft.fromSemester || !draft.toSemester || draft.fromSemester >= draft.toSemester) {
    ElMessage.warning('请选择有效的起始学期和目标学期')
    return
  }
  Object.assign(applied, draft)
  activeGroup.value = 'all'
  activeGroupLabel.value = '全部优先关注'
  selectedOrganizationId.value = ''
  selectedOrganizationName.value = ''
  keyword.value = ''
  page.value = 1
  await syncViewState()
  await loadOverview()
}

async function resetScope() {
  const newest = semesterOptions.value[0]?.value || ''
  const previous = semesterOptions.value[1]?.value || ''
  Object.assign(draft, {
    fromSemester: previous, toSemester: newest,
    college: scopeType.value === 'college' ? (authStore.user?.scope?.collegeId || '') : '',
    major: '', grade: '', classId: '',
  })
  await applyScope()
}

async function selectGroup(key: string, label: string) {
  activeGroup.value = key
  activeGroupLabel.value = label
  page.value = 1
  await syncViewState()
  await loadList(1)
  document.getElementById('growth-priority-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
async function selectOrganization(row: any) {
  selectedOrganizationId.value = row.organizationId
  selectedOrganizationName.value = row.organizationName
  page.value = 1
  await syncViewState()
  await loadList(1)
  document.getElementById('growth-priority-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
async function clearOrganization() {
  selectedOrganizationId.value = ''
  selectedOrganizationName.value = ''
  await syncViewState()
  await loadList(1)
}
function openEvidence(row: any) {
  selected.value = row
  evidenceVisible.value = true
}

watch(pageSize, () => {
  if (!initialLoading.value) void loadList(1)
})

onMounted(async () => {
  const scrollY = Number(route.query.scrollY || 0)
  const meta = await getFilterMeta()
  semesterOptions.value = (meta.semesters || []).slice().reverse()
  colleges.value = meta.colleges || []
  majors.value = meta.majors || []
  classes.value = meta.classes || []
  grades.value = meta.grades || []
  Object.assign(draft, {
    fromSemester: String(route.query.from_semester || semesterOptions.value[1]?.value || ''),
    toSemester: String(route.query.to_semester || semesterOptions.value[0]?.value || ''),
    college: String(route.query.college || (scopeType.value === 'college' ? authStore.user?.scope?.collegeId || '' : '')),
    major: String(route.query.major || ''),
    grade: String(route.query.grade || ''),
    classId: String(route.query.class || ''),
  })
  Object.assign(applied, draft)
  activeGroup.value = String(route.query.group || 'all')
  selectedOrganizationId.value = String(route.query.organization_id || '')
  selectedOrganizationName.value = String(route.query.organization_name || '')
  keyword.value = String(route.query.keyword || '')
  page.value = Math.max(1, Number(route.query.page || 1) || 1)
  pageSize.value = [10, 20, 50].includes(Number(route.query.page_size))
    ? Number(route.query.page_size) : 20
  await loadOverview(true)
  if (scrollY > 0) {
    await nextTick()
    window.scrollTo({ top: scrollY, behavior: 'auto' })
  }
})
</script>

<style scoped>
.sa-head-row { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:14px; }
.filter-card { margin-bottom:14px; padding:14px 16px; }
.filter-title { display:flex; justify-content:space-between; gap:16px; margin-bottom:10px; font-weight:700; color:#1e293b; }
.filter-title span:last-child { font-size:12px; font-weight:400; color:#64748b; }
.filter-row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
.slow-alert,.error-alert { margin-bottom:12px; }
.drill-card { position:relative; cursor:pointer; border-radius:14px; transition:transform .15s ease, box-shadow .15s ease; }
.drill-card :deep(.sa-kpi) { height:100%; padding-bottom:34px; }
.drill-card:hover,.drill-card.active { transform:translateY(-2px); box-shadow:0 8px 20px rgba(79,70,229,.12); }
.drill-card.active { outline:2px solid rgba(79,70,229,.28); }
.drill-hint { position:absolute; right:16px; bottom:11px; font-size:11px; line-height:1.2; color:#6366f1; }
.management-row { margin:16px 0; }
.group-panel,.organization-panel { height:100%; }
.section-note { margin:4px 0 12px; font-size:12px; color:#64748b; line-height:1.55; }
.group-item { width:100%; border:1px solid #e2e8f0; background:#fff; border-radius:10px; padding:11px 12px; margin-top:8px; display:flex; justify-content:space-between; align-items:center; gap:12px; text-align:left; cursor:pointer; }
.group-item:hover,.group-item.active { border-color:#818cf8; background:#f5f3ff; }
.group-item span { display:flex; flex-direction:column; gap:3px; }
.group-item b { color:#1e293b; }
.group-item small { color:#64748b; line-height:1.35; }
.group-item strong { color:#4f46e5; white-space:nowrap; }
.title-note { margin-left:8px; font-size:11px; font-weight:400; color:#64748b; }
.list-header { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
.list-actions { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.list-rule { margin-bottom:12px; }
.tag-wrap { display:flex; gap:5px; flex-wrap:wrap; }
.delta-good { color:#0d9488; font-weight:700; }
.delta-bad,.danger-text { color:#e11d48; font-weight:700; }
.pager { display:flex; justify-content:flex-end; margin-top:12px; }
@media (max-width: 1100px) {
  .management-row :deep(.el-col) { max-width:100%; flex:0 0 100%; margin-bottom:14px; }
  .list-header { flex-direction:column; }
}
</style>

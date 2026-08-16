<template>
  <div class="early-setback">
    <el-breadcrumb separator="/" class="crumb">
      <el-breadcrumb-item to="/admin/alert">学业预警监控</el-breadcrumb-item>
      <el-breadcrumb-item>低年级风险观察</el-breadcrumb-item>
    </el-breadcrumb>
    <h2 class="sa-page-title">低年级风险观察</h2>
    <p class="sa-page-sub">
      从大一首次出现未通过记录开始，观察后续变化，识别课程支持与持续核查的优先方向。
    </p>

    <div v-if="initialLoading" class="initial-loading">
      <b>正在建立低年级历史观察样本</b>
      <p>正在核对入学年、大一常规学期成绩和后续成绩轨迹，请稍候…</p>
      <el-skeleton :rows="9" animated />
    </div>

    <template v-else>
      <el-alert
        v-if="loadError"
        type="error"
        :closable="false"
        show-icon
        title="低年级风险观察加载失败"
      >
        <template #default>
          {{ loadError }}
          <el-button link type="primary" @click="load">重新加载</el-button>
        </template>
      </el-alert>
      <div class="filters">
        <b>观察条件</b>
        <el-select v-model="draft.college" clearable placeholder="学院" @change="handleCascadeChange('college')">
          <el-option v-for="item in options.college" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="draft.major" clearable placeholder="专业" @change="handleCascadeChange('major')">
          <el-option v-for="item in options.major" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="draft.grade" clearable placeholder="年级" @change="handleCascadeChange('grade')">
          <el-option v-for="item in options.grade" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="draft.classCode" clearable placeholder="班级" @change="handleCascadeChange('class')">
          <el-option v-for="item in options.class" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-button type="primary" :loading="refreshing" @click="applyFilter">查询</el-button>
        <el-button :disabled="refreshing" @click="reset">重置</el-button>
      </div>

      <div v-if="refreshing" class="refresh-feedback">
        正在按观察条件更新指标、课程、关注优先级和学生名单，原结果暂时保留…
      </div>

      <div class="kpis">
        <button
          v-for="item in kpis"
          :key="item.key"
          type="button"
          class="kpi"
          :class="{ active: listPreset === item.preset }"
          :aria-pressed="listPreset === item.preset"
          @click="applyKpiPreset(item)"
        >
          <b>{{ item.value }}</b>
          <KpiLabel :label="item.label" :formula="item.help" />
          <small>{{ item.note }}</small>
        </button>
      </div>

      <section class="sa-card management-value">
        <div class="sa-card-title">这组数据帮助管理员决定什么</div>
        <p>{{ definition.management_value }}</p>
        <div>
          <span><b>看人数</b>：估算课程支持和核查资源规模</span>
          <span><b>看比例</b>：排除专业规模差异，识别群体集中</span>
          <span><b>看持续</b>：优先打开学生变化证据进行人工核查</span>
          <span><b>看改善</b>：避免依据大一记录长期贴标签</span>
        </div>
      </section>

      <div class="grid">
        <section class="sa-card">
          <div class="section-title">
            <div>
              <h3>各年级大一未通过情况</h3>
            </div>
          </div>
          <DataTable
            :columns="gradeColumns"
            :data="data.by_grade"
            storage-key="alert:early-setback:grade"
            config-version="2"
            :max-business-columns="5"
            size="small"
          >
            <template #col-entry_grade="{ row }">{{ row.entry_grade }}级</template>
            <template #col-setback_rate="{ row }">
              {{ rate(row.setback_students, row.eligible_students) }}%
            </template>
          </DataTable>
        </section>

        <section class="sa-card">
          <div class="section-title">
            <div>
              <h3>大一未通过学生集中的课程 TOP10</h3>
            </div>
          </div>
          <DataTable
            :columns="courseColumns"
            :data="data.courses"
            storage-key="alert:early-setback:courses"
            config-version="2"
            :max-business-columns="2"
            size="small"
          />
          <p class="foot">学生数为去重人数；记录数可能包含同一学生的多次未通过。</p>
        </section>
      </div>

      <section class="sa-card">
        <div class="section-title">
          <div>
            <h3>{{ focusTitle }}</h3>
            <p>{{ focusDescription }}</p>
          </div>
        </div>
        <DataTable
          :columns="focusColumns"
          :data="data.focus_groups"
          storage-key="alert:early-setback:majors"
          config-version="3"
          :max-business-columns="5"
          size="small"
        >
          <template #col-setback_rate="{ row }">
            {{ rate(row.setback_students, row.eligible_students) }}%
          </template>
        </DataTable>
      </section>

      <section ref="studentListSection" class="sa-card student-list-section">
        <div class="section-title">
          <div>
            <h3>学生核查名单</h3>
            <p>共 {{ data.total || 0 }} 名学生；点击学生在抽屉中查看变化证据。</p>
          </div>
          <el-tag effect="plain" type="info">不自动建立处置任务</el-tag>
        </div>
        <DataTable
          :columns="studentColumns"
          :data="data.students"
          storage-key="alert:early-setback:students"
          config-version="3"
          :max-business-columns="8"
          :page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          size="small"
          row-class-name="row-clickable"
          empty-text="当前观察条件下没有符合名单条件的学生"
          @row-click="showStudent"
          @update:page-size="changePageSize"
        >
          <template #col-student="{ row }">
            <div class="student-cell">
              <button type="button" @click.stop="showStudent(row)">{{ row.display_name }}</button>
              <span>{{ row.student_id }}</span>
            </div>
          </template>
          <template #col-entry_grade="{ row }">{{ row.entry_grade }}级</template>
          <template #col-recovery_status="{ row }">
            <el-tag :type="tagType(row.recovery_status)" size="small">
              {{ statusName[row.recovery_status] }}
            </el-tag>
          </template>
          <template #col-action="{ row }">
            <el-button link type="primary" @click.stop="showStudent(row)">核查</el-button>
          </template>
        </DataTable>
        <el-pagination
          v-if="data.total"
          v-model:current-page="page"
          :page-size="pageSize"
          :total="data.total"
          layout="total, prev, pager, next"
          small
          @current-change="load"
        />
      </section>

      <section class="sa-card definition">
        <div class="sa-card-title">指标口径与适用边界</div>
        <div class="definition-grid">
          <p><b>纳入观察</b><span>{{ definition.first_year }}</span></p>
          <p><b>大一有未通过</b><span>{{ definition.setback }}</span></p>
          <p><b>后续未再出现未通过</b><span>{{ definition.recovered }}</span></p>
          <p><b>后续仍需观察</b><span>{{ definition.recovering }}</span></p>
          <p><b>后续持续出现未通过</b><span>{{ definition.persistent }}</span></p>
          <p><b>暂无后续成绩</b><span>{{ definition.pending_observation }}</span></p>
        </div>
      </section>
    </template>

    <EarlySetbackDrawer v-model="drawerVisible" :row="selectedStudent" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { http } from '@/utils/http'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import EarlySetbackDrawer from '@/views/admin/alert/EarlySetbackDrawer.vue'

type FilterState = {
  college: string
  major: string
  classCode: string
  grade?: number
}

type FilterOption = {
  value: string | number
  label: string
}

const emptyFilter = (): FilterState => ({ college: '', major: '', classCode: '', grade: undefined })
const refreshing = ref(false)
const initialLoading = ref(true)
const loadError = ref('')
const draft = reactive<FilterState>(emptyFilter())
const applied = reactive<FilterState>(emptyFilter())
const appliedLabels = reactive({ college: '', major: '', classCode: '' })
const options = reactive<Record<'college' | 'major' | 'class' | 'grade', FilterOption[]>>({
  college: [], major: [], class: [], grade: [],
})
const page = ref(1)
const pageSize = ref(50)
const requestId = ref(0)
const optionsRequestId = ref(0)
const listPreset = ref('')
const studentListSection = ref<HTMLElement | null>(null)
const drawerVisible = ref(false)
const selectedStudent = ref<any>(null)
const data = reactive<any>({
  summary: {}, by_grade: [], by_major: [], focus_groups: [], courses: [], students: [], total: 0,
})
const definition = reactive<any>({})
const statusName: Record<string, string> = {
  no_setback: '大一未出现未通过',
  recovered: '后续未再出现未通过',
  recovering: '后续仍需观察',
  persistent: '后续持续出现未通过',
  pending_observation: '暂无后续成绩',
}
const kpis = computed(() => [
  {
    key: 'eligible', preset: 'eligible', count: data.summary.eligible_students || 0,
    label: '纳入低年级观察', value: `${data.summary.eligible_students || 0}人`,
    note: '其余比例指标的统计分母', help: definition.first_year || '',
  },
  {
    key: 'setback', preset: 'setback', count: data.summary.setback_students || 0,
    label: '大一有未通过学生', value: `${data.summary.setback_students || 0}人`,
    note: `${data.summary.setback_students || 0}/${data.summary.eligible_students || 0}人，${data.summary.setback_rate || 0}%`,
    help: definition.setback || '',
  },
  {
    key: 'recovered', preset: 'recovered', count: data.summary.recovered_students || 0,
    label: '后续未再出现未通过', value: `${data.summary.recovered_students || 0}人`,
    note: '作为改善证据，不等于原课程已通过', help: definition.recovered || '',
  },
  {
    key: 'persistent', preset: 'persistent', count: data.summary.persistent_students || 0,
    label: '后续持续出现未通过', value: `${data.summary.persistent_students || 0}人`,
    note: '优先查看课程与学生变化证据', help: definition.persistent || '',
  },
  {
    key: 'pending', preset: 'pending_observation', count: data.summary.pending_students || 0,
    label: '暂无后续成绩', value: `${data.summary.pending_students || 0}人`,
    note: '下次成绩发布后复核', help: definition.pending_observation || '',
  },
])
const focusTitle = computed(() => {
  if (applied.classCode) return `${appliedLabels.classCode || applied.classCode}-关注优先级`
  if (applied.major) return '各班级关注优先级'
  if (applied.college) return '各专业关注优先级'
  return '各学院关注优先级'
})
const focusDescription = computed(() => {
  if (applied.classCode) return '展示当前班级，按未通过学生比例核查群体情况。'
  if (applied.major) return '展示当前专业下各班级，按未通过学生比例降序排序。'
  if (applied.college) return '展示当前学院下各专业，按未通过学生比例降序排序。'
  return '展示当前授权范围内各学院，按未通过学生比例降序排序。'
})
const focusIdentityLabel = computed(() => ({
  college: '学院', major: '专业', class: '班级',
}[data.focus_dimension as string] || '组织') as string)
const focusColumns = computed<DataTableColumn[]>(() => [
  { key: 'group_name', label: focusIdentityLabel.value, required: true, region: 'identity', minWidth: 180, tooltip: true },
  { key: 'eligible_students', label: '观察学生', region: 'business' },
  { key: 'setback_students', label: '大一有未通过', required: true, region: 'business' },
  { key: 'setback_rate', label: '未通过学生比例', required: true, region: 'business' },
  { key: 'persistent_students', label: '后续持续', required: true, region: 'business' },
  { key: 'improved_students', label: '后续未再出现', region: 'business' },
])
const gradeColumns: DataTableColumn[] = [
  { key: 'entry_grade', label: '年级', required: true, region: 'identity', width: 90 },
  { key: 'eligible_students', label: '观察学生', required: true, region: 'business' },
  { key: 'setback_students', label: '大一有未通过', required: true, region: 'business' },
  { key: 'setback_rate', label: '未通过学生比例', required: true, region: 'business' },
  { key: 'persistent_students', label: '后续持续', region: 'business' },
  { key: 'improved_students', label: '后续未再出现', region: 'business' },
]
const courseColumns: DataTableColumn[] = [
  { key: 'course_name', label: '课程', required: true, region: 'identity', minWidth: 190, tooltip: true },
  { key: 'affected_students', label: '未通过学生', required: true, region: 'business' },
  { key: 'failed_attempts', label: '未通过记录', region: 'business' },
]
const studentColumns: DataTableColumn[] = [
  { key: 'student', label: '学生', required: true, region: 'identity', fixed: 'left', width: 125 },
  { key: 'organization_name', label: '学院', region: 'business', minWidth: 170, tooltip: true },
  { key: 'major_name', label: '专业', region: 'business', minWidth: 150, tooltip: true },
  { key: 'class_code', label: '班级', region: 'business', minWidth: 130, tooltip: true },
  { key: 'entry_grade', label: '年级', region: 'business', width: 75 },
  { key: 'first_setback_semester', label: '首次未通过学期', required: true, region: 'business', width: 125 },
  { key: 'first_year_failures', label: '大一未通过记录', region: 'business', width: 115 },
  { key: 'later_failures', label: '后续未通过记录', region: 'business', width: 115 },
  { key: 'recovery_status', label: '当前观察状态', required: true, region: 'business', width: 150 },
  { key: 'action', label: '操作', required: true, region: 'action', fixed: 'right', width: 65 },
]

function rate(numerator: number, denominator: number) {
  return denominator ? Math.round(numerator * 1000 / denominator) / 10 : 0
}
function tagType(status: string) {
  return status === 'persistent' ? 'danger'
    : status === 'recovered' ? 'success'
      : status === 'recovering' ? 'warning' : 'info'
}
function appendFilters(query: URLSearchParams, filter: FilterState) {
  if (filter.college) query.set('organization_id', filter.college)
  if (filter.major) query.set('major_code', filter.major)
  if (filter.classCode) query.set('class_code', filter.classCode)
  if (filter.grade) query.set('entry_grade', String(filter.grade))
}
function optionLabel(key: 'college' | 'major' | 'class', value: string) {
  return options[key].find(item => String(item.value) === value)?.label || value
}
async function loadOptions(filter: FilterState = draft) {
  const id = ++optionsRequestId.value
  const query = new URLSearchParams()
  appendFilters(query, filter)
  const result = await http.get<any>(`/v2/topics/early-setback/options?${query.toString()}`)
  if (id !== optionsRequestId.value) return
  options.college = result.college || []
  options.major = result.major || []
  options.class = result.class || []
  options.grade = result.grade || []
}
async function handleCascadeChange(dimension: 'college' | 'major' | 'class' | 'grade') {
  if (dimension === 'college') {
    draft.major = ''
    draft.classCode = ''
  } else if (dimension === 'major') {
    draft.classCode = ''
  }
  try {
    await loadOptions(draft)
    if (draft.classCode && !options.class.some(item => item.value === draft.classCode)) draft.classCode = ''
  } catch (error: any) {
    loadError.value = error?.message || '观察条件加载失败，请稍后重试'
  }
}
async function applyFilter() {
  Object.assign(applied, draft)
  appliedLabels.college = optionLabel('college', applied.college)
  appliedLabels.major = optionLabel('major', applied.major)
  appliedLabels.classCode = optionLabel('class', applied.classCode)
  listPreset.value = ''
  page.value = 1
  await load()
}
async function reset() {
  Object.assign(draft, emptyFilter())
  Object.assign(applied, emptyFilter())
  Object.assign(appliedLabels, { college: '', major: '', classCode: '' })
  listPreset.value = ''
  page.value = 1
  await loadOptions(draft)
  await load()
}
async function applyKpiPreset(item: { preset: string, count: number }) {
  listPreset.value = item.preset
  page.value = 1
  const total = await load()
  if (typeof total === 'number' && total !== item.count) {
    loadError.value = `名单共 ${total} 人，与指标卡 ${item.count} 人不一致，请刷新后重试`
  }
  await nextTick()
  studentListSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function changePageSize(value: number) {
  if (value === pageSize.value) return
  pageSize.value = value
  page.value = 1
  load()
}
function showStudent(row: any) {
  selectedStudent.value = row
  drawerVisible.value = true
}
async function load() {
  const id = ++requestId.value
  refreshing.value = !initialLoading.value
  loadError.value = ''
  try {
    const query = new URLSearchParams({
      limit: String(pageSize.value),
      offset: String((page.value - 1) * pageSize.value),
    })
    appendFilters(query, applied)
    if (listPreset.value) query.set('observation_status', listPreset.value)
    const result = await http.get<any>(`/v2/topics/early-setback?${query.toString()}`)
    if (id !== requestId.value) return undefined
    Object.assign(data, result)
    Object.assign(definition, result.definition || {})
    return Number(result.total || 0)
  } catch (error: any) {
    if (id === requestId.value) loadError.value = error?.message || '请稍后重试'
    return undefined
  } finally {
    if (id === requestId.value) {
      refreshing.value = false
      initialLoading.value = false
    }
  }
}
onMounted(async () => {
  try {
    await loadOptions(draft)
  } catch (error: any) {
    loadError.value = error?.message || '观察条件加载失败，请稍后重试'
  }
  await load()
})
</script>

<style scoped>
.crumb {
  margin-bottom: 8px;
}
.initial-loading {
  padding: 18px;
  border: 1px solid var(--sa-border);
  border-radius: 12px;
  background: #fff;
}
.initial-loading > b {
  color: var(--sa-text);
  font-size: 15px;
}
.initial-loading > p {
  margin: 5px 0 18px;
  color: var(--sa-muted);
  font-size: 12px;
}
.early-setback > .el-alert {
  margin-bottom: 12px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px 0;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
}
.filters b {
  flex: 0 0 auto;
  color: #334155;
  font-size: 12px;
}
.filters .el-select {
  width: 178px;
}
.refresh-feedback {
  margin-bottom: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #eef2ff;
  color: #4338ca;
  font-size: 12px;
}
.kpis {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.kpi {
  min-width: 0;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  background: #fff;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.kpi:hover,
.kpi:focus-visible {
  border-color: #818cf8;
  box-shadow: 0 7px 18px rgba(79, 70, 229, .1);
  outline: none;
  transform: translateY(-1px);
}
.kpi.active {
  border-color: #6366f1;
  background: #f8f8ff;
  box-shadow: inset 0 0 0 1px #c7d2fe;
}
.kpi > b {
  display: block;
  margin-bottom: 7px;
  color: #1e293b;
  font-size: 24px;
}
.kpi small {
  display: block;
  margin-top: 4px;
  overflow: hidden;
  color: #94a3b8;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.management-value p {
  color: #475569;
  font-size: 12px;
  line-height: 1.7;
}
.management-value > div:last-child {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.management-value span {
  padding: 7px 10px;
  border-radius: 7px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 11px;
}
.management-value span b {
  color: #334155;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.sa-card {
  margin-bottom: 14px;
}
.section-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.section-title h3 {
  margin: 0;
  color: #1e293b;
  font-size: 14px;
}
.section-title p {
  margin: 4px 0 0;
  color: #94a3b8;
  font-size: 11px;
}
.foot {
  color: #94a3b8;
  font-size: 11px;
}
.student-list-section {
  scroll-margin-top: 16px;
}
.student-cell {
  display: flex;
  flex-direction: column;
}
.student-cell button {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--sa-primary);
  cursor: pointer;
  text-align: left;
  font-size: 12px;
  font-weight: 650;
}
.student-cell span {
  margin-top: 2px;
  color: #94a3b8;
  font-size: 10px;
}
.el-pagination {
  justify-content: flex-end;
  margin-top: 12px;
}
.definition-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 18px;
}
.definition-grid p {
  margin: 0;
  padding: 9px 0;
  border-bottom: 1px dashed #e2e8f0;
}
.definition-grid b,
.definition-grid span {
  display: block;
}
.definition-grid b {
  color: #334155;
  font-size: 12px;
}
.definition-grid span {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.6;
}
:deep(.row-clickable) {
  cursor: pointer;
}
:deep(.row-clickable:hover td.el-table__cell) {
  background: #f5f7ff !important;
}
@media (max-width: 1100px) {
  .kpis {
    grid-template-columns: repeat(3, 1fr);
  }
  .grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 900px) {
  .filters {
    align-items: stretch;
    flex-wrap: wrap;
  }
  .filters .el-select {
    width: calc(50% - 8px);
  }
}
@media (max-width: 760px) {
  .kpis,
  .definition-grid {
    grid-template-columns: 1fr;
  }
  .filters {
    flex-direction: column;
  }
  .filters .el-select {
    width: 100%;
  }
}
</style>

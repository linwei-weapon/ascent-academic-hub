<template>
  <div class="basic-report-page">
    <div v-if="!isRpt02 && !isRpt04A && !isRpt04B && !isRpt05 && !isRpt06 && !isFocusRoster" class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ definition.reportId }} {{ definition.title }}</h2>
        <p class="sa-page-sub">固定口径只读报表 · 查询结果按原始报表结构展示 · 支持 Excel 导出</p>
      </div>
      <el-button v-if="!isRpt06" type="primary" plain :disabled="!result?.capabilities?.export || !result?.snapshotToken || loading" :loading="exporting" @click="exportExcel">
        <el-icon><Download /></el-icon> 导出 Excel
      </el-button>
    </div>

    <el-card shadow="never" class="filter-card">
      <el-form :inline="true" label-position="top" class="report-filter">
        <el-form-item label="学年学期" :required="isRequired('semesterId')">
          <el-select v-model="draft.semesterId" clearable filterable placeholder="请选择学年学期" style="width:180px">
            <el-option v-for="item in options.semesters" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item :label="usesGradeLabel ? '年级' : '入学年级'" :required="isRequired('entryGrade')">
          <el-select v-model="draft.entryGrade" clearable :placeholder="usesGradeLabel ? '请选择年级' : '请选择入学年级'" style="width:150px">
            <el-option v-for="item in options.entryGrades" :key="item" :label="`${item}级`" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="学院" :required="isRequired('organizationId')">
          <el-select v-model="draft.organizationId" clearable filterable placeholder="请选择学院" style="width:220px">
            <el-option v-for="item in organizationOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!isRpt02" label="专业" :required="isRequired('majorCode')">
          <el-select v-model="draft.majorCode" clearable filterable placeholder="请选择专业" style="width:220px">
            <el-option v-for="item in majorOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!isRpt02 && !isRpt04A && !isRpt05" label="班级" :required="isRequired('classCode')">
          <el-select v-model="draft.classCode" clearable filterable placeholder="请选择班级" style="width:190px">
            <el-option v-for="item in classOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label=" "><el-button type="primary" :loading="loading" @click="applyFilters">查询</el-button><el-button @click="resetFilters">重置</el-button></el-form-item>
      </el-form>
      <p class="filter-tip">带 <span>*</span> 的条件必须填写；必选条件未完整填写时不发起查询，结果区仅展示原始报表表头。</p>
    </el-card>

    <div v-if="result && !isRpt02 && !isRpt04A && !isRpt04B && !isRpt05 && !isRpt06 && !isFocusRoster" class="context-strip">
      <span><b>当前身份：</b>{{ result.context.identity }}</span><span><b>学期：</b>{{ result.context.semesterId }}</span>
      <span><b>{{ usesGradeLabel ? '年级' : '入学年级' }}：</b>{{ result.context.entryGrade }}级</span><span><b>口径版本：</b>{{ result.context.ruleVersion }}</span>
      <span><b>结果行数：</b>{{ result.total }}</span>
    </div>

    <el-alert v-if="result?.status === 'source_unavailable' && !isFocusRoster" type="warning" :closable="false" show-icon title="当前没有可用的数据源" :description="sourceUnavailableDescription" />
    <el-alert v-else-if="result?.status === 'detail_forbidden'" type="warning" :closable="false" show-icon title="当前身份没有名单明细权限" description="已返回授权范围内的汇总人数；姓名、学号和课程证据需要现有 student.detail 动作权限。" />

    <el-card shadow="never" class="result-card" v-loading="loading">
      <template #header><div class="card-title">
        <div class="title-with-help">
          <span>{{ result?.title || definition.title }}</span>
          <el-tooltip v-if="isFocusRoster && focusRule" placement="top" :show-after="200">
            <template #content>
              <div class="focus-rule-tip">
                <b>重点关注学生规则</b>
                <div v-for="item in focusRule.items" :key="item.ruleId">
                  {{ item.ruleId }}（{{ item.level }}）：{{ item.description }}<span v-if="!item.enabled">（当前停用）</span>
                </div>
                <div>{{ focusRule.dedupDescription }}</div>
                <div v-if="focusRule.versions?.length">预警快照版本：{{ focusRule.versions.join('、') }}</div>
              </div>
            </template>
            <el-icon class="rule-help-icon" tabindex="0" aria-label="查看重点关注学生规则"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
        <el-button v-if="result && (isRpt02 || isRpt04A || isRpt04B || isRpt05 || isRpt06 || isFocusRoster)" type="primary" plain :disabled="!result.capabilities?.export || !result.snapshotToken || loading" :loading="exporting" @click="exportExcel">
          <el-icon><Download /></el-icon> 导出 Excel
        </el-button>
        <el-tag v-else-if="result" effect="plain">{{ result.status }}</el-tag>
      </div></template>

      <el-table v-if="definition.reportId === 'RPT-05'" :data="result?.rows || []" border :span-method="spanMethod" :row-class-name="rowClassName" empty-text="">
        <el-table-column prop="course" label="科目" min-width="190" fixed="left"><template #default="{ row }"><span class="multiline-cell">{{ row.course }}</span></template></el-table-column>
        <el-table-column prop="majorName" label="专业" min-width="160" fixed="left" />
        <el-table-column prop="majorStudentCount" label="专业人数" min-width="100" align="center" />
        <el-table-column label="补考前数据" align="center">
          <el-table-column prop="failedBeforeStudents" label="挂科人数" min-width="100" align="center" />
          <el-table-column prop="failedBeforeRate" label="专业挂科率" min-width="120" align="center"><template #default="{ row }">{{ formatRate(row.failedBeforeRate) }}</template></el-table-column>
          <el-table-column prop="failedBeforeCourseTotal" label="挂科总人数" min-width="110" align="center" />
          <el-table-column prop="failedBeforeCourseRate" label="总挂科率" min-width="110" align="center"><template #default="{ row }">{{ formatRate(row.failedBeforeCourseRate) }}</template></el-table-column>
        </el-table-column>
        <el-table-column label="补考后数据" align="center">
          <el-table-column prop="failedAfterStudents" label="挂科人数" min-width="100" align="center" />
          <el-table-column prop="failedAfterRate" label="专业挂科率" min-width="120" align="center"><template #default="{ row }">{{ formatRate(row.failedAfterRate) }}</template></el-table-column>
          <el-table-column prop="failedAfterCourseTotal" label="挂科总人数" min-width="110" align="center" />
          <el-table-column prop="failedAfterCourseRate" label="总挂科率" min-width="110" align="center"><template #default="{ row }">{{ formatRate(row.failedAfterCourseRate) }}</template></el-table-column>
        </el-table-column>
        <el-table-column prop="makeupPassedStudents" label="补考通过人数" min-width="120" align="center" />
        <template #empty><div class="blank-table-body">{{ result ? '当前授权范围和筛选条件下无数据' : '' }}</div></template>
      </el-table>

      <DataTable v-else :key="definition.reportId" :columns="definition.columns" :data="result?.rows || []" :storage-key="`basic-report:${definition.reportId}`" :span-method="spanMethod" :row-class-name="rowClassName" max-business-columns="12" :config-version="isRpt02 || isRpt06 ? 3 : 2" empty-text="">
        <template v-if="isRpt02" #header-failedBeforeRate>
          <span class="formula-header">挂科率（补考前）<el-tooltip content="挂科率（补考前）= 已挂人数 ÷ 专业人数" placement="top"><el-icon class="formula-help-icon" tabindex="0" aria-label="查看补考前挂科率计算公式"><QuestionFilled /></el-icon></el-tooltip></span>
        </template>
        <template v-if="isRpt02" #header-failedAfterRate>
          <span class="formula-header">挂科率（补考后）<el-tooltip content="挂科率（补考后）= 在挂人数 ÷ 专业人数" placement="top"><el-icon class="formula-help-icon" tabindex="0" aria-label="查看补考后挂科率计算公式"><QuestionFilled /></el-icon></el-tooltip></span>
        </template>
        <template v-if="isRpt02" #header-passRate>
          <span class="formula-header">通过率<el-tooltip content="通过率 =（专业人数－在挂人数）÷ 专业人数" placement="top"><el-icon class="formula-help-icon" tabindex="0" aria-label="查看通过率计算公式"><QuestionFilled /></el-icon></el-tooltip></span>
        </template>
        <template #col-courseEvidence="{ row }"><span class="multiline-cell">{{ row.courseEvidence || '—' }}</span></template>
        <template #col-cet4PassRateRank="{ row }">
          <span v-if="row.cet4PassRateRank" :class="rankClass(row.cet4PassRateRank)">{{ row.cet4PassRateRank }}</span><span v-else>—</span>
        </template>
        <template #empty><div class="blank-table-body">{{ result ? '当前授权范围和筛选条件下无数据' : '' }}</div></template>
      </DataTable>
    </el-card>

    <el-collapse v-if="result && !isRpt02 && !isRpt04A && !isRpt04B && !isRpt05 && !isRpt06 && !isFocusRoster" class="boundary-panel">
      <el-collapse-item title="数据来源、计算规则与适用边界" name="rules">
        <ul><li v-for="item in result.boundary" :key="item">{{ item }}</li></ul>
        <el-table :data="result.rules" size="small" border><el-table-column prop="ruleId" label="规则编号" width="190" /><el-table-column prop="provenance" label="来源类型" width="120" /><el-table-column prop="source" label="复用来源" min-width="240" /><el-table-column prop="formula" label="计算方法" min-width="300" /><el-table-column prop="boundary" label="适用边界" min-width="300" /></el-table>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DataTable from '@/components/DataTable.vue'
import { http } from '@/utils/http'
import { authStore } from '@/store/auth'
import { reportDefinitions, type BasicReportFilter } from './reportDefinitions'

const route = useRoute()
const router = useRouter()
const definition = computed(() => reportDefinitions[route.path] || reportDefinitions['/admin/basic-reports/failure-overview'])
const isRpt02 = computed(() => definition.value.reportId === 'RPT-02')
const isRpt04A = computed(() => definition.value.reportId === 'RPT-04A')
const isRpt04B = computed(() => definition.value.reportId === 'RPT-04B')
const isRpt06 = computed(() => definition.value.reportId === 'RPT-06')
const isRpt05 = computed(() => definition.value.reportId === 'RPT-05')
const isFocusRoster = computed(() => ['RPT-07', 'RPT-08'].includes(definition.value.reportId))
const usesGradeLabel = computed(() => isRpt02.value || isRpt04A.value || isRpt04B.value || isRpt05.value || isRpt06.value || isFocusRoster.value)
const options = reactive<any>({ semesters: [], entryGrades: [], organizations: [], majors: [], classes: [] })
const draft = reactive<any>({ semesterId: '', entryGrade: null, organizationId: '', majorCode: '', classCode: '' })
const applied = reactive<any>({ semesterId: '', entryGrade: null, organizationId: '', majorCode: '', classCode: '' })
const result = ref<any>(null)
const focusRule = computed(() => result.value?.focusRule || null)
const loading = ref(false)
const exporting = ref(false)

const organizationOptions = computed(() => options.organizations.map((item: any[]) => ({ value: item[0], label: item[1] })))
const sourceUnavailableDescription = computed(() => isFocusRoster.value
  ? '所选学期没有已接入的预警快照，不能把数据缺失解释为0名名单学生。'
  : '当前查询范围没有可用的数据源。')
const majorOptions = computed(() => {
  const values = options.majors.filter((item: any) => !draft.organizationId || item.organizationId === draft.organizationId)
  return Array.from(new Map(values.map((item: any) => [item.majorCode, { value: item.majorCode, label: item.majorName }])).values())
})
const classOptions = computed(() => Array.from(new Set(options.classes
  .filter((item: any) => !draft.majorCode || item.majorCode === draft.majorCode)
  .map((item: any) => item.classCode))))

watch(() => draft.organizationId, () => {
  if (!majorOptions.value.some((item: any) => item.value === draft.majorCode)) draft.majorCode = ''
  draft.classCode = ''
})
watch(() => draft.majorCode, () => { if (!classOptions.value.includes(draft.classCode)) draft.classCode = '' })
watch(() => authStore.user?.activeIdentityId, async () => { clearPage(); await loadOptions() })
watch(() => route.path, () => clearPage())

function isRequired(key: BasicReportFilter) { return definition.value.requiredFilters.includes(key) }
function formatRate(value: number | null | undefined) { return value == null ? '—' : `${(value * 100).toFixed(2)}%` }
function rankClass(rank: number) {
  return rank <= 3 ? ['cet4-rank', 'rank-' + rank] : 'cet4-rank-text'
}
function clearPage() {
  Object.assign(draft, { semesterId: '', entryGrade: null, organizationId: '', majorCode: '', classCode: '' })
  Object.assign(applied, draft)
  result.value = null
}

function queryParams() {
  const params = new URLSearchParams({ semesterId: applied.semesterId })
  if (applied.entryGrade != null && applied.entryGrade !== '') params.set('entryGrade', String(applied.entryGrade))
  if (applied.organizationId) params.set('organizationId', applied.organizationId)
  if (!isRpt02.value && applied.majorCode) params.set('majorCode', applied.majorCode)
  if (!isRpt02.value && !isRpt04A.value && !isRpt05.value && applied.classCode) params.set('classCode', applied.classCode)
  return params
}

async function loadOptions() {
  const data = await http.get<any>('/admin/basic-reports/options')
  Object.assign(options, data)
}

async function applyFilters() {
  const labels: Record<BasicReportFilter, string> = { semesterId: '学年学期', entryGrade: usesGradeLabel.value ? '年级' : '入学年级', organizationId: '学院', majorCode: '专业', classCode: '班级' }
  const missing = definition.value.requiredFilters.filter(key => !draft[key]).map(key => labels[key])
  if (missing.length) { ElMessage.warning(`请选择必选查询条件：${missing.join('、')}`); return }
  Object.assign(applied, draft)
  await router.replace({ path: route.path, query: Object.fromEntries(queryParams()) })
  await loadReport()
}

async function loadReport() {
  loading.value = true
  try { result.value = await http.get<any>(`/admin/basic-reports/${definition.value.slug}?${queryParams()}`) }
  finally { loading.value = false }
}

function resetFilters() { clearPage(); router.replace({ path: route.path }) }

function spanMethod({ rowIndex, column }: any) {
  const groupKey = definition.value.mergeBy?.[column.property]
  const rows = result.value?.rows || []
  if (!groupKey || !rows[rowIndex] || rows[rowIndex].isSummary) return [1, 1]
  const value = rows[rowIndex][groupKey]
  if (value == null || value === '') return [1, 1]
  if (rowIndex > 0 && rows[rowIndex - 1]?.[groupKey] === value && !rows[rowIndex - 1]?.isSummary) return [0, 0]
  let rowspan = 1
  while (rowIndex + rowspan < rows.length && rows[rowIndex + rowspan]?.[groupKey] === value && !rows[rowIndex + rowspan]?.isSummary) rowspan += 1
  return [rowspan, 1]
}

function rowClassName({ row }: any) { return row?.isSummary ? 'basic-report-summary-row' : '' }

async function exportExcel() {
  if (!result.value?.snapshotToken) return
  exporting.value = true
  try {
    const params = queryParams(); params.set('snapshotToken', result.value.snapshotToken)
    await http.download(`/admin/basic-reports/${definition.value.slug}/export?${params}`)
    ElMessage.success('Excel 已生成')
  } finally { exporting.value = false }
}

onMounted(loadOptions)
</script>

<style scoped>
.basic-report-page { display:flex; flex-direction:column; gap:16px; }
.filter-card,.result-card { border-color:var(--el-border-color-lighter); }
.report-filter { display:flex; align-items:flex-end; gap:4px 12px; }
.report-filter :deep(.el-form-item) { margin:0; }
.filter-tip { margin:10px 0 0; color:var(--el-text-color-secondary); font-size:12px; }
.formula-header { display:inline-flex; align-items:center; justify-content:center; gap:4px; }
.formula-help-icon { color:var(--el-color-primary); cursor:help; font-size:14px; }
.formula-help-icon:focus-visible { outline:2px solid var(--el-color-primary-light-5); outline-offset:2px; border-radius:50%; }
.filter-tip span { color:var(--el-color-danger); }
.context-strip { display:flex; flex-wrap:wrap; gap:8px 24px; padding:12px 16px; color:var(--el-text-color-regular); background:var(--el-fill-color-light); border-radius:6px; font-size:13px; }
.card-title { display:flex; justify-content:space-between; align-items:center; font-weight:600; }
.title-with-help { display:flex; align-items:center; gap:6px; min-width:0; }
.rule-help-icon { flex:0 0 auto; color:var(--el-color-primary); cursor:help; font-size:16px; }
.rule-help-icon:focus-visible { outline:2px solid var(--el-color-primary-light-5); outline-offset:2px; border-radius:50%; }
.focus-rule-tip { max-width:460px; line-height:1.7; }
.blank-table-body { min-height:48px; }
.multiline-cell { white-space:pre-line; line-height:1.65; }
.result-card :deep(.basic-report-summary-row td) { background:var(--el-fill-color-light); font-weight:700; }
.cet4-rank { display:inline-flex; width:28px; height:28px; align-items:center; justify-content:center; border-radius:50%; color:#fff; font-weight:700; line-height:1; box-shadow:0 1px 3px rgb(15 23 42 / 18%); }
.cet4-rank.rank-1 { background:#c9a227; }
.cet4-rank.rank-2 { background:#b87333; }
.cet4-rank.rank-3 { background:#9ca3af; }
.cet4-rank-text { font-weight:600; font-variant-numeric:tabular-nums; }
.boundary-panel { border:1px solid var(--el-border-color-lighter); border-radius:6px; padding:0 16px; }
.boundary-panel ul { margin:0 0 16px; padding-left:22px; color:var(--el-text-color-regular); line-height:1.8; }
</style>

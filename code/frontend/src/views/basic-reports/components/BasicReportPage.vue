<!-- 基础报表公共页面：集中维护授权筛选、查询、原快照导出和报表切换。 -->
<template>

  <div class="basic-report-page">
    <div v-if="!isRpt01 && !isRpt02 && !isRpt03 && !isRpt04A && !isRpt04B && !isRpt05 && !isRpt06 && !isFocusRoster" class="sa-head-row">
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
        <el-form-item v-if="!isRpt01" label="学年学期" :required="isRequired('semesterId')">
          <el-select size="small" v-model="draft.semesterId" clearable filterable placeholder="请选择学年学期" class="semester-control">
            <el-option v-for="item in options.semesters" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item :label="usesGradeLabel ? '年级' : '入学年级'" :required="isRequired('entryGrade')">
          <el-select size="small" v-model="draft.entryGrade" clearable :placeholder="usesGradeLabel ? '请选择年级' : '请选择入学年级'" class="grade-control">
            <el-option v-for="item in options.entryGrades" :key="item" :label="`${item}级`" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!isRpt01 && !isRpt03" label="学院" :required="isRequired('organizationId')">
          <el-select size="small" v-model="draft.organizationId" clearable filterable placeholder="请选择学院" class="organization-control">
            <el-option v-for="item in organizationOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!isRpt01 && !isRpt02 && !isRpt03" label="专业" :required="isRequired('majorCode')">
          <el-select size="small" v-model="draft.majorCode" clearable filterable placeholder="请选择专业" class="organization-control">
            <el-option v-for="item in majorOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!isRpt01 && !isRpt02 && !isRpt03 && !isRpt04A && !isRpt05" label="班级" :required="isRequired('classCode')">
          <el-select size="small" v-model="draft.classCode" clearable filterable placeholder="请选择班级" class="class-control">
            <el-option v-for="item in classOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label=" "><el-button size="small" type="primary" :loading="loading" @click="applyFilters">查询</el-button><el-button size="small" @click="resetFilters">重置</el-button></el-form-item>
      </el-form>
      <p class="filter-tip">带 <span>*</span> 的条件必须填写；必选条件未完整填写时不发起查询，结果区仅展示原始报表表头。</p>
    </el-card>

    <div v-if="result && !isRpt01 && !isRpt02 && !isRpt03 && !isRpt04A && !isRpt04B && !isRpt05 && !isRpt06 && !isFocusRoster" class="context-strip">
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
        <el-button v-if="result && (isRpt01 || isRpt02 || isRpt03 || isRpt04A || isRpt04B || isRpt05 || isRpt06 || isFocusRoster)" type="primary" plain :disabled="!result.capabilities?.export || !result.snapshotToken || loading" :loading="exporting" @click="exportExcel">
          <el-icon><Download /></el-icon> 导出 Excel
        </el-button>
        <el-tag v-else-if="result" effect="plain">{{ result.status }}</el-tag>
      </div></template>

      <component :is="reportTables[definition.reportId] || BasicReportTable" :key="definition.reportId"
        :definition="definition" :result="result" :span-method="spanMethod" :row-class-name="rowClassName" />


    </el-card>

    <el-collapse v-if="result && !isRpt01 && !isRpt02 && !isRpt03 && !isRpt04A && !isRpt04B && !isRpt05 && !isRpt06 && !isFocusRoster" class="boundary-panel">
      <el-collapse-item title="数据来源、计算规则与适用边界" name="rules">
        <ul><li v-for="item in result.boundary" :key="item">{{ item }}</li></ul>
        <AppTable :columns="ruleColumns" :data="result.rules" :storage-key="`basic-report:${definition.reportId}:rules`"
          :pagination="false" default-density="compact" border />
      </el-collapse-item>
    </el-collapse>
  </div>

</template>

<script setup lang="ts">
import type { Component } from 'vue'

import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import BasicReportTable from './BasicReportTable.vue'
import FailureOverviewTable from '../failure-overview/FailureOverviewTable.vue'
import MajorMakeupComparisonTable from '../major-makeup-comparison/MajorMakeupComparisonTable.vue'
import Cet4PassTable from '../cet4-pass/Cet4PassTable.vue'
import CourseMakeupComparisonTable from '../course-makeup-comparison/CourseMakeupComparisonTable.vue'
import * as basicReportsApi from '@/api/basicReports'
import { authStore } from '@/store/auth'
import { reportDefinitions, type BasicReportFilter } from '../config/reportDefinitions'

// 各报表通过公共 AppTable 或特有列插槽展示，查询与导出仍由本页面维护。
const reportTables: Record<string, Component> = {
  'RPT-01': FailureOverviewTable,
  'RPT-02': MajorMakeupComparisonTable,
  'RPT-06': Cet4PassTable,
  'RPT-05': CourseMakeupComparisonTable,
}

// 保留来源与规则折叠区的完整列；是否展示仍沿用原报表判断。
const ruleColumns: AppTableColumn[] = [
  { key: 'ruleId', label: '规则编号', width: 190 },
  { key: 'provenance', label: '来源类型', width: 120 },
  { key: 'source', label: '复用来源', minWidth: 240 },
  { key: 'formula', label: '计算方法', minWidth: 300 },
  { key: 'boundary', label: '适用边界', minWidth: 300 },
]

const route = useRoute()
const router = useRouter()
// 按原路由找到报表定义，未知地址保持年级总体挂科报表的兜底。
const definition = computed(() => reportDefinitions[route.path] || reportDefinitions['/admin/basic-reports/failure-overview'])
// 识别年级总体报表，保留其隐藏学期选择及默认学期行为。
const isRpt01 = computed(() => definition.value.reportId === 'RPT-01')
// 识别专业补考前后报表，保留原筛选组合。
const isRpt02 = computed(() => definition.value.reportId === 'RPT-02')
// 识别专业性别对比报表，不改变分母或人数含义。
const isRpt03 = computed(() => definition.value.reportId === 'RPT-03')
// 识别班级挂科门数报表，沿用原班级筛选边界。
const isRpt04A = computed(() => definition.value.reportId === 'RPT-04A')
// 识别班级成绩分布报表，保留学院与专业必选规则。
const isRpt04B = computed(() => definition.value.reportId === 'RPT-04B')
// 识别四级通过报表，保持原查询及导出入口。
const isRpt06 = computed(() => definition.value.reportId === 'RPT-06')
// 识别课程补考前后对比报表，沿用原合并与筛选规则。
const isRpt05 = computed(() => definition.value.reportId === 'RPT-05')
// 两张关注名单沿用原共同流程，编号和标题继续独立。
const isFocusRoster = computed(() => ['RPT-07', 'RPT-08'].includes(definition.value.reportId))
// 按原报表集合显示年级标签，不改变查询字段名。
const usesGradeLabel = computed(() => isRpt01.value || isRpt02.value || isRpt03.value || isRpt04A.value || isRpt04B.value || isRpt05.value || isRpt06.value || isFocusRoster.value)
const options = reactive<any>({ semesters: [], entryGrades: [], organizations: [], majors: [], classes: [] })
const draft = reactive<any>({ semesterId: '', entryGrade: null, organizationId: '', majorCode: '', classCode: '' })
const applied = reactive<any>({ semesterId: '', entryGrade: null, organizationId: '', majorCode: '', classCode: '' })
const result = ref<any>(null)
// 从服务端结果取得当前名单规则说明。
const focusRule = computed(() => result.value?.focusRule || null)
const loading = ref(false)
const exporting = ref(false)

// 将服务端学院元组转换为原下拉选项。
const organizationOptions = computed(() => options.organizations.map((item: any[]) => ({ value: item[0], label: item[1] })))
// 区分名单快照缺失与一般数据源缺失，保持原提示。
const sourceUnavailableDescription = computed(() => isFocusRoster.value
  ? '所选学期没有已接入的预警快照，不能把数据缺失解释为0名名单学生。'
  : '当前查询范围没有可用的数据源。')
// 从授权专业中按草稿学院过滤并按专业编码去重。
const majorOptions = computed(() => {
  const values = options.majors.filter((item: any) => !draft.organizationId || item.organizationId === draft.organizationId)
  return Array.from(new Map(values.map((item: any) => [item.majorCode, { value: item.majorCode, label: item.majorName }])).values())
})
// 从现有班级中按草稿专业过滤并去重。
const classOptions = computed(() => Array.from(new Set(options.classes
  .filter((item: any) => !draft.majorCode || item.majorCode === draft.majorCode)
  .map((item: any) => item.classCode))))

// 切换草稿学院后，沿用原规则清理失效专业和班级。
watch(() => draft.organizationId, () => {
  if (!majorOptions.value.some((item: any) => item.value === draft.majorCode)) draft.majorCode = ''
  draft.classCode = ''
})
// 切换草稿专业后，仅清理不再有效的班级选择。
watch(() => draft.majorCode, () => { if (!classOptions.value.includes(draft.classCode)) draft.classCode = '' })
// 工作身份变化时清空页面并重新读取授权选项。
watch(() => authStore.user?.activeIdentityId, async () => { clearPage(); await loadOptions() })
// 同一公共页面切换报表时清空筛选和结果，保留原复用生命周期。
watch(() => route.path, () => clearPage())

// 读取本报表原有必填筛选定义。
function isRequired(key: BasicReportFilter) { return definition.value.requiredFilters.includes(key) }


// 恢复原默认查询条件并清除结果，不自动重新查询。
function clearPage() {
  Object.assign(draft, { semesterId: isRpt01.value ? (options.semesters[0] || '') : '', entryGrade: null, organizationId: '', majorCode: '', classCode: '' })
  Object.assign(applied, draft)
  result.value = null
}

// 只序列化已应用条件，并沿用各报表排除不适用筛选的规则。
function queryParams() {
  const params = new URLSearchParams({ semesterId: applied.semesterId })
  if (applied.entryGrade != null && applied.entryGrade !== '') params.set('entryGrade', String(applied.entryGrade))
  if (!isRpt01.value && !isRpt03.value && applied.organizationId) params.set('organizationId', applied.organizationId)
  if (!isRpt01.value && !isRpt02.value && !isRpt03.value && applied.majorCode) params.set('majorCode', applied.majorCode)
  if (!isRpt01.value && !isRpt02.value && !isRpt03.value && !isRpt04A.value && !isRpt05.value && applied.classCode) params.set('classCode', applied.classCode)
  return params
}

// 加载当前身份授权的筛选选项，年级总体报表沿用默认学期。
async function loadOptions() {
  const data = await basicReportsApi.getBasicReportOptions<any>()
  Object.assign(options, data)
  if (isRpt01.value) {
    draft.semesterId = options.semesters[0] || ''
    applied.semesterId = draft.semesterId
  }
}

// 校验必填条件后应用草稿、同步原地址参数并查询。
async function applyFilters() {
  const labels: Record<BasicReportFilter, string> = { semesterId: '学年学期', entryGrade: usesGradeLabel.value ? '年级' : '入学年级', organizationId: '学院', majorCode: '专业', classCode: '班级' }
  const missing = definition.value.requiredFilters.filter(key => !draft[key]).map(key => labels[key])
  if (missing.length) { ElMessage.warning(`请选择必选查询条件：${missing.join('、')}`); return }
  Object.assign(applied, draft)
  await router.replace({ path: route.path, query: Object.fromEntries(queryParams()) })
  await loadReport()
}

// 按当前报表及已应用筛选加载原结果，保留加载状态处理。
async function loadReport() {
  loading.value = true
  try { result.value = await basicReportsApi.getBasicReport<any>(definition.value.slug, queryParams()) }
  finally { loading.value = false }
}

// 清空筛选结果并移除原路由查询参数。
function resetFilters() { clearPage(); router.replace({ path: route.path }) }

// 按报表定义合并相邻同组单元格，汇总行不参与合并。
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

// 仅标记服务端提供的汇总行，不在前端重新汇总。
function rowClassName({ row }: any) { return row?.isSummary ? 'basic-report-summary-row' : '' }

// 以当前已应用条件和原结果快照下载 Excel，保留权限与文件名协议。
async function exportExcel() {
  if (!result.value?.snapshotToken) return
  exporting.value = true
  try {
    const params = queryParams(); params.set('snapshotToken', result.value.snapshotToken)
    await basicReportsApi.downloadBasicReport(definition.value.slug, params)
    ElMessage.success('Excel 已生成')
  } finally { exporting.value = false }
}

// 进入公共页面时读取筛选选项，查询仍由用户主动触发。
onMounted(loadOptions)

</script>

<style scoped lang="scss">
.basic-report-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-card,.result-card {
  border-color: var(--el-border-color-lighter);
}

.report-filter {
  display: flex;
  align-items: flex-end;
  gap: 4px 12px;


  :deep(.el-form-item) {
    margin: 0;
  }

}

.filter-tip {
  margin: 10px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;


  span {
    color: var(--el-color-danger);
  }

}

.context-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  padding: 12px 16px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 13px;
}

.card-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}

.title-with-help {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.rule-help-icon {
  flex: 0 0 auto;
  color: var(--el-color-primary);
  cursor: help;
  font-size: 16px;


  &:focus-visible {
    outline: 2px solid var(--el-color-primary-light-5);
    outline-offset: 2px;
    border-radius: 50%;
  }

}

.focus-rule-tip {
  max-width: 460px;
  line-height: 1.7;
}

.result-card :deep(.basic-report-summary-row td) {
  background: var(--el-fill-color-light);
  font-weight: 700;
}

.boundary-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 0 16px;


  ul {
    margin: 0 0 16px;
    padding-left: 22px;
    color: var(--el-text-color-regular);
    line-height: 1.8;
  }

}

// 保留原筛选控件宽度，静态展示尺寸由类名管理。
.report-filter {
  .grade-control {
    width: 150px;
  }

  .semester-control {
    width: 180px;
  }

  .class-control {
    width: 190px;
  }

  .organization-control {
    width: 220px;
  }
}
</style>

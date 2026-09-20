<!-- 学生成长与学业分析：MyScope 页面或专用组件，保留原业务与权限行为。 -->
<template>
  <div v-loading="pageLoading" :element-loading-text="`正在加载${pageTitle}，请稍候…`" element-loading-background="rgba(248,250,252,.82)">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">数据来源：成绩表(fact_grade) + 学籍表(dim_student) + 预警事件(alert_event) · 仅含当前身份范围内的班级与学生</p>
      </div>
    </div>
    <BusinessPageContext
      :period="`本学期：${data.semester || '—'}`"
      source="学籍、成绩与预警事件数据"
      :loading="pageLoading"
      :error="loadError"
      :updated-at="updatedAt"
    />
    <el-alert v-if="loadError" type="error" :closable="false" show-icon style="margin-bottom:12px">
      <template #title>当前工作身份的学生范围加载失败</template>
      <template #default>
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="load">重新加载</el-button>
      </template>
    </el-alert>

    <el-alert v-if="data.evidence?.limitation" type="warning" :closable="false" show-icon style="margin-bottom:12px"
      title="证据说明：部分专业学分要求包含模拟数据"
      :description="data.evidence.limitation" />

    <!-- 关系身份异常返回无个性化视图时，明确披露范围状态。 -->
    <el-empty v-if="data.view === 'none' && !pageLoading"
      description="当前工作身份没有可用的班级或导师—学生关系，请联系管理员核对数据权限" />

    <!-- 范围为空：友好空态 -->
    <el-empty v-else-if="isEmpty && !pageLoading"
      :description="data.roleId === 'mentor' ? '当前身份暂无关联学生' : '当前身份暂无关联班级'" />

    <template v-else-if="data.view !== 'none'">
      <!-- 顶部汇总卡 -->
      <div class="sa-kpi-row" v-if="data.summary">
        <KpiCard :label="data.view === 'classes' ? '覆盖学生' : '我的学生'" :value="`${data.summary.studentCount}人`"
          hint="当前身份范围内的在籍学生总数" tone="primary" />
        <KpiCard label="本学期平均GPA" :value="gpaText(data.summary.avgGpa)"
          :sub="gradeCoverageText(data.summary)"
          hint="本学期每生学分加权GPA的平均值；缺少有效学分的成绩不参与计算" tone="teal" />
        <KpiCard label="本学期未通过学生率" :value="pctText(data.summary.failRate)"
          :sub="failRateSub(data.summary)"
          hint="本学期至少有1门未通过课程的学生÷本学期具有有效成绩的学生"
          :tone="(data.summary.failRate || 0) > 15 ? 'danger' : 'amber'" />
        <KpiCard label="学分完成率中位数" :value="pctText(data.summary.creditMedian)" hint="每生已修学分÷要求学分的中位数；要求学分缺失的学生不计入" tone="primary" />
        <KpiCard label="有未解除预警" :value="`${data.summary.withOpenAlerts}人`"
          :sub="`共 ${data.summary.openAlerts} 件未解除事件`"
          hint="预警事件工作流状态未进入已解决/已关闭" :tone="data.summary.withOpenAlerts ? 'danger' : 'teal'" />
      </div>

      <!-- 班级视图：辅导员/班主任 -->
      <template v-if="data.view === 'classes'">
        <div class="class-grid">
          <div v-for="c in data.classes" :key="c.classId" class="sa-card class-card"
            :class="{ expanded: expanded.has(c.classId) }" @click="toggleClass(c.classId)">
            <div class="class-card__head">
              <span class="class-card__name">{{ c.className }}</span>
              <el-tag size="small" effect="plain">{{ c.studentCount }}人</el-tag>
              <el-icon class="class-card__arrow" :class="{ open: expanded.has(c.classId) }"><ArrowDown /></el-icon>
            </div>
            <div class="class-card__metrics">
              <div class="metric"><span class="m-label">本学期平均GPA</span><b class="tnum">{{ gpaText(c.avgGpa) }}<small>{{ c.gradedStudentCount ? ` · ${c.gradedStudentCount}人有成绩` : ' · 暂无成绩' }}</small></b></div>
              <div class="metric"><span class="m-label">本学期未通过学生率</span><b class="tnum" :style="{ color: (c.failRate || 0) > 15 ? '#E11D48' : '#D97706' }">{{ pctText(c.failRate) }}<small>{{ c.gradedStudentCount ? `（${c.failedStudentCount || 0}/${c.gradedStudentCount}）` : ' · 暂不可计算' }}</small></b></div>
              <div class="metric"><span class="m-label">学分完成率中位数</span><b class="tnum">{{ pctText(c.creditMedian) }}</b></div>
              <div class="metric"><span class="m-label">未解除预警</span><b class="tnum" :style="{ color: c.openAlerts ? '#E11D48' : '#0D9488' }">{{ c.openAlerts }}件</b></div>
            </div>
            <div v-if="expanded.has(c.classId)" class="class-card__students" @click.stop>
              <ClassStudentsTable
                storage-key="students:my-class-students"
                 :max-business-columns="4" :config-version="1"
                 max-height="360" @row-click="openEvidence" row-class-name="row-clickable" :columns="classStudentCols" :data="c.students">
                <template #col-name="{ row }"><span class="link">{{ row.name }}</span></template>
                <template #col-gpa="{ row }"><b class="tnum">{{ gpaText(row.gpa) }}</b></template>
                <template #col-failCount="{ row }"><span class="tnum" :style="{ color: row.failCount ? '#E11D48' : '#64748B' }">{{ row.failCount }}门</span></template>
                <template #col-creditRatio="{ row }"><span class="tnum">{{ pctText(row.creditRatio) }}</span></template>
                <template #col-openAlerts="{ row }"><span class="tnum" :style="{ color: row.openAlerts ? '#E11D48' : '#64748B' }">{{ row.openAlerts }}件</span></template>
              </ClassStudentsTable>
            </div>
          </div>
        </div>
      </template>

      <!-- 导师视图：我的学生表 -->
      <div v-else class="sa-card">
        <div class="sa-card-title">我的学生 <KpiLabel label="" formula="按有效导师—学生关系取数；GPA 为本学期学分加权 GPA，未通过门数为本学期真实未通过课程数" /></div>
        <AppTable :columns="myStudentCols" :data="data.students" storage-key="students:my-students"  @row-click="openEvidence" row-class-name="row-clickable" :show-density="true" :show-column-settings="true" :pagination="false">
          <template #col-name="{ row }"><span class="link">{{ row.name }}</span></template>
          <template #col-gpa="{ row }"><b class="tnum">{{ gpaText(row.gpa) }}</b></template>
          <template #col-failCount="{ row }"><span class="tnum" :style="{ color: row.failCount ? '#E11D48' : '#64748B' }">{{ row.failCount }}门</span></template>
          <template #col-creditRatio="{ row }">
            <div v-if="row.creditRatio != null" style="display:flex;align-items:center;gap:8px">
              <el-progress :percentage="Math.min(row.creditRatio, 100)" :show-text="false" :stroke-width="9"
                :color="row.creditRatio >= 80 ? '#0D9488' : row.creditRatio >= 60 ? '#D97706' : '#E11D48'" style="flex:1" />
              <span class="tnum" style="min-width:48px;text-align:right">{{ pctText(row.creditRatio) }}</span>
            </div>
            <span v-else class="sa-faint">—</span>
          </template>
          <template #col-openAlerts="{ row }"><span class="tnum" :style="{ color: row.openAlerts ? '#E11D48' : '#64748B' }">{{ row.openAlerts }}件</span></template>
        </AppTable>
      </div>
    </template>
    <StudentEvidenceDrawer
      v-model="evidenceVisible"
      :student-id="selectedStudent.sid"
      :context="evidenceContext"
    />
  </div>
</template>

<script setup lang="ts">
import ClassStudentsTable from './ClassStudentsTable.vue'
import * as studentsApi from '@/api/teachingAnalysis/students'


import { reactive, ref, computed, onMounted } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import StudentEvidenceDrawer from '@/components/StudentEvidenceDrawer.vue'
import { authStore } from '@/store/auth'

const activeRole = computed(() => authStore.user?.permissionContext?.activeRole || authStore.user?.role || '')
const pageTitle = computed(() => activeRole.value === 'mentor' ? '我的学生学业关注' : '我的班级学业关注')
const pageLoading = ref(false)
const loadError = ref('')
const updatedAt = ref('')
const expanded = reactive(new Set<string>())
const evidenceVisible = ref(false)
const selectedStudent = ref<any>({})

const data = reactive<any>({
  scopeKind: '', view: 'none', roleId: '', semester: '',
  summary: null, classes: [], students: [], evidence: {},
})

const isEmpty = computed(() =>
  (data.view === 'classes' && !data.classes.length) ||
  (data.view === 'students' && !data.students.length))
const evidenceContext = computed(() => {
  const row = selectedStudent.value
  const reasons = []
  if (row.failCount > 0) reasons.push(`本学期有${row.failCount}门未通过课程`)
  if (row.openAlerts > 0) reasons.push(`有${row.openAlerts}条未解除预警`)
  if (row.creditRatio != null && row.creditRatio < 60) reasons.push('学分完成率低于60%')
  if (!reasons.length) reasons.push('当前管理范围内主动核查')
  return {
    studentName: row.name,
    reasons,
    period: data.semester || '当前学期',
    ruleVersion: 'academic-metrics-v1',
    returnLabel: pageTitle.value,
    boundary: '本工作区只提供学业证据核查，不执行预警处置或学生工作流程。',
  }
})

function gpaText(v: number | null) { return v == null ? '—' : v.toFixed(2) }
function pctText(v: number | null) { return v == null ? '—' : `${v}%` }
function gradeCoverageText(summary: any) {
  return summary?.gradedStudentCount
    ? `${summary.gradedStudentCount}/${summary.studentCount}人有有效成绩`
    : '本学期暂无有效成绩'
}
function failRateSub(summary: any) {
  return summary?.gradedStudentCount
    ? `${summary.failedStudentCount || 0}/${summary.gradedStudentCount}人`
    : '本学期暂无有效成绩，暂不可计算'
}

// 导师视图「我的学生」表列定义（AppTable）
const myStudentCols: AppTableColumn[] = [
  { key: 'name', label: '姓名', minWidth: 120 },
  { key: 'className', label: '行政班', minWidth: 150, tooltip: true },
  { key: 'gpa', label: 'GPA', minWidth: 90, align: 'center' },
  { key: 'failCount', label: '本学期挂科', minWidth: 110, align: 'center' },
  { key: 'creditRatio', label: '学分完成率', minWidth: 150 },
  { key: 'openAlerts', label: '未解除预警', minWidth: 100, align: 'center' },
]
const classStudentCols: AppTableColumn[] = [
  { key: 'name', label: '姓名', minWidth: 120, fixed: 'left', region: 'identity', required: true },
  { key: 'gpa', label: '本学期GPA', minWidth: 105, align: 'center', required: true },
  { key: 'failCount', label: '本学期未通过', minWidth: 120, align: 'center', required: true },
  { key: 'creditRatio', label: '学分完成率', minWidth: 115, align: 'center' },
  { key: 'openAlerts', label: '未解除预警', minWidth: 110, align: 'center' },
]

function toggleClass(classId: string) {
  if (expanded.has(classId)) expanded.delete(classId)
  else expanded.add(classId)
}
function openEvidence(row: any) {
  selectedStudent.value = row
  evidenceVisible.value = true
}

// 按当前页面上下文读取数据，沿用原加载状态和异常处理。
async function load() {
  pageLoading.value = true
  loadError.value = ''
  try {
    const d = await studentsApi.getMyStudents()
    if (d) {
      Object.assign(data, d)
      updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    }
  } catch (error: any) {
    loadError.value = error?.message || '数据加载失败，请稍后重试'
  } finally {
    pageLoading.value = false
  }
}

// 进入页面时执行原初始化流程，恢复路由条件与可用选项。
onMounted(load)
</script>

<style scoped lang="scss">
// 按页面区域、后代元素和状态组织，保留原选择器顺序与作用范围。
.sa-head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.class-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
  align-items: start;
}

.class-card {
  cursor: pointer;
  transition: transform .15s ease, box-shadow .15s ease;
  &.expanded {
    grid-column: 1 / -1;
  }
  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 18px rgba(15,23,42,.08);
  }
}

.class-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.class-card__name {
  font-size: 15px;
  font-weight: 700;
  color: #1E293B;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.class-card__arrow {
  color: #94A3B8;
  transition: transform .2s ease;
  &.open {
    transform: rotate(180deg);
  }
}

.class-card__metrics {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px 14px;
  margin-top: 12px;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.m-label {
  font-size: 11px;
  color: #94A3B8;
}

.metric {
  b {
    font-size: 16px;
    color: #1E293B;
  }
  b small {
    font-size: 11px;
    font-weight: 400;
    color: #94A3B8;
  }
}

.class-card__students {
  margin-top: 12px;
  cursor: default;
}

.link {
  color: var(--sa-primary);
  cursor: pointer;
  font-weight: 500;
  &:hover {
    text-decoration: underline;
  }
}

:deep(.row-clickable) {
  cursor: pointer;
}

:deep(.row-clickable:hover) {
  background: #eef2ff !important;
}
</style>

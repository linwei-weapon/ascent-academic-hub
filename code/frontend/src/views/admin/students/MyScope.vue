<template>
  <div v-loading="pageLoading" element-loading-text="正在加载我的班级/学生视图，请稍候…" element-loading-background="rgba(248,250,252,.82)">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">数据来源：成绩表(fact_grade) + 学籍表(dim_student) + 预警事件(alert_event) · 仅含当前身份范围内的班级与学生</p>
      </div>
      <div v-if="hasAnalysisMenu">
        <el-button size="small" plain @click="goAnalysis">前往学生成长与学业分析</el-button>
      </div>
    </div>
    <BusinessPageContext
      :period="`本学期：${data.semester || '—'}`"
      source="学籍、成绩与预警事件数据"
      :loading="pageLoading"
      :error="loadError"
      :updated-at="updatedAt"
    />

    <el-alert v-if="data.evidence?.limitation" type="warning" :closable="false" show-icon style="margin-bottom:12px"
      title="证据说明：部分专业学分要求包含模拟数据"
      :description="data.evidence.limitation" />

    <!-- 非带班/带生身份：引导到全校分析页，不报错 -->
    <el-empty v-if="data.view === 'none' && !pageLoading"
      description="当前身份为全校或组织视角，没有个人化的班级/学生范围">
      <el-button v-if="hasAnalysisMenu" type="primary" @click="goAnalysis">前往学生成长与学业分析</el-button>
    </el-empty>

    <!-- 范围为空：友好空态 -->
    <el-empty v-else-if="isEmpty && !pageLoading"
      :description="data.roleId === 'mentor' ? '当前身份暂无关联学生' : '当前身份暂无关联班级'" />

    <template v-else-if="data.view !== 'none'">
      <!-- 顶部汇总卡 -->
      <div class="sa-kpi-row" v-if="data.summary">
        <KpiCard :label="data.view === 'classes' ? '覆盖学生' : '我的学生'" :value="`${data.summary.studentCount}人`"
          hint="当前身份范围内的在籍学生总数" tone="primary" />
        <KpiCard label="平均GPA" :value="gpaText(data.summary.avgGpa)" hint="AVG(每生平均绩点)·5分制" tone="teal" />
        <KpiCard label="挂科率" :value="pctText(data.summary.failRate)" hint="有未通过记录学生占比（真实成绩）"
          :tone="(data.summary.failRate || 0) > 15 ? 'danger' : 'amber'" />
        <KpiCard label="学分完成率中位数" :value="pctText(data.summary.creditMedian)" hint="每生已修学分÷要求学分的中位数；要求学分缺失的学生不计入" tone="primary" />
        <KpiCard label="有未解除预警" :value="`${data.summary.withOpenAlerts}人`"
          :sub="`共 ${data.summary.openAlerts} 件未解除事件`"
          hint="预警事件工作流状态未进入已解决/已关闭" :tone="data.summary.withOpenAlerts ? 'danger' : 'teal'" />
      </div>

      <!-- 班级视图：辅导员/班主任 -->
      <template v-if="data.view === 'classes'">
        <div class="class-grid">
          <div v-for="c in data.classes" :key="c.classId" class="sa-card class-card" @click="toggleClass(c.classId)">
            <div class="class-card__head">
              <span class="class-card__name">{{ c.className }}</span>
              <el-tag size="small" effect="plain">{{ c.studentCount }}人</el-tag>
              <el-icon class="class-card__arrow" :class="{ open: expanded.has(c.classId) }"><ArrowDown /></el-icon>
            </div>
            <div class="class-card__metrics">
              <div class="metric"><span class="m-label">平均GPA</span><b class="tnum">{{ gpaText(c.avgGpa) }}</b></div>
              <div class="metric"><span class="m-label">挂科率</span><b class="tnum" :style="{ color: (c.failRate || 0) > 15 ? '#E11D48' : '#D97706' }">{{ pctText(c.failRate) }}</b></div>
              <div class="metric"><span class="m-label">学分完成率中位数</span><b class="tnum">{{ pctText(c.creditMedian) }}</b></div>
              <div class="metric"><span class="m-label">未解除预警</span><b class="tnum" :style="{ color: c.openAlerts ? '#E11D48' : '#0D9488' }">{{ c.openAlerts }}件</b></div>
            </div>
            <div v-if="expanded.has(c.classId)" class="class-card__students" @click.stop>
              <el-table :data="c.students" size="small" max-height="320" @row-click="goStudent" row-class-name="row-clickable">
                <el-table-column prop="name" label="姓名" width="110"><template #default="{ row }"><span class="link">{{ row.name }}</span></template></el-table-column>
                <el-table-column label="GPA" width="76" align="right"><template #default="{ row }"><b class="tnum">{{ gpaText(row.gpa) }}</b></template></el-table-column>
                <el-table-column label="本学期挂科" width="96" align="right"><template #default="{ row }"><span class="tnum" :style="{ color: row.failCount ? '#E11D48' : '#64748B' }">{{ row.failCount }}门</span></template></el-table-column>
                <el-table-column label="学分完成率" width="96" align="right"><template #default="{ row }"><span class="tnum">{{ pctText(row.creditRatio) }}</span></template></el-table-column>
                <el-table-column label="未解除预警" width="96" align="right"><template #default="{ row }"><span class="tnum" :style="{ color: row.openAlerts ? '#E11D48' : '#64748B' }">{{ row.openAlerts }}件</span></template></el-table-column>
              </el-table>
            </div>
          </div>
        </div>
      </template>

      <!-- 导师视图：我的学生表 -->
      <div v-else class="sa-card">
        <div class="sa-card-title">我的学生 <KpiLabel label="" formula="按有效导师—学生关系取数；GPA 为全部学期平均，挂科为本学期真实未通过门数" /></div>
        <DataTable :columns="myStudentCols" :data="data.students" storage-key="students:my-students" size="small" @row-click="goStudent" row-class-name="row-clickable">
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
        </DataTable>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import { useBusinessPageTitle } from '@/utils/businessPage'
import { authStore } from '@/store/auth'

const router = useRouter()
const pageTitle = useBusinessPageTitle('/admin/students/my', '我的班级/学生')
const pageLoading = ref(false)
const loadError = ref('')
const updatedAt = ref('')
const expanded = reactive(new Set<string>())

const data = reactive<any>({
  scopeKind: '', view: 'none', roleId: '', semester: '',
  summary: null, classes: [], students: [], evidence: {},
})

const hasAnalysisMenu = computed(() => authStore.menus.some(m => m.path === '/admin/students/analysis'))
const isEmpty = computed(() =>
  (data.view === 'classes' && !data.classes.length) ||
  (data.view === 'students' && !data.students.length))

function gpaText(v: number | null) { return v == null ? '—' : v.toFixed(2) }
function pctText(v: number | null) { return v == null ? '—' : `${v}%` }

// 导师视图「我的学生」表列定义（M6 DataTable）
const myStudentCols: DataTableColumn[] = [
  { key: 'name', label: '姓名', width: 120 },
  { key: 'className', label: '行政班', minWidth: 150, tooltip: true },
  { key: 'gpa', label: 'GPA', width: 90, align: 'right' },
  { key: 'failCount', label: '本学期挂科', width: 110, align: 'right' },
  { key: 'creditRatio', label: '学分完成率', minWidth: 150 },
  { key: 'openAlerts', label: '未解除预警', width: 100, align: 'right' },
]

function toggleClass(classId: string) {
  if (expanded.has(classId)) expanded.delete(classId)
  else expanded.add(classId)
}
function goStudent(row: any) {
  router.push({ path: `/admin/student/${row.sid}`, query: { returnTo: '/admin/students/my', returnLabel: '我的班级/学生' } })
}
function goAnalysis() { router.push('/admin/students/analysis') }

async function load() {
  pageLoading.value = true
  loadError.value = ''
  try {
    const d = await http.get('/admin/students/my-scope')
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

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.class-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; align-items: start; }
.class-card { cursor: pointer; transition: transform .15s ease, box-shadow .15s ease; }
.class-card:hover { transform: translateY(-2px); box-shadow: 0 8px 18px rgba(15,23,42,.08); }
.class-card__head { display: flex; align-items: center; gap: 8px; }
.class-card__name { font-size: 15px; font-weight: 700; color: #1E293B; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.class-card__arrow { color: #94A3B8; transition: transform .2s ease; }
.class-card__arrow.open { transform: rotate(180deg); }
.class-card__metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 14px; margin-top: 12px; }
.metric { display: flex; flex-direction: column; gap: 2px; }
.m-label { font-size: 11px; color: #94A3B8; }
.metric b { font-size: 16px; color: #1E293B; }
.class-card__students { margin-top: 12px; cursor: default; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
</style>

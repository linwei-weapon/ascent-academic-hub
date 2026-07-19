<template>
  <div v-loading="pageLoading" element-loading-text="正在加载学生成长与学业分析，请稍候…" element-loading-background="rgba(248,250,252,.82)">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">数据来源：成绩表(fact_grade) + 学籍表(dim_student) · 全年级统计分析</p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
        <el-select v-model="fGrade" size="small" style="width:110px" clearable placeholder="全部年级" @change="load">
          <el-option v-for="g in grades" :key="g" :label="g + '级'" :value="g" />
        </el-select>
        <el-select v-model="fCollege" size="small" style="width:160px" clearable filterable placeholder="全部学院" @change="onCollege">
          <el-option v-for="c in colleges" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-select v-model="fMajor" size="small" style="width:150px" clearable filterable placeholder="全部专业" @change="onMajor">
          <el-option v-for="m in majorOptions" :key="m.value" :label="m.label" :value="m.value" />
        </el-select>
        <el-select v-model="fClass" size="small" style="width:150px" clearable filterable placeholder="全部班级" @change="load">
          <el-option v-for="c in classOptions" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-select v-model="fSemester" size="small" style="width:170px" clearable placeholder="全部学期" @change="onSemester">
          <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-model="fYear" size="small" style="width:130px" clearable placeholder="全部学年" @change="onYear">
          <el-option v-for="y in years" :key="y" :label="y + '学年'" :value="y" />
        </el-select>
        <el-select v-model="fRetake" size="small" style="width:110px" clearable placeholder="重修/非" @change="load">
          <el-option label="重修" value="重修" /><el-option label="非重修" value="非重修" />
        </el-select>
        <el-select v-model="fRequired" size="small" style="width:110px" clearable placeholder="课程性质" @change="load">
          <el-option label="必修" value="必修" /><el-option label="选修" value="选修" />
        </el-select>
      </div>
    </div>
    <BusinessPageContext
      :period="studentPeriod"
      source="学籍、成绩、培养方案与历史预警数据"
      :loading="pageLoading"
      :error="loadError"
      :updated-at="updatedAt"
    />

    <el-alert v-if="evidence.limitation" type="warning" :closable="false" show-icon style="margin-bottom:12px"
      title="证据说明：毕业率、学位授予率和部分专业学分要求包含模拟数据"
      :description="evidence.limitation" />

    <div class="sa-kpi-row">
      <KpiCard v-for="k in studentKpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="kpiTone(k.label)" />
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="8">
        <div class="sa-card" style="height:100%">
          <div class="sa-card-title">学生 GPA 分层画像 <KpiLabel label="" formula="固定GPA分层（非机器学习聚类）：优秀≥3.5·良好3.0-3.5·一般2.5-3.0·困难2.0-2.5·高危<2.0" /></div>
          <EChart v-if="data.clusters.length" :option="clusterOption" :height="190" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          <div v-if="data.clusters.length" class="legend-list">
            <div v-for="c in data.clusters" :key="c.label" class="legend-item">
              <span class="dot" :style="{background:c.color}" />
              <span class="lg-label">{{ c.label }}</span>
              <span class="lg-val tnum">{{ c.count.toLocaleString() }}人 · {{ c.pct }}%</span>
            </div>
          </div>
        </div>
      </el-col>

      <el-col :span="8">
        <div class="sa-card" style="height:100%">
          <div class="sa-card-title">各年级 GPA 均值 <KpiLabel label="" formula="按年级统计平均GPA" /></div>
          <EChart v-if="data.gradeGpa.length" :option="gradeOption" :height="190" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          <div v-if="data.gradeGpa.length" class="grade-foot">
            <span v-for="g in data.gradeGpa" :key="g.grade">{{ g.grade }}级 挂科{{ g.failRate }}·预警{{ g.alertRate }}</span>
          </div>
        </div>
      </el-col>

      <el-col :span="8">
        <div class="sa-card" style="height:100%">
          <div class="sa-card-title">学分完成分布 <KpiLabel label="" formula="按已修学分÷要求学分比例分组" /></div>
          <EChart v-if="data.creditDist.length" :option="creditOption" :height="190" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="14">
        <div class="sa-card" style="height:100%">
          <div class="sa-card-title">
            相邻学期画像迁移
            <KpiLabel label="" :formula="data.migration.definition || '同时比较相邻学期GPA与挂科门次变化'" />
          </div>
          <div v-if="data.migration.fromSemester && data.migration.toSemester" class="migration-meta">
            <span>{{ data.migration.fromSemester }}</span><b>→</b><span>{{ data.migration.toSemester }}</span>
            <em>有效对比 {{ data.migration.compared }} 人 · GPA平均变化 {{ signed(data.migration.avgDelta) }} · 挂科平均变化 {{ signed(data.migration.avgFailDelta) }}门次</em>
          </div>
          <div class="migration-kpis">
            <div class="drill-card" @click="goMigration('improved', '改善')"><KpiCard label="改善" :value="`${data.migration.improved}人`" tone="teal" /></div>
            <div class="drill-card" @click="goMigration('stable', '稳定')"><KpiCard label="稳定" :value="`${data.migration.stable}人`" tone="primary" /></div>
            <div class="drill-card" @click="goMigration('declined', '恶化')"><KpiCard label="恶化" :value="`${data.migration.declined}人`" tone="danger" /></div>
            <div class="drill-card" @click="goMigration('mixed', '变化分化')"><KpiCard label="变化分化" :value="`${data.migration.mixed}人`" tone="amber" /></div>
            <div class="drill-card" @click="goMigration('insufficient', '数据不足')"><KpiCard label="数据不足" :value="`${data.migration.insufficient}人`" tone="amber" /></div>
          </div>
          <div v-if="!data.migration.fromSemester || !data.migration.toSemester" class="sa-faint" style="font-size:12px">当前范围不足两个可比较学期</div>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="sa-card" style="height:100%">
          <div class="sa-card-title">历史挂科模式 <KpiLabel label="" formula="基于筛选范围内真实不及格记录识别；各模式可相互重叠" /></div>
          <el-table :data="data.failPatterns" size="small" @row-click="goPattern" row-class-name="row-clickable">
            <el-table-column prop="label" label="模式" width="120" />
            <el-table-column prop="count" label="学生数" width="76" align="right"><template #default="{row}"><b class="tnum">{{ row.count }}</b></template></el-table-column>
            <el-table-column prop="definition" label="识别口径" min-width="180" show-overflow-tooltip />
          </el-table>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">挂科集中课程 TOP10 <KpiLabel label="" formula="挂科率=不及格人次÷总修读人次，仅统计修读≥30人次课程" /></div>
      <el-table v-if="data.failCourses.length" :data="data.failCourses" size="small" @row-click="goCourse" row-class-name="row-clickable">
        <el-table-column prop="name" label="课程" width="160"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="dept" label="开课学院" width="140" />
        <el-table-column label="挂科率" min-width="160"><template #default="{row}">
          <div style="display:flex;align-items:center;gap:8px">
            <el-progress :percentage="Math.min(row.failRate*5,100)" :show-text="false" :stroke-width="9" :color="row.failRate>15?'#E11D48':'#D97706'" style="flex:1" />
            <span class="tnum" :style="{color:row.failRate>15?'#E11D48':'#D97706',fontWeight:600,minWidth:'44px',textAlign:'right'}">{{ row.failRate }}%</span>
          </div>
        </template></el-table-column>
        <el-table-column prop="failCount" label="不及格" width="76" align="right" />
        <el-table-column prop="totalCount" label="修读人数" width="86" align="right" />
        <el-table-column prop="avgScore" label="平均分" width="76" align="right"><template #default="{row}"><b class="tnum">{{ row.avgScore }}</b></template></el-table-column>
        <el-table-column label="首次通过率" width="96" align="right"><template #default="{row}"><span class="tnum" :style="{color:(row.firstPassRate||0)>70?'#0D9488':'#E11D48'}">{{ row.firstPassRate ?? '—' }}{{ row.firstPassRate != null ? '%' : '' }}</span></template></el-table-column>
        <el-table-column label="最终通过率" width="96" align="right"><template #default="{row}"><span class="tnum" :style="{color:(row.finalPassRate||0)>85?'#0D9488':'#D97706'}">{{ row.finalPassRate ?? '—' }}{{ row.finalPassRate != null ? '%' : '' }}</span></template></el-table-column>
      </el-table>
      <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import { useBusinessPageTitle } from '@/utils/businessPage'
import { getFilterMeta, type SemesterOpt, type MajorOpt, type ClassOpt } from '@/utils/meta'
const router = useRouter()
const pageTitle = useBusinessPageTitle('/admin/students/analysis', '学生成长与学业分析')
const pageLoading = ref(false)
const loadError = ref('')
const updatedAt = ref('')
const studentPeriod = computed(() => fSemester.value ? `统计学期：${fSemester.value}` : fYear.value ? `统计学年：${fYear.value}` : '全部已接入学期')

const fSemester = ref('')
const fYear = ref('')
const fGrade = ref('')
const fCollege = ref('')
const fMajor = ref('')
const fClass = ref('')
const fRetake = ref('')
const fRequired = ref('')
const semesters = ref<SemesterOpt[]>([])
const years = ref<string[]>([])
const grades = ref<string[]>([])
const colleges = ref<{value:string;label:string}[]>([])
const allMajors = ref<MajorOpt[]>([])
const allClasses = ref<ClassOpt[]>([])

const majorOptions = computed(() =>
  fCollege.value ? allMajors.value.filter(m => m.college === fCollege.value) : allMajors.value)
const classOptions = computed(() =>
  fMajor.value ? allClasses.value.filter(c => c.major === fMajor.value) : allClasses.value)

function onCollege() { fMajor.value = ''; fClass.value = ''; load() }
function onMajor() { fClass.value = ''; load() }
function onSemester() { if (fSemester.value) fYear.value = ''; load() }
function onYear() { if (fYear.value) fSemester.value = ''; load() }

const studentKpis = ref<any[]>([])
const evidence = ref<any>({})
const data = reactive<any>({
  clusters: [], gradeGpa: [], creditDist: [], failCourses: [], failPatterns: [],
  migration: { fromSemester: null, toSemester: null, improved: 0, stable: 0, declined: 0, mixed: 0, insufficient: 0, compared: 0, avgDelta: null, avgFailDelta: null, threshold: 0.3, failThreshold: 1 },
})
function signed(value: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}` }
async function load() {
  pageLoading.value = true
  loadError.value = ''
  const params = new URLSearchParams()
  if (fSemester.value) params.set('semester', fSemester.value)
  else if (fYear.value) params.set('year', fYear.value)
  if (fGrade.value) params.set('grade', fGrade.value)
  if (fCollege.value) params.set('college', fCollege.value)
  if (fMajor.value) params.set('major', fMajor.value)
  if (fClass.value) params.set('class_id', fClass.value)
  if (fRetake.value) params.set('retake', fRetake.value)
  if (fRequired.value) params.set('required', fRequired.value)
  const qs = params.toString() ? `?${params.toString()}` : ''
  try {
    const d = await http.get('/admin/students/analysis' + qs)
    if (d) {
      studentKpis.value = d.studentKpis || []
      evidence.value = d.evidence || {}
      Object.assign(data, d)
      updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' })
    }
  } catch (error:any) {
    loadError.value = error?.message || '数据加载失败，请稍后重试'
  } finally {
    pageLoading.value = false
  }
}

function goCourse(row: any) { router.push({ path: '/admin/course/' + row.id, query: { ...(fSemester.value ? { semester: fSemester.value } : {}), returnTo:'/admin/students/analysis', returnLabel:'学生成长与学业分析' } }) }

function drillQuery() {
  const query: Record<string, string> = {}
  if (fSemester.value) query.semester = fSemester.value
  else if (fYear.value) query.year = fYear.value
  if (fGrade.value) query.grade = fGrade.value
  if (fCollege.value) query.college = fCollege.value
  if (fMajor.value) query.major = fMajor.value
  if (fClass.value) query.class = fClass.value
  if (fRetake.value) query.retake = fRetake.value
  if (fRequired.value) query.required = fRequired.value
  return query
}
function goPattern(row: any) {
  router.push({ path: '/admin/students/list', query: { ...drillQuery(), pattern: row.key, patternLabel: row.label } })
}
function goMigration(key: string, label: string) {
  if (!data.migration.fromSemester || !data.migration.toSemester) return
  router.push({ path: '/admin/students/list', query: {
    ...drillQuery(), migration: key, migrationLabel: label,
    from_semester: data.migration.fromSemester, to_semester: data.migration.toSemester,
  } })
}

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('高危') || label.includes('预警')) return 'danger'
  if (label.includes('优秀') || label.includes('GPA')) return 'teal'
  return 'primary'
}

const clusterOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c}人（{d}%）' },
  series: [{
    type: 'pie', radius: ['44%', '72%'], center: ['50%', '50%'], avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 }, label: { show: false },
    data: data.clusters.map((c: any) => ({ name: c.label, value: c.count, itemStyle: { color: c.color } })),
  }],
}))

const gradeOption = computed(() => {
  const g = data.gradeGpa || []
  const gpaColor = (v: number) => v > 3.0 ? '#0D9488' : v > 2.5 ? '#4F46E5' : '#D97706'
  return {
    grid: { left: 6, right: 16, top: 16, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any) => { const r = g[ps[0].dataIndex]; return `${r.grade}级<br/>GPA ${r.gpa} · ${r.students}人` } },
    xAxis: { type: 'category', data: g.map((x: any) => x.grade + '级'), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: { type: 'value', min: 0, max: 4, axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    series: [{
      type: 'bar', barWidth: '48%', itemStyle: { borderRadius: [4, 4, 0, 0] },
      data: g.map((x: any) => ({ value: x.gpa, itemStyle: { color: gpaColor(x.gpa) } })),
      label: { show: true, position: 'top', formatter: '{c}', color: '#64748B', fontSize: 11 },
    }],
  }
})

const creditOption = computed(() => {
  const c = [...(data.creditDist || [])].reverse()
  return {
    grid: { left: 6, right: 40, top: 6, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any) => { const d = c[ps[0].dataIndex]; return `${d.label}<br/>${d.count}人 · ${d.pct}%` } },
    xAxis: { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: c.map((x: any) => x.label), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [{
      type: 'bar', barWidth: '54%', itemStyle: { borderRadius: [0, 4, 4, 0] },
      data: c.map((x: any) => ({ value: x.count, itemStyle: { color: x.color } })),
      label: { show: true, position: 'right', formatter: (p: any) => `${c[p.dataIndex].count}人 ${c[p.dataIndex].pct}%`, color: '#64748B', fontSize: 11 },
    }],
  }
})

onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  years.value = (meta.years || []).slice().reverse()
  grades.value = meta.grades || []
  colleges.value = meta.colleges || []
  allMajors.value = meta.majors || []
  allClasses.value = meta.classes || []
  await load()
})
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.legend-list { margin-top: 6px; }
.legend-item { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; }
.dot { width: 9px; height: 9px; border-radius: 2px; flex-shrink: 0; }
.lg-label { color: #475569; }
.lg-val { margin-left: auto; color: #64748B; }
.grade-foot { margin-top: 6px; display: flex; flex-direction: column; gap: 2px; font-size: 10px; color: #94A3B8; }
.migration-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; color: #475569; font-size: 13px; }
.migration-meta b { color: var(--sa-primary); }
.migration-meta em { margin-left: auto; color: #64748B; font-style: normal; font-size: 12px; }
.migration-kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.drill-card { cursor: pointer; border-radius: 14px; transition: transform .15s ease, box-shadow .15s ease; }
.drill-card:hover { transform: translateY(-2px); box-shadow: 0 8px 18px rgba(15,23,42,.08); }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
</style>

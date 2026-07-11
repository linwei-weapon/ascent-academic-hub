<template>
  <div style="display:flex;gap:16px">
    <div class="report-nav">
      <div class="nav-title">报表中心</div>
      <div v-for="g in groups" :key="g.name" style="margin-bottom:12px">
        <div class="nav-group">{{ g.name }}</div>
        <div v-for="r in g.items" :key="r.key" class="nav-item" :class="{active:activeTab===r.key}" @click="selectReport(r.key)">
          {{ r.label }}
        </div>
      </div>
      <div style="margin-top:8px;border-top:1px solid var(--sa-border);padding-top:8px">
        <div class="nav-link" @click="$router.push('/admin/reports/custom')">自定义报表 →</div>
        <div class="nav-link" @click="$router.push('/admin/reports/accredit')">认证评估报表 →</div>
      </div>
    </div>

    <div style="flex:1;min-width:0">
      <h2 class="sa-page-title">{{ currentLabel }}</h2>
      <p class="sa-page-sub">数据证据：{{ evidence.label || '正在核验' }} · {{ scopeLabel }} · 共 {{ filteredData.length }} 条</p>

      <el-alert
        v-if="evidence.level && evidence.level !== 'real'"
        :title="evidence.level === 'simulated' ? '本报表使用规则模拟数据' : '本报表同时使用真实与模拟数据'"
        :description="evidenceDescription"
        type="warning" :closable="false" show-icon style="margin-bottom:12px"
      />
      <el-alert v-if="evidence.limitation" :title="evidence.limitation" type="info" :closable="false" show-icon style="margin-bottom:12px" />

      <div v-if="insights.length" class="insight-box">
        <div v-for="(ins,i) in insights" :key="i" class="insight-row">
          <span class="insight-dot" :class="ins.level">{{ ins.level==='red'?'!':ins.level==='yellow'?'–':'✓' }}</span>
          <span>{{ ins.text }}</span>
        </div>
      </div>

      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center">
        <el-select v-if="supports('semester')" v-model="fSemester" placeholder="全部学期" size="small" clearable style="width:160px" @change="onSemester">
          <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-if="supports('year')" v-model="fYear" placeholder="全部学年" size="small" clearable style="width:140px" @change="onYear">
          <el-option v-for="y in years" :key="y" :label="y + '学年'" :value="y" />
        </el-select>
        <el-select v-if="supports('college')" v-model="fCollege" placeholder="全部学院" size="small" clearable style="width:160px" @change="loadData">
          <el-option v-for="c in colleges" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-select v-if="supports('grade')" v-model="fGrade" placeholder="全部年级" size="small" clearable style="width:120px" @change="loadData">
          <el-option v-for="g in grades" :key="g" :label="g + '级'" :value="g" />
        </el-select>
        <el-select v-if="activeTab==='attrition'" v-model="fKind" placeholder="全部异动" size="small" clearable style="width:120px" @change="loadData">
          <el-option v-for="k in attritionKinds" :key="k" :label="k" :value="k" />
        </el-select>
        <div style="flex:1" />
        <div style="display:flex;gap:8px;white-space:nowrap">
          <el-button size="small" @click="exportTable('csv')">导出 CSV</el-button>
          <el-button size="small" @click="exportTable('pdf')">打印/另存为 PDF</el-button>
        </div>
      </div>

      <div class="sa-card" style="padding:0;overflow:hidden" v-loading="loading">
        <el-result v-if="loadError" icon="error" title="报表加载失败" :sub-title="loadError">
          <template #extra><el-button size="small" @click="loadData">重新加载</el-button></template>
        </el-result>
        <el-empty v-else-if="!loading && !filteredData.length" :description="evidence.limitation || '当前筛选范围内暂无数据'" />
        <el-table v-else :data="filteredData" size="small" style="width:100%" max-height="420">
          <el-table-column v-for="col in currentCols" :key="col.prop" :prop="col.prop" :label="col.label" :width="col.width" :min-width="col.minWidth" :sortable="col.sortable">
            <template v-if="col.html" #default="{row}"><span v-html="col.html(row)" /></template>
          </el-table-column>
        </el-table>
      </div>

      <div v-if="activeTab==='score' && scoreChartData.length" class="sa-card" style="margin-top:14px">
        <div class="sa-card-title">课程成绩分布对比 <span class="extra">挂科率最高 12 门</span></div>
        <EChart :option="scoreOption" :height="Math.max(220, scoreChartData.length*30)" />
      </div>

      <div v-else-if="activeTab==='passrank' && passChartData.length" class="sa-card" style="margin-top:14px">
        <div class="sa-card-title">课程通过率对比 <span class="extra">通过率最低 12 门</span></div>
        <EChart :option="passOption" :height="Math.max(220, passChartData.length*30)" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { ref, computed, onMounted } from 'vue'
import EChart from '@/components/EChart.vue'
import { getFilterMeta } from '@/utils/meta'
import { exportCsv, printReport, type ExportCol } from '@/utils/export'

const activeTab = ref('score')
const tableData = ref([] as any[])
const fSemester = ref('')
const fYear = ref('')
const fCollege = ref('')
const fGrade = ref('')
const fKind = ref('')
const semesters = ref<{ value: string; label: string }[]>([])
const years = ref<string[]>([])
const colleges = ref<{ value: string; label: string }[]>([])
const grades = ref<string[]>([])
const attritionKinds = ref<string[]>([])
const loading = ref(false)
const loadError = ref('')
const evidence = ref<any>({})
let requestSeq = 0

const groups = [
  { name: '教学质量', items: [
    { key: 'score', label: '成绩分布统计' },
    { key: 'passrank', label: '课程通过率排名' },
    { key: 'discipline', label: '考风考纪统计' },
  ] },
  { name: '学生发展', items: [
    { key: 'alert', label: '学业预警明细' },
    { key: 'credit', label: '学分修读进度' },
    { key: 'attrition', label: '学籍异动统计' },
  ] },
  { name: '培养成效', items: [
    { key: 'graduate', label: '毕业学位情况' },
    { key: 'exam', label: '校外考试统计' },
    { key: 'attend', label: '学生出勤率统计' },
  ] },
]
const labels: Record<string, string> = { score: '成绩分布统计', passrank: '课程通过率排名', discipline: '考风考纪统计', alert: '学业预警明细', credit: '学分修读进度', attrition: '学籍异动统计', graduate: '毕业学位情况', exam: '校外考试统计', attend: '学生出勤率统计' }
const currentLabel = computed(() => labels[activeTab.value] || '')

const supportedFilters: Record<string, string[]> = {
  score: ['semester', 'year', 'college', 'grade'], passrank: ['semester', 'year', 'college', 'grade'],
  discipline: ['semester', 'year', 'college', 'grade'], alert: ['semester', 'year', 'college', 'grade'],
  credit: ['college', 'grade'], attrition: ['semester', 'year', 'college', 'grade', 'kind'],
  graduate: ['semester', 'year', 'college', 'grade'], exam: ['college', 'grade'],
  attend: ['semester', 'year', 'college'],
}
const supports = (name: string) => supportedFilters[activeTab.value]?.includes(name) ?? false
const evidenceDescription = computed(() => {
  const tables = (evidence.value.details || []).map((d: any) => {
    const sources = (d.sources || []).map((s: any) => `${s.label} ${s.count} 条`).join('、')
    return `${d.table}：${sources || '无记录'}`
  })
  return tables.join('；')
})

// 维度筛选改为后端 WHERE（学期/学院/年级/学籍异动），前端不再客户端过滤
const filteredData = computed(() => tableData.value)

// 副标题范围说明：优先学期 → 学年 → 全部学期
const scopeLabel = computed(() => {
  if (fSemester.value) return semesters.value.find(s => s.value === fSemester.value)?.label || fSemester.value
  if (fYear.value) return fYear.value + '学年'
  return '全部学期'
})

const insights = computed(() => {
  const d = filteredData.value
  if (!d.length) return []
  const r1 = (n: number) => Math.round(n * 10) / 10
  const out: any[] = []
  if (activeTab.value === 'score') {
    const rows = d.map((r: any) => { const t = (r.score90 || 0) + (r.score80 || 0) + (r.score70 || 0) + (r.score60 || 0) + (r.scoreFail || 0); return { course: r.course, college: r.college, fr: t ? r.scoreFail / t * 100 : 0 } }).sort((a, b) => b.fr - a.fr)
    const top = rows[0]; const high = rows.filter(x => x.fr > 10).length
    if (top) out.push({ level: top.fr > 20 ? 'red' : 'yellow', text: `挂科率最高：${top.course}(${top.college}) ${r1(top.fr)}%${high ? `，共 ${high} 门课挂科率>10%` : ''}` })
    const good = rows.filter(x => x.fr < 3).length
    if (good) out.push({ level: 'green', text: `${good} 门课挂科率<3%，教学质量稳定` })
  } else if (activeTab.value === 'passrank') {
    const sorted = [...d].sort((a: any, b: any) => b.passRate - a.passRate)
    const low = sorted[sorted.length - 1]; const high = sorted[0]
    const lt85 = d.filter((x: any) => x.passRate < 85).length
    if (low) out.push({ level: low.passRate < 85 ? 'red' : 'yellow', text: `通过率最低：${low.course} ${low.passRate}%${lt85 ? `，${lt85} 门课通过率<85%` : ''}` })
    if (high) out.push({ level: 'green', text: `通过率最高：${high.course} ${high.passRate}%` })
  } else if (activeTab.value === 'alert') {
    const severe = d.filter((x: any) => x.level === '严重').length
    const warn = d.filter((x: any) => x.level === '警告').length
    const byCol: Record<string, number> = {}
    d.forEach((x: any) => { byCol[x.college] = (byCol[x.college] || 0) + 1 })
    const topCol = Object.entries(byCol).sort((a, b) => b[1] - a[1])[0]
    out.push({ level: severe ? 'red' : 'yellow', text: `严重预警 ${severe} 条、警告 ${warn} 条${topCol ? `，预警记录最集中：${topCol[0]}(${topCol[1]}条)` : ''}` })
  } else if (activeTab.value === 'credit') {
    const sorted = [...d].sort((a: any, b: any) => (b.gap || 0) - (a.gap || 0))
    const top = sorted[0]
    if (top) out.push({ level: top.gap > 15 ? 'red' : 'yellow', text: `学分缺口最大：${top.major}${top.grade || ''} ${top.gap}学分` })
    const avgReq = r1(d.reduce((s: number, x: any) => s + (x.majorReq || 0), 0) / d.length)
    out.push({ level: 'green', text: `专业必修要求平均 ${avgReq} 学分` })
  } else if (activeTab.value === 'attrition') {
    const sorted = [...d].sort((a: any, b: any) => (b.rate || 0) - (a.rate || 0))
    const top = sorted[0]
    if (top) out.push({ level: top.rate > 2 ? 'red' : 'yellow', text: `异动率最高：${top.college}${top.grade || ''} ${top.rate}%` })
  } else if (activeTab.value === 'graduate') {
    const avg = r1(d.reduce((s: number, x: any) => s + (x.onTime || 0), 0) / d.length)
    const low = [...d].sort((a: any, b: any) => (a.onTime || 0) - (b.onTime || 0))[0]
    out.push({ level: avg > 90 ? 'green' : 'yellow', text: `各专业按期毕业率平均 ${avg}%${low && low.onTime < 90 ? `，最低：${low.major} ${low.onTime}%` : ''}` })
  } else if (activeTab.value === 'exam') {
    const num = (v: any) => parseFloat(String(v ?? '').replace('%', '')) || 0
    const avgCet6 = r1(d.reduce((s: number, x: any) => s + num(x.cet6), 0) / d.length)
    out.push({ level: avgCet6 < 50 ? 'yellow' : 'green', text: `CET6 平均通过率 ${avgCet6}%` })
  } else if (activeTab.value === 'attend') {
    const sorted = [...d].sort((a: any, b: any) => (a.rate || 0) - (b.rate || 0))
    const low = sorted[0]; const lt88 = d.filter((x: any) => x.rate < 88).length
    if (low) out.push({ level: low.rate < 85 ? 'red' : 'yellow', text: `出勤率最低：${low.course} ${low.rate}%${lt88 ? `，${lt88} 门课<88%` : ''}` })
  } else if (activeTab.value === 'discipline') {
    const tv = d.reduce((s: number, x: any) => s + (x.violation || 0), 0)
    const tc = d.reduce((s: number, x: any) => s + (x.cheat || 0), 0)
    out.push({ level: (tv + tc) > 0 ? 'yellow' : 'green', text: `累计违纪 ${tv} 起、作弊 ${tc} 起` })
  }
  return out
})

const reportCols: Record<string, any[]> = {
  score: [
    { prop: 'course', label: '课程', minWidth: 150 }, { prop: 'college', label: '学院', minWidth: 130 },
    { prop: 'avgScore', label: '均值', width: 64, sortable: true }, { prop: 'median', label: '中位数', width: 70 }, { prop: 'stddev', label: '标准差', width: 70 },
    { prop: 'totalStudents', label: '修读人次', width: 90, html: (r: any) => `${(r.score90 + r.score80 + r.score70 + r.score60 + r.scoreFail).toLocaleString()}` },
  ],
  passrank: [
    { prop: 'course', label: '课程', minWidth: 150 }, { prop: 'college', label: '开课学院', minWidth: 130 }, { prop: 'teacher', label: '教师', width: 80 },
    { prop: 'passRate', label: '通过率', width: 80, sortable: true, html: (r: any) => `<span style="color:${r.passRate > 90 ? '#0D9488' : r.passRate > 80 ? '#4F46E5' : '#E11D48'};font-weight:600">${r.passRate}%</span>` },
    { prop: 'failRate', label: '挂科率', width: 76 }, { prop: 'avgScore', label: '平均分', width: 72 }, { prop: 'excellent', label: '优秀率', width: 72 }, { prop: 'rank', label: '排名', width: 56 },
  ],
  discipline: [
    { prop: 'college', label: '学院', minWidth: 160 }, { prop: 'semester', label: '学期', minWidth: 130 }, { prop: 'violation', label: '违纪', width: 70 }, { prop: 'cheat', label: '作弊', width: 70 },
    { prop: 'rate', label: '每千人率', width: 90, html: (r: any) => `<span style="color:${r.rate > 0.3 ? '#E11D48' : '#1E293B'};font-weight:600">${r.rate}‰</span>` },
  ],
  alert: [
    { prop: 'name', label: '姓名', width: 72 }, { prop: 'class', label: '班级', minWidth: 120 }, { prop: 'college', label: '学院', minWidth: 130 }, { prop: 'major', label: '专业', minWidth: 120 },
    { prop: 'level', label: '等级', width: 64, html: (r: any) => `<span style="color:${r.level === '严重' ? '#E11D48' : r.level === '警告' ? '#D97706' : '#94A3B8'};font-weight:600">${r.level}</span>` },
    { prop: 'type', label: '类型', width: 96 }, { prop: 'failCourses', label: '不及格门次', width: 92 }, { prop: 'failCredits', label: '不及格学分', width: 92 },
    { prop: 'gapCredits', label: '毕业差距', width: 80 }, { prop: 'status', label: '状态', width: 74 },
  ],
  credit: [
    { prop: 'major', label: '专业', minWidth: 140 }, { prop: 'grade', label: '年级', width: 76 },
    { prop: 'generalReq', label: '通识必修', width: 82 }, { prop: 'majorReq', label: '专业必修', width: 82, html: (r: any) => `<span style="color:${r.majorReq < 60 ? '#E11D48' : '#1E293B'};font-weight:600">${r.majorReq}</span>` },
    { prop: 'gap', label: '缺口学分', width: 82, html: (r: any) => `<span style="color:${r.gap > 15 ? '#E11D48' : '#D97706'};font-weight:600">${r.gap}</span>` },
  ],
  attrition: [
    { prop: 'college', label: '学院', minWidth: 160 }, { prop: 'grade', label: '年级', width: 84 }, { prop: 'total', label: '在校生', width: 76 },
    { prop: 'suspend', label: '休学', width: 60 }, { prop: 'resume', label: '复学', width: 60 }, { prop: 'dropout', label: '退学', width: 60 }, { prop: 'transfer', label: '转专业', width: 64 },
    { prop: 'rate', label: '异动率', width: 78, html: (r: any) => `<span style="color:${r.rate > 2 ? '#E11D48' : '#1E293B'};font-weight:600">${r.rate}%</span>` },
  ],
  graduate: [
    { prop: 'major', label: '专业', minWidth: 150 }, { prop: 'grade', label: '年级', width: 84 }, { prop: 'total', label: '应毕业', width: 72 },
    { prop: 'onTime', label: '按期毕业率', width: 96, html: (r: any) => `<span style="color:${r.onTime > 90 ? '#0D9488' : '#D97706'};font-weight:600">${r.onTime}%</span>` },
    { prop: 'degree', label: '学位授予率', width: 92 }, { prop: 'finish', label: '结业率', width: 72 }, { prop: 'delay', label: '延毕率', width: 72 },
  ],
  exam: [
    { prop: 'college', label: '学院', minWidth: 160 }, { prop: 'grade', label: '年级', width: 84 },
    { prop: 'cet4', label: 'CET4', width: 80 }, { prop: 'cet6', label: 'CET6', width: 80 }, { prop: 'nc2', label: '计算机二级', minWidth: 96 }, { prop: 'nc3', label: '计算机三级', minWidth: 96 },
  ],
  attend: [
    { prop: 'college', label: '学院', minWidth: 140 }, { prop: 'course', label: '课程', minWidth: 150 },
    { prop: 'rate', label: '出勤率', width: 78, sortable: true, html: (r: any) => `<span style="color:${r.rate < 85 ? '#E11D48' : '#0D9488'};font-weight:600">${r.rate}%</span>` },
    { prop: 'absentGT3', label: '缺勤>3次', width: 100, html: (r: any) => `${r.absentGT3}人(${r.absentGT3Pct}%)` },
    { prop: 'trend', label: '趋势', width: 56, html: (r: any) => `<span style="color:${r.trend === 'up' ? '#0D9488' : r.trend === 'down' ? '#E11D48' : '#94A3B8'}">${r.trend === 'up' ? '↑' : r.trend === 'down' ? '↓' : '→'}</span>` },
  ],
}
const currentCols = computed(() => reportCols[activeTab.value] || [])

// 成绩分布堆叠条形图：取挂科率最高的前 12 门
const scoreChartData = computed(() => {
  if (activeTab.value !== 'score') return []
  return [...filteredData.value].map((r: any) => {
    const total = (r.score90 || 0) + (r.score80 || 0) + (r.score70 || 0) + (r.score60 || 0) + (r.scoreFail || 0)
    return { ...r, total, failPct: total ? r.scoreFail / total * 100 : 0 }
  }).sort((a, b) => b.failPct - a.failPct).slice(0, 12).reverse()
})
const SCORE_SEGS = [
  { key: 'score90', name: '优秀≥90', color: '#0D9488' },
  { key: 'score80', name: '良好80-89', color: '#4F46E5' },
  { key: 'score70', name: '中等70-79', color: '#6366F1' },
  { key: 'score60', name: '及格60-69', color: '#D97706' },
  { key: 'scoreFail', name: '不及格<60', color: '#E11D48' },
]
const scoreOption = computed(() => {
  const d = scoreChartData.value
  return {
    grid: { left: 6, right: 16, top: 28, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, textStyle: { color: '#64748B', fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    xAxis: { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: d.map((x: any) => x.course), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: SCORE_SEGS.map(s => ({
      name: s.name, type: 'bar', stack: 'total', itemStyle: { color: s.color },
      data: d.map((x: any) => x[s.key] || 0),
    })),
  }
})

// 通过率条形图：取通过率最低前 12 门
const passChartData = computed(() => {
  if (activeTab.value !== 'passrank') return []
  return [...filteredData.value].sort((a: any, b: any) => a.passRate - b.passRate).slice(0, 12).reverse()
})
const passOption = computed(() => {
  const d = passChartData.value
  return {
    grid: { left: 6, right: 40, top: 6, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: '{b}：{c}%' },
    xAxis: { type: 'value', max: 100, axisLabel: { color: '#94A3B8', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: d.map((x: any) => x.course), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [{
      type: 'bar', barWidth: '56%', itemStyle: { borderRadius: [0, 4, 4, 0] },
      data: d.map((x: any) => ({ value: x.passRate, itemStyle: { color: x.passRate > 90 ? '#0D9488' : x.passRate > 80 ? '#4F46E5' : '#E11D48' } })),
      label: { show: true, position: 'right', formatter: '{c}%', color: '#64748B', fontSize: 11 },
    }],
  }
})

async function loadData() {
  const seq = ++requestSeq
  const qs = new URLSearchParams({ type: activeTab.value })
  if (supports('semester') && fSemester.value) qs.set('semester', fSemester.value)
  else if (supports('year') && fYear.value) qs.set('year', fYear.value)
  if (supports('college') && fCollege.value) qs.set('college', fCollege.value)
  if (supports('grade') && fGrade.value) qs.set('grade', fGrade.value)
  if (activeTab.value === 'attrition' && fKind.value) qs.set('kind', fKind.value)
  loading.value = true
  loadError.value = ''
  try {
    const d: any = await http.get('/admin/reports?' + qs.toString())
    if (seq !== requestSeq) return
    tableData.value = d?.rows || []
    evidence.value = d?.evidence || {}
  } catch (err: any) {
    if (seq !== requestSeq) return
    tableData.value = []
    evidence.value = {}
    loadError.value = err?.message || '请求失败'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}
// 学期与学年互斥（学期更细，选学期则清学年，反之亦然）
function onSemester() { if (fSemester.value) fYear.value = ''; loadData() }
function onYear() { if (fYear.value) fSemester.value = ''; loadData() }
function selectReport(key: string) {
  activeTab.value = key
  fKind.value = ''
  if (!supports('semester')) fSemester.value = ''
  else if (!fSemester.value && !fYear.value) fSemester.value = semesters.value.find(s => s.value)?.value || ''
  if (!supports('year')) fYear.value = ''
  if (!supports('grade')) fGrade.value = ''
  loadData()
}
function exportTable(fmt: string) {
  if (!filteredData.value.length) { window.alert('当前无数据可导出'); return }
  if (fmt === 'pdf') { printReport(); return }
  // 从列定义取 {prop,label}，剥离 html 渲染函数导出原始值；派生列补 value 取数
  const derived: Record<string, (r: any) => any> = {
    totalStudents: (r: any) => (r.score90 || 0) + (r.score80 || 0) + (r.score70 || 0) + (r.score60 || 0) + (r.scoreFail || 0),
    absentGT3: (r: any) => `${r.absentGT3}人(${r.absentGT3Pct}%)`,
  }
  const cols: ExportCol[] = currentCols.value.map((c: any) => ({
    prop: c.prop, label: c.label, value: derived[c.prop],
  }))
  exportCsv(currentLabel.value, cols, filteredData.value)
}
onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  years.value = (meta.years || []).slice().reverse()
  colleges.value = meta.colleges
  grades.value = meta.grades
  attritionKinds.value = meta.attritionKinds
  fSemester.value = meta.current  // 默认当前学期，避免聚合全部 9 学期产生歧义
  await loadData()
})
</script>

<style scoped>
.report-nav { width: 200px; flex-shrink: 0; }
.nav-title { font-size: 16px; font-weight: 700; margin-bottom: 12px; color: #1E293B; }
.nav-group { font-size: 11px; font-weight: 600; color: #94A3B8; letter-spacing: .03em; margin-bottom: 4px; }
.nav-item { padding: 8px 12px; font-size: 13px; cursor: pointer; border-radius: 8px; margin-bottom: 2px; color: #64748B; }
.nav-item:hover { background: #f1f5f9; }
.nav-item.active { background: #eef2ff; color: var(--sa-primary); font-weight: 600; }
.nav-link { padding: 8px 12px; font-size: 13px; cursor: pointer; border-radius: 8px; color: var(--sa-primary); font-weight: 600; }
.nav-link:hover { background: #eef2ff; }
.insight-box { background: #F8FAFC; border: 1px solid var(--sa-border); border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; }
.insight-row { margin-bottom: 6px; font-size: 12px; line-height: 1.6; display: flex; align-items: flex-start; gap: 8px; color: #334155; }
.insight-row:last-child { margin-bottom: 0; }
.insight-dot { display: inline-block; width: 18px; height: 18px; border-radius: 50%; text-align: center; line-height: 18px; font-size: 11px; flex-shrink: 0; margin-top: 1px; font-weight: 700; }
.insight-dot.red { background: #FEE2E2; color: #E11D48; }
.insight-dot.yellow { background: #FEF3C7; color: #D97706; }
.insight-dot.green { background: #CCFBF1; color: #0D9488; }
</style>

<template>
  <div class="dashboard-page">
    <div class="page-head">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">先判断数据是否可用，再定位偏离学院、受影响学生与重点课程。</p>
      </div>
      <el-select v-model="fSemester" size="small" class="semester-select" placeholder="选择学期" @change="onSemesterChange">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
    </div>
    <BusinessPageContext
      :period="fSemester ? `统计学期：${fSemester}` : ''"
      source="教务系统学籍、成绩、课程与当前有效预警"
      :loading="pageLoading"
      :error="loadError"
      :updated-at="updatedAt"
    />

    <template v-if="pageLoading && !hasData">
      <el-alert title="正在汇总本学期成绩覆盖、学院偏离与重点课程，预计需要数秒…" type="info" :closable="false" show-icon class="loading-alert" />
      <el-skeleton :rows="9" animated />
    </template>

    <template v-else-if="hasData">
      <div v-if="pageLoading" class="updating-bar">正在按 {{ fSemester }} 更新，当前结果暂时保留…</div>

      <div class="scope-background">
        <div><span>分析范围</span><b>{{ data.scope?.label || '—' }}</b></div>
        <div><span>在籍学生</span><b class="tnum">{{ formatNumber(data.scopeBackground?.students) }}</b></div>
        <div><span>本学期开课</span><b class="tnum">{{ formatNumber(data.scopeBackground?.courses) }}</b></div>
        <div><span>{{ data.scopeBackground?.teacherLabel || '相关教师' }}</span><b class="tnum">{{ formatNumber(data.scopeBackground?.teachers) }}</b></div>
        <div><span>对比周期</span><b>{{ data.period?.previousSemester || '暂无上期' }}</b></div>
      </div>

      <section class="dashboard-section">
        <div class="section-heading">
          <div><h3>本期管理判断</h3><p>变化均与上一可比学期比较；点击卡片进入对应核查区域。</p></div>
        </div>
        <div class="management-grid">
          <button v-for="item in data.managementSummary || []" :key="item.id"
            class="management-card" type="button" @click="openSummaryHistory(item)">
            <div class="management-label">{{ item.label }} <KpiLabel label="" :formula="`${item.formula}；管理用途：${item.managementUse}`" /></div>
            <div class="management-value">{{ displayMetric(item) }}</div>
            <div v-if="item.change != null" class="management-change" :class="changeClass(item)">
              {{ changeText(item) }}
            </div>
            <div v-else class="management-change is-neutral">{{ item.supplement || '当前状态指标，不与上期简单比较' }}</div>
            <div class="management-use">{{ item.managementUse }}</div>
            <div class="management-action">查看历年学期变化 →</div>
          </button>
        </div>
      </section>

      <section v-if="data.managementFocus?.length" class="dashboard-section">
        <div class="section-heading compact"><div><h3>优先核查事项</h3><p>仅显示按影响范围与偏离程度排序后的全局 TOP1，点击进入证据。</p></div></div>
        <div class="focus-list">
          <button v-for="focus in data.managementFocus" :key="`${focus.targetType}:${focus.targetId}`"
            class="focus-item" :class="`is-${focus.level}`" type="button" @click="openFocus(focus)">
            <span class="focus-dot"></span>
            <span class="focus-copy"><b>{{ focus.title }}</b><small>{{ focus.detail }}</small></span>
            <span class="focus-action">核查证据 →</span>
          </button>
        </div>
      </section>

      <section v-if="hasCoursePassData" class="dashboard-section course-result-strip">
        <div class="section-heading compact">
          <div><h3>课程结果辅助指标</h3><p>按 {{ fSemester }} 和当前授权学生范围统计，用于解释重点课程，不替代学生率。</p></div>
        </div>
        <div class="result-metrics">
          <button v-for="k in passRateKpis" :key="k.label" class="result-metric" type="button"
            @click="openHistory(k.metricId)">
            <span>{{ k.label }} <KpiLabel label="" :formula="k.hint" /></span>
            <b>{{ k.value }}</b>
            <small>{{ k.sub }}</small>
            <i>查看历年变化 →</i>
          </button>
        </div>
      </section>

      <div id="college-compare" class="sa-card dashboard-card">
        <div class="sa-card-title">
          {{ data.scope?.restricted ? '授权范围学院概览' : '学院偏离与变化' }}
          <span class="extra">默认优先显示偏离较大的学院，点击学院进入证据详情</span>
        </div>
        <DataTable :columns="collegeCols" :data="collegeRows" storage-key="dashboard:college-compare"
          :max-business-columns="7" :config-version="3" stripe size="small"
          @row-click="goCollege" row-class-name="college-row-clickable">
          <template #toolbar>
            <el-select v-model="collegeSortKey" size="small" style="width:190px">
              <el-option label="按挂科学生率从高到低" value="fail" />
              <el-option label="按较上期恶化排序" value="change" />
              <el-option label="按平均 GPA 从低到高" value="gpa" />
              <el-option label="按预警学生率从高到低" value="alert" />
              <el-option label="按成绩覆盖率从低到高" value="coverage" />
            </el-select>
          </template>
          <template #col-name="{row}"><span class="college-link">{{ row.name }}</span></template>
          <template #col-currentFailRate="{row}"><b class="tnum risk-number">{{ row.currentFailRate }}</b></template>
          <template #col-currentFailVsScopePp="{row}"><span :class="deltaClass(row.currentFailVsScopePp, false)">{{ ppText(row.currentFailVsScopePp, '范围均值') }}</span></template>
          <template #col-currentFailChangePp="{row}"><span :class="deltaClass(row.currentFailChangePp, false)">{{ ppChangeText(row.currentFailChangePp) }}</span></template>
          <template #col-avgGpa="{row}"><b v-if="row.avgGpa != null" class="tnum">{{ row.avgGpa }}</b><span v-else>—</span></template>
          <template #col-avgGpaRank="{row}"><span v-if="row.avgGpaRank">第 {{ row.avgGpaRank }}/{{ row.comparisonCount }}</span><span v-else>—</span></template>
          <template #col-alertRate="{row}">{{ row.alertRate }}</template>
          <template #col-resultCoverageRate="{row}">{{ row.resultCoverageRate == null ? '—' : `${row.resultCoverageRate}%` }}</template>
          <template #col-drill><span class="college-link">详情</span></template>
        </DataTable>
        <div class="card-actions"><el-button size="small" @click="goStudents">查看{{ data.scope?.restricted ? '范围内' : '全校' }}学生名单</el-button></div>
      </div>

      <div v-if="data.scope?.restricted && canCompareColleges" class="sa-card dashboard-card">
        <div class="sa-card-title">跨学院聚合参照 <span class="extra">他院只提供聚合比较，不能进入学生明细</span></div>
        <el-alert type="info" :closable="false" show-icon :title="comparison.definition.boundary" style="margin-bottom:10px" />
        <DataTable :columns="comparisonCols" :data="comparison.items"
          storage-key="dashboard:college-aggregate-compare" :max-business-columns="5"
          :config-version="1" stripe size="small" @row-click="goComparisonCollege">
          <template #col-collegeName="{row}"><span :class="row.canDrillDown ? 'college-link' : ''">{{ row.collegeName }}</span><el-tag v-if="row.canDrillDown" size="small" effect="plain" style="margin-left:6px">本院</el-tag></template>
          <template #header-weightedAverageScore><span>加权平均分 <KpiLabel label="" :formula="comparison.definition.weightedAverageScore" /></span></template>
          <template #col-weightedAverageScore="{row}">{{ row.weightedAverageScore ?? '—' }}</template>
          <template #header-averageGpa><span>平均GPA <KpiLabel label="" :formula="comparison.definition.averageGpa" /></span></template>
          <template #col-averageGpa="{row}">{{ row.averageGpa ?? '—' }}</template>
          <template #header-currentFailStudentRate><span>当前挂科学生率 <KpiLabel label="" :formula="comparison.definition.currentFailStudentRate" /></span></template>
          <template #col-currentFailStudentRate="{row}">{{ row.currentFailStudentRate == null ? '—' : `${row.currentFailStudentRate}%` }}</template>
          <template #header-activeAlertStudentRate><span>有效预警学生率 <KpiLabel label="" :formula="comparison.definition.activeAlertStudentRate" /></span></template>
          <template #col-activeAlertStudentRate="{row}">{{ row.activeAlertStudentRate == null ? '—' : `${row.activeAlertStudentRate}%` }}</template>
          <template #col-detailPermission="{row}"><span :class="row.canDrillDown ? 'college-link' : 'sa-faint'">{{ row.canDrillDown ? '查看本院' : '仅可比较' }}</span></template>
        </DataTable>
      </div>

      <el-row :gutter="16" class="dashboard-section">
        <el-col :span="8">
          <div class="sa-card auxiliary-card">
            <div class="sa-card-title">GPA 结构 <el-select v-model="gpaCollege" size="small" style="width:145px" @change="loadGpa"><el-option :label="data.scope?.label || '全校'" value="all" /><el-option v-for="c in data.colleges" :key="c.id" :label="c.name" :value="c.id" /></el-select></div>
            <div class="gpa-donut-wrap"><EChart :option="gpaOption" :height="200" /><div class="gpa-donut-center"><div class="gpa-donut-total tnum">{{ gpaTotal.toLocaleString() }}</div><div class="gpa-donut-cap">有 GPA 学生</div></div></div>
            <div class="gpa-legend"><div v-for="(g, i) in gpaDisplay" :key="g.range || i" class="gpa-legend-row"><span class="dot" :style="{ background: GPA_COLORS[i % GPA_COLORS.length] }"></span><span class="gpa-legend-label">{{ g.label }}</span><span class="tnum gpa-legend-pct">{{ g.percent }}%</span></div></div>
          </div>
        </el-col>
        <el-col :span="16">
          <div id="focus-courses" class="sa-card">
            <div class="sa-card-title">本学期重点核查课程 TOP10 <span class="extra">按受影响学生数优先，同规模参考变化和公共必修属性</span></div>
            <DataTable :columns="focusCourseCols" :data="failCourses" storage-key="dashboard:focus-courses"
              :max-business-columns="6" :config-version="2" stripe size="small"
              @row-click="goCourse" row-class-name="college-row-clickable">
              <template #col-priorityRank="{row}"><b class="tnum">#{{ row.priorityRank }}</b></template>
              <template #col-name="{row}"><span class="college-link">{{ row.name }}</span></template>
              <template #col-failRate="{row}"><b class="tnum risk-number">{{ row.failRate }}%</b></template>
              <template #col-changePp="{row}"><span :class="deltaClass(row.changePp, false)">{{ ppChangeText(row.changePp) }}</span></template>
              <template #col-selectionReason="{row}"><span class="reason-text">{{ row.selectionReason }}</span></template>
              <template #col-courseGroup="{row}"><el-tag v-if="row.courseGroup" size="small" effect="plain" :type="row.courseGroup==='公共必修'?'warning':'info'">{{ row.courseGroup }}</el-tag><span v-else>—</span></template>
              <template #col-firstPassRate="{row}">{{ row.firstPassRate == null ? '—' : `${row.firstPassRate}%` }}</template>
              <template #col-drill><span class="college-link">详情</span></template>
            </DataTable>
          </div>
        </el-col>
      </el-row>

      <el-collapse class="evidence-collapse">
        <el-collapse-item title="数据来源、指标口径与原型边界" name="evidence">
          <p>真实数据：{{ (data.evidence?.real || []).join('、') }}</p>
          <p>{{ data.evidence?.limitation }}</p>
          <p>合成毕业与学位结果仅保留在接口原型字段中，本页不将其作为正式管理结论。</p>
        </el-collapse-item>
      </el-collapse>

      <MetricHistoryDialog
        v-model="historyVisible"
        :metric-id="historyMetricId"
        scope-type="school"
        :scope-label="data.scope?.label || '全校'"
        :end-semester="fSemester"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted, ref, computed } from 'vue'
import { http } from '@/utils/http';
import { useRoute, useRouter } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue';
import EChart from '@/components/EChart.vue';
import BusinessPageContext from '@/components/BusinessPageContext.vue';
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue';
import MetricHistoryDialog from '@/components/MetricHistoryDialog.vue';
import { getFilterMeta, type SemesterOpt } from '@/utils/meta';
import { SUMMARY_HISTORY_METRIC_IDS } from '@/utils/dashboardHistory';
import { authStore } from '@/store/auth';
import { useBusinessPageTitle } from '@/utils/businessPage';
const pageTitle = useBusinessPageTitle('/admin/dashboard', '教学数据总览');
const router = useRouter();
const route = useRoute();
const data = reactive<any>({ kpi:[], colleges:[], gpaDist:[], gpaDistByCollege:{}, scope:{ restricted:false,label:'全校' }, evidence:{} });
const comparison = reactive<any>({ items:[], definition:{} });
const canCompareColleges = computed(() => !!authStore.user?.permissionContext?.comparisonScope?.allowOtherOrganizations);

// 学院横向对比表列定义（M6 DataTable）
const collegeCols: DataTableColumn[] = [
  { key: 'name', label: '学院', width: 170, fixed: 'left', region: 'identity', required: true },
  { key: 'students', label: '在籍学生', width: 84, align: 'right', defaultVisible: false },
  { key: 'currentFailRate', label: '当前挂科学生率', width: 118, align: 'right', required: true },
  { key: 'currentFailVsScopePp', label: '较范围均值', width: 105, align: 'right' },
  { key: 'currentFailChangePp', label: '较上期变化', width: 105, align: 'right' },
  { key: 'avgGpa', label: '平均 GPA', width: 90, align: 'right' },
  { key: 'avgGpaRank', label: 'GPA 排名', width: 90, align: 'center' },
  { key: 'alertRate', label: '有效预警学生率', width: 118, align: 'right' },
  { key: 'resultCoverageRate', label: '有效成绩覆盖率', width: 118, align: 'right' },
  { key: 'drill', label: '详情', width: 52, fixed: 'right', region: 'action', required: true },
];
const comparisonCols: DataTableColumn[] = [
  { key: 'collegeName', label: '学院', minWidth: 170, fixed: 'left', region: 'identity', required: true },
  { key: 'students', label: '在籍学生', width: 90, align: 'right' },
  { key: 'weightedAverageScore', label: '加权平均分', width: 118, align: 'right' },
  { key: 'averageGpa', label: '平均GPA', width: 100, align: 'right' },
  { key: 'currentFailStudentRate', label: '当前挂科学生率', width: 130, align: 'right', required: true },
  { key: 'activeAlertStudentRate', label: '有效预警学生率', width: 125, align: 'right' },
  { key: 'detailPermission', label: '明细权限', width: 95, align: 'center', fixed: 'right', region: 'action', required: true },
];
const focusCourseCols: DataTableColumn[] = [
  { key: 'priorityRank', label: '优先级', width: 68, fixed: 'left', region: 'identity', required: true },
  { key: 'name', label: '课程', minWidth: 160, fixed: 'left', region: 'identity', required: true },
  { key: 'affectedStudents', label: '受影响学生', width: 96, align: 'right', required: true },
  { key: 'failRate', label: '当前未通过率', width: 106, align: 'right', required: true },
  { key: 'changePp', label: '较上期变化', width: 102, align: 'right' },
  { key: 'selectionReason', label: '入选原因', minWidth: 220, tooltip: true, required: true },
  { key: 'courseGroup', label: '课程类别', width: 90, align: 'center' },
  { key: 'college', label: '开课学院', width: 120, defaultVisible: false },
  { key: 'firstPassRate', label: '首次通过率', width: 96, align: 'right', defaultVisible: false },
  { key: 'avgScore', label: '平均分', width: 76, align: 'right', defaultVisible: false },
  { key: 'drill', label: '详情', width: 52, fixed: 'right', region: 'action', required: true },
];

// 学期筛选
const semesters = ref<SemesterOpt[]>([]);
const fSemester = ref('');

const gpaCollege = ref('all');
const gpaDisplay = ref([] as any[]);
const gpaTotal = ref(0);
const failCourses = ref([] as any[]);
const pageLoading = ref(false);
const loadError = ref('');
const updatedAt = ref('');
const collegeSortKey = ref('fail');
const historyVisible = ref(false);
const historyMetricId = ref('');
const hasData = computed(() => !!data.definitionVersion);
let dashboardRequestSeq = 0;
const collegeRows = computed(() => {
  const rows = [...(data.colleges || [])];
  const value = (row:any, key:string, fallback:number) =>
    row[key] == null ? fallback : Number(row[key]);
  if (collegeSortKey.value === 'change') return rows.sort((a,b) => value(b,'currentFailChangePp',-999)-value(a,'currentFailChangePp',-999));
  if (collegeSortKey.value === 'gpa') return rows.sort((a,b) => value(a,'avgGpa',999)-value(b,'avgGpa',999));
  if (collegeSortKey.value === 'alert') return rows.sort((a,b) => value(b,'alertRateValue',-1)-value(a,'alertRateValue',-1));
  if (collegeSortKey.value === 'coverage') return rows.sort((a,b) => value(a,'resultCoverageRate',999)-value(b,'resultCoverageRate',999));
  return rows.sort((a,b) => value(b,'currentFailRateValue',-1)-value(a,'currentFailRateValue',-1));
});

// 课程通过率三分层按所选学期和当前授权学生范围计算。
const passRateKpis = computed(() => {
  const c = data.coursePassRates;
  const pctText = (v: any) => (v == null ? '—' : `${v}%`);
  const na = '当前范围暂无可计算数据';
  const fmtWan = (n: any) => (n == null ? '' : `${Number(n).toLocaleString()} 人次`);
  return [
    { metricId: 'first_pass_rate', label: '首次通过率', value: pctText(c?.firstPassRate), tone: 'primary' as const,
      sub: c ? `首次修读 ${fmtWan(c.attempts?.first)}` : na,
      hint: '所选学期、当前授权范围内，首次修读（含缓考）通过人次数÷首次修读人次数' },
    { metricId: 'makeup_pass_rate', label: '补考通过率', value: pctText(c?.makeupPassRate), tone: 'amber' as const,
      sub: c ? `补考 ${fmtWan(c.attempts?.makeup)}` : na,
      hint: '所选学期、当前授权范围内，补考通过人次数÷补考人次数' },
    { metricId: 'retake_pass_rate', label: '重修通过率', value: pctText(c?.retakePassRate), tone: 'teal' as const,
      sub: c ? `重修 ${fmtWan(c.attempts?.retake)}` : na,
      hint: '所选学期、当前授权范围内，重修通过人次数÷重修人次数' },
    { metricId: 'public_required_first_pass_rate', label: '公共必修首次通过率', value: pctText(c?.publicRequiredFirstPassRate), tone: 'danger' as const,
      sub: c ? '公共必修课组 · 重点关注' : na,
      hint: '所选学期、当前授权范围内公共必修课的首次通过率；公共必修通常影响面较大' },
  ];
});
const hasCoursePassData = computed(() => {
  const attempts = data.coursePassRates?.attempts;
  return Number(attempts?.first || 0) + Number(attempts?.makeup || 0)
    + Number(attempts?.retake || 0) > 0;
});

// GPA 5 档色：不及格→优秀（玫红/琥珀/靛/靛蓝/青绿）
const GPA_COLORS = ['#E11D48', '#D97706', '#6366F1', '#4F46E5', '#0D9488'];

async function loadData() {
  const requestId = ++dashboardRequestSeq;
  pageLoading.value = true;
  loadError.value = '';
  const qs = fSemester.value ? `?semester=${fSemester.value}` : '';
  try {
    const detailType = authStore.user?.permissionContext?.detailScope?.type;
    const comparePromise = detailType === 'college' && canCompareColleges.value
      ? http.get(`/admin/meta/college-comparison${qs}`).catch(() => null)
      : Promise.resolve(null);
    const [d, compare] = await Promise.all([
      http.get(`/admin/dashboard${qs}`),
      comparePromise,
    ]);
    if (requestId !== dashboardRequestSeq || !d) return;
    Object.assign(data, d);
    if (compare) {
      Object.assign(comparison, compare || {});
    } else {
      comparison.items = [];
    }
    failCourses.value = d.failCourses || [];
    if (gpaCollege.value !== 'all' && !data.gpaDistByCollege?.[gpaCollege.value]) gpaCollege.value = 'all';
    loadGpa();
    updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
  } catch (error:any) {
    if (requestId !== dashboardRequestSeq) return;
    loadError.value = error?.message || '数据加载失败，请稍后重试';
  } finally {
    if (requestId === dashboardRequestSeq) pageLoading.value = false;
  }
}

onMounted(async () => {
  const meta = await getFilterMeta();
  semesters.value = meta.semesters.slice().reverse();
  const requested = String(route.query.semester || '');
  fSemester.value = semesters.value.some(item => item.value === requested)
    ? requested : (meta.current || semesters.value[0]?.value || '');
  loadData();
});
function onSemesterChange() {
  router.replace({ path:'/admin/dashboard', query:fSemester.value ? { semester:fSemester.value } : {} });
  loadData();
}

function loadGpa() {
  const dist = gpaCollege.value === 'all'
    ? (data.gpaDist || [])
    : (data.gpaDistByCollege?.[gpaCollege.value] || []);
  gpaDisplay.value = dist;
  gpaTotal.value = dist.reduce((s:number,g:any)=>s+(g.count||0), 0);
}

const gpaOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c} 人（{d}%）' },
  series: [{
    type: 'pie', radius: ['56%', '82%'], center: ['50%', '50%'],
    avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 },
    label: { show: false },
    emphasis: { scale: true, scaleSize: 4 },
    data: gpaDisplay.value.map((g: any, i: number) => ({
      name: g.label, value: g.count ?? 0,
      itemStyle: { color: GPA_COLORS[i % GPA_COLORS.length] },
    })),
  }],
}));

function formatNumber(value:any) {
  return value == null ? '—' : Number(value).toLocaleString();
}
function displayMetric(item:any) {
  return item.value == null ? '—' : `${item.value}${item.unit || ''}`;
}
function changeClass(item:any) {
  if (!item.change) return 'is-neutral';
  const improved = item.betterDirection === 'up' ? item.change > 0 : item.change < 0;
  return improved ? 'is-good' : 'is-bad';
}
function changeText(item:any) {
  if (item.change == null) return '暂无上期可比数据';
  if (item.change === 0) return `较 ${data.period?.previousSemester || '上期'} 持平`;
  const direction = item.change > 0 ? '上升' : '下降';
  return `较 ${data.period?.previousSemester || '上期'} ${direction} ${Math.abs(item.change)}${item.changeUnit || ''}`;
}
function deltaClass(value:any, positiveIsGood=true) {
  if (value == null || Number(value) === 0) return 'delta is-neutral';
  const good = positiveIsGood ? Number(value) > 0 : Number(value) < 0;
  return `delta ${good ? 'is-good' : 'is-bad'}`;
}
function ppText(value:any, base:string) {
  if (value == null) return '—';
  if (Number(value) === 0) return `与${base}持平`;
  return `${Number(value) > 0 ? '高于' : '低于'}${base} ${Math.abs(Number(value))}pp`;
}
function ppChangeText(value:any) {
  if (value == null) return '暂无上期';
  if (Number(value) === 0) return '较上期持平';
  return `较上期${Number(value) > 0 ? '上升' : '下降'} ${Math.abs(Number(value))}pp`;
}
function scrollToSection(id:string) {
  document.getElementById(id)?.scrollIntoView({ behavior:'smooth', block:'start' });
}
function openHistory(metricId:string) {
  historyMetricId.value = metricId;
  historyVisible.value = true;
}
function openSummaryHistory(item:any) {
  const metricId = SUMMARY_HISTORY_METRIC_IDS[item.id];
  if (metricId) openHistory(metricId);
}
function openFocus(focus:any) {
  if (focus.targetType === 'college') goCollege({ id:focus.targetId });
  else if (focus.targetType === 'course') goCourse({ id:focus.targetId });
}
function goCollege(row: any) { router.push({ path:'/admin/college/' + row.id, query:{ semester:fSemester.value } }); }
function goComparisonCollege(row:any) {
  if (!row.canDrillDown) return;
  router.push({ path:'/admin/college/' + row.collegeId, query:{ semester:fSemester.value } });
}
function goCourse(row: any) { router.push({ path:'/admin/course/' + row.id, query:{ semester:fSemester.value } }); }
function goStudents() { router.push({ path:'/admin/students/list', query:{ semester:fSemester.value,returnTo:'/admin/dashboard',returnLabel:'返回教学数据总览' } }); }
</script>

<style scoped>
.dashboard-page { min-width: 0; }
.page-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.page-head .sa-page-title { margin-bottom: 0; }
.semester-select { width: 170px; flex: 0 0 auto; }
.loading-alert { margin: 14px 0; }
.updating-bar {
  position: sticky;
  top: 0;
  z-index: 5;
  margin: 10px 0;
  padding: 7px 12px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: rgba(239,246,255,.96);
  color: #1d4ed8;
  font-size: 12px;
}
.scope-background {
  display: grid;
  grid-template-columns: 1.25fr repeat(4, minmax(110px, 1fr));
  gap: 1px;
  overflow: hidden;
  margin: 14px 0 18px;
  border: 1px solid var(--sa-border);
  border-radius: 10px;
  background: var(--sa-border);
}
.scope-background > div {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  padding: 10px 13px;
  background: #fff;
}
.scope-background span { color: var(--sa-muted); font-size: 12px; }
.scope-background b { color: var(--sa-text); font-size: 13px; }
.dashboard-section { margin-bottom: 18px; }
.dashboard-card { margin-bottom: 18px; scroll-margin-top: 16px; }
.section-heading { display:flex; align-items:flex-end; justify-content:space-between; margin-bottom:10px; }
.section-heading.compact { margin-bottom: 8px; }
.section-heading h3 { margin:0; color:var(--sa-text); font-size:16px; }
.section-heading p { margin:3px 0 0; color:var(--sa-muted); font-size:12px; }
.management-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.management-card {
  min-width:0;
  padding:15px;
  border:1px solid var(--sa-border);
  border-radius:12px;
  background:#fff;
  text-align:left;
  transition: border-color .16s, box-shadow .16s, transform .16s;
  cursor:pointer;
}
.management-card:hover { border-color:#a5b4fc; box-shadow:0 8px 20px rgba(79,70,229,.08); transform:translateY(-1px); }
.management-label { color:var(--sa-muted); font-size:12px; }
.management-value { margin:7px 0 3px; color:var(--sa-text); font-family:var(--sa-font-head); font-size:28px; font-weight:750; }
.management-change { min-height:18px; font-size:12px; font-weight:600; }
.management-change.is-good,.delta.is-good { color:#047857; }
.management-change.is-bad,.delta.is-bad { color:#dc2626; }
.management-change.is-neutral,.delta.is-neutral { color:#64748b; }
.management-use { min-height:50px; margin-top:8px; color:#64748b; font-size:12px; line-height:1.55; }
.management-action { margin-top:8px; color:var(--sa-primary); font-size:12px; font-weight:600; }
.focus-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.focus-item {
  display:flex;
  align-items:center;
  gap:10px;
  min-width:0;
  padding:12px 14px;
  border:1px solid #fed7aa;
  border-radius:10px;
  background:#fffaf5;
  text-align:left;
  cursor:pointer;
}
.focus-item.is-danger { border-color:#fecdd3; background:#fff7f8; }
.focus-dot { width:8px; height:8px; flex:0 0 auto; border-radius:50%; background:#d97706; }
.focus-item.is-danger .focus-dot { background:#e11d48; }
.focus-copy { display:flex; flex:1; min-width:0; flex-direction:column; gap:3px; }
.focus-copy b { overflow:hidden; color:var(--sa-text); font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
.focus-copy small { overflow:hidden; color:var(--sa-muted); font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
.focus-action { flex:0 0 auto; color:var(--sa-primary); font-size:12px; }
.course-result-strip { padding:12px 14px; border:1px solid var(--sa-border); border-radius:10px; background:#f8fafc; }
.result-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.result-metric { display:grid; grid-template-columns:1fr auto; gap:2px 8px; padding:8px 10px; border:1px solid transparent; border-radius:8px; background:#fff; text-align:left; cursor:pointer; }
.result-metric:hover,.result-metric:focus-visible { border-color:var(--sa-primary); outline:none; }
.result-metric span { color:var(--sa-muted); font-size:12px; }
.result-metric b { grid-row:span 2; align-self:center; color:var(--sa-text); font-size:18px; }
.result-metric small { color:var(--sa-faint); font-size:11px; }
.result-metric i { color:var(--sa-primary); font-size:11px; font-style:normal; }
.risk-number { color:#b91c1c; }
.delta { font-size:12px; }
.reason-text { color:#475569; }
.card-actions { margin-top:10px; text-align:right; }
.auxiliary-card { height:100%; }
.evidence-collapse { margin: 4px 0 20px; }
.evidence-collapse p { margin:5px 0; color:var(--sa-muted); font-size:12px; line-height:1.6; }
:deep(.college-row-clickable) { cursor: pointer; }
:deep(.college-row-clickable:hover) { background: #eef2ff !important; }
.college-link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.college-link:hover { text-decoration: underline; }

/* GPA 卡片：允许下拉弹窗透出 */
.gpa-donut-wrap { position: relative; }
.gpa-donut-center {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; pointer-events: none;
}
.gpa-donut-total { font-family: var(--sa-font-head); font-size: 26px; font-weight: 700; color: var(--sa-text); line-height: 1; }
.gpa-donut-cap { font-size: 11px; color: var(--sa-muted); margin-top: 4px; }

.gpa-legend { margin-top: 8px; }
.gpa-legend-row { display: flex; align-items: center; gap: 8px; padding: 4px 2px; font-size: 12px; }
.gpa-legend-row .dot { width: 9px; height: 9px; border-radius: 3px; flex-shrink: 0; }
.gpa-legend-label { color: var(--sa-text); flex: 1; }
.gpa-legend-pct { color: var(--sa-muted); }

/* 修复选中标签与下拉对齐 */
.sa-card-title :deep(.el-select) {
  vertical-align: middle;
}

/* 下拉面板：文本超长时省略 */
:deep(.el-select-dropdown__item) {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 1280px) {
  .management-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .scope-background { grid-template-columns:repeat(3,minmax(0,1fr)); }
  .result-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
</style>

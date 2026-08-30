<template><div>
  <el-breadcrumb separator="/" class="crumb"><el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item><el-breadcrumb-item>课程质量与教学运行</el-breadcrumb-item></el-breadcrumb>
  <h2 class="sa-page-title">课程质量与教学运行</h2><p class="sa-page-sub">从跨学期课程结果发现需要进一步核查的课程，再按需查看学期变化。</p>
  <el-alert v-if="loadError" type="error" :closable="false" show-icon class="load-alert"
    title="课程结果加载失败" :description="loadError">
    <template #default><el-button link type="primary" @click="retryLoad">重新加载</el-button></template>
  </el-alert>
  <div class="filters">
    <el-select v-model="draftFrom" clearable placeholder="起始学期"><el-option v-for="s in semesterOptions" :key="s" :label="s" :value="s"/></el-select><span>至</span>
    <el-select v-model="draftTo" clearable placeholder="结束学期"><el-option v-for="s in semesterOptions" :key="s" :label="s" :value="s"/></el-select>
    <el-select v-model="draftGroup" clearable placeholder="全部课程类别" style="width:150px"><el-option v-for="g in COURSE_GROUPS" :key="g" :label="g" :value="g"/></el-select>
    <el-button type="primary" :loading="loading" @click="apply">查询</el-button>
    <el-button :disabled="loading" @click="reset">重置</el-button>
  </div>
  <el-skeleton v-if="!loadError" :loading="initialLoading" animated :rows="4"><div class="kpis"><div v-for="x in kpis" :key="x.label" class="kpi"><span>{{x.label}} <el-tooltip :content="x.help"><i>?</i></el-tooltip></span><b>{{x.value}}</b></div></div></el-skeleton>

  <section v-if="!loadError" class="sa-card">
    <div class="sa-card-title">公共必修课重点关注</div>
    <el-empty v-if="!pubCourses.length" description="当前筛选范围内没有满足样本要求的公共必修课" :image-size="70"/>
    <DataTable v-else :columns="publicCols" :data="pubCourses" storage-key="reports:course-quality-public"
      stripe :row-class-name="pubRowClass" class="clickable" :max-business-columns="5">
      <template #col-first_pass_rate="{row}"><b class="tnum" :style="{color:belowAvg(row)?'#E11D48':'#0D9488'}">{{pct(row.first_pass_rate)}}</b><el-tag v-if="belowAvg(row)" type="danger" size="small" effect="plain" style="margin-left:6px">低于均值</el-tag></template>
      <template #col-makeup_pass_rate="{row}">{{pct(row.makeup_pass_rate)}}</template>
      <template #col-retake_pass_rate="{row}">{{pct(row.retake_pass_rate)}}</template>
      <template #col-attention_reasons="{row}"><el-tag v-for="r in row.attention_reasons" :key="r" :type="tagType(r)" size="small" class="reason">{{reasonText(r,row)}}</el-tag></template>
      <template #col-actions="{row}"><el-button link type="primary" :loading="detailLoading&&selected===row.course_id" @click.stop="selectCourse(row)">{{selected===row.course_id?'正在查看':'查看学期变化'}}</el-button></template>
    </DataTable>
  </section>

  <section v-if="!loadError" class="sa-card" v-loading="loading"><div class="sa-card-title">需要进一步核查的课程</div><DataTable :columns="courseCols" :data="data.courses" storage-key="reports:course-quality" stripe :row-class-name="rowClass" v-model:page-size="pageSize" :default-page-size="50" config-version="2"><template #col-course_group="{row}"><el-tag size="small" effect="plain" :type="groupTagType(row.course_group)">{{row.course_group||'—'}}</el-tag></template><template #col-first_pass_rate="{row}"><b class="tnum" :style="{color:row.first_pass_rate==null?'#94a3b8':row.first_pass_rate>=85?'#0D9488':row.first_pass_rate<70?'#E11D48':'#334155'}">{{pct(row.first_pass_rate)}}</b></template><template #col-makeup_pass_rate="{row}">{{pct(row.makeup_pass_rate)}}</template><template #col-retake_pass_rate="{row}">{{pct(row.retake_pass_rate)}}</template><template #col-fail_rate="{row}">{{pct(row.fail_rate)}}</template><template #col-volatility="{row}">{{row.volatility}} 个百分点</template><template #col-attention_reasons="{row}"><el-tag v-for="r in row.attention_reasons" :key="r" :type="tagType(r)" size="small" class="reason">{{reasonText(r,row)}}</el-tag></template><template #col-actions="{row}"><el-button link type="primary" :loading="detailLoading&&selected===row.course_id" @click="selectCourse(row)">{{selected===row.course_id?'正在查看':'查看学期变化'}}</el-button></template></DataTable><el-pagination v-if="data.total" v-model:current-page="page" :page-size="pageSize" :total="data.total" layout="total, prev, pager, next" @current-change="load"/></section>
  <el-drawer v-model="detailDrawer" :title="`${detail.course_name || '课程'}｜学期结果信息`" size="920px">
    <div v-loading="detailLoading" class="detail">
      <h4>学期变化</h4>
      <el-table :data="detail.trends" size="small">
        <el-table-column prop="semester_id" label="学期"/><el-table-column prop="students" label="学生数"/>
        <el-table-column prop="avg_score" label="平均分"/>
        <el-table-column label="首次通过率"><template #default="{row}">{{pct(row.first_pass_rate)}}</template></el-table-column>
        <el-table-column label="补考通过率"><template #default="{row}">{{pct(row.makeup_pass_rate)}}</template></el-table-column>
        <el-table-column label="重修通过率"><template #default="{row}">{{pct(row.retake_pass_rate)}}</template></el-table-column>
        <el-table-column prop="retake_attempts" label="重修记录"/>
      </el-table>
    </div>
  </el-drawer>
</div></template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { http } from '@/utils/http';
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue';

const COURSE_GROUPS = ['公共必修', '专业必修', '选修', '实践', '其他'];
const KPI_TOOLTIPS = {
  sample: '至少有一个学期达到30条有效成绩记录的去重课程数；有效记录是指已发布且未作废且 是否通过 非空的记录；',
  firstPassRate: "首次修读（含缓考）通过人次数÷首次修读人次数，分母为0时 输出 '-' ",
  persistentHigh: '同一门课程至少有2个学期及以上且每学期首次未通过率均高于15%',
  volatile: '同一门课程至少有2个学期及以上，最高与最低首次未通过率相差高于15个百分点',
  retakeAttempts: '筛选条件范围内重修成绩记录数量',
} as const;

const loading = ref(false), initialLoading = ref(true), detailLoading = ref(false), detailDrawer = ref(false);
const loadError = ref('');
const draftFrom = ref(''), draftTo = ref(''), draftGroup = ref(''), from = ref(''), to = ref(''), group = ref('');
const page = ref(1), pageSize = ref(50), selected = ref(''), requestId = ref(0);
// M6：每页行数由 DataTable 偏好驱动，变化时回到第一页重新加载
watch(pageSize, () => { page.value = 1; load(); });

// 需要进一步核查的课程表列定义（M6 DataTable）
const courseCols: DataTableColumn[] = [
  { key: 'course_name', label: '课程', minWidth: 170, required: true, region: 'identity', fixed: 'left' },
  { key: 'course_group', label: '课程类别', width: 96 },
  { key: 'observed_terms', label: '达到样本要求的学期数', width: 145 },
  { key: 'student_term_count', label: '修读学生人次', width: 105 },
  { key: 'failures', label: '未通过记录数', width: 105 },
  { key: 'first_pass_rate', label: '首次通过率', width: 100, required: true },
  { key: 'makeup_pass_rate', label: '补考通过率', width: 100 },
  { key: 'retake_pass_rate', label: '重修通过率', width: 100 },
  { key: 'fail_rate', label: '首次未通过率', width: 105 },
  { key: 'volatility', label: '首次通过率最大差值', width: 150 },
  { key: 'retake_attempts', label: '重修记录人次', width: 105 },
  { key: 'attention_reasons', label: '关注原因', minWidth: 250, required: true },
  { key: 'actions', label: '操作', width: 125, fixed: 'right', required: true, region: 'action' },
];
const publicCols: DataTableColumn[] = [
  {key:'course_name',label:'课程',minWidth:180,required:true,region:'identity',fixed:'left'},
  {key:'student_term_count',label:'修读学生人次',width:105,align:'right',required:true},
  {key:'first_pass_rate',label:'首次通过率',width:115,required:true},
  {key:'makeup_pass_rate',label:'补考通过率',width:100},
  {key:'retake_pass_rate',label:'重修通过率',width:100},
  {key:'attention_reasons',label:'关注原因',minWidth:220,required:true},
  {key:'actions',label:'操作',width:125,required:true,region:'action',fixed:'right'},
];
const data = reactive<any>({ summary: {}, courses: [], semesters: [], total: 0 });
const detail = reactive<any>({ course_name: '', course_group: '', trends: [] });
const pubCourses = ref<any[]>([]), pubSummary = reactive<any>({});
const pubAvg = computed(() => pubSummary.overall_first_pass_rate ?? null);
const semesterOptions = computed(() =>
  [...new Set<string>(data.semesters || [])].sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
);

const kpis = computed(() => [
  { label: '达到统计样本要求的课程', value: (data.summary.observed_courses || 0) + ' 门', help: KPI_TOOLTIPS.sample },
  { label: '首次通过率', value: firstPassPct(data.summary.overall_first_pass_rate), help: KPI_TOOLTIPS.firstPassRate },
  { label: '连续高未通过课程', value: (data.summary.persistent_high_courses || 0) + ' 门', help: KPI_TOOLTIPS.persistentHigh },
  { label: '学期间变化较大课程', value: (data.summary.volatile_courses || 0) + ' 门', help: KPI_TOOLTIPS.volatile },
  { label: '累计重修记录', value: (data.summary.retake_attempts || 0) + ' 人次', help: KPI_TOOLTIPS.retakeAttempts },
]);

function pct(v: any) { return v == null ? '—' : v + '%'; }
function firstPassPct(v: any) { return v == null ? '-' : v + '%'; }
function tagType(r: string) { return r === 'persistent_high' ? 'danger' : r === 'wide_impact' ? 'warning' : 'info'; }
function groupTagType(g: string) { return g === '公共必修' ? 'warning' : g === '专业必修' ? 'primary' : g === '实践' ? 'success' : 'info'; }
function reasonText(r: string, row: any) { return r === 'persistent_high' ? `连续${row.observed_terms}学期>15%` : r === 'volatile' ? `学期间相差${row.volatility}个百分点` : r === 'wide_impact' ? `累计未通过${row.failures}人次` : `重修${row.retake_attempts}人次`; }
function rowClass({ row }: any) { return row.course_id === selected.value ? 'selected-row' : ''; }
function belowAvg(row: any) { return pubAvg.value != null && row.first_pass_rate != null && row.first_pass_rate < pubAvg.value; }
function pubRowClass({ row }: any) { return (belowAvg(row) ? 'warn-row ' : '') + (row.course_id === selected.value ? 'selected-row' : ''); }
function apply() { from.value = draftFrom.value; to.value = draftTo.value; group.value = draftGroup.value; page.value = 1; selected.value = ''; load(); }
function reset() { draftFrom.value = ''; draftTo.value = ''; draftGroup.value = ''; from.value = ''; to.value = ''; group.value = ''; page.value = 1; selected.value = ''; load(); }

async function load() {
  const id = ++requestId.value;
  loading.value = true;
  loadError.value = '';
  try {
    const q = new URLSearchParams({ limit: String(pageSize.value), offset: String((page.value - 1) * pageSize.value), min_sample: '30' });
    if (from.value) q.set('semester_from', from.value);
    if (to.value) q.set('semester_to', to.value);
    if (group.value) q.set('course_group', group.value);
    const r = await http.get<any>('/v2/topics/course-quality?' + q);
    if (id !== requestId.value) return;
    Object.assign(data, r);
    Object.assign(pubSummary, r.publicRequiredSummary || {});
    pubCourses.value = r.publicRequiredTop || [];
  } catch (error:any) {
    if (id === requestId.value) {
      Object.assign(data, { summary: {}, courses: [], semesters: [], total: 0 });
      loadError.value = error?.message || '课程结果数据加载失败，请稍后重试。';
    }
  } finally {
    if (id === requestId.value) { loading.value = false; initialLoading.value = false; }
  }
}

function retryLoad() {
  load();
}

async function selectCourse(row: any) {
  selected.value = row.course_id;
  detailDrawer.value = true;
  detailLoading.value = true;
  try {
    const q = new URLSearchParams();
    if (from.value) q.set('semester_from', from.value);
    if (to.value) q.set('semester_to', to.value);
    const r = await http.get<any>(`/v2/topics/course-quality/${encodeURIComponent(row.course_id)}/detail?${q}`);
    Object.assign(detail, r);
  } finally { detailLoading.value = false; }
}

onMounted(load);
</script>
<style scoped>
.crumb{margin-bottom:8px}
.load-alert{margin-top:12px}
.filters{display:flex;gap:10px;align-items:center;margin:14px 0}
.filters .el-select{width:165px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}
.kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:15px}
.kpi span{display:block;color:#64748b}
.kpi b{display:block;font-size:24px;margin:6px 0}
.kpi i{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:#e2e8f0;font-style:normal}
.sa-card{margin-bottom:14px}
.reason{margin:2px}
.detail h4{margin:4px 0 10px}
.el-pagination{justify-content:flex-end;margin-top:12px}
.clickable :deep(tbody tr){cursor:pointer}
:deep(.selected-row td){background:#eef2ff!important}
:deep(.warn-row td){background:#fef2f2!important}
:deep(.warn-row.selected-row td){background:#fde8ef!important}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}}
</style>

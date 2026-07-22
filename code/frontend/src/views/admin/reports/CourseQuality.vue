<template><div>
  <el-breadcrumb separator="/" class="crumb"><el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item><el-breadcrumb-item>课程质量与教学运行</el-breadcrumb-item></el-breadcrumb>
  <h2 class="sa-page-title">课程质量与教学运行</h2><p class="sa-page-sub">从跨学期课程结果发现需要进一步核查的课程，再按需查看学期变化和已接入开课资源。</p>
  <el-alert type="info" :closable="false" show-icon title="课程结果不等于教学归因" :description="definition.boundary"/>
  <div class="filters">
    <el-select v-model="draftFrom" clearable placeholder="起始学期"><el-option v-for="s in data.semesters" :key="s" :label="s" :value="s"/></el-select><span>至</span>
    <el-select v-model="draftTo" clearable placeholder="结束学期"><el-option v-for="s in data.semesters" :key="s" :label="s" :value="s"/></el-select>
    <el-select v-model="draftGroup" clearable placeholder="全部课程类别" style="width:150px"><el-option v-for="g in COURSE_GROUPS" :key="g" :label="g" :value="g"/></el-select>
    <el-button type="primary" :loading="loading" @click="apply">应用筛选</el-button><span class="hint">趋势和开课资源仅在选择课程后加载</span>
  </div>
  <el-skeleton :loading="initialLoading" animated :rows="4"><div class="kpis"><div v-for="x in kpis" :key="x.label" class="kpi"><span>{{x.label}} <el-tooltip :content="x.help"><i>?</i></el-tooltip></span><b>{{x.value}}</b><small>{{x.note}}</small></div></div></el-skeleton>

  <section class="sa-card" v-loading="pubLoading">
    <div class="sa-card-title">公共必修课重点关注
      <span class="extra">公共必修影响面覆盖全校学生，按首次通过率升序排列<template v-if="pubAvg!=null">，低于公共必修整体首次通过率（{{pubAvg}}%）的课程高亮警示</template></span>
    </div>
    <el-empty v-if="!pubCourses.length" description="当前筛选范围内没有满足样本要求的公共必修课" :image-size="70"/>
    <el-table v-else :data="pubCourses" stripe :row-class-name="pubRowClass" class="clickable">
      <el-table-column prop="course_name" label="课程" min-width="180"/>
      <el-table-column prop="student_term_count" label="修读学生人次" width="105"/>
      <el-table-column label="首次通过率" width="115"><template #default="{row}"><b class="tnum" :style="{color:belowAvg(row)?'#E11D48':'#0D9488'}">{{pct(row.first_pass_rate)}}</b><el-tag v-if="belowAvg(row)" type="danger" size="small" effect="plain" style="margin-left:6px">低于均值</el-tag></template></el-table-column>
      <el-table-column label="补考通过率" width="100"><template #default="{row}">{{pct(row.makeup_pass_rate)}}</template></el-table-column>
      <el-table-column label="重修通过率" width="100"><template #default="{row}">{{pct(row.retake_pass_rate)}}</template></el-table-column>
      <el-table-column label="关注原因" min-width="220"><template #default="{row}"><el-tag v-for="r in row.attention_reasons" :key="r" :type="tagType(r)" size="small" class="reason">{{reasonText(r,row)}}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="125" fixed="right"><template #default="{row}"><el-button link type="primary" :loading="detailLoading&&selected===row.course_id" @click.stop="selectCourse(row)">{{selected===row.course_id?'正在查看':'查看学期变化'}}</el-button></template></el-table-column>
    </el-table>
  </section>

  <section class="sa-card" v-loading="loading"><div class="sa-card-title">需要进一步核查的课程 <span class="extra">关注原因可同时满足多项，不再强制归入单一类型</span></div><DataTable :columns="courseCols" :data="data.courses" storage-key="reports:course-quality" stripe :row-class-name="rowClass" v-model:page-size="pageSize"><template #col-course_group="{row}"><el-tag size="small" effect="plain" :type="groupTagType(row.course_group)">{{row.course_group||'—'}}</el-tag></template><template #col-first_pass_rate="{row}"><b class="tnum" :style="{color:row.first_pass_rate==null?'#94a3b8':row.first_pass_rate>=85?'#0D9488':row.first_pass_rate<70?'#E11D48':'#334155'}">{{pct(row.first_pass_rate)}}</b></template><template #col-makeup_pass_rate="{row}">{{pct(row.makeup_pass_rate)}}</template><template #col-retake_pass_rate="{row}">{{pct(row.retake_pass_rate)}}</template><template #col-fail_rate="{row}">{{pct(row.fail_rate)}}</template><template #col-volatility="{row}">{{row.volatility}} 个百分点</template><template #col-attention_reasons="{row}"><el-tag v-for="r in row.attention_reasons" :key="r" :type="tagType(r)" size="small" class="reason">{{reasonText(r,row)}}</el-tag></template><template #col-actions="{row}"><el-button link type="primary" :loading="detailLoading&&selected===row.course_id" @click="selectCourse(row)">{{selected===row.course_id?'正在查看':'查看学期变化'}}</el-button></template></DataTable><el-pagination v-if="data.total" v-model:current-page="page" :page-size="pageSize" :total="data.total" layout="total, prev, pager, next" @current-change="load"/></section>
  <section ref="detailSection" class="sa-card detail" v-loading="detailLoading"><template v-if="selected"><div class="sa-card-title">{{detail.course_name}}<el-tag v-if="detail.course_group" size="small" effect="plain" :type="groupTagType(detail.course_group)" style="margin-left:8px;vertical-align:2px">{{detail.course_group}}</el-tag>｜学期结果与开课资源</div><div class="grid"><div><h4>学期变化</h4><el-table :data="detail.trends" size="small"><el-table-column prop="semester_id" label="学期"/><el-table-column prop="students" label="学生数"/><el-table-column prop="avg_score" label="平均分"/><el-table-column label="首次通过率"><template #default="{row}">{{pct(row.first_pass_rate)}}</template></el-table-column><el-table-column label="补考通过率"><template #default="{row}">{{pct(row.makeup_pass_rate)}}</template></el-table-column><el-table-column label="重修通过率"><template #default="{row}">{{pct(row.retake_pass_rate)}}</template></el-table-column><el-table-column prop="retake_attempts" label="重修记录"/></el-table></div><div><h4>该课程已接入开课资源</h4><el-empty v-if="!detail.offerings?.length" description="当前接入教学任务中未找到该课程" :image-size="70"/><el-table v-else :data="detail.offerings" size="small"><el-table-column prop="semester_id" label="学期"/><el-table-column prop="lesson_count" label="教学班"/><el-table-column prop="teacher_count" label="教师"/><el-table-column prop="enrolled" label="选课人数"/><el-table-column prop="avg_class_size" label="平均班额"/></el-table><p class="hint">{{detail.offering_boundary}}</p></div></div></template><el-empty v-else description="请在上方选择一门课程查看学期变化与开课资源" :image-size="80"/></section>
  <section class="sa-card definition"><div class="sa-card-title">指标口径与管理含义</div><p><b>达到统计样本要求的课程：</b>{{definition.sample}}</p><p><b>通过率三分层：</b>首次通过率——{{definition.first_pass_rate}} 补考通过率——{{definition.makeup_pass_rate}} 重修通过率——{{definition.retake_pass_rate}} 分母为 0 时不输出，页面显示为“—”。</p><p><b>课程类别：</b>{{definition.course_group}}</p><p><b>首次未通过率：</b>{{definition.fail_rate}}</p><p><b>成绩记录未通过率：</b>{{definition.overall}}</p><p><b>连续高未通过：</b>{{definition.persistent_high}}</p><p><b>学期间变化较大：</b>{{definition.volatile}}</p><p><b>影响面较广：</b>{{definition.wide_impact}} <b>重修记录较多：</b>{{definition.retake_pressure}}</p></section>
</div></template>
<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { http } from '@/utils/http';
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue';

const COURSE_GROUPS = ['公共必修', '专业必修', '选修', '实践', '其他'];

const loading = ref(false), initialLoading = ref(true), detailLoading = ref(false), pubLoading = ref(false);
const draftFrom = ref(''), draftTo = ref(''), draftGroup = ref(''), from = ref(''), to = ref(''), group = ref('');
const page = ref(1), pageSize = ref(50), selected = ref(''), detailSection = ref<HTMLElement>(), requestId = ref(0), pubRequestId = ref(0);
// M6：每页行数由 DataTable 偏好驱动，变化时回到第一页重新加载
watch(pageSize, () => { page.value = 1; load(); });

// 需要进一步核查的课程表列定义（M6 DataTable）
const courseCols: DataTableColumn[] = [
  { key: 'course_name', label: '课程', minWidth: 170 },
  { key: 'course_group', label: '课程类别', width: 96 },
  { key: 'observed_terms', label: '达到样本要求的学期数', width: 145 },
  { key: 'student_term_count', label: '修读学生人次', width: 105 },
  { key: 'failures', label: '未通过记录数', width: 105 },
  { key: 'first_pass_rate', label: '首次通过率', width: 100 },
  { key: 'makeup_pass_rate', label: '补考通过率', width: 100 },
  { key: 'retake_pass_rate', label: '重修通过率', width: 100 },
  { key: 'fail_rate', label: '首次未通过率', width: 105 },
  { key: 'volatility', label: '最高与最低学期差值', width: 150 },
  { key: 'retake_attempts', label: '重修记录人次', width: 105 },
  { key: 'attention_reasons', label: '关注原因', minWidth: 250 },
  { key: 'actions', label: '操作', width: 125, fixed: 'right' },
];
const data = reactive<any>({ summary: {}, courses: [], semesters: [], total: 0 });
const detail = reactive<any>({ course_name: '', course_group: '', trends: [], offerings: [] });
const definition = reactive<any>({});
const pubCourses = ref<any[]>([]), pubSummary = reactive<any>({});
const pubAvg = computed(() => pubSummary.overall_first_pass_rate ?? null);

const kpis = computed(() => [
  { label: '达到统计样本要求的课程', value: (data.summary.observed_courses || 0) + ' 门', note: '至少一个学期满足样本量', help: definition.sample || '' },
  { label: '首次通过率', value: pct(data.summary.overall_first_pass_rate), note: '筛选范围内全部课程加权', help: definition.first_pass_rate || '' },
  { label: '连续高未通过课程', value: (data.summary.persistent_high_courses || 0) + ' 门', note: '每个可比学期均≥15%', help: definition.persistent_high || '' },
  { label: '学期间变化较大课程', value: (data.summary.volatile_courses || 0) + ' 门', note: '最大差值≥15个百分点', help: definition.volatile || '' },
  { label: '累计重修记录', value: (data.summary.retake_attempts || 0) + ' 人次', note: '同一学生多次会重复计数', help: '筛选范围内重修成绩记录数量，用于评估重修资源压力。' },
]);

function pct(v: any) { return v == null ? '—' : v + '%'; }
function tagType(r: string) { return r === 'persistent_high' ? 'danger' : r === 'wide_impact' ? 'warning' : 'info'; }
function groupTagType(g: string) { return g === '公共必修' ? 'warning' : g === '专业必修' ? 'primary' : g === '实践' ? 'success' : 'info'; }
function reasonText(r: string, row: any) { return r === 'persistent_high' ? `连续${row.observed_terms}学期≥15%` : r === 'volatile' ? `学期间相差${row.volatility}个百分点` : r === 'wide_impact' ? `累计未通过${row.failures}人次` : `重修${row.retake_attempts}人次`; }
function rowClass({ row }: any) { return row.course_id === selected.value ? 'selected-row' : ''; }
function belowAvg(row: any) { return pubAvg.value != null && row.first_pass_rate != null && row.first_pass_rate < pubAvg.value; }
function pubRowClass({ row }: any) { return (belowAvg(row) ? 'warn-row ' : '') + (row.course_id === selected.value ? 'selected-row' : ''); }
function apply() { from.value = draftFrom.value; to.value = draftTo.value; group.value = draftGroup.value; page.value = 1; selected.value = ''; load(); loadPublic(); }

async function load() {
  const id = ++requestId.value;
  loading.value = true;
  try {
    const q = new URLSearchParams({ limit: String(pageSize.value), offset: String((page.value - 1) * pageSize.value), min_sample: '30' });
    if (from.value) q.set('semester_from', from.value);
    if (to.value) q.set('semester_to', to.value);
    if (group.value) q.set('course_group', group.value);
    const r = await http.get<any>('/v2/topics/course-quality?' + q);
    if (id !== requestId.value) return;
    Object.assign(data, r);
    Object.assign(definition, r.definition);
  } finally {
    if (id === requestId.value) { loading.value = false; initialLoading.value = false; }
  }
}

async function loadPublic() {
  const id = ++pubRequestId.value;
  pubLoading.value = true;
  try {
    const q = new URLSearchParams({ limit: '200', offset: '0', min_sample: '30', course_group: '公共必修' });
    if (from.value) q.set('semester_from', from.value);
    if (to.value) q.set('semester_to', to.value);
    const r = await http.get<any>('/v2/topics/course-quality?' + q);
    if (id !== pubRequestId.value) return;
    Object.assign(pubSummary, r.summary || {});
    pubCourses.value = (r.courses || []).slice()
      .sort((a: any, b: any) => (a.first_pass_rate ?? 999) - (b.first_pass_rate ?? 999))
      .slice(0, 10);
  } finally {
    if (id === pubRequestId.value) pubLoading.value = false;
  }
}

async function selectCourse(row: any) {
  selected.value = row.course_id;
  detailLoading.value = true;
  try {
    const q = new URLSearchParams();
    if (from.value) q.set('semester_from', from.value);
    if (to.value) q.set('semester_to', to.value);
    const r = await http.get<any>(`/v2/topics/course-quality/${encodeURIComponent(row.course_id)}/detail?${q}`);
    Object.assign(detail, r);
    await nextTick();
    detailSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } finally { detailLoading.value = false; }
}

onMounted(() => { load(); loadPublic(); });
</script>
<style scoped>
.crumb{margin-bottom:8px}
.filters{display:flex;gap:10px;align-items:center;margin:14px 0}
.filters .el-select{width:165px}
.hint{font-size:12px;color:#94a3b8}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}
.kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:15px}
.kpi span,.kpi small{display:block;color:#64748b}
.kpi b{display:block;font-size:24px;margin:6px 0}
.kpi i{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:#e2e8f0;font-style:normal}
.sa-card{margin-bottom:14px}
.reason{margin:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.detail{scroll-margin-top:20px}
.detail h4{margin:4px 0 10px}
.definition p{font-size:13px;color:#475569;line-height:1.8}
.el-pagination{justify-content:flex-end;margin-top:12px}
.clickable :deep(tbody tr){cursor:pointer}
:deep(.selected-row td){background:#eef2ff!important}
:deep(.warn-row td){background:#fef2f2!important}
:deep(.warn-row.selected-row td){background:#fde8ef!important}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
</style>

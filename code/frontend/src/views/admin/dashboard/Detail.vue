<template>
  <div v-loading="pageLoading && !!data.name" element-loading-text="正在更新学院分析，当前结果暂时保留…" :aria-busy="pageLoading">
    <el-breadcrumb separator="›"><el-breadcrumb-item :to="{path:'/admin/dashboard',query:{semester:fSemester}}">教学数据总览</el-breadcrumb-item><el-breadcrumb-item>{{ data.name || '学院详情' }}</el-breadcrumb-item></el-breadcrumb>
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <h2 class="sa-page-title" style="margin-top:14px;margin-bottom:0">{{ data.name || '加载中…' }} · 学院详情</h2>
        <p class="sa-page-sub">统计学期：<b>{{ fSemester }}</b> · {{ data.scope?.restricted ? '当前角色授权范围' : '二级学院学业全景' }}</p>
      </div>
      <el-select v-model="fSemester" size="small" style="width:170px" placeholder="选择学期" @change="loadData">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
    </div>

    <el-alert v-if="loadError" type="error" :closable="false" show-icon style="margin:12px 0"
      title="学院数据加载失败" :description="loadError">
      <template #default><el-button size="small" @click="loadData">重新加载</el-button></template>
    </el-alert>
    <div v-if="pageLoading && !data.name" class="sa-card" style="margin:12px 0">
      <el-skeleton :rows="10" animated />
    </div>
    <template v-if="data.name">
    <el-alert v-if="data.evidence?.limitation" type="warning" :closable="false" show-icon style="margin:12px 0"
      title="证据与口径说明" :description="data.evidence.limitation" />

    <div class="sa-kpi-row">
      <KpiCard v-for="k in data.kpi" :key="k.id || k.label" :label="k.label" :value="k.value"
        :tone="kpiTone(k.label)" :hint="k.formula" :sub="k.detail"
        :interactive="historyMetricIds.includes(k.id)" action-text="查看历年学期变化"
        @drilldown="openHistory(k.id)" />
    </div>

    <!-- 各专业数据（全宽）-->
    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">本学院所有专业偏离与核查 <span class="extra">优先项置顶；点击专业查看年级与课程证据</span></div>
      <DataTable :columns="majorCols" :data="data.majors" storage-key="dashboard:college-majors"
        :max-business-columns="7" :config-version="3" size="small"
        @row-click="goMajor" row-class-name="row-clickable">
        <template #col-name="{row}"><span class="link">{{ row.name }}</span></template>
        <template #col-priorityRank="{row}"><span class="rank" :class="{hot:row.needsPriorityReview}">{{ row.priorityRank }}</span></template>
        <template #col-gpa="{row}"><b v-if="row.gpa != null" class="tnum">{{ row.gpa }}</b><span v-else class="sa-faint">—</span></template>
        <template #col-creditDone="{row}">{{ row.creditDone == null ? '—' : `${row.creditDone}%` }}</template>
        <template #col-resultCoverageRate="{row}">{{ row.resultCoverageRate == null ? '—' : `${row.resultCoverageRate}%` }}</template>
        <template #col-currentFailRate="{row}"><span class="tnum" :style="{color:parseFloat(row.currentFailRate||'0')>10?'#DC2626':'#6B7280'}">{{ row.currentFailRate || '—' }}</span></template>
        <template #col-currentFailVsCollegePp="{row}">
          <span v-if="row.currentFailVsCollegePp != null" class="tnum" :class="row.currentFailVsCollegePp>=3?'risk-text':'muted-text'">
            {{ row.currentFailVsCollegePp > 0 ? '+' : '' }}{{ row.currentFailVsCollegePp }}pp
          </span><span v-else class="sa-faint">—</span>
        </template>
        <template #col-priorityReason="{row}">
          <el-tag v-if="row.needsPriorityReview" type="danger" effect="plain" size="small">{{ row.priorityReason }}</el-tag>
          <span v-else class="sa-faint">{{ row.priorityReason }}</span>
        </template>
        <template #col-drill><span style="color:var(--sa-faint)">›</span></template>
      </DataTable>
      <div style="margin-top:8px;text-align:right">
        <el-button size="small" @click="goStudents">查看{{ data.scope?.restricted ? '授权范围' : '本学院全部' }}学生 →</el-button>
      </div>
    </div>

    <!-- 各年级修读结果 + 挂科集中课程 TOP6（同行）-->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">各年级本学期修读结果 <KpiLabel label="" formula="同时比较课程学分通过占比、有效成绩人数、学生平均GPA与挂科学生率；课程学分通过占比不代表培养方案完成度" /></div>
          <DataTable v-if="data.gradeCompare.length" :columns="gradeCompareCols" :data="data.gradeCompare"
            storage-key="dashboard:college-grade-results" :max-business-columns="5"
            :config-version="1" size="small">
            <template #col-creditDone="{row}">{{ row.creditDone == null ? '—' : `${row.creditDone}%` }}</template>
            <template #col-gpaAvg="{row}">{{ row.gpaAvg == null ? '—' : Number(row.gpaAvg).toFixed(2) }}</template>
          </DataTable>
          <el-empty v-else description="本学期暂无可比较的年级修读结果" :image-size="64" />
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">优先核查课程 TOP6 <span class="extra">按受影响学生数优先；点击课程查看趋势和班级证据</span></div>
          <DataTable :columns="collegeFailCourseCols" :data="failCourses"
            storage-key="dashboard:college-focus-courses" :max-business-columns="6"
            :config-version="1" size="small" @row-click="goCourse" row-class-name="row-clickable">
            <template #col-name="{row}"><span class="link">{{ row.name }}</span></template>
            <template #col-priorityRank="{row}"><span class="rank hot">{{ row.priorityRank }}</span></template>
            <template #col-college>{{ data.name }}</template>
            <template #col-currentFailRate="{row}">
              <div style="display:flex;align-items:center;gap:6px">
                <el-progress :percentage="Math.min(parseFloat(row.failRate)*5,100)" :show-text="false" :stroke-width="8" :color="parseFloat(row.failRate)>15?'#E11D48':'#D97706'" style="flex:1" />
                <span class="tnum" :style="{color:parseFloat(row.failRate)>15?'#E11D48':'#D97706',fontWeight:600,minWidth:'40px',textAlign:'right'}">{{ row.failRate }}%</span>
              </div>
            </template>
            <template #col-avgScore="{row}"><b class="tnum">{{ row.avgScore }}</b></template>
            <template #col-courseGroup="{row}"><el-tag v-if="row.courseGroup" size="small" effect="plain" :type="row.courseGroup==='公共必修'?'warning':'info'">{{ row.courseGroup }}</el-tag><span v-else class="sa-faint">—</span></template>
            <template #col-firstPassRate="{row}">{{ row.firstPassRate ?? '—' }}{{ row.firstPassRate != null ? '%' : '' }}</template>
            <template #col-makeupPassRate="{row}">{{ row.makeupPassRate ?? '—' }}{{ row.makeupPassRate != null ? '%' : '' }}</template>
            <template #col-retakePassRate="{row}">{{ row.retakePassRate ?? '—' }}{{ row.retakePassRate != null ? '%' : '' }}</template>
            <template #col-changePp="{row}">
              <span v-if="row.changePp != null" :class="row.changePp>0?'risk-text':'good-text'">{{ row.changePp>0?'+':'' }}{{ row.changePp }}pp</span>
              <span v-else class="sa-faint">无基线</span>
            </template>
            <template #col-drill><span style="color:var(--sa-faint)">›</span></template>
          </DataTable>
        </div>
      </el-col>
    </el-row>
    <MetricHistoryDialog v-model="historyVisible" :metric-id="historyMetricId"
      scope-type="college" :scope-id="collegeId" :scope-label="data.name"
      :end-semester="fSemester" :semester-options="semesters" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted, computed, ref } from 'vue'
import { http } from '@/utils/http';
import { useRoute, useRouter } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue';
import KpiCard from '@/components/KpiCard.vue';
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue';
import MetricHistoryDialog from '@/components/MetricHistoryDialog.vue';
import { getFilterMeta, type SemesterOpt } from '@/utils/meta';
const route = useRoute(); const router = useRouter();
const collegeId = route.params.id as string;
const data = reactive<any>({ name:'', kpi:[], majors:[], gradeCompare:[], scope:{restricted:false}, evidence:{} });
const failCourses = reactive([] as any[]);
const semesters = ref<SemesterOpt[]>([]);
const fSemester = ref('');
const pageLoading = ref(false);
const loadError = ref('');
const historyVisible = ref(false);
const historyMetricId = ref('');
const historyMetricIds = [
  'valid_result_coverage_rate',
  'current_fail_student_rate',
  'average_student_gpa',
  'active_alert_student_rate',
];
let requestSeq = 0;

// 各专业数据表列定义（M6 DataTable；自定义渲染见模板 col-* / header-* 插槽）
const majorCols: DataTableColumn[] = [
  { key: 'priorityRank', label: '序', width: 48, fixed: 'left', region: 'identity', required: true },
  { key: 'name', label: '专业', minWidth: 140, fixed: 'left', region: 'identity', required: true },
  { key: 'creditDone', label: '课程学分通过占比', width: 130, align: 'right', required: true },
  { key: 'studentsWithResults', label: '有效成绩人数', width: 108, align: 'right', required: true },
  { key: 'gpa', label: '学生平均GPA', width: 105, align: 'right', required: true },
  { key: 'currentFailRate', label: '当前挂科学生率', width: 118, align: 'right', required: true },
  { key: 'currentFailVsCollegePp', label: '较学院挂科率偏离值', width: 150, align: 'right', required: true },
  { key: 'students', label: '在籍学生', width: 82, align: 'right', defaultVisible: false },
  { key: 'resultCoverageRate', label: '成绩覆盖率', width: 98, align: 'right', defaultVisible: false },
  { key: 'alertRate', label: '预警学生率', width: 98, align: 'right', defaultVisible: false },
  { key: 'priorityReason', label: '优先核查原因', minWidth: 260, defaultVisible: false },
  { key: 'drill', label: '详情', width: 52, fixed: 'right', region: 'action', required: true },
];
const gradeCompareCols: DataTableColumn[] = [
  { key: 'grade', label: '年级', width: 92, fixed: 'left', region: 'identity', required: true },
  { key: 'creditDone', label: '课程学分通过占比', minWidth: 138, align: 'right', required: true },
  { key: 'studentsWithResults', label: '有效成绩人数', minWidth: 110, align: 'right', required: true },
  { key: 'gpaAvg', label: '学生平均 GPA', minWidth: 110, align: 'right', required: true },
  { key: 'failRate', label: '挂科学生率', minWidth: 108, align: 'right', required: true },
];
const collegeFailCourseCols: DataTableColumn[] = [
  { key: 'priorityRank', label: '序', width: 46, fixed: 'left', region: 'identity', required: true },
  { key: 'name', label: '课程', minWidth: 140, fixed: 'left', region: 'identity', required: true },
  { key: 'college', label: '开课学院', width: 110, defaultVisible: false },
  { key: 'currentFailRate', label: '当前未通过率', minWidth: 130, required: true },
  { key: 'failCount', label: '不及格', width: 64, align: 'right' },
  { key: 'affectedStudents', label: '影响学生', width: 80, align: 'right', required: true },
  { key: 'changePp', label: '较上学期', width: 86, align: 'right' },
  { key: 'selectionReason', label: '入选原因', minWidth: 190 },
  { key: 'avgScore', label: '平均分', width: 70, align: 'right' },
  { key: 'courseGroup', label: '类别', width: 82, align: 'center', defaultVisible: false },
  { key: 'firstPassRate', label: '首次通过率', width: 86, align: 'right' },
  { key: 'makeupPassRate', label: '补考通过率', width: 86, align: 'right', defaultVisible: false },
  { key: 'retakePassRate', label: '重修通过率', width: 86, align: 'right' },
  { key: 'drill', label: '详情', width: 52, fixed: 'right', region: 'action', required: true },
];

async function loadData() {
  const currentRequest = ++requestSeq;
  pageLoading.value = true;
  loadError.value = '';
  const id = route.params.id as string || 'C05';
  const qs = fSemester.value ? `?semester=${fSemester.value}` : '';
  try {
    const d = await http.get('/admin/college/'+id+qs);
    if (d && currentRequest === requestSeq) {
      Object.assign(data, d);
      if (d.failCourses) { failCourses.length=0; failCourses.push(...d.failCourses.slice(0,6)); }
    }
  } catch (error:any) {
    if (currentRequest === requestSeq) loadError.value = error?.message || '数据加载失败，请稍后重试';
  } finally {
    if (currentRequest === requestSeq) pageLoading.value = false;
  }
}

onMounted(async () => {
  const meta = await getFilterMeta();
  semesters.value = meta.semesters.slice().reverse();
  fSemester.value = (route.query.semester as string) || meta.current || semesters.value[0]?.value || '';
  loadData();
});

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('预警')) return 'danger';
  if (label.includes('挂科')) return 'amber';
  return 'primary';
}
function openHistory(metricId:string) {
  historyMetricId.value = metricId;
  historyVisible.value = true;
}
function drillQuery(extra:Record<string,string>={}) { return { semester:fSemester.value, collegeId, collegeName:data.name, ...extra } }
function goMajor(row: any) { router.push({ path:'/admin/major/'+row.id, query:drillQuery({majorId:row.id,majorName:row.name}) }); }
function goCourse(row: any) { router.push({ path:'/admin/course/'+row.id, query:drillQuery() }); }
function goStudents() { router.push({ path:'/admin/students/list', query:{college:collegeId,collegeName:data.name,semester:fSemester.value,returnTo:route.fullPath,returnLabel:'返回学院详情'} }); }
</script>
<style scoped>
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
.rank { display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:7px;background:#f1f5f9;color:#64748b;font-weight:700; }
.rank.hot { background:#fff1f2;color:#be123c; }
.risk-text { color:#dc2626;font-weight:600; }
.good-text { color:#0d9488;font-weight:600; }
.muted-text { color:#64748b; }
</style>

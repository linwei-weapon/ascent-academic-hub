<template>
  <div v-loading="pageLoading && !!data.name" element-loading-text="正在更新课程分析，当前结果暂时保留…" :aria-busy="pageLoading">
    <el-breadcrumb separator="›">
      <el-breadcrumb-item v-if="route.query.returnTo" :to="String(route.query.returnTo)">{{ route.query.returnLabel || '返回来源' }}</el-breadcrumb-item>
      <el-breadcrumb-item v-else :to="{path:'/admin/dashboard',query:semLabel?{semester:semLabel}:{}}">教学数据总览</el-breadcrumb-item>
      <el-breadcrumb-item v-if="route.query.collegeId" :to="{path:'/admin/college/'+route.query.collegeId,query:semLabel?{semester:semLabel}:{}}">{{ route.query.collegeName || '学院详情' }}</el-breadcrumb-item>
      <el-breadcrumb-item v-if="route.query.majorId" :to="{path:'/admin/major/'+route.query.majorId,query:semLabel?{semester:semLabel}:{}}">{{ route.query.majorName || '专业详情' }}</el-breadcrumb-item>
      <el-breadcrumb-item>{{ data.name || '课程详情' }}</el-breadcrumb-item>
    </el-breadcrumb>
    <h2 class="sa-page-title" style="margin-top:14px">{{ data.name || '加载中…' }} · 课程详情</h2>
    <p class="sa-page-sub">
      <span v-if="data.credits">{{ data.credits }} 学分 · {{ data.type }} · {{ data.college }}</span>
      <span v-else>成绩分布、历年趋势与各教学班通过情况。</span>
      <span v-if="semLabel" style="margin-left:10px;padding:1px 8px;border-radius:10px;background:#EEF2FF;color:#4F46E5;font-size:12px">数据周期：{{ semLabel }}</span>
      <span v-if="data.scope?.restricted" style="margin-left:8px;padding:1px 8px;border-radius:10px;background:#FFF7ED;color:#C2410C;font-size:12px">仅当前角色授权学生范围</span>
      <span v-if="data.analysisScope?.label" style="margin-left:8px;padding:1px 8px;border-radius:10px;background:#ECFDF5;color:#047857;font-size:12px">
        分析范围：{{ data.analysisScope.label }}
      </span>
    </p>

    <el-alert v-if="loadError" type="error" :closable="false" show-icon style="margin-bottom:12px"
      title="课程数据加载失败" :description="loadError">
      <template #default><el-button size="small" @click="loadData">重新加载</el-button></template>
    </el-alert>
    <div v-if="pageLoading && !data.name" class="sa-card">
      <el-skeleton :rows="10" animated />
    </div>
    <template v-if="data.name">
    <el-alert v-if="data.evidence?.limitation" type="info" :closable="false" show-icon style="margin-bottom:12px"
      title="统计范围说明" :description="data.evidence.limitation" />

    <div class="sa-kpi-row">
      <KpiCard v-for="k in data.kpi" :key="k.label" :label="k.label" :value="k.value" :tone="kpiTone(k.label)" :hint="k.formula" :sub="k.detail" />
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">成绩分布 <span class="extra">按分数段统计修读人次</span></div>
          <EChart v-if="data.scoreDistribution.length" :option="scoreOption" :height="240" />
          <div v-else class="sa-faint" style="font-size:12px">暂无成绩分布数据</div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">历年趋势 <span class="extra">平均分 / 未通过人次率</span></div>
          <EChart v-if="data.history.length" :option="historyOption" :height="240" />
          <div v-else class="sa-faint" style="font-size:12px">暂无历年数据</div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">
        全部行政班
        <span class="extra">共 {{ data.classSummary?.totalAdministrativeClasses || 0 }} 个行政班；{{ data.classSummary?.sort }}</span>
        <KpiLabel label="" formula="当前数据按修读学生所属行政班聚合，并非教学班。未通过人次率=该行政班未通过有效成绩人次÷有效成绩人次×100%" />
      </div>
      <DataTable :columns="classCols" :data="data.classDetail"
        storage-key="dashboard:course-class-distribution" :max-business-columns="4"
        :config-version="3" :pagination="true" :default-page-size="20" size="small">
        <template #col-riskRank="{row}"><span class="rank" :class="{hot:row.riskRank<=3}">{{ row.riskRank }}</span></template>
        <template #col-avgScore="{row}"><b class="tnum" :style="{color:row.avgScore<60?'#E11D48':'#1E293B'}">{{ row.avgScore }}</b></template>
        <template #col-failRate="{row}"><span class="tnum" :style="{color:parseFloat(row.failRate)>25?'#E11D48':'#D97706',fontWeight:600}">{{ row.failRate }}</span></template>
      </DataTable>
    </div>
    <div style="margin-top:16px"><el-button type="primary" @click="goStudents">查看全部修读学生 →</el-button></div>
    </template>

  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, onMounted, computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import KpiLabel from '@/components/KpiLabel.vue';
import KpiCard from '@/components/KpiCard.vue';
import EChart from '@/components/EChart.vue';
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue';
import { withReturnContext } from '@/utils/dashboardDrill';
const route = useRoute(); const router = useRouter();
const semLabel = (route.query.semester as string) || '';
const pageLoading = ref(false);
const loadError = ref('');
let requestSeq = 0;
const data = reactive<any>({ name:'', credits:0, type:'', college:'', kpi:[], scoreDistribution:[], classDetail:[], classSummary:{}, history:[], scope:{restricted:false}, analysisScope:{}, evidence:{} });
const classCols: DataTableColumn[] = [
  { key: 'riskRank', label: '序', width: 48, fixed: 'left', region: 'identity', required: true },
  { key: 'className', label: '行政班', width: 150, fixed: 'left', region: 'identity', required: true },
  { key: 'students', label: '有效成绩人次', width: 112, align: 'right' },
  { key: 'avgScore', label: '平均分', width: 80, align: 'right' },
  { key: 'failRate', label: '未通过人次率', width: 112, align: 'right', required: true },
  { key: 'teacher', label: '任课教师', minWidth: 120 },
];

function barColor(label: string) {
  if (label === '不及格') return '#E11D48';
  if (label === '优秀') return '#0D9488';
  return '#4F46E5';
}

async function loadData() {
  const currentRequest = ++requestSeq;
  pageLoading.value = true;
  loadError.value = '';
  const params = new URLSearchParams();
  if (semLabel) params.set('semester', semLabel);
  if (route.query.collegeId) params.set('college_id', String(route.query.collegeId));
  if (route.query.majorId) params.set('major_id', String(route.query.majorId));
  if (route.query.grade) params.set('grade', String(route.query.grade));
  const qs = params.toString() ? `?${params.toString()}` : '';
  try {
    const d = await http.get('/admin/course/' + (route.params.id || '100101C003') + qs);
    if (d && currentRequest === requestSeq) Object.assign(data, d);
  } catch (error:any) {
    if (currentRequest === requestSeq) {
      loadError.value = error?.message || '数据加载失败，请稍后重试';
    }
  } finally {
    if (currentRequest === requestSeq) pageLoading.value = false;
  }
}
onMounted(loadData);
watch(() => route.fullPath, () => loadData());

const scoreOption = computed(() => {
  const sd = data.scoreDistribution || [];
  return {
    grid: { left: 6, right: 12, top: 24, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps: any) => { const s = sd[ps[0].dataIndex]; return `${s.label}（${s.range}）<br/>人次 <b>${s.count}</b> · 占有分数记录 <b>${s.pct == null ? '—' : `${s.pct}%`}</b>`; },
    },
    xAxis: { type: 'category', data: sd.map((s: any) => s.label), axisLabel: { color: '#475569' }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '人数', nameTextStyle: { color: '#94A3B8', fontSize: 11 }, axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    series: [{
      type: 'bar', data: sd.map((s: any) => ({ value: s.count, itemStyle: { color: barColor(s.label) } })),
      barWidth: '50%', itemStyle: { borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: 'top', formatter: '{c}', color: '#64748B', fontSize: 11 },
    }],
  };
});

const historyOption = computed(() => {
  const h = data.history || [];
  return {
    grid: { left: 6, right: 6, top: 36, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    legend: { data: ['平均分', '未通过人次率'], top: 0, textStyle: { color: '#64748B', fontSize: 12 }, itemWidth: 14, itemHeight: 8 },
    xAxis: { type: 'category', data: h.map((x: any) => x.semester), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', name: '平均分', min: 40, max: 100, nameTextStyle: { color: '#94A3B8', fontSize: 11 }, axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
      { type: 'value', name: '未通过率%', nameTextStyle: { color: '#94A3B8', fontSize: 11 }, axisLabel: { color: '#94A3B8', formatter: '{value}%' }, splitLine: { show: false } },
    ],
    series: [
      { name: '平均分', type: 'line', smooth: true, data: h.map((x: any) => x.avgScore), itemStyle: { color: '#4F46E5' }, lineStyle: { width: 3 }, symbolSize: 7 },
      { name: '未通过人次率', type: 'line', smooth: true, yAxisIndex: 1, data: h.map((x: any) => parseFloat(x.failRate)), itemStyle: { color: '#E11D48' }, lineStyle: { width: 2, type: 'dashed' }, symbolSize: 6 },
    ],
  };
});

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('预警')) return 'danger';
  if (label.includes('挂科') || label.includes('未通过')) return 'amber';
  if (label.includes('优秀') || label.includes('通过')) return 'teal';
  return 'primary';
}
function goStudents() {
  const query:any = { course:String(route.params.id), courseName:data.name, semester:semLabel };
  if (route.query.collegeId) {
    query.college=route.query.collegeId; query.collegeName=route.query.collegeName;
  }
  if (route.query.majorId) {
    query.major=route.query.majorId; query.majorName=route.query.majorName;
  }
  if (route.query.grade) query.grade=route.query.grade;
  router.push({
    path:`/admin/course/${String(route.params.id)}/students`,
    query:withReturnContext(query, route.fullPath, '返回课程详情'),
  });
}
</script>

<style scoped>
.rank { display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:7px;background:#f1f5f9;color:#64748b;font-weight:700; }
.rank.hot { background:#fff1f2;color:#be123c; }
</style>

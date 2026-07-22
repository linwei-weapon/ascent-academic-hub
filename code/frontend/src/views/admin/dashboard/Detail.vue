<template>
  <div>
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

    <el-alert v-if="data.evidence?.limitation" type="warning" :closable="false" show-icon style="margin:12px 0"
      title="证据与口径说明" :description="data.evidence.limitation" />

    <div class="sa-kpi-row">
      <KpiCard v-for="k in data.kpi" :key="k.label" :label="k.label" :value="k.value" :tone="kpiTone(k.label)" :hint="k.formula" />
    </div>

    <!-- 各专业数据（全宽）-->
    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">各专业数据 <span class="extra">点击专业行下钻</span></div>
      <DataTable :columns="majorCols" :data="data.majors" storage-key="dashboard:college-majors" size="small" @row-click="goMajor" row-class-name="row-clickable">
        <template #col-name="{row}"><span class="link">{{ row.name }}</span></template>
        <template #col-gpa="{row}"><b class="tnum">{{ row.gpa }}</b></template>
        <template #col-currentFailRate="{row}"><span class="tnum" :style="{color:parseFloat(row.currentFailRate||'0')>10?'#DC2626':'#6B7280'}">{{ row.currentFailRate || '—' }}</span></template>
        <template #col-trend="{row}"><span :style="{color:row.trend==='up'?'#E11D48':row.trend==='down'?'#0D9488':'#94A3B8',fontSize:'14px'}">{{ row.trend==='up'?'▲':'▼' }}</span></template>
        <template #header-trend><span>对比全院<KpiLabel label="" formula="当前挂科率高于全院均值为▲(红)，低于为▼(绿)" /></span></template>
        <template #col-drill><span style="color:var(--sa-faint)">›</span></template>
      </DataTable>
      <div style="margin-top:8px;text-align:right">
        <el-button size="small" @click="goStudents">查看{{ data.scope?.restricted ? '授权范围' : '本学院全部' }}学生 →</el-button>
      </div>
    </div>

    <!-- 各年级学分完成率 + 挂科集中课程 TOP6（同行）-->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">各年级课程学分通过占比 <KpiLabel label="" formula="当前学期已通过课程学分人次÷修读课程学分人次×100%，不等同于培养方案完成度" /></div>
          <EChart v-if="data.gradeCompare.length" :option="gradeOption" :height="Math.max(150, data.gradeCompare.length*46)" />
          <div v-else class="sa-faint" style="font-size:12px">暂无年级数据</div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">挂科集中课程 TOP6 <span class="extra">点击课程查看详情</span></div>
          <el-table :data="failCourses" size="small" @row-click="goCourse" row-class-name="row-clickable">
            <el-table-column prop="name" label="课程" min-width="140"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
            <el-table-column :formatter="() => data.name" label="开课学院" width="110" />
            <el-table-column label="挂科率" min-width="130"><template #default="{row}">
              <div style="display:flex;align-items:center;gap:6px">
                <el-progress :percentage="Math.min(parseFloat(row.failRate)*5,100)" :show-text="false" :stroke-width="8" :color="parseFloat(row.failRate)>15?'#E11D48':'#D97706'" style="flex:1" />
                <span class="tnum" :style="{color:parseFloat(row.failRate)>15?'#E11D48':'#D97706',fontWeight:600,minWidth:'40px',textAlign:'right'}">{{ row.failRate }}%</span>
              </div>
            </template></el-table-column>
            <el-table-column prop="failCount" label="不及格" width="64" align="right" />
            <el-table-column prop="totalCount" label="修读人数" width="80" align="right" />
            <el-table-column prop="avgScore" label="平均分" width="70" align="right"><template #default="{row}"><b class="tnum">{{ row.avgScore }}</b></template></el-table-column>
            <el-table-column label="类别" width="82" align="center"><template #default="{row}"><el-tag v-if="row.courseGroup" size="small" effect="plain" :type="row.courseGroup==='公共必修'?'warning':'info'">{{ row.courseGroup }}</el-tag><span v-else class="sa-faint">—</span></template></el-table-column>
            <el-table-column label="首次通过率" width="86" align="right"><template #default="{row}">{{ row.firstPassRate ?? '—' }}{{ row.firstPassRate != null ? '%' : '' }}</template></el-table-column>
            <el-table-column label="补考通过率" width="86" align="right"><template #default="{row}">{{ row.makeupPassRate ?? '—' }}{{ row.makeupPassRate != null ? '%' : '' }}</template></el-table-column>
            <el-table-column label="重修通过率" width="86" align="right"><template #default="{row}">{{ row.retakePassRate ?? '—' }}{{ row.retakePassRate != null ? '%' : '' }}</template></el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted, computed, ref } from 'vue'
import { http } from '@/utils/http';
import { useRoute, useRouter } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue';
import KpiCard from '@/components/KpiCard.vue';
import EChart from '@/components/EChart.vue';
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue';
import { getFilterMeta, type SemesterOpt } from '@/utils/meta';
const route = useRoute(); const router = useRouter();
const collegeId = route.params.id as string;
const data = reactive<any>({ name:'', kpi:[], majors:[], gradeCompare:[], scope:{restricted:false}, evidence:{} });
const failCourses = reactive([] as any[]);
const semesters = ref<SemesterOpt[]>([]);
const fSemester = ref('');

// 各专业数据表列定义（M6 DataTable；自定义渲染见模板 col-* / header-* 插槽）
const majorCols: DataTableColumn[] = [
  { key: 'name', label: '专业', minWidth: 140 },
  { key: 'students', label: '人数', width: 70, align: 'right' },
  { key: 'gpa', label: '平均GPA', width: 80, align: 'right' },
  { key: 'currentFailRate', label: '当前挂科率', width: 90, align: 'right' },
  { key: 'failRate', label: '历史挂科经历率', width: 120, align: 'right' },
  { key: 'alertCount', label: '预警人数', width: 80, align: 'right' },
  { key: 'trend', label: '对比全院', width: 72, align: 'center' },
  { key: 'drill', label: '下钻', width: 36 },
];

async function loadData() {
  const id = route.params.id as string || 'C05';
  const qs = fSemester.value ? `?semester=${fSemester.value}` : '';
  const d = await http.get('/admin/college/'+id+qs);
  if (d) {
    Object.assign(data, d);
    if (d.failCourses) { failCourses.length=0; failCourses.push(...d.failCourses.slice(0,6)); }
  }
}

onMounted(async () => {
  const meta = await getFilterMeta();
  semesters.value = meta.semesters.slice().reverse();
  fSemester.value = (route.query.semester as string) || meta.current || semesters.value[0]?.value || '';
  loadData();
});

const gradeOption = computed(() => {
  const gc = data.gradeCompare || [];
  return {
    grid: { left: 8, right: 36, top: 8, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps: any) => { const g = gc[ps[0].dataIndex]; return `${g.grade}<br/>学分完成 <b>${g.creditDone}%</b><br/>GPA ${g.gpaAvg} · 挂科率 ${g.failRate}`; },
    },
    xAxis: { type: 'value', max: 100, axisLabel: { color: '#94A3B8', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: gc.map((g: any) => g.grade), axisLabel: { color: '#475569' }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [{
      type: 'bar', data: gc.map((g: any) => g.creditDone), barWidth: '52%',
      itemStyle: { color: '#4F46E5', borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: 'right', formatter: '{c}%', color: '#64748B', fontSize: 11 },
    }],
  };
});

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('预警')) return 'danger';
  if (label.includes('挂科')) return 'amber';
  return 'primary';
}
function drillQuery(extra:Record<string,string>={}) { return { semester:fSemester.value, collegeId, collegeName:data.name, ...extra } }
function goMajor(row: any) { router.push({ path:'/admin/major/'+row.id, query:drillQuery({majorId:row.id,majorName:row.name}) }); }
function goCourse(row: any) { router.push({ path:'/admin/course/'+row.id, query:drillQuery() }); }
function goStudents() { router.push({ path:'/admin/students/list', query:{college:collegeId,collegeName:data.name,semester:fSemester.value,returnTo:`/admin/college/${collegeId}`,returnLabel:'返回学院详情'} }); }
</script>
<style scoped>
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
</style>

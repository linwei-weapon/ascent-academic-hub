<template>
  <div>
    <el-breadcrumb separator="›"><el-breadcrumb-item :to="{path:'/admin/dashboard'}">数据大屏</el-breadcrumb-item><el-breadcrumb-item>{{ data.name || '学院详情' }}</el-breadcrumb-item></el-breadcrumb>
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <h2 class="sa-page-title" style="margin-top:14px;margin-bottom:0">{{ data.name || '加载中…' }} · 学院详情</h2>
        <p class="sa-page-sub">统计学期：<b>{{ curSemester }}</b> · 二级学院学业全景</p>
      </div>
      <el-select v-model="fSemester" size="small" style="width:170px" placeholder="选择学期" @change="loadData">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
    </div>

    <div class="sa-kpi-row">
      <KpiCard v-for="k in data.kpi" :key="k.label" :label="k.label" :value="k.value" :tone="kpiTone(k.label)" :hint="k.formula" />
    </div>

    <!-- 各专业数据（全宽）-->
    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">各专业数据 <span class="extra">点击专业行下钻</span></div>
      <el-table :data="data.majors" size="small" @row-click="goMajor" row-class-name="row-clickable">
        <el-table-column prop="name" label="专业" min-width="140"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="students" label="人数" width="70" align="right" />
        <el-table-column prop="gpa" label="平均GPA" width="80" align="right"><template #default="{row}"><b class="tnum">{{ row.gpa }}</b></template></el-table-column>
        <el-table-column label="当前挂科率" width="90" align="right">
          <template #default="{row}"><span class="tnum" :style="{color:parseFloat(row.currentFailRate||'0')>10?'#DC2626':'#6B7280'}">{{ row.currentFailRate || '—' }}</span></template>
        </el-table-column>
        <el-table-column prop="failRate" label="历史挂科经历率" width="120" align="right" />
        <el-table-column prop="alertCount" label="预警人数" width="80" align="right" />
        <el-table-column label="对比全院" width="72" align="center">
          <template #default="{row}"><span :style="{color:row.trend==='up'?'#E11D48':row.trend==='down'?'#0D9488':'#94A3B8',fontSize:'14px'}">{{ row.trend==='up'?'▲':'▼' }}</span></template>
          <template #header><span>对比全院<KpiLabel label="" formula="当前挂科率高于全院均值为▲(红)，低于为▼(绿)" /></span></template>
        </el-table-column>
        <el-table-column label="" width="36"><template #default><span style="color:var(--sa-faint)">›</span></template></el-table-column>
      </el-table>
      <div style="margin-top:8px;text-align:right">
        <el-button size="small" @click="router.push('/admin/students/list?college=' + collegeId + '&collegeName=' + encodeURIComponent(data.name))">查看本学院全部学生 →</el-button>
      </div>
    </div>

    <!-- 各年级学分完成率 + 挂科集中课程 TOP6（同行）-->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">各年级学分完成率 <KpiLabel label="" formula="已通过课程学分÷修读课程总学分×100%，按年级统计均值。反映该年级学生整体学业进度与培养方案完成情况" /></div>
          <EChart v-if="data.gradeCompare.length" :option="gradeOption" :height="Math.max(150, data.gradeCompare.length*46)" />
          <div v-else class="sa-faint" style="font-size:12px">暂无年级数据</div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">挂科集中课程 TOP6 <span class="extra">点击课程查看详情</span></div>
          <el-table :data="failCourses" size="small" @row-click="goCourse" row-class-name="row-clickable">
            <el-table-column prop="name" label="课程" min-width="100"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
            <el-table-column label="挂科率" min-width="130"><template #default="{row}">
              <div style="display:flex;align-items:center;gap:6px">
                <el-progress :percentage="Math.min(parseFloat(row.failRate)*5,100)" :show-text="false" :stroke-width="8" :color="parseFloat(row.failRate)>15?'#E11D48':'#D97706'" style="flex:1" />
                <span class="tnum" :style="{color:parseFloat(row.failRate)>15?'#E11D48':'#D97706',fontWeight:600,minWidth:'40px',textAlign:'right'}">{{ row.failRate }}%</span>
              </div>
            </template></el-table-column>
            <el-table-column prop="failCount" label="不及格" width="64" align="right" />
            <el-table-column prop="totalCount" label="修读" width="64" align="right" />
            <el-table-column prop="avgScore" label="均分" width="54" align="right"><template #default="{row}"><b class="tnum">{{ row.avgScore }}</b></template></el-table-column>
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
import { getFilterMeta, type SemesterOpt } from '@/utils/meta';
const route = useRoute(); const router = useRouter();
const collegeId = route.params.id as string;
const data = reactive({ name:'', kpi:[] as any[], majors:[] as any[], gradeCompare:[] as any[] });
const failCourses = reactive([] as any[]);
const semesters = ref<SemesterOpt[]>([]);
const fSemester = ref('');
const curSemester = ref('');

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
  curSemester.value = meta.current || semesters.value[0]?.value || '';
  fSemester.value = curSemester.value;
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
function goMajor(row: any) { router.push('/admin/major/'+(row.id||'M051')); }
function goCourse(row: any) { router.push('/admin/course/'+(row.id||'100101C003')); }
</script>
<style scoped>
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
</style>

<template>
  <div>
    <el-breadcrumb separator="›">
      <el-breadcrumb-item :to="{path:'/admin/dashboard',query:semLabel?{semester:semLabel}:{}}">数据大屏</el-breadcrumb-item>
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
    </p>

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
          <div class="sa-card-title">历年趋势 <span class="extra">平均分 / 挂科率</span></div>
          <EChart v-if="data.history.length" :option="historyOption" :height="240" />
          <div v-else class="sa-faint" style="font-size:12px">暂无历年数据</div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">
        各班级详情
        <KpiLabel label="" formula="按教学班统计该课程的通过率、平均分。挂科率=该班不及格人次÷该班修读人次×100%" />
      </div>
      <el-table :data="data.classDetail" size="small">
        <el-table-column prop="className" label="班级" width="150" />
        <el-table-column prop="students" label="人数" width="70" align="right" />
        <el-table-column prop="avgScore" label="平均分" width="80" align="right"><template #default="{row}"><b class="tnum" :style="{color:row.avgScore<60?'#E11D48':'#1E293B'}">{{ row.avgScore }}</b></template></el-table-column>
        <el-table-column prop="failRate" label="挂科率" width="90" align="right"><template #default="{row}"><span class="tnum" :style="{color:parseFloat(row.failRate)>25?'#E11D48':'#D97706',fontWeight:600}">{{ row.failRate }}</span></template></el-table-column>
        <el-table-column prop="teacher" label="任课教师" min-width="120" />
      </el-table>
    </div>
    <div style="margin-top:16px"><el-button type="primary" @click="goStudents">查看全部修读学生 →</el-button></div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, onMounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import KpiLabel from '@/components/KpiLabel.vue';
import KpiCard from '@/components/KpiCard.vue';
import EChart from '@/components/EChart.vue';
const route = useRoute(); const router = useRouter();
const semLabel = (route.query.semester as string) || '';
const data = reactive<any>({ name:'', credits:0, type:'', college:'', kpi:[], scoreDistribution:[], classDetail:[], history:[], scope:{restricted:false}, evidence:{} });

function barColor(label: string) {
  if (label === '不及格') return '#E11D48';
  if (label === '优秀') return '#0D9488';
  return '#4F46E5';
}

onMounted(async () => {
  const qs = semLabel ? '?semester=' + encodeURIComponent(semLabel) : '';
  const d = await http.get('/admin/course/' + (route.params.id || '100101C003') + qs);
  if (d) Object.assign(data, d);
});

const scoreOption = computed(() => {
  const sd = data.scoreDistribution || [];
  return {
    grid: { left: 6, right: 12, top: 24, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps: any) => { const s = sd[ps[0].dataIndex]; return `${s.label}（${s.range}）<br/>人数 <b>${s.count}</b> · 占比 <b>${s.pct}%</b>`; },
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
    legend: { data: ['平均分', '挂科率'], top: 0, textStyle: { color: '#64748B', fontSize: 12 }, itemWidth: 14, itemHeight: 8 },
    xAxis: { type: 'category', data: h.map((x: any) => x.semester), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', name: '平均分', min: 40, max: 100, nameTextStyle: { color: '#94A3B8', fontSize: 11 }, axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
      { type: 'value', name: '挂科率%', nameTextStyle: { color: '#94A3B8', fontSize: 11 }, axisLabel: { color: '#94A3B8', formatter: '{value}%' }, splitLine: { show: false } },
    ],
    series: [
      { name: '平均分', type: 'line', smooth: true, data: h.map((x: any) => x.avgScore), itemStyle: { color: '#4F46E5' }, lineStyle: { width: 3 }, symbolSize: 7 },
      { name: '挂科率', type: 'line', smooth: true, yAxisIndex: 1, data: h.map((x: any) => parseFloat(x.failRate)), itemStyle: { color: '#E11D48' }, lineStyle: { width: 2, type: 'dashed' }, symbolSize: 6 },
    ],
  };
});

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('预警')) return 'danger';
  if (label.includes('挂科')) return 'amber';
  if (label.includes('优秀') || label.includes('通过')) return 'teal';
  return 'primary';
}
function goStudents() {
  const query:any = { course:String(route.params.id), courseName:data.name, semester:semLabel, returnTo:route.fullPath, returnLabel:'返回课程详情' };
  if (route.query.collegeId) { query.collegeId=route.query.collegeId; query.collegeName=route.query.collegeName; }
  if (route.query.majorId) { query.majorId=route.query.majorId; query.majorName=route.query.majorName; }
  router.push({path:'/admin/students/list',query});
}
</script>

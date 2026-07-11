<template>
  <div>
    <el-breadcrumb separator="›">
      <el-breadcrumb-item :to="{path:'/admin/dashboard',query:semLabel?{semester:semLabel}:{}}">数据大屏</el-breadcrumb-item>
      <el-breadcrumb-item>{{ data.name || '专业详情' }}</el-breadcrumb-item>
    </el-breadcrumb>
    <h2 class="sa-page-title" style="margin-top:14px">{{ data.name || '加载中…' }} · 专业详情</h2>
    <p class="sa-page-sub">{{ data.college }} · {{ semLabel || '默认学期' }} · {{ data.scope?.restricted ? '当前角色授权范围' : '本专业全量' }}</p>

    <el-alert v-if="data.evidence?.limitation" type="warning" :closable="false" show-icon style="margin-bottom:12px"
      title="证据与口径说明" :description="data.evidence.limitation" />

    <div class="sa-kpi-row">
      <KpiCard v-for="k in data.kpi" :key="k.label" :label="k.label" :value="k.value" :tone="kpiTone(k.label)" :hint="k.formula" />
    </div>

    <el-row :gutter="16">
      <el-col :span="16">
        <div class="sa-card">
          <div class="sa-card-title">各年级详情</div>
          <div v-if="!data.gradeDetail.length" class="sa-faint" style="font-size:12px">暂无年级数据</div>
          <div v-for="g in data.gradeDetail" :key="g.grade" class="grade-block">
            <div class="grade-head">
              <span class="grade-name">{{ g.grade }}</span>
              <span class="chip">{{ g.students }}人</span>
              <span class="chip">GPA <b class="tnum">{{ g.gpaAvg }}</b></span>
              <span class="chip">挂科率 <b class="tnum" style="color:#E11D48">{{ g.failRate }}</b></span>
              <span class="chip">预警 <b class="tnum" style="color:#E11D48">{{ g.alertCount }}</b>人</span>
              <span class="grade-credit">
                <span class="sa-faint" style="font-size:11px">课程学分通过</span>
                <el-progress :percentage="g.creditDone" :stroke-width="7" :color="g.creditDone>75?'#0D9488':'#D97706'" style="width:120px" />
              </span>
            </div>
            <el-table v-if="g.courses && g.courses.length" :data="g.courses" size="small" @row-click="goCourse" row-class-name="course-row-clickable">
              <el-table-column prop="name" label="挂科课程" width="160"><template #default="{row}"><span class="course-link">{{ row.name }}</span></template></el-table-column>
              <el-table-column label="挂科率计算" min-width="220"><template #default="{row}"><span style="font-size:12px"><b style="color:#E11D48" class="tnum">{{ row.failCount }}</b> 不及格 ÷ <b class="tnum">{{ row.totalCount }}</b> 总修读 = <b style="color:#E11D48" class="tnum">{{ row.failRate }}%</b></span></template></el-table-column>
            </el-table>
            <div v-else class="sa-faint" style="font-size:12px;padding:2px 0 4px">该年级无集中挂科课程</div>
          </div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="sa-card">
          <div class="sa-card-title">毕业去向分布（合成）</div>
          <template v-if="goalRows.length">
            <div class="goal-donut-wrap">
              <EChart :option="goalOption" :height="200" />
              <div class="goal-donut-center">
                <div class="goal-donut-total tnum">{{ goalTotal.toLocaleString() }}</div>
                <div class="goal-donut-cap">目标人次</div>
              </div>
            </div>
            <div class="goal-legend">
              <div v-for="(g,i) in goalRows" :key="g.name" class="goal-legend-row">
                <span class="dot" :style="{background: GOAL_COLORS[i % GOAL_COLORS.length]}"></span>
                <span class="goal-legend-label">{{ g.name }}</span>
                <span class="tnum goal-legend-val">{{ g.value }}</span>
                <span class="tnum goal-legend-pct">{{ g.pct }}%</span>
              </div>
            </div>
          </template>
          <div v-else class="sa-faint" style="font-size:12px">暂无毕业去向数据</div>
        </div>
      </el-col>
    </el-row>
    <div style="margin-top:16px"><el-button type="primary" @click="goStudents">查看{{ data.scope?.restricted ? '授权范围' : '本专业全部' }}学生 →</el-button></div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, onMounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import KpiCard from '@/components/KpiCard.vue';
import EChart from '@/components/EChart.vue';
const route = useRoute(); const router = useRouter();
const semLabel = (route.query.semester as string) || '';
const data = reactive<any>({ name:'', college:'', collegeId:'', kpi:[], gradeDetail:[], goalDistribution:{}, scope:{restricted:false}, evidence:{} });

const GOAL_COLORS = ['#4F46E5', '#0D9488', '#D97706', '#6366F1', '#94A3B8', '#E11D48', '#0EA5E9', '#A855F7'];

onMounted(async () => {
  const qs = semLabel ? '?semester=' + encodeURIComponent(semLabel) : '';
  const d = await http.get('/admin/major/' + (route.params.id || 'M051') + qs);
  if (d) Object.assign(data, d);
});

const goalRows = computed(() => {
  const gd = data.goalDistribution || {};
  const entries = Object.entries(gd).filter(([, v]) => Number(v) > 0);
  const total = entries.reduce((s, [, v]) => s + Number(v), 0) || 1;
  return entries.map(([name, v]) => ({ name, value: Number(v), pct: Math.round(Number(v) / total * 100) }));
});
const goalTotal = computed(() => goalRows.value.reduce((s, g) => s + g.value, 0));

const goalOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c} 人（{d}%）' },
  series: [{
    type: 'pie', radius: ['54%', '80%'], center: ['50%', '50%'],
    avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 },
    label: { show: false },
    emphasis: { scale: true, scaleSize: 4 },
    data: goalRows.value.map((g, i) => ({ name: g.name, value: g.value, itemStyle: { color: GOAL_COLORS[i % GOAL_COLORS.length] } })),
  }],
}));

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('预警')) return 'danger';
  if (label.includes('挂科')) return 'amber';
  if (label.includes('毕业') || label.includes('学位')) return 'teal';
  return 'primary';
}
function goStudents() {
  const majorId = route.params.id as string;
  router.push({ path:'/admin/students/list', query:{college:data.collegeId,major:majorId,majorName:data.name,...(semLabel?{semester:semLabel}:{})} });
}
function goCourse(row: any) { router.push({ path:'/admin/course/'+row.id, query:semLabel?{semester:semLabel}:{} }); }
</script>

<style scoped>
.grade-block { padding: 12px 0; border-top: 1px solid var(--sa-border); }
.grade-block:first-of-type { border-top: none; padding-top: 4px; }
.grade-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.grade-name { font-size: 14px; font-weight: 700; color: var(--sa-text); }
.chip { font-size: 12px; color: var(--sa-muted); background: #f1f5f9; padding: 2px 9px; border-radius: 99px; }
.grade-credit { display: flex; align-items: center; gap: 8px; margin-left: auto; }

.goal-donut-wrap { position: relative; }
.goal-donut-center {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; pointer-events: none;
}
.goal-donut-total { font-family: var(--sa-font-head); font-size: 26px; font-weight: 700; color: var(--sa-text); line-height: 1; }
.goal-donut-cap { font-size: 11px; color: var(--sa-muted); margin-top: 4px; }
.goal-legend { margin-top: 10px; }
.goal-legend-row { display: flex; align-items: center; gap: 8px; padding: 4px 2px; font-size: 12px; }
.goal-legend-row .dot { width: 9px; height: 9px; border-radius: 3px; flex-shrink: 0; }
.goal-legend-label { color: var(--sa-text); flex: 1; }
.goal-legend-val { color: var(--sa-text); font-weight: 600; }
.goal-legend-pct { color: var(--sa-muted); width: 38px; text-align: right; }
:deep(.course-row-clickable) { cursor: pointer; }
.course-link { color: var(--sa-primary); font-weight: 500; }
</style>

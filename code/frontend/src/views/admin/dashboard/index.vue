<template>
  <div v-loading="pageLoading" element-loading-text="正在加载教学数据总览，请稍候…" element-loading-background="rgba(248,250,252,.82)">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <h2 class="sa-page-title" style="margin-bottom:0">{{ pageTitle }}</h2>
        <p class="sa-page-sub">
          数据来源：教务系统同步 · 统计学期：<b>{{ fSemester }}</b> ·
          <span style="color:var(--sa-primary);font-weight:500">{{ data.scope?.restricted ? '受限视角（仅当前身份授权明细）' : '校级视角（全校数据）' }}</span>
        </p>
      </div>
      <el-select v-model="fSemester" size="small" style="width:170px" placeholder="选择学期" @change="onSemesterChange">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
    </div>
    <BusinessPageContext
      :period="fSemester ? `统计学期：${fSemester}` : ''"
      source="教务系统学籍、成绩与预警计算结果"
      :loading="pageLoading"
      :error="loadError"
      :updated-at="updatedAt"
    />

    <el-alert v-if="data.evidence?.limitation" type="warning" :closable="false" show-icon style="margin:12px 0"
      title="证据说明：毕业率和学位授予率为合成业务数据"
      :description="data.evidence.limitation" />

    <!-- KPI 卡片行 — 在校生指标 -->
    <div style="margin-bottom:4px;font-size:12px;color:var(--sa-faint)">在校生运行指标</div>
    <div class="sa-kpi-row">
      <KpiCard
        v-for="k in schoolKpis"
        :key="k.label"
        :label="k.label"
        :value="k.value"
        :sub="k.sub || k.trend"
        :tone="kpiTone(k.label)"
        :hint="k.formula"
      />
    </div>
    <!-- KPI 卡片行 — 毕业生指标 -->
    <div style="margin-bottom:4px;font-size:12px;color:var(--sa-faint)">应届毕业质量指标</div>
    <div class="sa-kpi-row">
      <KpiCard
        v-for="k in gradKpis"
        :key="k.label"
        :label="k.label"
        :value="k.value"
        :sub="k.sub || k.trend"
        :tone="kpiTone(k.label)"
        :hint="k.formula"
      />
    </div>

    <!-- 学院对比表（全宽） -->
    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">
        {{ data.scope?.restricted ? '授权范围学院概览' : '学院横向对比' }}
        <span class="extra">点击学院行查看详情 · 成绩指标按所选学期和当前授权学生范围计算</span>
      </div>
      <el-table :data="data.colleges" stripe size="small" @row-click="goCollege" row-class-name="college-row-clickable">
        <el-table-column prop="name" label="学院" width="170"><template #default="{row}"><span class="college-link">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="students" label="人数" width="70" align="right" />
        <el-table-column width="108" align="right"><template #header><span>加权平均分 <KpiLabel label="" formula="当前学期真实课程成绩按课程学分加权：Σ(成绩×学分)÷Σ学分；不含成绩为空或学分≤0的记录" /></span></template><template #default="{row}"><span v-if="row.avgScore != null" class="tnum" :style="{color: scoreColor(row.avgScore), fontWeight:700}">{{ row.avgScore }}</span><span v-else class="sa-faint">—</span></template></el-table-column>
        <el-table-column width="96" align="right"><template #header><span>平均GPA <KpiLabel label="" formula="先计算每名学生当前学期课程平均GPA，再对学院内有GPA学生求平均，避免修读课程多的学生被重复加权" /></span></template><template #default="{row}"><b v-if="row.avgGpa != null" class="tnum" :style="{color:row.avgGpa>=3?'#0D9488':row.avgGpa<2?'#E11D48':'#4F46E5'}">{{ row.avgGpa }}</b><span v-else class="sa-faint">—</span></template></el-table-column>
        <el-table-column label="当前挂科率" width="90" align="right">
          <template #default="{row}"><span class="tnum" :style="{color:parseFloat(row.currentFailRate)>10?'#DC2626':'#6B7280'}">{{ row.currentFailRate }}</span></template>
        </el-table-column>
        <el-table-column prop="failRate" label="历史挂科经历率" width="120" align="right" />
        <el-table-column prop="alertRate" label="预警率" width="80" align="right" />
        <el-table-column label="课程学分通过占比" min-width="150"><template #default="{row}"><el-progress v-if="row.creditDone != null" :percentage="row.creditDone" :stroke-width="8" :color="row.creditDone>75?'#0D9488':'#D97706'" /><span v-else class="sa-faint">—</span></template></el-table-column>
        <el-table-column label="" width="36"><template #default><span style="color:var(--sa-faint)">&rsaquo;</span></template></el-table-column>
      </el-table>
      <div style="margin-top:8px;text-align:right">
        <el-button size="small" @click="goStudents">查看{{ data.scope?.restricted ? '范围内' : '全校' }}学生画像 →</el-button>
      </div>
    </div>

    <div v-if="data.scope?.restricted && canCompareColleges" class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">
        学院聚合对比
        <span class="extra">可比较他院聚合指标；仅本学院允许进入明细</span>
      </div>
      <el-alert type="info" :closable="false" show-icon :title="comparison.definition.boundary" style="margin-bottom:10px" />
      <el-table :data="comparison.items" stripe size="small" @row-click="goComparisonCollege">
        <el-table-column prop="collegeName" label="学院" min-width="170">
          <template #default="{row}">
            <span :class="row.canDrillDown ? 'college-link' : ''">{{ row.collegeName }}</span>
            <el-tag v-if="row.canDrillDown" size="small" effect="plain" style="margin-left:6px">本院</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="students" label="在籍学生" width="90" align="right" />
        <el-table-column prop="weightedAverageScore" width="118" align="right">
          <template #header><span>加权平均分 <KpiLabel label="" :formula="comparison.definition.weightedAverageScore" /></span></template>
          <template #default="{row}">{{ row.weightedAverageScore ?? '—' }}</template>
        </el-table-column>
        <el-table-column prop="averageGpa" width="100" align="right">
          <template #header><span>平均GPA <KpiLabel label="" :formula="comparison.definition.averageGpa" /></span></template>
          <template #default="{row}">{{ row.averageGpa ?? '—' }}</template>
        </el-table-column>
        <el-table-column width="130" align="right">
          <template #header><span>当前挂科学生率 <KpiLabel label="" :formula="comparison.definition.currentFailStudentRate" /></span></template>
          <template #default="{row}">{{ row.currentFailStudentRate == null ? '—' : `${row.currentFailStudentRate}%` }}</template>
        </el-table-column>
        <el-table-column width="125" align="right">
          <template #header><span>有效预警学生率 <KpiLabel label="" :formula="comparison.definition.activeAlertStudentRate" /></span></template>
          <template #default="{row}">{{ row.activeAlertStudentRate == null ? '—' : `${row.activeAlertStudentRate}%` }}</template>
        </el-table-column>
        <el-table-column label="明细权限" width="95" align="center">
          <template #default="{row}"><span :class="row.canDrillDown ? 'college-link' : 'sa-faint'">{{ row.canDrillDown ? '查看本院' : '仅可比较' }}</span></template>
        </el-table-column>
      </el-table>
    </div>

    <!-- GPA分布 (左1/2) + 挂科集中课程 TOP8 (右1/2) -->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">
            GPA 分布
            <el-select
              v-model="gpaCollege"
              size="small"
              style="width:148px"
              teleported
              placement="bottom-end"
              :popper-options="{ modifiers: [{ name: 'offset', options: { offset: [0, 4] } }] }"
              @change="loadGpa"
            >
              <el-option :label="data.scope?.label || '全校'" value="all" />
              <el-option v-for="c in data.colleges" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </div>
          <div class="gpa-donut-wrap">
            <EChart :option="gpaOption" :height="200" />
            <div class="gpa-donut-center">
              <div class="gpa-donut-total tnum">{{ gpaTotal.toLocaleString() }}</div>
              <div class="gpa-donut-cap">{{ gpaCollege === 'all' ? (data.scope?.label || '全校') : '所选学院' }}学生数</div>
            </div>
          </div>
          <div class="gpa-legend">
            <div v-for="(g, i) in gpaDisplay" :key="g.range || i" class="gpa-legend-row">
              <span class="dot" :style="{ background: GPA_COLORS[i % GPA_COLORS.length] }"></span>
              <span class="gpa-legend-label">{{ g.label }}</span>
              <span class="tnum gpa-legend-pct">{{ g.percent }}%</span>
            </div>
          </div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">
            <span>挂科集中课程 TOP8
              <KpiLabel label="" formula="挂科率=不及格人次÷总修读人次×100%，仅统计修读≥30人的课程" />
            </span>
            <span class="extra">点击课程查看详情</span>
          </div>
          <el-table :data="failCourses" stripe size="small" @row-click="goCourse" row-class-name="college-row-clickable">
            <el-table-column prop="name" label="课程" width="140"><template #default="{row}"><span class="college-link">{{ row.name }}</span></template></el-table-column>
            <el-table-column prop="college" label="开课学院" width="110" />
            <el-table-column label="挂科率" min-width="140"><template #default="{row}">
              <div style="display:flex;align-items:center;gap:8px">
                <el-progress :percentage="Math.min(row.failRate*5,100)" :show-text="false" :stroke-width="9" :color="parseFloat(row.failRate)>15?'#E11D48':'#D97706'" style="flex:1" />
                <span class="tnum" :style="{color:parseFloat(row.failRate)>15?'#E11D48':'#D97706',fontWeight:600,minWidth:'44px',textAlign:'right'}">{{ row.failRate }}%</span>
              </div>
            </template></el-table-column>
            <el-table-column prop="failCount" label="不及格" width="70" align="right" />
            <el-table-column prop="totalCount" label="修读人数" width="80" align="right">
              <template #default="{row}"><span>{{ row.totalCount.toLocaleString() }}</span></template>
            </el-table-column>
            <el-table-column prop="avgScore" label="平均分" width="70" align="right"><template #default="{row}"><b class="tnum">{{ row.avgScore }}</b></template></el-table-column>
            <el-table-column label="首次通过率" width="90" align="right">
              <template #default="{row}"><span class="tnum" :style="{color:(row.firstPassRate||0)>70?'#0D9488':'#E11D48'}">{{ row.firstPassRate ?? '—' }}{{ row.firstPassRate != null ? '%' : '' }}</span></template>
            </el-table-column>
            <el-table-column label="最终通过率" width="90" align="right">
              <template #default="{row}"><span class="tnum" :style="{color:(row.finalPassRate||0)>85?'#0D9488':'#D97706'}">{{ row.finalPassRate ?? '—' }}{{ row.finalPassRate != null ? '%' : '' }}</span></template>
            </el-table-column>
            <el-table-column label="" width="36"><template #default><span style="color:var(--sa-faint)">&rsaquo;</span></template></el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted, ref, computed } from 'vue'
import { http } from '@/utils/http';
import { useRoute, useRouter } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue';
import KpiCard from '@/components/KpiCard.vue';
import EChart from '@/components/EChart.vue';
import BusinessPageContext from '@/components/BusinessPageContext.vue';
import { getFilterMeta, type SemesterOpt } from '@/utils/meta';
import { authStore } from '@/store/auth';
import { useBusinessPageTitle } from '@/utils/businessPage';
const pageTitle = useBusinessPageTitle('/admin/dashboard', '教学数据总览');
const router = useRouter();
const route = useRoute();
const data = reactive<any>({ kpi:[], colleges:[], gpaDist:[], gpaDistByCollege:{}, scope:{ restricted:false,label:'全校' }, evidence:{} });
const comparison = reactive<any>({ items:[], definition:{} });
const canCompareColleges = computed(() => !!authStore.user?.permissionContext?.comparisonScope?.allowOtherOrganizations);

// 学期筛选
const semesters = ref<SemesterOpt[]>([]);
const fSemester = ref('');

// V1.1 KPI 分组
const schoolKpis = computed(() => data.kpi.filter((k:any) => k.group === '在校生'))
const gradKpis = computed(() => data.kpi.filter((k:any) => k.group === '毕业生'))
const gpaCollege = ref('all');
const gpaDisplay = ref([] as any[]);
const gpaTotal = ref(0);
const failCourses = ref([] as any[]);
const pageLoading = ref(false);
const loadError = ref('');
const updatedAt = ref('');

// GPA 5 档色：不及格→优秀（玫红/琥珀/靛/靛蓝/青绿）
const GPA_COLORS = ['#E11D48', '#D97706', '#6366F1', '#4F46E5', '#0D9488'];

async function loadData() {
  pageLoading.value = true;
  loadError.value = '';
  const qs = fSemester.value ? `?semester=${fSemester.value}` : '';
  try {
    const d = await http.get(`/admin/dashboard${qs}`);
    if (!d) return;
    Object.assign(data, d);
    if (data.scope?.restricted && canCompareColleges.value) {
      const compare = await http.get(`/admin/meta/college-comparison${qs}`);
      Object.assign(comparison, compare || {});
    } else {
      comparison.items = [];
    }
    failCourses.value = d.failCourses || [];
    if (gpaCollege.value !== 'all' && !data.gpaDistByCollege?.[gpaCollege.value]) gpaCollege.value = 'all';
    loadGpa();
    updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
  } catch (error:any) {
    loadError.value = error?.message || '数据加载失败，请稍后重试';
  } finally {
    pageLoading.value = false;
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

function scoreColor(s: number) { return s > 74 ? '#0D9488' : s > 70 ? '#D97706' : '#E11D48'; }
function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('预警')) return 'danger';
  if (label.includes('挂科')) return 'amber';
  if (label.includes('毕业') || label.includes('学位')) return 'teal';
  return 'primary';
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
</style>

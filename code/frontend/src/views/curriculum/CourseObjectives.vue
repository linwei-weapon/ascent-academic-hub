<template>
  <div>
    <template v-if="!embedded">
      <el-breadcrumb separator="›" style="margin-bottom:12px">
        <el-breadcrumb-item :to="{path:'/admin/curriculum'}">培养方案分析</el-breadcrumb-item>
        <el-breadcrumb-item>课程目标达成度</el-breadcrumb-item>
      </el-breadcrumb>

      <div class="sa-head-row">
        <div>
          <h2 class="sa-page-title">课程目标达成度</h2>
          <p class="sa-page-sub">
            以培养方案各模块作为课程目标维度，基于该模块所含课程的学生成绩计算达成度 ·
            达成标准 ≥65%
          </p>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <span class="sa-faint" style="font-size:12px">专业：</span>
          <el-select v-model="major" size="small" style="width:160px" @change="load">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </div>
      </div>
    </template>

    <template v-if="data.objectives.length">
      <!-- 总达成度 -->
      <div class="sa-kpi-row" style="margin-bottom:16px">
        <KpiCard
          label="综合达成度"
          :value="data.overallAchievement"
          :sub="data.overallStatus"
          :tone="data.overallAchievement >= 65 ? 'teal' : 'danger'"
          hint="各课程目标按学分加权平均"
        />
      </div>

      <!-- 达成度横向柱状图 -->
      <div class="sa-card" style="margin-bottom:16px">
        <div class="sa-card-title">各课程目标达成度</div>
        <EChart v-if="data.objectives.length" :option="barOption" :height="Math.max(180, data.objectives.length * 38)" />
      </div>

      <!-- 明细表 -->
      <div class="sa-card">
        <div class="sa-card-title">课程目标达成明细</div>
        <DataTable :columns="objectiveCols" :data="data.objectives" storage-key="curriculum:course-objectives" size="small">
          <template #col-avgScore="{row}"><span class="tnum">{{ row.avgScore }}</span></template>
          <template #col-passRate="{row}"><span class="tnum">{{ row.passRate }}%</span></template>
          <template #col-achievement="{row}">
            <div style="display:flex;align-items:center;gap:10px">
              <el-progress
                :percentage="Math.min(row.achievement, 100)"
                :stroke-width="10"
                :color="row.achievement >= 65 ? '#0D9488' : '#E11D48'"
                style="flex:1"
              />
              <span class="tnum" :style="{color: row.achievement >= 65 ? '#0D9488' : '#E11D48', fontWeight:700, minWidth:'42px', textAlign:'right'}">{{ row.achievement }}%</span>
              <el-tag :type="row.status === '达标' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
            </div>
          </template>
        </DataTable>
      </div>
    </template>

    <div v-else class="sa-card" style="margin-top:14px">
      <el-empty :image-size="110" description="暂无课程目标达成度数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { ref, reactive, computed, onMounted } from 'vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'

// 课程目标达成明细表列定义（M6 DataTable）
const objectiveCols: DataTableColumn[] = [
  { key: 'objective', label: '课程目标（培养方案模块）', minWidth: 180 },
  { key: 'courseCount', label: '覆盖课程数', width: 100, align: 'center' },
  { key: 'credits', label: '学分', width: 80, align: 'center' },
  { key: 'avgScore', label: '平均分', width: 80, align: 'center' },
  { key: 'passRate', label: '通过率', width: 90, align: 'center' },
  { key: 'achievement', label: '达成度', minWidth: 240 },
]

const props = defineProps<{ majorId?: string }>()
const embedded = computed(() => !!props.majorId)

const majors = [
  { id: 'me_safety', name: '安全工程' },
  { id: 'pe_ocean', name: '海洋油气工程' },
]
const major = ref(props.majorId || 'me_safety')

const data = reactive<{ objectives: any[]; overallAchievement: number; overallStatus: string }>({
  objectives: [], overallAchievement: 0, overallStatus: '',
})

async function load() {
  try {
    const d = await http.get('/admin/curriculum/objectives/' + major.value)
    if (d) Object.assign(data, d)
    else data.objectives = []
  } catch {
    data.objectives = []
  }
}

const barOption = computed(() => {
  const items = [...data.objectives]
  return {
    grid: { left: 6, right: 60, top: 6, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (ps: any) => {
        const d = items[ps[0].dataIndex]
        return `${d.objective}<br/>达成度：${d.achievement}% · 平均分：${d.avgScore}<br/>通过率：${d.passRate}% · ${d.status}`
      },
    },
    xAxis: { type: 'value', max: 100, axisLabel: { color: '#94A3B8', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: {
      type: 'category',
      data: items.map((o: any) => o.objective),
      axisLabel: { color: '#475569', fontSize: 11 },
      axisLine: { lineStyle: { color: '#E2E8F0' } },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      barWidth: '56%',
      data: items.map((o: any) => ({
        value: o.achievement,
        itemStyle: { color: o.achievement >= 65 ? '#0D9488' : '#E11D48', borderRadius: [0, 4, 4, 0] },
      })),
      label: { show: true, position: 'right', formatter: '{c}%', color: '#64748B', fontSize: 11 },
      markLine: {
        silent: true, symbol: 'none',
        data: [{ xAxis: 65 }],
        lineStyle: { color: '#D97706', type: 'dashed' },
        label: { formatter: '达标线 65%', color: '#D97706', fontSize: 10 },
      },
    }],
  }
})

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
</style>

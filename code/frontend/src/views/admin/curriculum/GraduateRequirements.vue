<template>
  <div>
    <template v-if="!embedded">
      <el-breadcrumb separator="›" style="margin-bottom:12px">
        <el-breadcrumb-item :to="{path:'/admin/curriculum'}">培养方案分析</el-breadcrumb-item>
        <el-breadcrumb-item>毕业要求达成度</el-breadcrumb-item>
      </el-breadcrumb>

      <div class="sa-head-row">
        <div>
          <h2 class="sa-page-title">毕业要求达成度</h2>
          <p class="sa-page-sub">
            培养方案毕业要求 × 课程模块支撑矩阵，基于课程目标达成度加权计算 ·
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

    <template v-if="data.requirements.length">
      <!-- 总达成度 -->
      <div class="sa-kpi-row" style="margin-bottom:16px">
        <KpiCard
          label="毕业要求综合达成度"
          :value="data.overallAchievement"
          :sub="data.overallStatus"
          :tone="data.overallAchievement >= 65 ? 'teal' : 'danger'"
          hint="12 条毕业要求按学分加权平均"
        />
      </div>

      <!-- 雷达图 -->
      <el-row :gutter="16" style="margin-bottom:16px">
        <el-col :span="10">
          <div class="sa-card">
            <div class="sa-card-title">毕业要求达成度雷达图</div>
            <EChart v-if="data.requirements.length" :option="radarOption" :height="360" />
          </div>
        </el-col>
        <el-col :span="14">
          <div class="sa-card">
            <div class="sa-card-title">达成度明细</div>
            <el-table :data="data.requirements" size="small" max-height="360">
              <el-table-column prop="index" label="#" width="44" align="center" />
              <el-table-column prop="name" label="毕业要求" width="160" />
              <el-table-column label="达成度" min-width="200">
                <template #default="{row}">
                  <div style="display:flex;align-items:center;gap:8px">
                    <el-progress
                      :percentage="Math.min(row.achievement, 100)"
                      :stroke-width="8"
                      :color="row.achievement >= 65 ? '#0D9488' : '#E11D48'"
                      style="flex:1"
                    />
                    <span class="tnum" :style="{color: row.achievement >= 65 ? '#0D9488' : '#E11D48', fontWeight:700, minWidth:'40px', textAlign:'right'}">{{ row.achievement }}%</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="70" align="center">
                <template #default="{row}">
                  <el-tag :type="row.status === '达标' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-col>
      </el-row>

      <!-- 支撑矩阵表 -->
      <div class="sa-card">
        <div class="sa-card-title">课程模块 → 毕业要求支撑矩阵 <span class="extra">数字为支撑权重（0-3）</span></div>
        <div style="overflow-x:auto">
          <table class="matrix-table">
            <thead>
              <tr>
                <th class="matrix-hd module-col">课程模块</th>
                <th v-for="(req, i) in reqNames" :key="i" class="matrix-hd req-col">{{ i + 1 }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="mod in planModules" :key="mod">
                <td class="matrix-cell module-col">{{ mod }}</td>
                <td v-for="(req, i) in reqNames" :key="i" class="matrix-cell req-col" :class="weightClass(getWeight(mod, i))">
                  {{ getWeight(mod, i) || '' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="sa-faint" style="font-size:11px;margin-top:8px">
          ※ 12 条毕业要求编号：1-工程知识 2-问题分析 3-设计/开发解决方案 4-研究 5-使用现代工具
          6-工程与社会 7-环境和可持续发展 8-职业规范 9-个人和团队 10-沟通 11-项目管理 12-终身学习
        </div>
      </div>
    </template>

    <div v-else class="sa-card" style="margin-top:14px">
      <el-empty :image-size="110" description="暂无毕业要求达成度数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { ref, reactive, computed, onMounted } from 'vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'

const props = defineProps<{ majorId?: string }>()
const embedded = computed(() => !!props.majorId)

const majors = [
  { id: 'me_safety', name: '安全工程' },
  { id: 'pe_ocean', name: '海洋油气工程' },
]
const major = ref(props.majorId || 'me_safety')

const reqNames = computed(() => data.requirementNames || [])
const weightMatrix = computed<Record<string, number[]>>(() => data.supportMatrix || {})
const planModules = computed(() => data.planModules || [])

function getWeight(mod: string, idx: number): number {
  return weightMatrix.value[mod]?.[idx] || 0
}

function weightClass(w: number): string {
  if (w >= 3) return 'w-high'
  if (w >= 2) return 'w-mid'
  if (w >= 1) return 'w-low'
  return 'w-none'
}

const data = reactive<{ requirements: any[]; overallAchievement: number; overallStatus: string;
  requirementNames: string[]; supportMatrix: Record<string, number[]>; planModules: string[] }>({
  requirements: [], overallAchievement: 0, overallStatus: '', requirementNames: [], supportMatrix: {}, planModules: [],
})

async function load() {
  try {
    const d = await http.get('/admin/curriculum/graduate-requirements/' + major.value)
    if (d) Object.assign(data, d)
    else data.requirements = []
  } catch {
    data.requirements = []
  }
}

// 雷达图指标最大值100
const radarOption = computed(() => {
  const items = data.requirements || []
  return {
    radar: {
      center: ['50%', '54%'],
      radius: '64%',
      indicator: items.map((r: any) => ({ name: r.index + '.' + r.name, max: 100 })),
      axisName: { color: '#475569', fontSize: 11, borderRadius: 3, padding: [3, 5] as any },
      splitArea: { areaStyle: { color: ['#fff', '#f8fafc'] } },
      splitLine: { lineStyle: { color: '#E2E8F0' } },
    },
    series: [{
      type: 'radar',
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 2, color: '#4F46E5' },
      areaStyle: { color: 'rgba(79,70,229,0.12)' },
      itemStyle: { color: '#4F46E5' },
      data: [{
        value: items.map((r: any) => r.achievement),
        name: '达成度',
      }],
      markLine: {
        silent: true, symbol: 'none',
        data: [{ name: '达标线', value: 65 }],
        lineStyle: { color: '#D97706', type: 'dashed' },
        label: { formatter: '65%', color: '#D97706', fontSize: 10 },
      },
    }],
  }
})

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.matrix-hd { padding: 6px 4px; text-align: center; color: #64748B; font-weight: 600; background: #f8fafc; border: 1px solid #E2E8F0; }
.matrix-cell { padding: 4px; text-align: center; border: 1px solid #E2E8F0; font-weight: 600; }
.module-col { min-width: 130px; text-align: left; padding-left: 8px; color: #334155; }
.req-col { min-width: 28px; }
.w-high { background: #4F46E5; color: #fff; }
.w-mid { background: #A5B4FC; color: #1E293B; }
.w-low { background: #EEF2FF; color: #475569; }
.w-none { background: #fff; color: #CBD5E1; }
</style>

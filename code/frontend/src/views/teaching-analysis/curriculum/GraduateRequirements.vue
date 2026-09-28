<!-- 培养质量分析：GraduateRequirements 页面或专用组件，保留原业务与权限行为。 -->
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
      <el-alert type="warning" :closable="false" show-icon :title="data.boundaryNote" style="margin-bottom:14px" />
      <div class="sa-kpi-row" style="margin-bottom:16px">
        <KpiCard label="毕业要求" :value="data.requirements.length" sub="方案原文" tone="teal" hint="当前专业培养方案中明确列出的毕业要求条数" />
        <KpiCard label="独立指标点" :value="data.indicatorCount" sub="尚未提供" tone="amber" hint="原始材料中独立编号的毕业要求指标点" />
        <KpiCard label="课程支撑关系" :value="data.courseMappingCount" sub="尚未提供" tone="amber" hint="课程对毕业要求或指标点的正式支撑矩阵记录数" />
      </div>
      <div class="sa-card">
        <div class="sa-card-title">毕业要求原文 <span class="extra">不同专业条数可以不同，不套用通用12条模板</span></div>
        <div v-for="row in data.requirements" :key="row.requirementId" class="real-requirement">
          <el-tag size="small">{{ row.requirementNo }}</el-tag>
          <div><b>{{ row.title }}</b><p>{{ row.text }}</p><small>来源：{{ row.sourceFile }}</small></div>
        </div>
      </div>
      <div class="sa-card" style="margin-top:14px">
        <div class="sa-card-title">达成度计算条件</div>
        <p class="evidence-note">只有取得“指标点—支撑课程—评价环节—目标值—实际评价结果”的完整证据链后，系统才展示达成度和雷达图。当前不再用课程平均分或通过率代替毕业要求达成度。</p>
      </div>
    </template>

    <div v-else class="sa-card" style="margin-top:14px">
      <el-empty :image-size="110" description="暂无毕业要求达成度数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import * as curriculumApi from '@/api/teachingAnalysis/curriculum'


import { ref, reactive, computed, onMounted, watch } from 'vue'
import KpiCard from '@/components/KpiCard.vue'
const props = defineProps<{ majorId?: string }>()
const embedded = computed(() => !!props.majorId)

const majors = [
  { id: 'me_safety', name: '安全工程' },
  { id: 'pe_ocean', name: '海洋油气工程' },
]
const major = ref(props.majorId || 'me_safety')

const data = reactive<{
  requirements: any[]; indicatorCount: number; courseMappingCount: number; boundaryNote: string;
}>({
  requirements: [], indicatorCount: 0, courseMappingCount: 0, boundaryNote: '',
})

// 按当前页面上下文读取数据，沿用原加载状态和异常处理。
async function load() {
  try {
    const d = await curriculumApi.getGraduateRequirementPlan(major.value)
    if (d) Object.assign(data, d.evidence, { requirements:d.requirements || [] })
    else data.requirements = []
  } catch {
    data.requirements = []
  }
}

// 进入页面时执行原初始化流程，恢复路由条件与可用选项。
onMounted(load)
// 按既有监听条件响应路由、筛选或身份变化，保留原重载与清理时机。
watch(() => props.majorId, value => { if (value) { major.value = value; load() } })
</script>

<style scoped lang="scss">
// 按页面区域、后代元素和状态组织，保留原选择器顺序与作用范围。
.sa-head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.real-requirement {
  display: flex;
  gap: 10px;
  padding: 12px 0;
  border-bottom: 1px solid var(--sa-border);
  &:last-child {
    border-bottom: 0;
  }
  b {
    color: #334155;
    font-size: 13px;
  }
  p {
    color: #475569;
    font-size: 12px;
    line-height: 1.7;
    margin: 6px 0;
  }
  small {
    color: #94A3B8;
  }
}

.evidence-note {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.8;
}
</style>

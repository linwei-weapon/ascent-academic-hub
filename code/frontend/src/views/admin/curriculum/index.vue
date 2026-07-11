<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">培养质量分析</h2>
        <p class="sa-page-sub">
          数据来源：培养方案表 + 方案课程表 + 学生成绩 ·
          <span v-if="plan.name">{{ plan.name }} · {{ plan.grade }} · {{ plan.college }} · 方案版本 {{ plan.planVersion }}</span>
          <span v-else>仅已脱敏接入的真实方案可查</span>
        </p>
      </div>
      <el-select v-model="selectedMajor" size="small" style="width:200px" @change="loadPlan">
        <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
      </el-select>
    </div>

    <el-tabs v-model="activeTab">
      <!-- Tab 1: 培养方案详情 -->
      <el-tab-pane label="培养方案详情" name="plan">
        <template v-if="hasPlan">
          <el-alert type="info" :closable="false" style="margin-bottom:14px"
            :title="`${plan.dataSource || '培养方案'}：${plan.coverageNote || '按专业与年级匹配适用方案'}`" />
          <div class="sa-kpi-row">
            <KpiCard v-for="k in planKpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="k.tone" />
          </div>

          <el-row :gutter="16" style="margin-bottom:16px">
            <el-col :span="10">
              <div class="sa-card">
                <div class="sa-card-title">学分结构 <KpiLabel label="" formula="各课程模块学分占总学分比例" /></div>
                <EChart v-if="creditDist.length" :option="creditOption" :height="240" />
                <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
              </div>
            </el-col>
            <el-col :span="14">
              <div class="sa-card">
                <div class="sa-card-title">各模块学分与课程数 <span class="extra">★ 为核心课程</span></div>
                <el-table :data="moduleSummary" size="small">
                  <el-table-column prop="name" label="模块" min-width="160" />
                  <el-table-column label="性质" width="80"><template #default="{row}">
                    <el-tag :type="row.required?'danger':'warning'" size="small">{{ row.required?'必修':'选修' }}</el-tag>
                  </template></el-table-column>
                  <el-table-column prop="credits" label="学分" width="70" align="right"><template #default="{row}"><b class="tnum">{{ row.credits }}</b></template></el-table-column>
                  <el-table-column prop="courseCount" label="课程数" width="70" align="right"><template #default="{row}"><span class="tnum">{{ row.courseCount }}</span></template></el-table-column>
                  <el-table-column prop="coreCount" label="核心" width="60" align="right"><template #default="{row}"><span class="tnum" :style="{color:row.coreCount?'#0D9488':'#94A3B8'}">{{ row.coreCount || '—' }}</span></template></el-table-column>
                </el-table>
              </div>
            </el-col>
          </el-row>

          <div v-for="(mod, mi) in plan.modules" :key="mi" class="sa-card" style="margin-bottom:14px">
            <div class="sa-card-title" style="justify-content:space-between;display:flex">
              <span>{{ mod.name }}</span>
              <el-tag :type="mod.required?'danger':'warning'" size="small">
                {{ mod.required?'必修':'选修' }} · {{ mod.credits }}学分
                <span v-if="mod.electiveRequired"> · 要求≥{{ mod.electiveRequired }}学分</span>
              </el-tag>
            </div>
            <div v-for="sm in mod.subModules" :key="sm.name">
              <el-table :data="sm.courses" size="small">
                <el-table-column prop="code" label="课程代码" width="130" />
                <el-table-column prop="name" label="课程名称" min-width="200">
                  <template #default="{row}"><span :style="{fontWeight:row.name.includes('★')?'700':'400'}">{{ row.name }}</span></template>
                </el-table-column>
                <el-table-column prop="credits" label="学分" width="64" align="right"><template #default="{row}"><span class="tnum">{{ row.credits }}</span></template></el-table-column>
                <el-table-column prop="hours" label="学时" width="64" align="right"><template #default="{row}"><span class="tnum">{{ row.hours }}</span></template></el-table-column>
                <el-table-column prop="term" label="学期" width="64" align="center">
                  <template #default="{row}"><el-tag size="small" :type="row.term<=4?'success':row.term<=6?'warning':'info'">{{ row.term||'-' }}</el-tag></template>
                </el-table-column>
                <el-table-column prop="dept" label="开课院系" width="150" />
              </el-table>
            </div>
          </div>

          <!-- 毕业要求文本（原独立Tab内容，合并到此处） -->
          <div class="sa-card" style="margin-bottom:16px" v-if="plan.graduationRequirements.length">
            <div class="sa-card-title">毕业生应获得的知识和能力</div>
            <div v-for="(r,i) in plan.graduationRequirements" :key="i" class="grad-row">
              <el-tag size="small" type="primary">{{ i+1 }}</el-tag>
              <span>{{ r }}</span>
            </div>
          </div>
          <div class="sa-card" v-if="plan.degreeRequirement">
            <div class="sa-card-title">学位授予条件</div>
            <p style="font-size:13px;color:#475569;line-height:1.7">{{ plan.degreeRequirement }}</p>
          </div>
        </template>
        <el-empty v-else description="" :image-size="100">
          <template #description>
            <div style="font-size:13px;color:#64748B">暂无该专业培养方案数据</div>
            <div style="font-size:11px;color:#94A3B8;margin-top:4px">当前已接入真实脱敏培养方案：安全工程、海洋油气工程</div>
          </template>
        </el-empty>
      </el-tab-pane>

      <!-- Tab 2: 课程目标达成度 -->
      <el-tab-pane label="课程目标达成度" name="objectives">
        <CourseObjectivesView v-if="activeTab === 'objectives'" :major-id="selectedMajor" />
      </el-tab-pane>

      <!-- Tab 3: 毕业要求达成度 -->
      <el-tab-pane label="毕业要求达成度" name="gradReqs">
        <GraduateRequirementsView v-if="activeTab === 'gradReqs'" :major-id="selectedMajor" />
      </el-tab-pane>

      <!-- Tab 4: 学业进度监控 -->
      <el-tab-pane label="学业进度监控" name="progress">
        <ProgressView v-if="activeTab === 'progress'" :major-id="selectedMajor" />
      </el-tab-pane>
      <el-tab-pane label="例外规则治理" name="governance">
        <GovernanceView v-if="activeTab === 'governance'" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { ref, reactive, computed, onMounted } from 'vue'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import CourseObjectivesView from './CourseObjectives.vue'
import GraduateRequirementsView from './GraduateRequirements.vue'
import ProgressView from './Progress.vue'
import GovernanceView from './Governance.vue'

const majors = [
  { id: 'me_safety', name: '安全工程' },
  { id: 'pe_ocean', name: '海洋油气工程' },
]
const selectedMajor = ref('me_safety')
const activeTab = ref('plan')

const plan = reactive<any>({
  name: '', grade: '', college: '', totalCredits: 0, requiredCredits: 0,
  electiveMinCredits: 0, practiceCredits: 0, modules: [], graduationRequirements: [], degreeRequirement: '',
  planVersion: '', applicableGrade: '', dataSource: '', coverageNote: '',
})
const hasPlan = ref(true)

function resetPlan() {
  Object.assign(plan, {
    name: '', grade: '', college: '', totalCredits: 0, requiredCredits: 0,
    electiveMinCredits: 0, practiceCredits: 0, modules: [], graduationRequirements: [], degreeRequirement: '',
    planVersion: '', applicableGrade: '', dataSource: '', coverageNote: '',
  })
}

const planKpis = computed(() => [
  { label: '总学分', value: plan.totalCredits, formula: '毕业最低总学分要求', tone: 'primary' as const },
  { label: '必修课学分', value: plan.requiredCredits, formula: '通识必修+专业基础必修+专业必修+实践必修', tone: 'teal' as const },
  { label: '选修课最低', value: plan.electiveMinCredits, formula: '通识选修+专业基础选修+专业方向选修', tone: 'amber' as const },
  { label: '实践环节', value: plan.practiceCredits, formula: '单独设置的实践教学环节学分', tone: 'primary' as const },
])

const moduleSummary = computed(() => (plan.modules || []).map((m: any) => {
  const courses = (m.subModules || []).flatMap((sm: any) => sm.courses || [])
  return {
    name: m.name, required: m.required, credits: m.credits,
    courseCount: courses.length,
    coreCount: courses.filter((c: any) => String(c.name).includes('★')).length,
  }
}))

const MOD_COLORS = ['#4F46E5', '#0D9488', '#D97706', '#6366F1', '#0EA5E9', '#94A3B8', '#A855F7', '#E11D48']
const creditDist = computed(() => (plan.modules || []).filter((m: any) => (m.credits || 0) > 0))
const creditOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c} 学分（{d}%）' },
  legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748B', fontSize: 11 } },
  series: [{
    type: 'pie', radius: ['46%', '72%'], center: ['32%', '50%'], avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 }, label: { show: false },
    data: creditDist.value.map((m: any, i: number) => ({ name: m.name, value: m.credits, itemStyle: { color: MOD_COLORS[i % MOD_COLORS.length] } })),
  }],
}))

async function loadPlan() {
  try {
    const d = await http.get('/admin/curriculum/plan/' + selectedMajor.value)
    if (d) { Object.assign(plan, d); hasPlan.value = true }
    else { hasPlan.value = false; resetPlan() }
  } catch {
    hasPlan.value = false; resetPlan()
  }
}

onMounted(loadPlan)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.grad-row { padding: 8px 0; border-bottom: 1px solid var(--sa-border); font-size: 13px; display: flex; gap: 8px; align-items: flex-start; color: #334155; }
.grad-row:last-child { border-bottom: none; }
</style>

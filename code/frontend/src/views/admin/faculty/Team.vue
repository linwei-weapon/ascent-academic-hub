<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/faculty'}">师资结构分析</el-breadcrumb-item>
      <el-breadcrumb-item>课程教学团队分析</el-breadcrumb-item>
    </el-breadcrumb>

    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">课程教学团队分析</h2>
        <p class="sa-page-sub">按课程查看授课团队构成、职称分布与师资缺口风险</p>
      </div>
    </div>

    <!-- 课程搜索 -->
    <div class="sa-card" style="margin-bottom:16px">
      <div style="display:flex;gap:12px;align-items:center">
        <el-input v-model="courseQuery" placeholder="输入课程名称或代码" size="small" style="width:360px" clearable
          @keyup.enter="searchCourse" />
        <el-button type="primary" size="small" @click="searchCourse" :loading="searching">查询</el-button>
        <span v-if="searchResults.length" class="sa-faint" style="font-size:12px">
          搜索到 {{ searchResults.length }} 门课程，点击选择：
        </span>
      </div>
      <div v-if="searchResults.length" style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px">
        <el-tag v-for="c in searchResults" :key="c.id" type="primary" effect="plain" style="cursor:pointer"
          @click="selectCourse(c)">
          {{ c.name }}（{{ c.code }}）
        </el-tag>
      </div>
    </div>

    <template v-if="selectedCourse">
      <div class="filter-banner">
        <span>当前课程：<b>{{ selectedCourse.name }}</b>（{{ selectedCourse.code }}）· {{ selectedCourse.dept || '' }}</span>
      </div>
      <el-alert v-if="evidence.limitation" type="warning" :closable="false" show-icon style="margin-bottom:12px"
        title="证据边界：团队成员与授课记录为真实数据，年龄、学历和教龄为模拟画像"
        :description="evidence.limitation" />

      <!-- KPI 行 -->
      <div class="sa-kpi-row">
        <KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="k.tone" />
      </div>

      <el-row :gutter="16" style="margin-bottom:16px">
        <!-- 团队成员表 -->
        <el-col :span="14">
          <div class="sa-card">
            <div class="sa-card-title">授课团队成员</div>
            <el-table v-if="team.length" :data="team" size="small" @row-click="goTeacher" row-class-name="row-clickable">
              <el-table-column prop="name" label="教师" width="90"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
              <el-table-column prop="title" label="职称" width="100" />
              <el-table-column prop="education" label="学历（模拟）" width="105" />
              <el-table-column prop="age" label="年龄（模拟）" width="95" align="right" />
              <el-table-column prop="teachingYears" label="教龄（模拟）" width="95" align="right" />
              <el-table-column prop="teachingCount" label="近两学期教学班" width="115" align="right" />
              <el-table-column prop="coursesThisSemester" label="本学期授课门数" width="110" align="right" />
              <el-table-column label="历史教室倾向（行为推断）" min-width="165"><template #default="{row}">{{ row.observedClassroom }}<span v-if="row.observedClassroomPct" class="sa-faint"> · {{ row.observedClassroomPct }}%</span></template></el-table-column>
            </el-table>
            <div v-else class="sa-faint" style="font-size:12px;padding:20px;text-align:center">暂无团队成员数据</div>
          </div>
        </el-col>

        <!-- 职称分布 -->
        <el-col :span="10">
          <div class="sa-card" style="height:100%">
            <div class="sa-card-title">团队职称分布 <KpiLabel label="" formula="授课团队中各职称层级的人数占比" /></div>
            <EChart v-if="titleDist.length" :option="titleDistOption" :height="200" />
            <div v-else class="sa-faint" style="font-size:12px;padding:60px 0;text-align:center">请在下方查询后查看图表</div>
          </div>
        </el-col>
      </el-row>

      <!-- 梯队模拟场景 -->
      <div class="sa-card">
        <div class="sa-card-title">师资梯队模拟场景</div>
        <el-alert v-if="gapRisks.length === 0" title="当前模拟画像未识别明显梯队风险，仍需真实人员档案核验" type="info" :closable="false" show-icon />
        <div v-else>
          <div v-for="(r, i) in gapRisks" :key="i" style="margin-bottom:8px">
            <el-alert :title="r.title" :description="r.desc" :type="r.level === '高' ? 'error' : r.level === '中' ? 'warning' : 'info'"
              :closable="false" show-icon />
          </div>
        </div>
      </div>

      <div class="sa-card" style="margin-top:16px">
        <div class="sa-card-title">团队建设核验建议 <span class="extra">仅依据真实授课覆盖与数据质量台账</span></div>
        <el-alert type="info" :closable="false" show-icon :title="decisionBoundary" style="margin-bottom:10px" />
        <el-table :data="supportSuggestions" size="small" stripe>
          <el-table-column prop="level" label="关注级别" width="90" />
          <el-table-column prop="topic" label="主题" width="150" />
          <el-table-column prop="basis" label="事实依据" min-width="220" />
          <el-table-column prop="suggestion" label="核验建议" min-width="300" />
          <el-table-column prop="readiness" label="状态" width="100" />
        </el-table>
      </div>
    </template>

    <el-empty v-else description="请输入课程名称查询授课团队" :image-size="80" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import { http } from '@/utils/http'
import { useRouter } from 'vue-router'

const router = useRouter()

const courseQuery = ref('')
const searching = ref(false)
const searchResults = ref<any[]>([])
const selectedCourse = ref<any>(null)
const team = ref<any[]>([])
const gapRisks = ref<any[]>([])
const evidence = ref<any>({})
const supportSuggestions = ref<any[]>([])
const decisionBoundary = ref('')

const kpis = ref<any[]>([])

const titleDist = computed(() => {
  const m: Record<string, number> = {}
  team.value.forEach(t => {
    const title = t.title || '其他'
    m[title] = (m[title] || 0) + 1
  })
  return Object.entries(m).map(([name, value]) => ({ name, value }))
})

const TITLE_COLORS = ['#4F46E5', '#0D9488', '#D97706', '#6366F1', '#0EA5E9', '#94A3B8']
const titleDistOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c}人（{d}%）' },
  legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748B', fontSize: 11 } },
  series: [{
    type: 'pie', radius: ['46%', '72%'], center: ['34%', '50%'], avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 },
    label: { show: false },
    data: titleDist.value.map((d: any, i: number) => ({ name: d.name, value: d.value, itemStyle: { color: TITLE_COLORS[i % TITLE_COLORS.length] } })),
  }],
}))

async function searchCourse() {
  if (!courseQuery.value.trim()) return
  searching.value = true
  try {
    const data = await http.get<any>(`/admin/faculty/team/search?q=${encodeURIComponent(courseQuery.value)}`)
    searchResults.value = data || []
  } catch { /* http 工具已 toast */ }
  finally { searching.value = false }
}

async function selectCourse(c: any) {
  selectedCourse.value = c
  searchResults.value = []
  courseQuery.value = ''
  await loadTeam(c.id)
}

async function loadTeam(courseId: string) {
  try {
    const data = await http.get<any>(`/admin/faculty/team/${courseId}`)
    team.value = data.team || []
    gapRisks.value = data.gapRisks || []
    evidence.value = data.evidence || {}
    supportSuggestions.value = data.supportSuggestions || []
    decisionBoundary.value = data.decisionBoundary || ''
    kpis.value = data.kpis || [
      { label: '团队人数', value: team.value.length, formula: '参与授课的教师总数', tone: 'primary' as const },
      { label: '教授占比', value: computeProfRatio(), formula: '教授人数 ÷ 团队总人数', tone: 'teal' as const },
      { label: '模拟平均教龄', value: computeAvgAge(), formula: '模拟画像中的团队成员教龄平均值', tone: 'primary' as const },
      { label: '模拟风险场景', value: gapRisks.value.length ? `${gapRisks.value.length}项` : '未识别', formula: '基于模拟年龄画像识别，需真实档案核验', tone: gapRisks.value.length ? 'danger' as const : 'primary' as const },
    ]
  } catch { /* http 工具已 toast */ }
}

function goTeacher(row:any) { router.push('/admin/faculty/' + row.teacherId) }

function computeProfRatio() {
  if (!team.value.length) return '—'
  const profs = team.value.filter(t => t.title === '教授')
  return Math.round(profs.length / team.value.length * 100) + '%'
}

function computeAvgAge() {
  const arr = team.value.map(t => t.teachingYears).filter(v => typeof v === 'number')
  if (!arr.length) return '—'
  return (arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(1) + '年'
}
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.filter-banner { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 10px; padding: 8px 14px; margin-bottom: 12px; font-size: 12px; color: var(--sa-primary); }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
</style>

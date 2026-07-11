<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">师资结构分析</h2>
        <p class="sa-page-sub">数据来源：教职工画像(fact_teacher_profile) + 真实排课(fact_lesson) + 真实成绩(fact_grade)</p>
      </div>
      <div style="display:flex;gap:8px">
        <el-select v-model="fTitle" size="small" style="width:130px" clearable placeholder="全部职称" @change="load">
          <el-option v-for="t in titles" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="fSemester" size="small" style="width:180px" clearable placeholder="全部学期" @change="load">
          <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </div>
    </div>

    <el-alert v-if="evidence.limitation" type="warning" :closable="false" show-icon style="margin-bottom:12px"
      title="师资画像证据说明：职称与教学记录来自真实源，学历、年龄、学缘和教龄为模拟字段"
      :description="evidence.limitation" />

    <div v-if="collegeFilter" class="filter-banner">
      <span>当前学院视图：<b>{{ collegeFilter.name }}</b></span>
      <el-button size="small" type="primary" text @click="clearCollegeFilter">← 返回全校视图</el-button>
    </div>

    <div class="sa-kpi-row">
      <KpiCard v-for="k in facultyKpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="kpiTone(k.label, k.value)" />
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="6" v-for="(d, di) in data.structure" :key="d.title">
        <div class="sa-card" style="height:100%">
          <div class="sa-card-title" style="font-size:13px">{{ d.title }}</div>
          <EChart v-if="d.items && d.items.length" :option="structOption(d, di)" :height="160" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="14">
        <div class="sa-card">
          <div class="sa-card-title">教授/副教授为本科生上课率（按学院） <KpiLabel label="" formula="为本科生授课的教授(副教授)÷该学院教授(副教授)总数。教育部要求教授上课率≥85%" /></div>
          <el-table :data="data.teachingRates" size="small" @row-click="goCollege" row-class-name="row-clickable">
            <el-table-column prop="name" label="学院" width="130"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
            <el-table-column prop="profTotal" label="教授数" width="70" align="right" />
            <el-table-column label="教授上课率" min-width="170"><template #default="{row}">
              <div style="display:flex;align-items:center;gap:8px">
                <el-progress :percentage="row.profRate" :show-text="false" :stroke-width="9" :color="row.profRate>=85?'#0D9488':'#E11D48'" style="flex:1" />
                <span class="tnum" :style="{color:row.profRate>=85?'#0D9488':'#E11D48',fontWeight:600,minWidth:'48px',textAlign:'right'}">{{ row.profRate }}% {{ row.profRate>=85?'✓':'↓' }}</span>
              </div>
            </template></el-table-column>
            <el-table-column label="副教授上课率" min-width="150"><template #default="{row}">
              <div style="display:flex;align-items:center;gap:8px">
                <el-progress :percentage="row.assocRate" :show-text="false" :stroke-width="9" color="#4F46E5" style="flex:1" />
                <span class="tnum" style="color:#4F46E5;font-weight:600;min-width:42px;text-align:right">{{ row.assocRate }}%</span>
              </div>
            </template></el-table-column>
          </el-table>
        </div>
      </el-col>

      <el-col :span="10">
        <div class="sa-card">
          <div class="sa-card-title">教师任课均分排行 <KpiLabel label="" formula="本学期可归因教学班学生平均分排行(修读≥20)。↑优于全体任课均分" /></div>
          <div v-if="data.teacherTrends.length">
            <div v-for="t in data.teacherTrends" :key="t.id" class="trend-row" @click="goTeacher(t)">
              <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
                <span><span class="link">{{ t.name }}</span> <span class="sa-faint">· {{ t.title }} · {{ t.dept }}</span></span>
                <span class="tnum" :style="{color:t.trend==='up'?'#0D9488':'#E11D48',fontWeight:600}">{{ t.avgScore }}分 {{ t.trend==='up'?'↑':'↓' }}</span>
              </div>
              <div style="display:flex;align-items:center;gap:8px">
                <el-progress :percentage="Math.min(Math.round(t.avgScore),100)" :show-text="false" :stroke-width="8" :color="t.avgScore>=80?'#0D9488':t.avgScore>=70?'#4F46E5':'#D97706'" style="flex:1" />
                <span class="sa-faint" style="font-size:11px;width:64px;text-align:right">{{ t.students }}人修读</span>
              </div>
            </div>
          </div>
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">未上课教授名单 <KpiLabel label="" formula="本学期未承担本科生课程的教授名单，需关注原因" /></div>
      <el-table v-if="data.notTeaching.length" :data="data.notTeaching" size="small">
        <el-table-column prop="name" label="姓名" width="90" />
        <el-table-column prop="title" label="职称" width="70" />
        <el-table-column prop="dept" label="学院" width="150" />
        <el-table-column prop="reason" label="原因" min-width="220" />
        <el-table-column prop="semesters" label="连续未上课" width="110" />
      </el-table>
      <div v-else class="sa-faint" style="font-size:12px">本学期无未上课教授</div>
    </div>

    <div style="margin-top:16px;text-align:right">
      <el-button type="primary" @click="router.push('/admin/faculty/team')">课程教学团队分析 →</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, ref, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import { COLLEGE_MAP } from '@/constants/colleges'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
const router = useRouter(); const route = useRoute()
const collegeFilter = ref<{id:string;name:string}|null>(null)
const collegeMap = COLLEGE_MAP
function applyCollegeFilter() { const cid = route.query.college as string; collegeFilter.value = (cid && collegeMap[cid]) ? { id: cid, name: collegeMap[cid] } : null }
applyCollegeFilter(); watch(() => route.query.college, () => { applyCollegeFilter(); load() })
function clearCollegeFilter() { collegeFilter.value = null; router.replace({ query: {} }) }
function goCollege(row: any) { router.push({ query: { college: row.id } }) }
function goTeacher(row: any) { router.push({ path: '/admin/faculty/' + row.id, query: fSemester.value ? { semester: fSemester.value } : {} }) }

const fTitle = ref('')
const fSemester = ref('')
const titles = ref<string[]>([])
const semesters = ref<SemesterOpt[]>([])

const facultyKpis = ref<any[]>([])
const evidence = ref<any>({})
const data = reactive<{structure:any[];teachingRates:any[];teacherTrends:any[];notTeaching:any[]}>({
  structure: [], teachingRates: [], teacherTrends: [], notTeaching: [],
})

async function load() {
  const cid = route.query.college as string
  const params = new URLSearchParams()
  if (cid && collegeMap[cid]) params.set('college', cid)
  if (fTitle.value) params.set('title', fTitle.value)
  if (fSemester.value) params.set('semester', fSemester.value)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const d = await http.get('/admin/faculty/structure' + qs)
  if (d) { facultyKpis.value = d.facultyKpis || []; evidence.value = d.evidence || {}; Object.assign(data, d) }
}
onMounted(async () => {
  const meta = await getFilterMeta()
  titles.value = meta.titles || []
  semesters.value = meta.semesters.slice().reverse()
  await load()
})

function kpiTone(label: string, value: any): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('上课率')) return parseFloat(String(value)) >= 85 ? 'teal' : 'danger'
  if (label.includes('博士') || label.includes('生师比')) return 'teal'
  return 'primary'
}

const STRUCT_COLORS = [
  ['#4F46E5', '#6366F1', '#A5B4FC', '#C7D2FE', '#E0E7FF'],
  ['#0D9488', '#2DD4BF', '#99F6E4', '#CCFBF1'],
  ['#D97706', '#F59E0B', '#FCD34D', '#FEF08A'],
  ['#6366F1', '#0EA5E9', '#94A3B8', '#CBD5E1'],
]
function structOption(d: any, di: number) {
  const palette = STRUCT_COLORS[di % STRUCT_COLORS.length]
  return {
    tooltip: { trigger: 'item', formatter: '{b}：{c}人（{d}%）' },
    series: [{
      type: 'pie', radius: ['42%', '70%'], center: ['50%', '50%'], avoidLabelOverlap: true,
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      label: { show: true, fontSize: 10, color: '#64748B', formatter: '{b}\n{d}%' },
      labelLine: { length: 6, length2: 6 },
      data: (d.items || []).map((it: any, i: number) => ({ name: it.label, value: it.value, itemStyle: { color: palette[i % palette.length] } })),
    }],
  }
}
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.filter-banner { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 10px; padding: 8px 14px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--sa-primary); }
.trend-row { padding: 8px 0; border-bottom: 1px solid var(--sa-border); cursor: pointer; }
.trend-row:last-child { border-bottom: none; }
.trend-row:hover { background: #f8fafc; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
</style>

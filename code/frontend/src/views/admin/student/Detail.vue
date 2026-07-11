<template>
  <div>
    <!-- 返回溯源 -->
    <div v-if="backLink" style="margin-bottom:8px">
      <el-button size="small" text @click="backLink.action">
        ← {{ backLink.label }}
      </el-button>
    </div>

    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/dashboard'}">全校总览</el-breadcrumb-item>
      <el-breadcrumb-item :to="{path:'/admin/college/'+data.collegeId}">{{ data.collegeName }}</el-breadcrumb-item>
      <el-breadcrumb-item>{{ data.name || '学生详情' }}</el-breadcrumb-item>
    </el-breadcrumb>

    <el-empty v-if="status==='error'" :image-size="100" description="">
      <template #description>
        <div style="font-size:13px;color:#64748B">未找到该学生的学业档案</div>
        <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
          学号 <b>{{ route.params.id }}</b> 在教务数据中不存在或已失效。<br />
          请从<span class="link" @click="$router.push('/admin/students/analysis')">学生学业分析</span>或学院/专业页面进入有效学生。
        </div>
      </template>
    </el-empty>

    <template v-else>
    <h2 class="sa-page-title">{{ data.name || '加载中…' }} · 学生学业档案</h2>
    <div class="info-bar">
      <span>学号：{{ data.code || '—' }}</span><el-divider direction="vertical" />
      <span>{{ data.collegeName || '—' }}</span><el-divider direction="vertical" />
      <span>{{ data.majorName || '—' }} · {{ data.className || '—' }}</span><el-divider direction="vertical" />
      <span>入学：{{ data.enrollOn || '—' }}</span>
      <template v-if="data.graduateOn"><el-divider direction="vertical" /><span>预计毕业：{{ data.graduateOn }}</span></template>
    </div>

    <el-row :gutter="12" style="margin-bottom:12px">
      <el-col :span="8">
        <KpiCard v-if="data.kpis[0]" :label="data.kpis[0].label" :value="data.kpis[0].value" :sub="data.kpis[0].sub" :hint="data.kpis[0].formula" :tone="kpiTone(data.kpis[0].label, data.kpis[0].value)" />
      </el-col>
      <el-col :span="8">
        <KpiCard v-if="data.kpis[1]" :label="data.kpis[1].label" :value="data.kpis[1].value" :sub="data.kpis[1].sub" :hint="data.kpis[1].formula" :tone="kpiTone(data.kpis[1].label, data.kpis[1].value)" />
      </el-col>
      <el-col :span="8">
        <KpiCard label="已修学时" :value="studyHours" sub="学时" hint="已修读课程总学时（credits×16）" tone="primary" />
      </el-col>
    </el-row>
    <el-row :gutter="12" style="margin-bottom:12px">
      <el-col :span="8">
        <KpiCard label="通过门数" :value="studyCourses" :sub="completionRateSub" hint="已通过课程门数" tone="primary" />
      </el-col>
      <el-col :span="8">
        <KpiCard v-if="data.kpis[2]" :label="data.kpis[2].label" :value="data.kpis[2].value" :sub="data.kpis[2].sub" :hint="data.kpis[2].formula" :tone="kpiTone(data.kpis[2].label, data.kpis[2].value)" />
      </el-col>
      <el-col :span="8">
        <KpiCard v-if="data.kpis[3]" :label="data.kpis[3].label" :value="data.kpis[3].value" :sub="data.kpis[3].sub" :hint="data.kpis[3].formula" :tone="kpiTone(data.kpis[3].label, data.kpis[3].value)" />
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin:4px 0 16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">GPA 趋势 <span class="extra">逐学期</span></div>
          <EChart v-if="data.gpaHistory && data.gpaHistory.length" :option="gpaOption" :height="180" />
          <div v-else class="sa-faint" style="font-size:12px">暂无 GPA 数据</div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">预警历史</div>
          <div v-if="data.alertHistory && data.alertHistory.length">
            <div v-for="a in data.alertHistory" :key="a.time + a.type" class="alert-row">
              <div style="font-size:12px"><el-tag :type="tagType(a.level)" size="small">{{ a.level }}</el-tag><span style="margin-left:6px">{{ a.type }}</span></div>
              <div class="sa-faint" style="font-size:11px;margin-top:2px">{{ a.detail }} · {{ a.time }}</div>
            </div>
          </div>
          <div v-else class="sa-faint" style="font-size:12px">无预警记录</div>
        </div>
      </el-col>
    </el-row>

    <!-- V1.1 成长轨迹摘要 -->
    <div class="sa-card" v-if="data.semesterSummary && data.semesterSummary.length">
      <div class="sa-card-title">成长轨迹 <span class="extra">逐学期 GPA/挂科/学分</span></div>
      <el-table :data="data.semesterSummary" size="small">
        <el-table-column prop="semester" label="学期" width="120" />
        <el-table-column prop="gpa" label="GPA" width="70" align="right">
          <template #default="{row}"><span class="tnum" :style="{color:row.gpa>=2.0?'#16A34A':'#DC2626'}">{{ row.gpa }}</span></template>
        </el-table-column>
        <el-table-column prop="failCount" label="挂科门数" width="80" align="right">
          <template #default="{row}"><span :style="{color:row.failCount>0?'#DC2626':'#6B7280',fontWeight:row.failCount>0?700:400}">{{ row.failCount }}</span></template>
        </el-table-column>
        <el-table-column prop="earnedCredits" label="已修学分" width="80" align="right" />
      </el-table>
    </div>

    <!-- V1.1 挂科溯源 -->
    <div class="sa-card" v-if="data.failTrace && data.failTrace.length">
      <div class="sa-card-title">挂科溯源 <span class="extra">课程/教师/学院/次数</span></div>
      <el-table :data="data.failTrace" size="small">
        <el-table-column prop="courseName" label="课程" width="150" />
        <el-table-column prop="teacherName" label="任课教师" width="100" />
        <el-table-column prop="college" label="开课学院" width="130" />
        <el-table-column prop="failCount" label="挂科次数" width="80" align="right">
          <template #default="{row}"><span class="tnum" style="color:#DC2626;font-weight:700">{{ row.failCount }}</span></template>
        </el-table-column>
        <el-table-column label="挂科学期" min-width="180">
          <template #default="{row}"><span v-for="(s,i) in (row.semesters||[])" :key="i"><el-tag size="small" type="danger" style="margin:1px">{{ s }}</el-tag></span></template>
        </el-table-column>
      </el-table>
    </div>

    <div class="sa-card">
      <div class="sa-card-title">成绩明细 <span class="extra">挂科课程标红</span></div>
      <el-table :data="data.scores" size="small">
        <el-table-column prop="semester" label="学期" width="120" />
        <el-table-column prop="courseCode" label="课程代码" width="110" />
        <el-table-column prop="courseName" label="课程名称" min-width="150" />
        <el-table-column prop="score" label="成绩" width="74" align="right"><template #default="{row}"><b class="tnum" :style="{color:row.passed?'#0D9488':'#E11D48'}">{{ row.score }}</b></template></el-table-column>
        <el-table-column prop="gp" label="绩点" width="64" align="right"><template #default="{row}"><span class="tnum">{{ row.gp }}</span></template></el-table-column>
        <el-table-column label="通过" width="60" align="center"><template #default="{row}"><span :style="{color:row.passed?'#0D9488':'#E11D48',fontWeight:700}">{{ row.passed ? '✓' : '✗' }}</span></template></el-table-column>
        <el-table-column prop="takeType" label="修读类别" width="90" />
        <el-table-column prop="examStatus" label="考试情况" width="90" />
      </el-table>
      <div class="sa-faint" style="font-size:11px;margin-top:12px;text-align:center">
        数据来源：教务系统 · 本页仅做数据展示，预警处理请在教务系统中操作
      </div>
    </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, computed } from 'vue'
import { http } from '@/utils/http'
import { useRoute, useRouter } from 'vue-router'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'

const route = useRoute()
const router = useRouter()

// 返回溯源：根据 from 参数判断来源页面
const backLink = computed(() => {
  const from = route.query.from as string
  if (from === 'alert') {
    return { label: '返回预警列表', action: () => router.push('/admin/alert') }
  }
  if (from === 'list') {
    // 保留筛选上下文
    const qs = new URLSearchParams()
    const keys = ['college', 'major', 'grade', 'class', 'semester', 'course', 'courseName']
    keys.forEach(k => { const v = route.query[k]; if (v) qs.set(k, v as string) })
    return { label: '返回学生清单', action: () => router.push('/admin/students/list?' + qs.toString()) }
  }
  if (from === 'analysis') {
    return { label: '返回学业分析', action: () => router.push('/admin/students/analysis') }
  }
  return null
})

const status = ref<'loading' | 'ok' | 'error'>('loading')
const data = reactive<any>({
  code: '', name: '', collegeId: '', collegeName: '', majorName: '', className: '',
  enrollOn: '', graduateOn: '', kpis: [], gpaHistory: [], alertHistory: [], scores: []
})

onMounted(async () => {
  try {
    const d = await http.get('/admin/student/' + route.params.id)
    if (d) { Object.assign(data, d); status.value = 'ok' }
    else status.value = 'error'
  } catch {
    status.value = 'error'
  }
})

function tagType(level: string) { return level === '严重' ? 'danger' : level === '警告' ? 'warning' : 'info' }
function kpiTone(label: string, value: any): 'primary'|'teal'|'danger'|'amber' {
  const v = String(value || '')
  if (label.includes('预警') || label.includes('毕业')) return v.includes('严重') || v.includes('延') ? 'danger' : 'amber'
  if (label.includes('GPA')) return parseFloat(v) < 2 ? 'danger' : 'primary'
  return 'primary'
}

const studySummary = computed(() => data.studySummary || { passed: {}, failed: {} })
const studyHours = computed(() => {
  const h = studySummary.value.passed?.hours
  return h != null ? String(h) + 'h' : '—'
})
const studyCourses = computed(() => {
  const c = studySummary.value.passed?.courses
  return c != null ? String(c) : '—'
})
const completionRateSub = computed(() => {
  const s = studySummary.value
  const rate = s.passed?.completionRate
  return rate != null ? '培养方案完成率 ' + rate + '%' : ''
})

const gpaOption = computed(() => {
  const g = data.gpaHistory || []
  return {
    grid: { left: 4, right: 12, top: 18, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: g.map((_: any, i: number) => `S${i + 1}`), axisLabel: { color: '#94A3B8', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: { type: 'value', min: 0, max: 5, axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    series: [{
      type: 'line', smooth: true, data: g, symbolSize: 8, lineStyle: { width: 3, color: '#4F46E5' }, itemStyle: { color: '#4F46E5' },
      areaStyle: { color: 'rgba(79,70,229,0.08)' },
      markLine: { silent: true, symbol: 'none', data: [{ yAxis: 2 }], lineStyle: { color: '#E11D48', type: 'dashed' }, label: { formatter: '预警线 2.0', color: '#E11D48', fontSize: 10 } },
    }],
  }
})
</script>

<style scoped>
.info-bar { font-size: 12px; color: var(--sa-muted); margin: 8px 0 16px; }
.alert-row { padding: 6px 0; border-bottom: 1px solid var(--sa-border); }
.alert-row:last-child { border-bottom: none; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
</style>

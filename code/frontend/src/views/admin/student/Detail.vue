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
          请从<span class="link" @click="$router.push('/admin/students/analysis')">学生成长与学业分析</span>或学院/专业页面进入有效学生。
        </div>
      </template>
    </el-empty>

    <template v-else>
    <h2 class="sa-page-title">{{ data.name || '加载中…' }} · 学生学业档案</h2>
    <div class="ai-profile-action">
      <el-button type="primary" plain @click="openStudentInsight">AI学业研判</el-button>
    </div>
    <div class="info-bar">
      <span>学号：{{ data.code || '—' }}</span><el-divider direction="vertical" />
      <span>{{ data.collegeName || '—' }}</span><el-divider direction="vertical" />
      <span>{{ data.majorName || '—' }} · {{ data.className || '—' }}</span><el-divider direction="vertical" />
      <span>入学：{{ data.enrollOn || '—' }}</span>
      <template v-if="data.graduateOn"><el-divider direction="vertical" /><span>预计毕业：{{ data.graduateOn }}</span></template>
    </div>

    <el-alert v-if="v2Status==='ok'" type="success" :closable="false" show-icon class="v2-banner">
      <template #title>V2真实数据档案 · 成绩有效结果、培养方案、学籍异动和毕业结果已统一关联</template>
    </el-alert>

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
          <div class="sa-card-title">预警历史与变化</div>
          <div v-if="data.alertComparison" class="alert-comparison">
            <span><b>{{ data.alertComparison.totalCycles || 0 }}</b> 历史</span>
            <span><b>{{ data.alertComparison.activeAlerts || 0 }}</b> 当前有效</span>
            <span><b>{{ data.alertComparison.interventionCount || 0 }}</b> 干预</span>
            <el-tag size="small" effect="plain">{{ data.alertComparison.latestChange || '无预警' }}</el-tag>
          </div>
          <div v-if="data.alertHistory && data.alertHistory.length">
            <div v-for="a in data.alertHistory" :key="a.time + a.type" class="alert-row">
              <div class="alert-head"><div><el-tag :type="tagType(a.level)" size="small">{{ a.level }}</el-tag><span>{{ a.type }}</span></div><small>{{ a.changeType }}</small></div>
              <div class="sa-faint" style="font-size:11px;margin-top:2px">{{ a.detail }} · {{ a.time }}<span v-if="a.workflowStatusLabel"> · {{ a.workflowStatusLabel }}</span></div>
            </div>
          </div>
          <div v-else class="sa-faint" style="font-size:12px">无预警记录</div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card growth-timeline-card" v-if="unifiedTimeline.length">
      <div class="growth-head">
        <div><div class="sa-card-title">学生成长轨迹</div><div class="sa-faint growth-sub">按时间合并学期表现、挂科、预警、干预和学籍事件；点击类型可快速聚焦。</div></div>
        <el-radio-group v-model="timelineFilter" size="small"><el-radio-button label="all">全部</el-radio-button><el-radio-button label="academic">学业</el-radio-button><el-radio-button label="alert">预警</el-radio-button><el-radio-button label="intervention">干预</el-radio-button><el-radio-button label="status">学籍</el-radio-button></el-radio-group>
      </div>
      <div class="trajectory-summary">
        <span>学期表现 <b>{{ timelineCounts.academic }}</b></span><span>挂科事件 <b>{{ timelineCounts.failure }}</b></span><span>预警记录 <b>{{ timelineCounts.alert }}</b></span><span>人工干预 <b>{{ timelineCounts.intervention }}</b></span><span>学籍/毕业 <b>{{ timelineCounts.status }}</b></span>
      </div>
      <el-timeline class="unified-timeline">
        <el-timeline-item v-for="item in filteredTimeline" :key="item.key" :timestamp="item.timestamp" placement="top" :type="item.color" :hollow="item.hollow">
          <div class="timeline-event-head"><div><el-tag size="small" :type="item.tagType">{{ item.typeLabel }}</el-tag><b>{{ item.title }}</b></div><span v-if="item.state">{{ item.state }}</span></div>
          <p>{{ item.detail }}</p><small v-if="item.evidence">依据：{{ item.evidence }}</small><small v-if="item.nextAction"> · 下次跟进：{{ item.nextAction }}</small>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!filteredTimeline.length" description="当前类型没有成长事件" :image-size="70" />
    </div>

    <!-- 确定性学业建议：AI启用前的可追溯原型 -->
    <div class="sa-card advice-panel" v-if="v2Status==='ok' && advice.cards.length">
      <div class="sa-card-title advice-title">
        <span>学业建议与关注要点 <span class="extra">确定性证据模板 · 非自由生成</span></span>
        <el-select v-model="adviceAudience" size="small" style="width:150px">
          <el-option v-for="item in audienceOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>
      <el-alert type="info" :closable="false" show-icon :title="advice.wording" style="margin-bottom:12px" />
      <div class="advice-list">
        <div v-for="card in advice.cards" :key="card.advice_id" class="advice-card" :class="card.priority">
          <div class="advice-card-head">
            <div><el-tag size="small" :type="adviceTagType(card.priority)">{{ advicePriority(card.priority) }}</el-tag><b>{{ card.title }}</b></div>
            <span class="topic">{{ card.topic }}</span>
          </div>
          <p class="advice-message">{{ card.messages?.[adviceAudience] || card.messages?.student }}</p>
          <div class="advice-evidence"><b>依据：</b>{{ card.evidence }}</div>
          <div v-if="card.verification" class="advice-limit"><b>需核验：</b>{{ card.verification }}</div>
        </div>
      </div>
      <div class="sa-faint advice-footer">生成方式：{{ advice.generated_by }} · 当前未启用外部AI模型 · 正式课程、成绩和毕业审核以学校业务系统为准</div>
    </div>

    <!-- V2 成长指标与困难证据 -->
    <div class="sa-card" v-if="v2Status==='ok' && v2Growth.indicator">
      <div class="sa-card-title">V2 成长指标 <span class="extra">growth-v1 · 可回溯证据</span></div>
      <el-row :gutter="12" class="v2-metrics">
        <el-col :span="4"><div class="metric"><b>{{ v2Growth.indicator.passed_courses }}</b><span>已通过课程</span></div></el-col>
        <el-col :span="4"><div class="metric danger"><b>{{ v2Growth.indicator.failed_courses }}</b><span>当前未通过</span></div></el-col>
        <el-col :span="4"><div class="metric"><b>{{ fmtNumber(v2Growth.indicator.earned_credits) }}</b><span>已获学分</span></div></el-col>
        <el-col :span="4"><div class="metric"><b>{{ fmtNumber(v2Growth.indicator.avg_gpa) }}</b><span>平均 GPA</span></div></el-col>
        <el-col :span="4"><div class="metric amber"><b>{{ v2Growth.indicator.retake_attempts }}</b><span>重修尝试</span></div></el-col>
        <el-col :span="4"><div class="metric"><b>{{ v2Growth.indicator.status_events }}</b><span>学籍异动</span></div></el-col>
      </el-row>
      <div v-if="v2Growth.flags?.length" class="flag-list">
        <span class="sa-faint">困难证据：</span>
        <el-tag v-for="flag in v2Growth.flags" :key="flag.flag_code" :type="flag.severity==='high'?'danger':'warning'" effect="light">
          {{ flagLabel(flag.flag_code) }} · {{ flag.evidence_count }}
        </el-tag>
      </div>
      <div v-else class="sa-faint" style="font-size:12px;margin-top:10px">当前没有V2困难标签</div>
    </div>

    <!-- V2 培养方案课程状态 -->
    <div class="sa-card" v-if="v2Status==='ok' && v2Growth.student?.plan_id">
      <div class="sa-card-title">培养方案课程状态 <span class="extra">{{ v2Growth.student.plan_name || '已绑定方案' }}</span></div>
      <el-alert type="info" :closable="false" show-icon class="wording-alert"
        title="“尚无完成证据”仅表示当前成绩与认定记录未发现完成结果，不等同于漏选或不能毕业。" />
      <el-tabs v-model="planTab">
        <el-tab-pane label="明确未通过（可行动）" name="actionable">
          <el-table :data="actionableCourses.items" size="small" empty-text="没有明确未通过的必修课程">
            <el-table-column prop="course_id" label="课程代码" width="120" />
            <el-table-column prop="course_name" label="课程名称" min-width="180" />
            <el-table-column prop="module" label="模块" width="140" />
            <el-table-column prop="suggested_term" label="建议学期" width="90" />
            <el-table-column prop="effective_score" label="有效成绩" width="90" align="right" />
            <el-table-column label="建议" width="100"><template #default><el-tag type="danger">优先重修</el-tag></template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane :label="`尚无完成证据（前${candidateCourses.items.length}条）`" name="candidate">
          <el-table :data="candidateCourses.items" size="small" empty-text="没有候选课程缺口">
            <el-table-column prop="course_id" label="课程代码" width="120" />
            <el-table-column prop="course_name" label="课程名称" min-width="180" />
            <el-table-column prop="module" label="模块" width="140" />
            <el-table-column prop="requirement_type" label="性质" width="80" />
            <el-table-column prop="suggested_term" label="建议学期" width="90" />
            <el-table-column label="状态" width="130"><template #default><el-tag type="info">待选课/认定核验</el-tag></template></el-table-column>
          </el-table>
          <div class="sa-faint" style="font-size:11px;margin-top:8px">候选总数 {{ candidateCourses.total }}，当前仅展示前100条。</div>
        </el-tab-pane>
      </el-tabs>
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
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="AI学业研判" />
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, computed } from 'vue'
import { http } from '@/utils/http'
import { getStudentAIInsight } from '@/utils/ai'
import { useRoute, useRouter } from 'vue-router'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'

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
    const keys = ['college', 'collegeId', 'collegeName', 'major', 'majorId', 'majorName', 'grade', 'class', 'semester', 'course', 'courseName', 'returnTo', 'returnLabel', 'page', 'scrollY']
    keys.forEach(k => { const v = route.query[k]; if (v) qs.set(k, v as string) })
    return { label: '返回学生清单', action: () => router.push('/admin/students/list?' + qs.toString()) }
  }
  const returnTo = route.query.returnTo as string
  if (returnTo) {
    return { label: (route.query.returnLabel as string) || '返回来源页面', action: () => router.push(returnTo) }
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
const v2Status = ref<'loading'|'ok'|'unavailable'>('loading')
const v2Growth = reactive<any>({ student: null, indicator: null, flags: [], timeline: [], graduation: [] })
const actionableCourses = reactive<any>({ items: [], total: 0 })
const candidateCourses = reactive<any>({ items: [], total: 0 })
const advice = reactive<any>({ cards: [], audiences: [], generated_by: '', wording: '' })
const adviceAudience = ref('student')
const timelineFilter = ref('all')
const aiDrawerVisible = ref(false)
const aiLoading = ref(false)
const aiInsight = ref<any>(null)
const interventionTimeline = computed(() => [
  ...(data.interventionHistory || []).map((x:any) => ({...x,key:`followup-${x.event_id}-${x.created_at}`,timestamp:x.created_at,title:x.action_type,content:x.content,nextActionAt:x.next_action_at})),
  ...(data.alertStatusHistory || []).map((x:any) => ({...x,key:`status-${x.event_id}-${x.changed_at}`,timestamp:x.changed_at,title:`状态更新：${x.fromStatusLabel || '首次记录'} → ${x.toStatusLabel}`,content:x.reason})),
].sort((a:any,b:any) => String(b.timestamp).localeCompare(String(a.timestamp))))
type TimelineColor = 'primary'|'success'|'warning'|'danger'|'info'
const unifiedTimeline = computed(() => {
  const items:any[] = []
  for (const s of data.semesterSummary || []) items.push({key:`semester-${s.semester}`,category:'academic',subtype:'academic',timestamp:s.semester,typeLabel:'学期表现',title:`${s.semester} 学业结果`,detail:`GPA ${s.gpa}，挂科 ${s.failCount} 门次，获得学分 ${s.earnedCredits}`,evidence:'成绩有效结果按学期聚合',color:(s.failCount>0?'warning':'success') as TimelineColor,tagType:s.failCount>0?'warning':'success'})
  for (const f of data.failTrace || []) for (const sem of f.semesters || []) items.push({key:`failure-${f.courseName}-${sem}`,category:'academic',subtype:'failure',timestamp:sem,typeLabel:'课程未通过',title:f.courseName,detail:`该课程未通过；累计记录 ${f.failCount} 次`,evidence:`授课教师 ${f.teacherName || '待核验'} · 开课单位 ${f.college || '待核验'}`,color:'danger' as TimelineColor,tagType:'danger'})
  for (const a of data.alertHistory || []) items.push({key:`alert-${a.alertId}-${a.time}`,category:'alert',subtype:'alert',timestamp:a.time||'—',typeLabel:'学业预警',title:`${a.level} · ${a.type}`,detail:a.detail||'未提供触发说明',evidence:a.changeType||'历史预警记录',state:a.workflowStatusLabel,color:(a.level==='严重'?'danger':'warning') as TimelineColor,tagType:a.level==='严重'?'danger':'warning'})
  for (const x of data.interventionHistory || []) items.push({key:`followup-${x.event_id}-${x.created_at}`,category:'intervention',subtype:'intervention',timestamp:x.created_at||'—',typeLabel:'人工干预',title:x.action_type||'跟进记录',detail:x.content||'未填写处置内容',evidence:`${x.operator||'未知操作人'} · ${x.type||'预警'}（${x.level||'—'}）`,nextAction:x.next_action_at,color:'primary' as TimelineColor,tagType:'primary'})
  for (const x of data.alertStatusHistory || []) items.push({key:`workflow-${x.event_id}-${x.changed_at}`,category:'intervention',subtype:'intervention',timestamp:x.changed_at||'—',typeLabel:'处置流转',title:`${x.fromStatusLabel||'首次记录'} → ${x.toStatusLabel||'—'}`,detail:x.reason||'未填写状态变更说明',evidence:x.operator||'未知操作人',color:'info' as TimelineColor,tagType:'info',hollow:true})
  for (const e of v2Growth.timeline || []) if (e.event_type !== 'semester_result') items.push({key:`v2-${e.event_type}-${e.event_date||e.semester_id}-${e.title}`,category:'status',subtype:'status',timestamp:e.event_date||e.semester_id||'—',typeLabel:e.event_type==='graduation'?'毕业结果':'学籍事件',title:e.title,detail:timelineDetail(e)||'已记录',evidence:'统一学生成长事件',color:timelineType(e.event_type),tagType:e.event_type==='graduation'?'success':'warning'})
  return items.sort((a,b)=>String(b.timestamp).localeCompare(String(a.timestamp)))
})
const filteredTimeline = computed(() => timelineFilter.value==='all' ? unifiedTimeline.value : unifiedTimeline.value.filter(x=>x.category===timelineFilter.value))
const timelineCounts = computed(() => ({
  academic: unifiedTimeline.value.filter(x=>x.subtype==='academic').length,
  failure: unifiedTimeline.value.filter(x=>x.subtype==='failure').length,
  alert: unifiedTimeline.value.filter(x=>x.subtype==='alert').length,
  intervention: unifiedTimeline.value.filter(x=>x.subtype==='intervention').length,
  status: unifiedTimeline.value.filter(x=>x.subtype==='status').length,
}))
const audienceOptions = [
  {value:'student',label:'学生本人视角'}, {value:'counselor',label:'辅导员视角'},
  {value:'class_adviser',label:'班主任视角'}, {value:'college',label:'学院视角'},
  {value:'academic_affairs',label:'教务处视角'},
]
const planTab = ref('actionable')

onMounted(async () => {
  try {
    const d = await http.get('/admin/student/' + route.params.id)
    if (d) { Object.assign(data, d); status.value = 'ok' }
    else status.value = 'error'
  } catch {
    status.value = 'error'
  }
  try {
    const id = String(route.params.id)
    const [growth, actionable, candidates, adviceData] = await Promise.all([
      http.getSilent<any>('/v2/students/' + id + '/growth?timeline_limit=80'),
      http.getSilent<any>('/v2/students/' + id + '/plan-courses?actionable=true&limit=200'),
      http.getSilent<any>('/v2/students/' + id + '/plan-courses?status=not_completed&limit=100'),
      http.getSilent<any>('/v2/students/' + id + '/advice'),
    ])
    Object.assign(v2Growth, growth)
    Object.assign(actionableCourses, actionable)
    Object.assign(candidateCourses, candidates)
    Object.assign(advice, adviceData)
    v2Status.value = 'ok'
    if (status.value === 'error' && growth?.student) {
      Object.assign(data, {
        code: growth.student.student_id,
        name: growth.student.display_name,
        collegeName: growth.student.organization_id || '—',
        majorName: growth.student.major_name || growth.student.major_code || '—',
        className: growth.student.class_code || '—',
        kpis: [], gpaHistory: [], alertHistory: [], scores: [], semesterSummary: [],
      })
      status.value = 'ok'
    }
  } catch {
    v2Status.value = 'unavailable'
  }
})

function fmtNumber(value: any) { return value == null ? '—' : Number(value).toFixed(2).replace(/\.00$/, '') }
function adviceTagType(priority:string) { return priority==='high'?'danger':priority==='positive'?'success':'warning' }
function advicePriority(priority:string) { return priority==='high'?'优先关注':priority==='positive'?'积极进展':'建议关注' }
function flagLabel(code: string) {
  return ({ multiple_current_failures: '当前多门未通过', repeated_course_failure: '同一课程重复失败', required_course_gap: '必修课程明确失败' } as Record<string,string>)[code] || code
}
function timelineType(type: string): 'primary'|'success'|'warning'|'danger'|'info' {
  if (type === 'graduation') return 'success'
  if (type === 'status_change') return 'warning'
  return 'primary'
}
function timelineDetail(event: any) {
  try {
    const d = JSON.parse(event.detail_json || '{}')
    if (event.event_type === 'semester_result') return `课程 ${d.courses || 0} 门，通过 ${d.passed || 0} 门，未通过 ${d.failed || 0} 门，平均成绩 ${d.avg_score ?? '—'}`
    if (event.event_type === 'status_change') return [d.before_status, d.after_status].filter(Boolean).join(' → ') + (d.reason ? ` · ${d.reason}` : '')
    if (event.event_type === 'graduation') return `${d.graduation_status || '—'} · ${d.degree_status || '—'}`
  } catch { return '' }
  return ''
}

async function openStudentInsight() {
  const sid = String(route.params.id || data.code || '')
  if (!sid) return
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try {
    aiInsight.value = await getStudentAIInsight(sid, 'student_profile')
  } finally {
    aiLoading.value = false
  }
}

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
.ai-profile-action { display:flex; justify-content:flex-end; margin:-6px 0 14px; }
.alert-row { padding: 6px 0; border-bottom: 1px solid var(--sa-border); }
.alert-row:last-child { border-bottom: none; }
.alert-head { display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:12px; }
.alert-head span { margin-left:6px; }
.alert-head small { color:#6366f1; }
.alert-comparison { display:flex; align-items:center; flex-wrap:wrap; gap:6px 10px; padding:7px 8px; margin:5px 0 7px; background:#f8fafc; border-radius:7px; font-size:10px; color:#64748b; }
.alert-comparison b { color:#1e293b; font-size:13px; }
.intervention-panel { margin-bottom:16px; }
.intervention-head { display:flex; justify-content:space-between; gap:10px; font-size:12px; }
.intervention-head span { color:#94a3b8; font-size:11px; }
.intervention-panel p { margin:5px 0 2px; color:#475569; font-size:12px; line-height:1.6; }
.intervention-panel small { color:#d97706; }
.growth-timeline-card { margin-bottom:16px; }
.growth-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
.growth-sub { font-size:11px; margin-top:3px; }
.trajectory-summary { display:flex; flex-wrap:wrap; gap:8px 18px; margin:12px 0 16px; padding:10px 12px; background:#f8fafc; border-radius:8px; color:#64748b; font-size:12px; }
.trajectory-summary b { color:#1e293b; margin-left:4px; }
.timeline-event-head { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.timeline-event-head b { margin-left:8px; color:#1e293b; font-size:13px; }
.timeline-event-head > span { color:#6366f1; font-size:11px; }
.unified-timeline p { margin:5px 0 2px; color:#475569; font-size:12px; line-height:1.6; }
.unified-timeline small { color:#94a3b8; font-size:11px; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
.v2-banner { margin-bottom: 12px; }
.v2-metrics { margin-top: 4px; }
.metric { background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:12px; text-align:center; }
.metric b { display:block; color:#1E3A5F; font-size:22px; font-variant-numeric:tabular-nums; }
.metric span { display:block; color:#64748B; font-size:11px; margin-top:4px; }
.metric.danger b { color:#DC2626; }
.metric.amber b { color:#D97706; }
.flag-list { display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin-top:12px; }
.wording-alert { margin-bottom:8px; }
.timeline-detail { font-size:12px; margin-top:4px; line-height:1.6; }
.advice-title { display:flex; justify-content:space-between; align-items:center; }
.advice-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.advice-card { border:1px solid #E2E8F0; border-left:4px solid #D97706; border-radius:9px; padding:13px 14px; background:#fff; }
.advice-card.high { border-left-color:#DC2626; }
.advice-card.positive { border-left-color:#0D9488; }
.advice-card-head { display:flex; justify-content:space-between; gap:12px; align-items:center; }
.advice-card-head b { margin-left:8px; font-size:13px; color:#1E293B; }
.advice-card-head .topic { color:#94A3B8; font-size:11px; white-space:nowrap; }
.advice-message { margin:10px 0; color:#334155; font-size:13px; line-height:1.7; }
.advice-evidence,.advice-limit { font-size:11px; color:#64748B; line-height:1.6; }
.advice-limit { color:#92400E; margin-top:3px; }
.advice-footer { font-size:11px; margin-top:12px; text-align:right; }
@media (max-width:1000px) { .advice-list { grid-template-columns:1fr; } .growth-head { flex-direction:column; } }
</style>

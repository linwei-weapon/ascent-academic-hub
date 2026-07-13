<template>
  <div>
    <h2 class="sa-page-title">学业进度监控</h2>
    <p class="sa-page-sub">用同一套方案课程状态识别群体进度、明确未通过与需要核验的到期记录</p>

    <div v-if="!planName" class="sa-faint" style="text-align:center;padding:60px">
      请先选择培养方案
    </div>

    <template v-else>
      <div class="sa-kpi-row">
        <KpiCard label="覆盖学生" :value="summary.coveredStudents" hint="已匹配当前培养方案且生成课程状态的去重学生数" tone="primary" />
        <KpiCard label="平均课程完成率" :value="`${summary.avgCourseCompletionRate}%`" hint="每名学生已通过或认定的方案课程门数占比，再求平均" tone="teal" />
        <KpiCard label="明确需处理" :value="summary.actionRequiredStudents" hint="至少一门方案必修课存在明确未通过成绩的学生数" tone="danger" />
        <KpiCard label="待核验" :value="summary.verificationStudents" hint="到建议修读学期但尚无结果证据，需结合选课数据核验" tone="amber" />
      </div>
      <el-alert :title="definition.boundary" type="info" :closable="false" show-icon style="margin-bottom:12px" />
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <el-input v-model="keyword" placeholder="搜索学号或姓名" clearable style="width:200px" />
        <el-select v-model="statusFilter" placeholder="证据状态" clearable style="width:140px">
          <el-option v-for="x in ['明确需处理','待核验','未发现到期问题']" :key="x" :label="x" :value="x" />
        </el-select>
        <el-button @click="exportCsv">导出当前结果</el-button>
        <span class="sa-faint" style="align-self:center">{{ filteredProgress.length }} 人</span>
      </div>

      <el-table :data="filteredProgress" stripe size="small" v-loading="loading">
        <el-table-column prop="studentId" label="学号" width="130" />
        <el-table-column prop="name" label="姓名" width="80" />
        <el-table-column prop="grade" label="年级" width="72" />
        <el-table-column label="已完成/方案课程" width="140">
          <template #default="{row}">
            <span class="tnum">{{ row.completedCourses }}</span>
            <span class="sa-faint">/{{ row.planCourses }} 门</span>
          </template>
        </el-table-column>
        <el-table-column label="完成率" width="100">
          <template #default="{row}">
            <el-progress :percentage="row.completionRate" :stroke-width="8"
              :color="row.completionRate >= 80 ? '#16A34A' : row.completionRate >= 60 ? '#EA580C' : '#DC2626'" />
          </template>
        </el-table-column>
        <el-table-column label="明确未通过必修" width="120" align="right">
          <template #default="{row}">
            <b class="tnum" :style="{color:row.failedRequired?'#DC2626':'#64748B'}">{{ row.failedRequired }}</b> 门
          </template>
        </el-table-column>
        <el-table-column label="到期待核验" width="100" align="right">
          <template #default="{row}"><span class="tnum">{{ row.verificationRequired }}</span> 门</template>
        </el-table-column>
        <el-table-column label="证据状态" width="120">
          <template #default="{row}">
            <el-tag size="small" :type="row.status === '明确需处理' ? 'danger' : row.status === '待核验' ? 'warning' : 'success'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{row}"><el-button link type="primary" @click="openStudent(row)">详情</el-button></template>
        </el-table-column>
      </el-table>
    </template>

    <el-drawer v-model="detailVisible" :title="`${selectedStudent.name || ''}｜培养方案进度详情`" size="900px">
      <div v-loading="detailLoading" style="min-height:320px">
        <el-alert type="info" :closable="false" show-icon title="本详情只核查培养方案课程完成证据，不跳转学业预警档案；“待核验”不等同于漏选或不能毕业。" />
        <el-descriptions :column="4" border size="small" style="margin:14px 0">
          <el-descriptions-item label="学号">{{ selectedStudent.studentId }}</el-descriptions-item><el-descriptions-item label="年级">{{ selectedStudent.grade || '—' }}</el-descriptions-item><el-descriptions-item label="方案">{{ planName }}</el-descriptions-item><el-descriptions-item label="证据状态"><el-tag size="small" :type="selectedStudent.status==='明确需处理'?'danger':selectedStudent.status==='待核验'?'warning':'success'">{{ selectedStudent.status }}</el-tag></el-descriptions-item>
        </el-descriptions>
        <div class="detail-kpis"><KpiCard label="方案课程" :value="`${selectedStudent.planCourses || 0}门`" hint="当前方案结构化课程总数" tone="primary" /><KpiCard label="已有完成证据" :value="`${selectedStudent.completedCourses || 0}门`" hint="存在通过成绩或课程替代认定的课程" tone="teal" /><KpiCard label="明确未通过必修" :value="`${failedCourses.length}门`" hint="必修课程存在明确未通过成绩，可直接形成重修核查清单" tone="danger" /><KpiCard label="到期待核验" :value="`${verificationCourses.length}门`" hint="建议修读学期已到但尚无完成或失败证据，需结合选课数据核验" tone="amber" /></div>
        <el-tabs v-model="detailTab" style="margin-top:14px">
          <el-tab-pane :label="`明确未通过必修 (${failedCourses.length})`" name="failed"><el-table :data="failedCourses" size="small" empty-text="没有明确未通过的必修课程"><el-table-column prop="course_id" label="课程代码" width="120" /><el-table-column prop="course_name" label="课程" min-width="190" /><el-table-column prop="module" label="模块" width="150" /><el-table-column prop="suggested_term" label="建议学期" width="90" /><el-table-column prop="effective_score" label="有效成绩" width="90" align="right" /><el-table-column label="核查原因" min-width="170"><template #default>必修课存在明确未通过成绩</template></el-table-column></el-table></el-tab-pane>
          <el-tab-pane :label="`到期待核验 (${verificationCourses.length})`" name="verification"><el-table :data="verificationCourses" size="small" empty-text="没有到期待核验课程"><el-table-column prop="course_id" label="课程代码" width="120" /><el-table-column prop="course_name" label="课程" min-width="190" /><el-table-column prop="module" label="模块" width="150" /><el-table-column prop="requirement_type" label="性质" width="75" /><el-table-column prop="suggested_term" label="建议学期" width="90" /><el-table-column label="核查内容" min-width="200"><template #default>核验是否已选课、缓修、替代或成绩尚未同步</template></el-table-column></el-table></el-tab-pane>
          <el-tab-pane label="全部方案课程" name="all"><el-table :data="detailCourses" size="small" max-height="520"><el-table-column prop="course_id" label="课程代码" width="120" /><el-table-column prop="course_name" label="课程" min-width="180" /><el-table-column prop="module" label="模块" width="140" /><el-table-column prop="requirement_type" label="性质" width="75" /><el-table-column prop="suggested_term" label="建议学期" width="90" /><el-table-column label="完成证据" width="120"><template #default="{row}"><el-tag size="small" :type="courseTag(row.completion_status)">{{ courseStatus(row.completion_status) }}</el-tag></template></el-table-column></el-table></el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { http } from '@/utils/http'
import KpiCard from '@/components/KpiCard.vue'

const props = defineProps<{ majorId: string }>()

const loading = ref(false)
const planName = ref('')
const planVersion = ref('')
const planCourses = ref<any[]>([])
const progress = ref<any[]>([])
const summary = ref<any>({ coveredStudents:0, avgCourseCompletionRate:0, actionRequiredStudents:0, verificationStudents:0 })
const definition = ref<any>({ boundary:'' })
const keyword = ref('')
const statusFilter = ref('')
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailTab = ref('failed')
const selectedStudent = ref<any>({})
const detailCourses = ref<any[]>([])
const failedCourses = computed(() => detailCourses.value.filter(x => x.requirement_type === '必修' && x.completion_status === 'failed'))
const verificationCourses = computed(() => detailCourses.value.filter(x => x.requirement_type === '必修' && ['not_completed','unknown'].includes(x.completion_status) && Number(x.is_overdue) === 1))
const filteredProgress = computed(() => progress.value.filter(row =>
  (!keyword.value || row.studentId.toLowerCase().includes(keyword.value.toLowerCase()) || (row.name || '').includes(keyword.value)) &&
  (!statusFilter.value || row.status === statusFilter.value)
))

function exportCsv() {
  const header = ['学号','姓名','年级','方案版本','已完成课程数','方案课程数','课程完成率(%)','明确未通过必修(门)','到期待核验(门)','证据状态']
  const rows = filteredProgress.value.map(r => [r.studentId,r.name,r.grade,planVersion.value,r.completedCourses,
    r.planCourses,r.completionRate,r.failedRequired,r.verificationRequired,r.status])
  const csv = '\uFEFF' + [header, ...rows].map(row => row.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = `培养方案进度证据_${planVersion.value}.csv`; a.click()
  URL.revokeObjectURL(url)
}

async function load(major: string) {
  loading.value = true
  try {
    const data = await http.get<any>(`/v2/curriculum/progress/${major}`)
    if (data.plan) {
      planName.value = data.plan.planName || major
      planVersion.value = data.plan.planId || ''
      planCourses.value = Array(data.students?.[0]?.planCourses || 0).fill(null)
      progress.value = data.students || []
      summary.value = data.summary || summary.value
      definition.value = data.definition || definition.value
    } else {
      planName.value = ''
      planVersion.value = ''
      planCourses.value = []
      progress.value = []
    }
  } catch { /* http 工具已 toast */ }
  finally { loading.value = false }
}

async function openStudent(row:any) {
  selectedStudent.value = row; detailVisible.value = true; detailLoading.value = true
  detailTab.value = row.failedRequired ? 'failed' : row.verificationRequired ? 'verification' : 'all'
  try { const d = await http.get<any>(`/v2/students/${encodeURIComponent(row.studentId)}/plan-courses?limit=1000`); detailCourses.value = d?.items || [] }
  finally { detailLoading.value = false }
}
function courseStatus(status:string){return({passed:'成绩通过',recognized:'替代/认定',failed:'明确未通过',not_completed:'尚无完成证据',unknown:'证据未知'} as Record<string,string>)[status]||status||'未知'}
function courseTag(status:string):'success'|'danger'|'warning'|'info'{return ['passed','recognized'].includes(status)?'success':status==='failed'?'danger':status==='not_completed'?'warning':'info'}

onMounted(() => load(props.majorId))
watch(() => props.majorId, (v) => load(v))
</script>

<style scoped>
.detail-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
</style>

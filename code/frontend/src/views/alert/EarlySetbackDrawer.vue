<template>
  <el-drawer
    :model-value="modelValue"
    title="低年级风险核查"
    size="720px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="row" class="drawer-body">
      <div class="student-head">
        <div>
          <h3>{{ row.display_name }}</h3>
          <p>{{ row.student_id }} · {{ row.major_name }} · {{ row.class_code }}</p>
        </div>
        <el-tag :type="statusType(row.recovery_status)">
          {{ statusName[row.recovery_status] || row.recovery_status }}
        </el-tag>
      </div>

      <div class="evidence-grid">
        <div><b>{{ row.first_setback_semester || '—' }}</b><span>首次未通过学期</span></div>
        <div><b>{{ row.first_year_failures || 0 }}条</b><span>大一未通过记录</span></div>
        <div><b>{{ row.later_failures || 0 }}条</b><span>后续未通过记录</span></div>
        <div><b>{{ gpaChange }}</b><span>大一至后续GPA变化</span></div>
      </div>

      <div v-if="loading" class="drawer-loading">
        <el-skeleton :rows="8" animated />
        <p>正在加载学生成绩轨迹和历史预警证据…</p>
      </div>
      <el-alert
        v-else-if="error"
        type="error"
        :closable="false"
        show-icon
        title="学业证据加载失败"
        :description="error"
      />
      <el-tabs v-else v-model="activeTab">
        <el-tab-pane label="成绩与变化" name="grades">
          <section class="section-card">
            <h4>GPA轨迹</h4>
            <EChart v-if="gpaPoints.length" :option="gpaOption" :height="190" />
            <el-empty v-else description="暂无可用GPA轨迹" :image-size="65" />
          </section>
          <section class="section-card">
            <h4>未通过课程记录</h4>
            <div v-if="failedScores.length" class="record-list">
              <div v-for="item in failedScores.slice(0, 12)" :key="item.courseName + item.semester">
                <span>{{ item.courseName }}</span>
                <b>{{ item.score }}分 · {{ item.semester }}</b>
              </div>
            </div>
            <el-empty v-else description="暂无未通过课程明细" :image-size="65" />
          </section>
        </el-tab-pane>
        <el-tab-pane label="历史预警" name="alerts">
          <section class="section-card">
            <div v-if="student.alertHistory?.length" class="record-list">
              <div v-for="item in student.alertHistory.slice(0, 12)" :key="item.time + item.type">
                <span>{{ item.type }}</span>
                <b>{{ item.level }} · {{ formatDate(item.time) }}</b>
              </div>
            </div>
            <el-empty v-else description="暂无历史预警记录" :image-size="70" />
          </section>
        </el-tab-pane>
      </el-tabs>

      <div class="drawer-footer">
        <el-button type="primary" plain @click="openFullProfile">查看完整学业档案</el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http } from '@/utils/http'
import EChart from '@/components/EChart.vue'

const props = defineProps<{ modelValue: boolean; row: any | null }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const student = ref<any>({})
const activeTab = ref('grades')
let requestSequence = 0

const statusName: Record<string, string> = {
  no_setback: '大一未出现未通过',
  recovered: '后续未再出现未通过',
  recovering: '后续仍需观察',
  persistent: '后续持续出现未通过',
  pending_observation: '暂无后续成绩',
}
const failedScores = computed(() =>
  (student.value.scores || []).filter((item: any) => !item.passed),
)
const gpaChange = computed(() => {
  const first = Number(props.row?.first_year_gpa)
  const later = Number(props.row?.later_gpa)
  if (!Number.isFinite(first) || !Number.isFinite(later)) return '—'
  const delta = later - first
  return `${delta > 0 ? '+' : ''}${delta.toFixed(2)}`
})
const gpaPoints = computed(() => {
  const summaries = (student.value.semesterSummary || [])
    .filter((item: any) => item.semester && Number.isFinite(Number(item.gpa)))
    .slice(-6)
    .map((item: any) => ({ semester: String(item.semester), gpa: Number(item.gpa) }))
  if (summaries.length) return summaries

  const values = (student.value.gpaHistory || []).map((value: any) => Number(value))
  const semesters = [...new Set(
    (student.value.scores || []).map((item: any) => String(item.semester || '')).filter(Boolean),
  )].sort().slice(-values.length)
  return values.map((gpa: number, index: number) => ({
    semester: semesters[index] || '—',
    gpa,
  }))
})
const gpaOption = computed(() => {
  const values = gpaPoints.value
  return {
    grid: { left: 8, right: 16, top: 20, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category', data: values.map((point: any) => point.semester),
      axisLabel: { color: '#64748b' }, axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'value', min: 0, max: 5,
      axisLabel: { color: '#64748b' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    series: [{
      type: 'line', data: values.map((point: any) => point.gpa), smooth: true, symbolSize: 7,
      lineStyle: { color: '#4f46e5', width: 3 },
      itemStyle: { color: '#4f46e5' },
      areaStyle: { color: 'rgba(79,70,229,.08)' },
    }],
  }
})

function statusType(status: string) {
  return status === 'persistent' ? 'danger'
    : status === 'recovered' ? 'success'
      : status === 'recovering' ? 'warning' : 'info'
}
function formatDate(value: string) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '—'
}
async function load() {
  if (!props.modelValue || !props.row?.student_id) return
  const sequence = ++requestSequence
  loading.value = true
  error.value = ''
  student.value = {}
  activeTab.value = 'grades'
  try {
    const data = await http.get(`/admin/student/${props.row.student_id}`)
    if (sequence === requestSequence) student.value = data || {}
  } catch (reason: any) {
    if (sequence === requestSequence) error.value = reason?.message || '请稍后重试'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}
function openFullProfile() {
  router.push({
    path: `/admin/student/${props.row.student_id}`,
    query: { returnTo: route.fullPath, returnLabel: '低年级风险观察' },
  })
}
watch(
  () => [props.modelValue, props.row?.student_id],
  () => props.modelValue ? load() : requestSequence += 1,
)
</script>

<style scoped>
.drawer-body{min-height:420px}.student-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding-bottom:14px;border-bottom:1px solid var(--sa-border)}.student-head h3{margin:0;color:var(--sa-text);font-size:20px}.student-head p{margin:5px 0 0;color:var(--sa-muted);font-size:12px}.evidence-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.evidence-grid div{padding:12px;border:1px solid #e2e8f0;border-radius:9px;background:#f8fafc}.evidence-grid b,.evidence-grid span{display:block}.evidence-grid b{color:#1e293b;font-size:17px}.evidence-grid span{margin-top:4px;color:#64748b;font-size:10px}.drawer-loading{padding:22px 4px}.drawer-loading p{text-align:center;color:#94a3b8;font-size:11px}.section-card{margin-bottom:12px;padding:14px;border:1px solid #e2e8f0;border-radius:10px}.section-card h4{margin:0 0 10px;color:#334155;font-size:13px}.record-list div{display:flex;justify-content:space-between;gap:14px;padding:8px 0;border-bottom:1px dashed #e2e8f0;font-size:12px}.record-list div:last-child{border-bottom:0}.record-list span{color:#475569}.record-list b{color:#64748b;font-weight:500}.drawer-footer{display:flex;align-items:center;justify-content:flex-end;gap:16px;margin-top:14px;padding-top:12px;border-top:1px solid #e2e8f0}@media(max-width:760px){.evidence-grid{grid-template-columns:repeat(2,1fr)}}
</style>

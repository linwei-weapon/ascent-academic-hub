<template>
  <el-drawer
    :model-value="modelValue"
    title="学生预警核查"
    size="760px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="row" class="review-drawer">
      <div class="review-head">
        <div>
          <div class="review-name">
            {{ row.studentName }}
            <el-tag :type="levelType(row.highestLevel)" size="small">{{ row.highestLevel }}</el-tag>
            <el-tag size="small" effect="plain">{{ row.managementLabel }}</el-tag>
          </div>
          <div class="review-meta">
            {{ row.studentId }} · {{ row.collegeName }} · {{ row.majorName }} · {{ row.className }}
          </div>
        </div>
        <div class="review-head__actions">
          <el-button
            v-if="row.highestLevel === '严重'"
            type="primary"
            plain
            size="small"
            @click="emit('ai', row)"
          >AI管理研判</el-button>
          <el-button size="small" @click="openFullProfile">完整学业档案</el-button>
        </div>
      </div>

      <el-alert
        v-if="loadError"
        type="error"
        :closable="false"
        show-icon
        title="学生核查数据加载失败"
      >
        <template #default>
          <span>{{ loadError }}</span>
          <el-button link type="primary" @click="load">重新加载</el-button>
        </template>
      </el-alert>

      <div v-if="loading" class="drawer-loading" aria-live="polite">
        <el-skeleton :rows="8" animated />
        <p>正在并行加载学生学业证据与核查记录，请稍候…</p>
      </div>

      <el-tabs v-else v-model="activeSection" class="review-tabs">
        <el-tab-pane label="核查摘要" name="summary">
          <section class="summary-callout">
            <div>
              <span>为什么需要关注</span>
              <b>{{ row.primaryType }}</b>
              <p>{{ row.primaryReason }}</p>
            </div>
            <div class="summary-count">
              <b>{{ row.alertCount }}</b>
              <span>条当前规则命中</span>
            </div>
          </section>

          <div class="drawer-kpis">
            <div v-for="item in studentKpis" :key="item.label" class="drawer-kpi">
              <b>{{ item.value }}</b>
              <span>{{ item.label }}</span>
            </div>
          </div>

          <div class="section-card">
            <h4>当前规则命中证据</h4>
            <div v-if="row.signals?.length" class="signal-list">
              <div v-for="signal in row.signals" :key="signal.alertId" class="signal-item">
                <div>
                  <el-tag :type="levelType(signal.level)" size="small">{{ signal.level }}</el-tag>
                  <b>{{ signal.type }}</b>
                  <span>{{ workflowLabel(signal.managementStatus) }}</span>
                </div>
                <p>{{ signal.reason }}</p>
                <small>
                  规则 {{ signal.ruleId }} · 版本 {{ signal.ruleVersion || 'legacy' }}
                  · 首次生成 {{ formatDate(signal.detectedAt) }}
                </small>
              </div>
            </div>
            <el-empty v-else description="暂无当前规则命中证据" :image-size="70" />
          </div>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="风险状态与核查状态分别记录"
            description="当前规则仍命中，不代表尚未核查；已有核查记录，也不代表风险信号已经消失。"
          />
        </el-tab-pane>

        <el-tab-pane label="学业证据" name="evidence">
          <div class="section-card">
            <h4>GPA变化</h4>
            <EChart
              v-if="student.gpaHistory?.length"
              :option="gpaTrendOption"
              :height="180"
            />
            <el-empty v-else description="暂无可用GPA轨迹" :image-size="70" />
          </div>

          <div class="evidence-grid">
            <div class="section-card">
              <h4>未通过课程证据</h4>
              <div v-if="failedScores.length" class="evidence-list">
                <div v-for="score in failedScores.slice(0, 10)" :key="score.courseName + score.semester">
                  <span>{{ score.courseName }}</span>
                  <b>{{ score.score }}分 · {{ score.semester }}</b>
                </div>
              </div>
              <el-empty v-else description="暂无未通过成绩记录" :image-size="60" />
            </div>
            <div class="section-card">
              <h4>预警历史</h4>
              <div v-if="student.alertHistory?.length" class="evidence-list">
                <div v-for="item in student.alertHistory.slice(0, 10)" :key="item.time + item.type">
                  <span>{{ item.type }}</span>
                  <b>{{ item.level }} · {{ formatDate(item.time) }}</b>
                </div>
              </div>
              <el-empty v-else description="暂无历史预警" :image-size="60" />
            </div>
          </div>

          <TrajectoryCard
            v-if="primarySignal"
            :rule-id="primarySignal.ruleId"
            :level="primarySignal.level"
          />
        </el-tab-pane>

        <el-tab-pane label="核查与跟进记录" name="records">
          <div class="section-card">
            <div class="section-title-row">
              <h4>当前核查状态</h4>
              <el-tag size="small" effect="plain">
                {{ workflowLabel(workflow.workflowStatus) }}
              </el-tag>
            </div>
            <div v-if="workflow.eventId" class="workflow-info">
              <p>
                主责任人：{{ primaryAssignee?.username || '未分派' }}
                <span v-if="primaryAssignee?.assignment_reason">
                  · {{ primaryAssignee.assignment_reason }}
                </span>
              </p>
              <p>风险周期：第 {{ workflow.cycleNo || 1 }} 周期</p>
            </div>
            <el-empty v-else description="当前主预警暂无核查事件" :image-size="60" />
          </div>

          <div v-if="canManage && workflow.eventId" class="section-card record-editor">
            <h4>记录本次核查进展</h4>
            <div class="status-editor">
              <el-select v-model="nextStatus" size="small" placeholder="选择核查状态">
                <el-option
                  v-for="status in workflowStatuses"
                  :key="status.value"
                  :label="status.label"
                  :value="status.value"
                />
              </el-select>
              <el-button
                type="primary"
                size="small"
                :loading="saving"
                @click="saveStatus"
              >更新状态</el-button>
            </div>
            <el-input
              v-model="followup"
              type="textarea"
              :rows="3"
              maxlength="1000"
              show-word-limit
              placeholder="填写已核实事实、联系情况或后续关注事项"
            />
            <div class="record-editor__footer">
              <span>记录保存在本平台，不回写教务源库。</span>
              <el-button
                type="primary"
                size="small"
                :loading="saving"
                @click="addFollowup"
              >保存核查记录</el-button>
            </div>
          </div>

          <div class="section-card">
            <h4>历史记录</h4>
            <div v-if="workflow.followups?.length" class="followup-list">
              <div v-for="item in workflow.followups" :key="item.followup_id" class="followup-item">
                <div>
                  <b>{{ item.operator }}</b>
                  <span>{{ item.action_type }} · {{ formatDate(item.created_at) }}</span>
                </div>
                <p>{{ item.content }}</p>
              </div>
            </div>
            <el-empty v-else description="暂无人工核查或跟进记录" :image-size="70" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { http } from '@/utils/http'
import { authStore } from '@/store/auth'
import EChart from '@/components/EChart.vue'
import TrajectoryCard from './TrajectoryCard.vue'

const props = defineProps<{
  modelValue: boolean
  row: any | null
}>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'ai', row: any): void
  (event: 'changed'): void
}>()

const route = useRoute()
const router = useRouter()
const activeSection = ref('summary')
const loading = ref(false)
const loadError = ref('')
const student = ref<any>({})
const workflow = ref<any>({})
const nextStatus = ref('')
const followup = ref('')
const saving = ref(false)
let requestSequence = 0

const workflowStatuses = [
  { value: 'new', label: '待核查' },
  { value: 'assigned', label: '已分派' },
  { value: 'notified', label: '已通知' },
  { value: 'contacted', label: '核查中' },
  { value: 'supporting', label: '跟进中' },
  { value: 'review_pending', label: '待复核' },
  { value: 'resolved', label: '已有核查记录' },
  { value: 'closed', label: '已关闭' },
]

const primarySignal = computed(() => props.row?.signals?.[0] || null)
const failedScores = computed(() =>
  (student.value.scores || []).filter((item: any) => !item.passed),
)
const primaryAssignee = computed(() =>
  workflow.value.assignees?.find((item: any) => item.is_primary)
  || workflow.value.assignees?.[0],
)
const canManage = computed(() => {
  const actions = authStore.user?.permissionContext?.actionPermissions || []
  return actions.includes('alert.event.manage_all') || Boolean(props.row?.assignedToCurrent)
})
const studentKpis = computed(() => {
  const summary = student.value.studySummary || {}
  return [
    { label: '当前GPA', value: findKpi('当前GPA') || '—' },
    { label: '已修学分', value: summary.passed?.credits ?? findKpi('已修学分') ?? '—' },
    { label: '当前未解决课程', value: `${summary.failed?.courses ?? failedScores.value.length}门` },
    { label: '当前规则命中', value: `${props.row?.alertCount || 0}条` },
  ]
})
const gpaTrendOption = computed(() => {
  const values = student.value.gpaHistory || []
  return {
    grid: { left: 8, right: 16, top: 20, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: values.map((_: number, index: number) => `学期${index + 1}`),
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b' },
    },
    yAxis: {
      type: 'value', min: 0, max: 5,
      splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#64748b' },
    },
    series: [{
      type: 'line',
      data: values,
      smooth: true,
      symbolSize: 7,
      lineStyle: { color: '#4f46e5', width: 3 },
      itemStyle: { color: '#4f46e5' },
      areaStyle: { color: 'rgba(79,70,229,.08)' },
    }],
  }
})

function findKpi(label: string) {
  return (student.value.kpis || []).find((item: any) => item.label === label)?.value
}
function levelType(level: string) {
  return level === '严重' ? 'danger' : level === '警告' ? 'warning' : 'info'
}
function workflowLabel(status: string) {
  return workflowStatuses.find(item => item.value === status)?.label || status || '—'
}
function formatDate(value: string) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}
function openFullProfile() {
  if (!props.row?.studentId) return
  router.push({
    path: `/admin/student/${props.row.studentId}`,
    query: {
      returnTo: route.fullPath,
      returnLabel: '学业预警监控',
    },
  })
}

async function load() {
  if (!props.modelValue || !props.row?.studentId) return
  const sequence = ++requestSequence
  loading.value = true
  loadError.value = ''
  activeSection.value = 'summary'
  student.value = {}
  workflow.value = {}
  nextStatus.value = ''
  followup.value = ''
  const eventId = primarySignal.value?.eventId
  try {
    const [studentResult, workflowResult] = await Promise.allSettled([
      http.get(`/admin/student/${props.row.studentId}`),
      eventId ? http.get(`/admin/alert-events/${eventId}`) : Promise.resolve({}),
    ])
    if (sequence !== requestSequence) return
    if (studentResult.status === 'rejected') throw studentResult.reason
    student.value = studentResult.value || {}
    if (workflowResult.status === 'fulfilled') {
      workflow.value = workflowResult.value || {}
      nextStatus.value = workflow.value.workflowStatus || ''
    }
  } catch (error: any) {
    if (sequence !== requestSequence) return
    loadError.value = error?.message || '请稍后重试'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function addFollowup() {
  if (!workflow.value.eventId || !followup.value.trim()) {
    ElMessage.warning('请填写本次核查事实或跟进事项')
    return
  }
  saving.value = true
  try {
    await http.post(`/admin/alert-events/${workflow.value.eventId}/followups`, {
      action_type: '核查记录',
      content: followup.value.trim(),
    })
    followup.value = ''
    await load()
    activeSection.value = 'records'
    emit('changed')
    ElMessage.success('核查记录已保存')
  } finally {
    saving.value = false
  }
}

async function saveStatus() {
  if (!workflow.value.eventId || !nextStatus.value) return
  saving.value = true
  try {
    await http.put(`/admin/alert-events/${workflow.value.eventId}/status`, {
      status: nextStatus.value,
      reason: '在学生预警核查抽屉中更新',
    })
    await load()
    activeSection.value = 'records'
    emit('changed')
    ElMessage.success('核查状态已更新')
  } finally {
    saving.value = false
  }
}

watch(
  () => [props.modelValue, props.row?.studentId],
  () => {
    if (props.modelValue) load()
    else requestSequence += 1
  },
)
</script>

<style scoped>
.review-drawer { min-height: 420px; }
.review-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 16px; padding-bottom: 14px; border-bottom: 1px solid var(--sa-border);
}
.review-name { display: flex; align-items: center; gap: 8px; color: var(--sa-text); font-size: 20px; font-weight: 700; }
.review-meta { margin-top: 5px; color: var(--sa-muted); font-size: 12px; }
.review-head__actions { display: flex; gap: 8px; }
.drawer-loading { padding: 22px 6px; }
.drawer-loading p { margin-top: 12px; color: var(--sa-muted); text-align: center; font-size: 12px; }
.review-tabs { margin-top: 12px; }
.summary-callout {
  display: flex; justify-content: space-between; gap: 16px;
  padding: 16px; border: 1px solid #fecdd3; border-left: 4px solid #e11d48;
  border-radius: 10px; background: #fff7f8;
}
.summary-callout span { display: block; color: #9f1239; font-size: 11px; }
.summary-callout b { display: block; margin-top: 3px; color: #881337; font-size: 15px; }
.summary-callout p { margin: 5px 0 0; color: #475569; font-size: 12px; line-height: 1.65; }
.summary-count { min-width: 100px; text-align: center; }
.summary-count b { color: #e11d48; font-size: 28px; }
.drawer-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 12px 0; }
.drawer-kpi { padding: 12px; text-align: center; border: 1px solid var(--sa-border); border-radius: 9px; background: #f8fafc; }
.drawer-kpi b { display: block; color: var(--sa-text); font-size: 18px; }
.drawer-kpi span { display: block; margin-top: 3px; color: var(--sa-muted); font-size: 11px; }
.section-card { margin-bottom: 12px; padding: 14px; border: 1px solid var(--sa-border); border-radius: 10px; background: #fff; }
.section-card h4 { margin: 0 0 10px; color: var(--sa-text); font-size: 14px; }
.section-title-row { display: flex; align-items: center; justify-content: space-between; }
.signal-item { padding: 9px 0; border-bottom: 1px solid #f1f5f9; }
.signal-item:last-child { border-bottom: 0; }
.signal-item > div { display: flex; align-items: center; gap: 7px; }
.signal-item > div b { color: var(--sa-text); font-size: 12px; }
.signal-item > div span { margin-left: auto; color: var(--sa-muted); font-size: 11px; }
.signal-item p { margin: 5px 0 2px; color: #475569; font-size: 12px; }
.signal-item small { color: #94a3b8; }
.evidence-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.evidence-list > div { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-bottom: 1px solid #f1f5f9; font-size: 12px; }
.evidence-list > div:last-child { border-bottom: 0; }
.evidence-list span { color: #475569; }
.evidence-list b { color: var(--sa-text); text-align: right; font-weight: 600; }
.workflow-info p { margin: 5px 0; color: #475569; font-size: 12px; }
.status-editor { display: flex; gap: 8px; margin-bottom: 10px; }
.status-editor .el-select { width: 180px; }
.record-editor__footer { display: flex; align-items: center; justify-content: space-between; margin-top: 9px; }
.record-editor__footer span { color: #94a3b8; font-size: 11px; }
.followup-item { padding: 9px 0; border-bottom: 1px solid #f1f5f9; }
.followup-item:last-child { border-bottom: 0; }
.followup-item > div { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.followup-item > div span { color: #94a3b8; }
.followup-item p { margin: 5px 0 0; color: #475569; font-size: 12px; white-space: pre-wrap; }
@media (max-width: 900px) {
  .drawer-kpis { grid-template-columns: repeat(2, 1fr); }
  .evidence-grid { grid-template-columns: 1fr; }
  .review-head { flex-direction: column; }
}
</style>

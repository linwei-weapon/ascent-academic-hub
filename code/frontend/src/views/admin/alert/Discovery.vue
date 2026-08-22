<template>
  <div>
    <el-breadcrumb v-if="!embedded" separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/alert'}">学业预警监控</el-breadcrumb-item>
      <el-breadcrumb-item>规则自发现</el-breadcrumb-item>
    </el-breadcrumb>
    <div class="sa-head-row">
      <div v-if="!embedded">
        <h2 class="sa-page-title">规则自发现</h2>
        <p class="sa-page-sub">历史风险关联建议 · 采纳后必须进入规则治理流程，不会自动产生预警</p>
      </div>
      <el-button
        type="primary"
        size="small"
        :loading="isDiscovering"
        :disabled="!canManageDiscovery || isDiscovering"
        @click="openRunConfirmation"
      >{{ isDiscovering ? '新一轮分析运行中' : '运行新一轮分析' }}</el-button>
    </div>

    <el-alert
      v-if="isDiscovering"
      class="run-state-alert"
      type="info"
      :closable="false"
      show-icon
      title="新一轮规则自发现正在后台运行"
      description="可以继续查看或离开本页；运行完成后，候选规则会自动刷新到待审核建议。"
    />
    <el-alert
      v-else-if="runStatus.status === 'failed'"
      class="run-state-alert"
      type="error"
      :closable="false"
      show-icon
      title="上一轮规则自发现运行失败"
      :description="runStatus.errorMessage || '请核对模型接入与样本数据后重试。'"
    />

    <el-alert v-if="loadError" type="error" :closable="false" show-icon
      title="规则自发现结果加载失败" style="margin-bottom:14px">
      <template #default>{{loadError}} <el-button link type="primary" @click="loadData">重新加载</el-button></template>
    </el-alert>
    <div v-if="initialLoading" class="discovery-loading">
      <b>正在加载候选规则、历史样本和治理衔接状态</b>
      <el-skeleton :rows="7" animated />
    </div>
    <template v-else>
      <el-alert :title="evidence.limitation || '历史关联不等于因果关系'" type="warning"
        :closable="false" show-icon style="margin-bottom:14px" />

    <div class="sa-card summary">
      <div><span>分析周期</span><b>{{ lastSemester || '—' }}</b></div>
      <div><span>轨迹学生</span><b>{{ totalStudents.toLocaleString() }}</b></div>
      <div><span>待审核</span><b>{{ discovered.pending.length }}</b></div>
      <div><span>已采纳</span><b>{{ discovered.approved.length }}</b></div>
    </div>

    <div class="sa-card" style="margin-top:14px">
      <div class="sa-card-title">待审核建议（{{ discovered.pending.length }}）</div>
      <el-empty v-if="!discovered.pending.length" description="当前没有待审核建议" />
      <div v-for="rule in discovered.pending" :key="rule.id" class="rule-card">
        <div class="rule-head">
          <div><b>{{ rule.name }}</b><el-tag size="small" style="margin-left:8px" :type="levelType(rule.level)">建议{{ rule.level }}</el-tag></div>
          <span class="risk">风险倍数 {{ rule.riskRatio }}×</span>
        </div>
        <div class="conditions">
          <span v-for="(c,index) in rule.conditions" :key="c.key">
            <i v-if="index">且</i>{{ c.label }} {{ c.op }} <b>{{ c.value }}{{ c.unit }}</b>
          </span>
        </div>
        <div class="evidence-line">
          命中 {{ rule.sampleSize.toLocaleString() }} 人；其中风险信号
          {{ rule.detail?.match_rate ?? '—' }}%（{{ rule.detail?.match_positive ?? '—' }}/{{ rule.detail?.match_total ?? '—' }}），
          全体基线 {{ rule.detail?.overall_rate ?? '—' }}%。算法 {{ rule.detail?.algorithm_version || '—' }}。
        </div>
        <div class="actions">
          <el-button size="small" type="success" :disabled="!canReview" @click="review(rule,'approve')">采纳并创建变更草稿</el-button>
          <el-button size="small" type="danger" plain :disabled="!canReview" @click="review(rule,'reject')">拒绝建议</el-button>
        </div>
      </div>
    </div>

    <div v-if="discovered.approved.length" class="sa-card" style="margin-top:14px">
      <div class="sa-card-title">已采纳建议</div>
      <el-table :data="discovered.approved" size="small">
        <el-table-column prop="name" label="规则建议" min-width="220" />
        <el-table-column prop="approvedAt" label="采纳时间" width="180" />
        <el-table-column label="治理衔接" min-width="180">
          <template #default="{row}">
            <span v-if="row.detail?.governance_change_id">规则变更单 #{{ row.detail.governance_change_id }}</span>
            <span v-else class="sa-faint">历史规则</span>
          </template>
        </el-table-column>
        <el-table-column width="130"><template #default><span class="sa-faint">已进入上方规则治理流程</span></template></el-table-column>
      </el-table>
    </div>

    <div v-if="discovered.rejected.length" class="sa-card" style="margin-top:14px">
      <div class="sa-card-title">已拒绝建议（{{ discovered.rejected.length }}）</div>
      <el-table :data="discovered.rejected" size="small" max-height="280">
        <el-table-column prop="name" label="规则建议" min-width="220" />
        <el-table-column prop="createdAt" label="发现时间" width="180" />
        <el-table-column prop="riskRatio" label="风险倍数" width="100" />
      </el-table>
    </div>
    <div v-if="discovered.superseded.length" class="sa-card" style="margin-top:14px">
      <div class="sa-card-title">已被新一轮分析替代（{{ discovered.superseded.length }}）</div>
      <el-table :data="discovered.superseded" size="small" max-height="240">
        <el-table-column prop="name" label="历史建议" min-width="220" />
        <el-table-column prop="createdAt" label="发现时间" width="180" />
        <el-table-column prop="riskRatio" label="当时风险倍数" width="120" />
      </el-table>
    </div>
    </template>

    <el-dialog
      v-model="confirmationVisible"
      title="运行新一轮分析"
      width="760px"
      destroy-on-close
      :close-on-click-modal="false"
      @closed="consentAccepted = false"
    >
      <div v-if="previewLoading" class="confirmation-loading">
        <el-skeleton :rows="8" animated />
      </div>
      <el-alert
        v-else-if="previewError"
        type="error"
        :closable="false"
        show-icon
        title="本次计算样本清单加载失败"
        :description="previewError"
      />
      <div v-else class="confirmation-content">
        <section class="manifest-summary">
          <span>本次计算样本库表总数</span>
          <b>{{ preview.summary?.tableCount || 0 }} 个</b>
          <i></i>
          <span>样本数据总量</span>
          <b>{{ (preview.summary?.totalRows || 0).toLocaleString() }} 条</b>
          <i></i>
          <span>样本学生数</span>
          <b>{{ (preview.summary?.analyzableStudents || 0).toLocaleString() }} 人</b>
        </section>

        <section class="confirmation-section">
          <h4>样本库表数据清单</h4>
          <el-table :data="preview.tables || []" size="small" max-height="250" border>
            <el-table-column prop="tableLabel" label="库表中文名称" min-width="180" />
            <el-table-column prop="tableName" label="库表英文名称" min-width="180" />
            <el-table-column label="拟参与计算数据量" width="160" align="right">
              <template #default="{ row }">
                {{ Number(row.rowCount || 0).toLocaleString() }} 条
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section class="confirmation-section">
          <h4>数据脱敏说明</h4>
          <p>{{ preview.anonymization?.summary }}</p>
          <ul>
            <li v-for="rule in preview.anonymization?.rules || []" :key="rule">{{ rule }}</li>
          </ul>
        </section>

        <section class="confirmation-section agreement-section">
          <h4>免责说明协议</h4>
          <el-checkbox v-model="consentAccepted">
            {{ preview.agreement?.text }}
          </el-checkbox>
          <p>执行后，本周期原“待审核建议”将标记为“已替代”；候选建议不会自动成为生产规则。</p>
        </section>
      </div>

      <template #footer>
        <el-button @click="rejectExecution">拒绝</el-button>
        <el-button
          type="primary"
          :loading="executing"
          :disabled="!consentAccepted"
          @click="executeDiscovery"
        >执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{embedded?:boolean}>(), {embedded:false})
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '@/utils/http'
import { authStore } from '@/store/auth'

interface DiscoveredRule { id:number; name:string; level:string; conditions:any[]; riskRatio:number; sampleSize:number; detail:any; approvedAt?:string }
const discovered = reactive<{pending:DiscoveredRule[];approved:DiscoveredRule[];rejected:DiscoveredRule[];superseded:DiscoveredRule[]}>({pending:[],approved:[],rejected:[],superseded:[]})
const lastSemester = ref('')
const totalStudents = ref(0)
const evidence = ref<any>({})
const canReview = ref(false)
const initialLoading = ref(true)
const loadError = ref('')
const confirmationVisible = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const preview = ref<any>({})
const consentAccepted = ref(false)
const executing = ref(false)
const runStatus = ref<any>({ status: 'idle' })
const isDiscovering = computed(() => ['queued', 'running'].includes(runStatus.value.status))
const canManageDiscovery = computed(() => (
  authStore.user?.permissionContext?.actionPermissions || []
).includes('rule.discovery.manage'))
let statusTimer: ReturnType<typeof setInterval> | undefined
const levelType = (level:string) => level === '严重' ? 'danger' : level === '警告' ? 'warning' : 'info'

async function loadData() {
  loadError.value = ''
  try {
    const data:any = await http.get('/admin/settings/rules/discovered')
    discovered.pending = data.pending || []
    discovered.approved = data.approved || []
    discovered.rejected = data.rejected || []
    discovered.superseded = data.superseded || []
    lastSemester.value = data.lastSemester || ''
    totalStudents.value = data.totalStudents || 0
    evidence.value = data.evidence || {}
  } catch (error:any) {
    loadError.value = error?.message || '请稍后重试'
  } finally {
    initialLoading.value = false
  }
}
async function openRunConfirmation() {
  confirmationVisible.value = true
  previewLoading.value = true
  previewError.value = ''
  consentAccepted.value = false
  try {
    preview.value = await http.get('/admin/settings/rules/discovery/preview')
  } catch (error:any) {
    previewError.value = error?.message || '请稍后重试'
  } finally {
    previewLoading.value = false
  }
}
function rejectExecution() {
  confirmationVisible.value = false
  consentAccepted.value = false
}
async function executeDiscovery() {
  if (!consentAccepted.value || !preview.value.manifestFingerprint) return
  executing.value = true
  try {
    const data:any = await http.post('/admin/settings/rules/discover', {
      consent: true,
      manifestFingerprint: preview.value.manifestFingerprint,
    })
    runStatus.value = data
    confirmationVisible.value = false
    consentAccepted.value = false
    ElMessage.success('新一轮分析已进入后台运行')
    await loadData()
    startStatusPolling()
  } catch (error:any) {
    ElMessage.error(error?.message || '规则自发现启动失败')
  } finally {
    executing.value = false
  }
}
async function loadRunStatus(notifyOnCompletion = false) {
  const wasRunning = isDiscovering.value
  try {
    const data:any = await http.get('/admin/settings/rules/discovery/status')
    runStatus.value = data || { status: 'idle' }
    if (['queued', 'running'].includes(runStatus.value.status)) {
      startStatusPolling()
      return
    }
    stopStatusPolling()
    if (notifyOnCompletion && wasRunning && runStatus.value.status === 'completed') {
      await loadData()
      ElMessage.success(`分析完成，形成 ${runStatus.value.candidateCount || 0} 条候选建议`)
    } else if (notifyOnCompletion && wasRunning && runStatus.value.status === 'failed') {
      ElMessage.error(runStatus.value.errorMessage || '规则自发现运行失败')
    }
  } catch {
    if (notifyOnCompletion) stopStatusPolling()
  }
}
function startStatusPolling() {
  if (statusTimer) return
  statusTimer = setInterval(() => loadRunStatus(true), 2000)
}
function stopStatusPolling() {
  if (!statusTimer) return
  clearInterval(statusTimer)
  statusTimer = undefined
}
async function review(rule:DiscoveredRule, action:'approve'|'reject') {
  const text = action === 'approve'
    ? '采纳后仅创建规则变更草稿，仍需试算、复核、发布和激活。确认采纳？'
    : '确认拒绝该规则建议？'
  await ElMessageBox.confirm(text, action === 'approve' ? '采纳规则建议' : '拒绝规则建议', {type:action === 'approve'?'warning':'info'})
  const data:any = await http.put(`/admin/settings/rules/discovered/${rule.id}`, {action})
  ElMessage.success(data.msg || (action === 'approve' ? '已创建治理草稿' : '已拒绝'))
  await loadData()
}
onMounted(async () => {
  try {
    const perms:any = await http.get('/admin/settings/rule-permissions/me')
    canReview.value = (perms.permissions || []).includes('edit')
  } catch { canReview.value = false }
  await Promise.all([loadData(), loadRunStatus()])
})
onBeforeUnmount(stopStatusPolling)
</script>

<style scoped>
.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.discovery-loading{padding:16px;border:1px solid var(--sa-border);border-radius:10px;background:#fff}.discovery-loading b{display:block;margin-bottom:14px;color:#334155;font-size:13px}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.summary div{display:flex;flex-direction:column;gap:5px}.summary span{font-size:12px;color:#94A3B8}.summary b{font-size:20px;color:#1E293B}.rule-card{border:1px solid var(--sa-border);border-radius:10px;padding:14px;margin-top:10px}.rule-head{display:flex;justify-content:space-between;align-items:center}.risk{font-size:13px;font-weight:600;color:#D97706}.conditions{font-size:13px;color:#475569;margin-top:10px}.conditions i{font-style:normal;color:#94A3B8;margin:0 8px}.evidence-line{font-size:12px;color:#64748B;background:#F8FAFC;border-radius:7px;padding:9px 10px;margin-top:10px;line-height:1.7}.actions{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}@media(max-width:900px){.summary{grid-template-columns:repeat(2,1fr)}}
.run-state-alert { margin-bottom: 14px; }
.confirmation-loading { padding: 8px 0; }
.confirmation-content { display: flex; flex-direction: column; gap: 16px; }
.manifest-summary {
  display: grid; grid-template-columns: auto auto 1px auto auto 1px auto auto;
  align-items: baseline; gap: 8px 12px; padding: 13px 14px;
  border: 1px solid #c7d2fe; border-radius: 9px; background: #f8faff;
}
.manifest-summary span { color: #64748b; font-size: 12px; }
.manifest-summary b { color: #1e293b; font-size: 17px; }
.manifest-summary i { width: 1px; height: 24px; background: #dbe3f4; }
.confirmation-section h4 { margin: 0 0 8px; color: #1e293b; font-size: 14px; }
.confirmation-section > p { margin: 0 0 8px; color: #475569; font-size: 12px; line-height: 1.7; }
.confirmation-section ul { margin: 0; padding-left: 20px; color: #64748b; font-size: 12px; line-height: 1.8; }
.agreement-section {
  padding: 12px 14px; border: 1px solid #fed7aa; border-radius: 9px; background: #fffaf5;
}
.agreement-section :deep(.el-checkbox) { height: auto; align-items: flex-start; white-space: normal; }
.agreement-section :deep(.el-checkbox__label) { color: #334155; line-height: 1.65; white-space: normal; }
.agreement-section > p { margin: 8px 0 0 24px; color: #b45309; font-size: 11px; }
@media(max-width:900px){
  .manifest-summary { grid-template-columns: 1fr auto; }
  .manifest-summary i { display: none; }
}
</style>

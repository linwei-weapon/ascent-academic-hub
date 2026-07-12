<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/alert'}">预警查看</el-breadcrumb-item>
      <el-breadcrumb-item>规则自发现</el-breadcrumb-item>
    </el-breadcrumb>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">规则自发现</h2>
        <p class="sa-page-sub">历史风险关联建议 · 采纳后必须进入规则治理流程，不会自动产生预警</p>
      </div>
      <el-button type="primary" size="small" :loading="discovering" :disabled="!canEdit" @click="runDiscovery">运行新一轮分析</el-button>
    </div>

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
          <el-button size="small" type="success" :disabled="!canEdit" @click="review(rule,'approve')">采纳并创建变更草稿</el-button>
          <el-button size="small" type="danger" plain :disabled="!canEdit" @click="review(rule,'reject')">拒绝建议</el-button>
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
        <el-table-column width="130"><template #default><el-button text type="primary" @click="$router.push('/admin/settings')">查看规则治理</el-button></template></el-table-column>
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
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '@/utils/http'

interface DiscoveredRule { id:number; name:string; level:string; conditions:any[]; riskRatio:number; sampleSize:number; detail:any; approvedAt?:string }
const discovered = reactive<{pending:DiscoveredRule[];approved:DiscoveredRule[];rejected:DiscoveredRule[];superseded:DiscoveredRule[]}>({pending:[],approved:[],rejected:[],superseded:[]})
const lastSemester = ref('')
const totalStudents = ref(0)
const evidence = ref<any>({})
const discovering = ref(false)
const canEdit = ref(false)
const levelType = (level:string) => level === '严重' ? 'danger' : level === '警告' ? 'warning' : 'info'

async function loadData() {
  const data:any = await http.get('/admin/settings/rules/discovered')
  discovered.pending = data.pending || []
  discovered.approved = data.approved || []
  discovered.rejected = data.rejected || []
  discovered.superseded = data.superseded || []
  lastSemester.value = data.lastSemester || ''
  totalStudents.value = data.totalStudents || 0
  evidence.value = data.evidence || {}
}
async function runDiscovery() {
  await ElMessageBox.confirm('新一轮分析会将当前待审核建议标记为“已替代”，但不会修改生产规则。是否继续？','运行规则自发现',{type:'warning'})
  discovering.value = true
  try {
    const data:any = await http.post('/admin/settings/rules/discover')
    ElMessage.success(`分析完成，形成 ${data.count} 条候选建议`)
    await loadData()
  } finally { discovering.value = false }
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
    canEdit.value = (perms.permissions || []).includes('edit')
  } catch { canEdit.value = false }
  await loadData()
})
</script>

<style scoped>
.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.summary div{display:flex;flex-direction:column;gap:5px}.summary span{font-size:12px;color:#94A3B8}.summary b{font-size:20px;color:#1E293B}.rule-card{border:1px solid var(--sa-border);border-radius:10px;padding:14px;margin-top:10px}.rule-head{display:flex;justify-content:space-between;align-items:center}.risk{font-size:13px;font-weight:600;color:#D97706}.conditions{font-size:13px;color:#475569;margin-top:10px}.conditions i{font-style:normal;color:#94A3B8;margin:0 8px}.evidence-line{font-size:12px;color:#64748B;background:#F8FAFC;border-radius:7px;padding:9px 10px;margin-top:10px;line-height:1.7}.actions{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}@media(max-width:900px){.summary{grid-template-columns:repeat(2,1fr)}}
</style>

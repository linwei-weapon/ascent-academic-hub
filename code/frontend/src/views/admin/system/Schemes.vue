<template>
  <div class="scheme-page">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">分析方案管理</h2>
        <p class="sa-page-sub">集中管理学校管理专家版本与分析方案；普通用户不需要理解技术 Skill 或 Prompt。</p>
      </div>
      <el-button type="primary" @click="$router.push('/admin/reports/decision')">前往决策简报</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="boundary-alert" :title="data.boundary || '学校方案不改变正式指标和数据权限。'" />

    <div class="summary-grid">
      <div><span>管理专家</span><b>{{ data.experts?.length || 0 }}</b><small>产品注册并通过协议校验</small></div>
      <div><span>已发布方案</span><b>{{ statusCount('published') }}</b><small>可供适用角色使用</small></div>
      <div><span>待测试草稿</span><b>{{ statusCount('draft') }}</b><small>发布前应完成兼容性测试</small></div>
      <div><span>学校专家版本</span><b>{{ data.versions?.length || 0 }}</b><small>支持发布与回滚</small></div>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="分析方案" name="schemes">
        <div class="sa-card">
          <el-table :data="data.schemes || []" v-loading="loading" size="small">
            <el-table-column label="方案" min-width="210">
              <template #default="{row}">
                <div class="main-cell">{{ row.name }}</div>
                <div class="sub-cell">#{{ row.scheme_id }} · {{ expertName(row.expert_id) }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="expert_version" label="专家版本" width="150" />
            <el-table-column label="状态" width="100">
              <template #default="{row}"><el-tag size="small" effect="plain" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="适用角色" min-width="220">
              <template #default="{row}">
                <span>{{ roleSummary(row.roleIds) }}</span>
                <el-button text type="primary" size="small" @click="editRoles(row)">调整</el-button>
              </template>
            </el-table-column>
            <el-table-column label="创建/发布" min-width="190">
              <template #default="{row}">
                <div>{{ row.created_by }} · {{ row.created_at }}</div>
                <div class="sub-cell">{{ row.published_at ? `发布：${row.published_by} · ${row.published_at}` : '尚未发布' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{row}">
                <el-button text size="small" @click="testScheme(row)">测试</el-button>
                <el-button v-if="row.status==='draft'" text type="primary" size="small" @click="publishScheme(row)">发布</el-button>
                <el-button v-if="row.status!=='retired'" text type="danger" size="small" @click="retireScheme(row)">停用</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="专家版本" name="versions">
        <div class="expert-grid">
          <article v-for="expert in data.experts || []" :key="expert.expertId">
            <span>{{ expert.versionSource === 'school_override' ? '学校配置' : '产品默认' }}</span>
            <b>{{ expert.name }}</b>
            <p>当前版本 {{ expert.effectiveVersion }} · 产品定义 {{ expert.productVersion }}</p>
          </article>
        </div>
        <div class="sa-card">
          <el-table :data="data.versions || []" v-loading="loading" size="small">
            <el-table-column label="专家" min-width="190"><template #default="{row}">{{ expertName(row.expert_id) }}</template></el-table-column>
            <el-table-column prop="version_no" label="学校版本" min-width="160" />
            <el-table-column label="状态" width="100"><template #default="{row}"><el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
            <el-table-column prop="change_reason" label="变更原因" min-width="220" show-overflow-tooltip />
            <el-table-column label="操作" width="170">
              <template #default="{row}">
                <el-button v-if="row.status==='draft'" text type="primary" size="small" @click="publishVersion(row)">发布</el-button>
                <el-button v-if="row.status!=='draft'" text type="warning" size="small" @click="rollbackVersion(row)">回滚到此版本</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="roleVisible" title="方案适用角色" size="520px">
      <p class="drawer-tip">只允许选择该管理专家协议登记的适用角色；运行时仍按用户当前工作身份计算数据范围。</p>
      <el-checkbox-group v-model="selectedRoles" class="role-list">
        <el-checkbox v-for="role in availableRoles" :key="role" :value="role">{{ roleLabel(role) }}</el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="roleVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRoles">保存适用角色</el-button>
      </template>
    </el-drawer>

    <el-dialog v-model="testVisible" title="分析方案测试结果" width="560px">
      <el-result v-if="testResult" :icon="testResult.passed ? 'success' : 'warning'"
        :title="testResult.passed ? '方案可以发布' : '方案暂不能发布'"
        :sub-title="`测试专家版本：${testResult.testedVersion || '—'}`" />
      <div v-if="testResult" class="check-list">
        <div v-for="(passed,key) in testResult.checks" :key="key">
          <span>{{ checkLabel(String(key)) }}</span>
          <el-tag size="small" :type="passed ? 'success' : 'danger'">{{ passed ? '通过' : '未通过' }}</el-tag>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '@/utils/http'
import { ROLE_LABELS } from '@/store/role'

const loading = ref(false)
const saving = ref(false)
const activeTab = ref('schemes')
const data = reactive<any>({experts:[],schemes:[],versions:[]})
const roleVisible = ref(false)
const currentScheme = ref<any>(null)
const selectedRoles = ref<string[]>([])
const testVisible = ref(false)
const testResult = ref<any>(null)

const currentExpert = computed(() => (data.experts || []).find((item:any) => item.expertId === currentScheme.value?.expert_id))
const availableRoles = computed<string[]>(() => currentExpert.value?.applicableRoles || [])

async function load() {
  loading.value = true
  try { Object.assign(data, await http.get('/admin/system/analysis-schemes')) }
  finally { loading.value = false }
}
function expertName(id:string) { return (data.experts || []).find((item:any) => item.expertId === id)?.name || id }
function statusCount(status:string) { return (data.schemes || []).filter((item:any) => item.status === status).length }
function statusLabel(status:string) { return ({draft:'草稿',published:'已发布',retired:'已停用'} as any)[status] || status }
function statusType(status:string) { return status === 'published' ? 'success' : status === 'draft' ? 'warning' : 'info' }
function roleLabel(role:string) { return (ROLE_LABELS as any)[role] || role }
function roleSummary(roles:string[]) { return !roles?.length ? '全部专家适用角色' : roles.slice(0,3).map(roleLabel).join('、') + (roles.length > 3 ? ` 等${roles.length}类` : '') }
function checkLabel(key:string) { return ({expertExists:'专家存在',expertVersionCurrent:'专家版本一致',parametersValid:'参数符合白名单',rolesValid:'适用角色有效',permissionBoundary:'权限边界有效'} as any)[key] || key }

function editRoles(row:any) {
  currentScheme.value = row
  selectedRoles.value = [...(row.roleIds || [])]
  roleVisible.value = true
}
async function saveRoles() {
  if (!currentScheme.value) return
  saving.value = true
  try {
    await http.put(`/admin/system/analysis-schemes/${currentScheme.value.scheme_id}/roles`, {roleIds:selectedRoles.value})
    ElMessage.success('适用角色已保存')
    roleVisible.value = false
    await load()
  } finally { saving.value = false }
}
async function testScheme(row:any) {
  testResult.value = await http.post(`/admin/system/analysis-schemes/${row.scheme_id}/test`)
  testVisible.value = true
}
async function publishScheme(row:any) {
  const result:any = await http.post(`/admin/system/analysis-schemes/${row.scheme_id}/test`)
  if (!result.passed) { testResult.value=result;testVisible.value=true;return }
  await ElMessageBox.confirm('发布后将成为学校正式分析方案，仍按用户实时权限运行。是否发布？','发布分析方案',{type:'warning'})
  await http.post(`/admin/ai/experts/${row.expert_id}/schemes/${row.scheme_id}/publish`)
  ElMessage.success('分析方案已发布')
  await load()
}
async function retireScheme(row:any) {
  await ElMessageBox.confirm('停用后普通用户不再使用该方案，历史记录仍保留。','停用分析方案',{type:'warning'})
  await http.post(`/admin/system/analysis-schemes/${row.scheme_id}/retire`)
  ElMessage.success('分析方案已停用')
  await load()
}
async function publishVersion(row:any) {
  await ElMessageBox.confirm('发布会使同一专家的上一学校版本退役。是否继续？','发布专家版本',{type:'warning'})
  await http.post(`/admin/ai/experts/${row.expert_id}/versions/${row.version_id}/publish`)
  ElMessage.success('专家版本已发布')
  await load()
}
async function rollbackVersion(row:any) {
  await ElMessageBox.confirm('系统会基于该版本生成新的已发布版本，不覆盖历史。是否继续？','回滚专家版本',{type:'warning'})
  await http.post(`/admin/ai/experts/${row.expert_id}/versions/${row.version_id}/rollback`)
  ElMessage.success('已生成新的回滚发布版本')
  await load()
}
onMounted(load)
</script>

<style scoped>
.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}.boundary-alert{margin-bottom:14px}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}.summary-grid>div{padding:16px;background:#fff;border:1px solid var(--sa-border);border-radius:12px}.summary-grid span,.summary-grid small{display:block;color:#64748b;font-size:12px}.summary-grid b{display:block;margin:6px 0;font-size:25px;color:#1e293b}.main-cell{font-weight:650;color:#1e293b}.sub-cell{margin-top:3px;color:#94a3b8;font-size:11px}.expert-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:14px}.expert-grid article{padding:15px;border:1px solid #e2e8f0;border-radius:12px;background:#fff}.expert-grid span{font-size:11px;color:#6366f1}.expert-grid b{display:block;margin:6px 0;color:#1e293b}.expert-grid p,.drawer-tip{color:#64748b;font-size:12px;line-height:1.7}.role-list{display:flex;flex-direction:column;gap:12px}.check-list{display:grid;gap:9px}.check-list>div{display:flex;justify-content:space-between;padding:10px 12px;background:#f8fafc;border-radius:8px}
@media(max-width:1000px){.summary-grid,.expert-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>

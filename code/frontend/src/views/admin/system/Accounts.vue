<template>
  <div
    v-loading="initialLoading"
    element-loading-text="正在核验账号、认证映射和权限准备状态…"
    element-loading-background="rgba(248,250,252,.86)"
  >
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">账号管理</h2>
        <p class="sa-page-sub">管理平台访问账号、认证接入状态和权限准备度；人员与组织主数据仍由学校权威系统维护。</p>
      </div>
      <div class="head-actions">
        <el-button @click="openReadiness">认证接入检查</el-button>
        <el-button type="primary" @click="openCreate">+ 新建本地账号</el-button>
      </div>
    </div>

    <el-alert
      class="boundary-alert"
      type="info"
      :closable="false"
      show-icon
      title="统一认证账号应优先由学校人员数据和认证主体映射产生；手工账号仅用于本地应急、实施测试或服务接入。"
    />

    <div class="account-kpis">
      <button
        v-for="card in summaryCards"
        :key="card.key"
        type="button"
        class="account-kpi"
        :class="{ active: activeCard === card.key }"
        @click="applySummaryCard(card.key)"
      >
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.description }}</small>
      </button>
    </div>

    <div class="sa-card filter-card">
      <div class="filter-head">
        <b>查询账号</b>
        <span>查询条件只影响下方列表，顶部卡片始终反映全部账号治理状态</span>
      </div>
      <div class="filter-row">
        <el-input
          v-model="draft.keyword"
          clearable
          placeholder="账号、姓名或教职工号"
          style="width:220px"
          @keyup.enter="applyFilters"
        />
        <el-select v-model="draft.accountSource" clearable placeholder="全部账号来源" style="width:150px">
          <el-option label="本地账号" value="local" />
          <el-option label="学校同步" value="school_sync" />
          <el-option label="服务账号" value="service" />
        </el-select>
        <el-select v-model="draft.roleId" clearable filterable placeholder="全部工作身份" style="width:170px">
          <el-option v-for="role in roles" :key="role.role_id" :label="role.name" :value="role.role_id" />
        </el-select>
        <el-select v-model="draft.authStatus" clearable placeholder="全部认证状态" style="width:150px">
          <el-option label="已映射" value="mapped" />
          <el-option label="待映射" value="unmapped" />
        </el-select>
        <el-select v-model="draft.permissionStatus" clearable placeholder="全部权限状态" style="width:150px">
          <el-option label="权限就绪" value="ready" />
          <el-option label="需要处理" value="issue" />
        </el-select>
        <el-select v-model="draft.status" clearable placeholder="全部账号状态" style="width:135px">
          <el-option label="已启用" value="active" />
          <el-option label="已停用" value="disabled" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </div>

    <el-alert v-if="loadError" class="load-error" type="error" :closable="false" show-icon>
      <template #title>账号列表加载失败，已保留当前查询条件</template>
      <template #default>
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="loadUsers">重新加载</el-button>
      </template>
    </el-alert>

    <div class="sa-card account-table-card">
      <div class="table-title">
        <div>
          <b>账号与接入状态</b>
          <span>共 {{ total }} 个结果；点击账号在当前页面核查完整证据</span>
        </div>
      </div>
      <DataTable
        :columns="columns"
        :data="users"
        storage-key="system:accounts"
        :max-business-columns="6"
        :config-version="2"
        v-model:page-size="pageSize"
        :page-sizes="[10,20,50,100]"
        stripe
        size="small"
        v-loading="loading"
        row-class-name="clickable-row"
        @row-click="openDetail"
      >
        <template #col-user="{ row }">
          <div class="user-cell">
            <b>{{ row.name || '未填写姓名' }}</b>
            <span>{{ row.username }}</span>
          </div>
        </template>
        <template #col-account_source="{ row }">
          <el-tag size="small" effect="plain" :type="sourceTag(row.account_source)">
            {{ sourceLabel(row.account_source) }}
          </el-tag>
        </template>
        <template #col-auth="{ row }">
          <div v-if="row.auth_status === 'mapped'" class="auth-cell">
            <span>{{ providerLabel(row.auth_provider) }}</span>
            <small>{{ row.auth_subject_id }}</small>
            <el-tag v-if="row.auth_mapping_count > 1" size="small" effect="plain">
              +{{ row.auth_mapping_count - 1 }}个来源
            </el-tag>
          </div>
          <el-tag v-else size="small" type="warning" effect="plain">待映射</el-tag>
        </template>
        <template #col-role="{ row }">
          <div v-if="row.role_name">
            <el-tag size="small" effect="plain">{{ row.role_name }}</el-tag>
            <small v-if="row.identity_count > 1" class="inline-note">共{{ row.identity_count }}个身份</small>
          </div>
          <el-tag v-else size="small" type="danger" effect="plain">缺少默认身份</el-tag>
        </template>
        <template #col-permission="{ row }">
          <div v-if="row.permissionStatus === 'ready'" class="status-line ready">
            <i></i><span>权限就绪</span>
          </div>
          <div v-else class="permission-issue">
            <div class="status-line issue"><i></i><span>需要处理</span></div>
            <small>{{ row.issues?.[0] || '权限映射不完整' }}</small>
          </div>
        </template>
        <template #col-status="{ row }">
          <el-tag
            size="small"
            effect="plain"
            :type="row.status === 'active' && !row.archived_at ? 'success' : 'info'"
          >{{ row.archived_at ? '已归档' : row.status === 'active' ? '已启用' : '已停用' }}</el-tag>
        </template>
        <template #col-last_login="{ row }">{{ formatTime(row.last_login_at) }}</template>
        <template #col-staff_id="{ row }">{{ row.staff_id || '—' }}</template>
        <template #col-actions="{ row }">
          <div class="row-actions" @click.stop>
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-dropdown trigger="click" @command="(command:any) => handleCommand(command,row)">
              <el-button link>更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="auth">认证映射</el-dropdown-item>
                  <el-dropdown-item command="permission">数据权限</el-dropdown-item>
                  <el-dropdown-item command="edit">编辑基本信息</el-dropdown-item>
                  <el-dropdown-item command="status">
                    {{ row.status === 'active' ? '停用账号' : '启用账号' }}
                  </el-dropdown-item>
                  <el-dropdown-item v-if="row.can_reset_local_password" command="password">重置本地密码</el-dropdown-item>
                  <el-dropdown-item v-if="!row.archived_at" command="archive" divided>归档账号</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </template>
        <template #empty>
          <el-empty description="当前条件下没有账号">
            <el-button @click="resetFilters">清除查询条件</el-button>
          </el-empty>
        </template>
      </DataTable>
      <el-pagination
        v-if="total"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next, jumper"
        size="small"
        @current-change="loadUsers"
      />
    </div>

    <el-drawer v-model="detailVisible" size="640px" :title="`账号核查 · ${detail?.name || detail?.username || ''}`">
      <div v-loading="detailLoading" class="detail-drawer">
        <template v-if="detail">
          <el-alert
            :type="detail.permissionStatus === 'ready' ? 'success' : 'warning'"
            :closable="false"
            show-icon
            :title="detail.permissionStatus === 'ready' ? '账号、工作身份和数据范围已具备访问条件' : '该账号仍有需要处理的接入或权限问题'"
          >
            <template v-if="detail.issues?.length" #default>
              {{ detail.issues.join('；') }}
            </template>
          </el-alert>

          <div class="detail-grid">
            <div><span>账号</span><b>{{ detail.username }}</b></div>
            <div><span>姓名</span><b>{{ detail.name || '未填写' }}</b></div>
            <div><span>账号来源</span><b>{{ sourceLabel(detail.account_source) }}</b></div>
            <div><span>账号状态</span><b>{{ detail.archived_at ? '已归档' : detail.status === 'active' ? '已启用' : '已停用' }}</b></div>
            <div><span>最近登录</span><b>{{ formatTime(detail.lastLoginAt) }}</b></div>
            <div><span>最近更新</span><b>{{ formatTime(detail.updated_at) }}</b></div>
          </div>

          <section class="detail-section">
            <div class="section-head">
              <div><h3>统一身份认证映射</h3><p>只保存认证主体标识，不保存学校认证密码或票据。</p></div>
              <el-button size="small" @click="openAuthMapping(detail)">新增认证来源</el-button>
            </div>
            <div v-if="detail.authMappings?.length" class="mapping-list">
              <div v-for="mapping in detail.authMappings" :key="mapping.auth_identity_id" class="mapping-row">
                <div>
                  <b>{{ providerLabel(mapping.provider) }}</b>
                  <span>{{ mapping.subject_id }}</span>
                  <small>来源：{{ mapping.source || '未知' }} · 更新：{{ formatTime(mapping.updated_at) }}</small>
                </div>
                <div>
                  <el-tag size="small" effect="plain" :type="mapping.status === 'active' ? 'success' : 'info'">
                    {{ mapping.status === 'active' ? '有效' : '已停用' }}
                  </el-tag>
                  <el-button link type="primary" @click="openAuthMapping(detail,mapping)">编辑</el-button>
                </div>
              </div>
            </div>
            <el-empty v-else :image-size="54" description="尚未建立统一身份映射" />
          </section>

          <section class="detail-section">
            <div class="section-head">
              <div><h3>工作身份与数据准备</h3><p>这里只核查摘要，具体范围在数据权限工作台配置。</p></div>
              <el-button size="small" type="primary" plain @click="goPermission(detail)">配置数据权限</el-button>
            </div>
            <div class="identity-list">
              <div v-for="identity in detail.identities || []" :key="identity.identity_id" class="identity-row">
                <div>
                  <b>{{ identity.role_name || identity.role_id }}</b>
                  <span>{{ scopeTypeLabel(identity.data_scope_type) }}</span>
                </div>
                <div>
                  <el-tag v-if="identity.is_default" size="small" effect="plain">默认身份</el-tag>
                  <el-tag v-if="identity.status !== 'active'" size="small" type="info" effect="plain">已失效</el-tag>
                </div>
              </div>
              <el-empty v-if="!detail.identities?.length" :image-size="54" description="没有工作身份" />
            </div>
            <div class="staff-summary">
              教职工号：
              <b>{{ activeStaffIds(detail).join('、') || '未关联' }}</b>
            </div>
          </section>

          <section class="detail-section">
            <div class="section-head"><div><h3>最近账号变更</h3><p>只展示账号治理动作，不展示敏感请求内容。</p></div></div>
            <el-timeline v-if="detail.auditTrail?.length">
              <el-timeline-item
                v-for="audit in detail.auditTrail"
                :key="audit.audit_id"
                :timestamp="formatTime(audit.created_at)"
              >
                {{ auditLabel(audit.action) }} · {{ audit.actor || '系统' }}
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else :image-size="50" description="暂无账号变更记录" />
          </section>
        </template>
      </div>
    </el-drawer>

    <el-dialog v-model="accountDialogVisible" :title="editing ? '编辑账号基本信息' : '新建本地账号'" width="500px">
      <el-alert
        v-if="!editing"
        class="dialog-alert"
        type="warning"
        :closable="false"
        show-icon
        title="本地账号用于应急管理员、实施测试或服务接入；正式人员账号应优先通过学校认证与人员数据同步。"
      />
      <el-form :model="form" label-width="100px">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" :disabled="editing" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.name" placeholder="显示姓名" />
        </el-form-item>
        <el-form-item v-if="!editing" label="初始工作身份" required>
          <el-select v-model="form.role_id" filterable placeholder="选择初始工作身份" style="width:100%">
            <el-option v-for="role in roles" :key="role.role_id" :label="role.name" :value="role.role_id" />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="工作身份">
          <div class="readonly-tip">请在“数据权限”页面添加、停用或调整默认工作身份。</div>
        </el-form-item>
        <el-form-item v-if="!editing" label="初始密码" required>
          <el-input v-model="form.password" type="password" show-password placeholder="至少12位，包含大小写、数字和特殊字符" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAccount">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="authVisible" :title="`认证映射 · ${authUser?.name || authUser?.username || ''}`" width="520px">
      <el-alert class="dialog-alert" type="info" :closable="false" show-icon
        title="认证主体标识在同一认证来源中必须唯一；停用映射不会删除历史记录。" />
      <el-form label-width="120px">
        <el-form-item label="本地账号"><b>{{ authUser?.username }}</b></el-form-item>
        <el-form-item label="认证来源">
          <el-select v-model="authForm.provider" :disabled="authEditingProvider" style="width:100%">
            <el-option label="学校统一身份认证" value="unified_identity" />
            <el-option label="企业微信" value="wecom" />
            <el-option label="学校小程序/APP" value="school_app" />
          </el-select>
        </el-form-item>
        <el-form-item label="认证主体标识" required>
          <el-input v-model="authForm.subject_id" placeholder="学校认证返回的稳定 subject / uid" />
        </el-form-item>
        <el-form-item label="映射状态"><el-switch v-model="authForm.active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="authVisible=false">取消</el-button>
        <el-button type="primary" :loading="authSaving" @click="saveAuthMapping">保存映射</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="readinessVisible" size="620px" title="统一认证接入检查">
      <div v-loading="readinessLoading" class="readiness-drawer">
        <template v-if="readiness">
          <el-alert
            :type="readiness.orphanMappings || readiness.multipleProviderAccounts ? 'warning' : 'success'"
            :closable="false"
            show-icon
            :title="readiness.orphanMappings || readiness.multipleProviderAccounts ? '正式切换前仍有认证映射需要核验' : '当前未发现认证主体冲突或孤儿映射'"
          />
          <div class="readiness-grid">
            <div><span>有效账号</span><b>{{ readiness.active }}</b></div>
            <div><span>已完成映射</span><b>{{ readiness.mapped }}</b></div>
            <div><span>待完成映射</span><b>{{ readiness.pendingAuth }}</b></div>
            <div><span>权限准备异常</span><b>{{ readiness.permissionIssues }}</b></div>
          </div>

          <section class="detail-section">
            <div class="section-head"><div><h3>接入检查清单</h3><p>每所学校只调整字段映射与认证适配，不复制账号页面。</p></div></div>
            <div v-for="item in readiness.implementationChecks || []" :key="item.key" class="check-row">
              <el-icon :class="item.status"><CircleCheckFilled v-if="item.status === 'ready'" /><WarningFilled v-else /></el-icon>
              <div><b>{{ item.label }}</b><span>{{ item.description }}</span></div>
            </div>
          </section>

          <section class="detail-section">
            <div class="section-head">
              <div><h3>学校需确认的字段</h3><p>作为实施接口确认模板，不在页面保存密钥。</p></div>
              <el-button size="small" @click="copyDeliveryTemplate">复制确认模板</el-button>
            </div>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="认证主体">稳定 subject / uid 字段</el-descriptions-item>
              <el-descriptions-item label="人员关联">教职工号字段及有效状态字段</el-descriptions-item>
              <el-descriptions-item label="展示信息">姓名、所属组织字段</el-descriptions-item>
              <el-descriptions-item label="权限来源">角色、带班和导师关系的数据来源</el-descriptions-item>
              <el-descriptions-item label="生命周期">新增、调岗、离职、停用和恢复规则</el-descriptions-item>
            </el-descriptions>
          </section>

          <section class="detail-section">
            <div class="section-head"><div><h3>当前认证来源</h3><p>一个账号可以绑定多个入口，列表仍只保留一个账号事实。</p></div></div>
            <el-table :data="readiness.providers || []" size="small">
              <el-table-column label="认证来源" min-width="170">
                <template #default="{row}">{{ providerLabel(row.provider) }}</template>
              </el-table-column>
              <el-table-column prop="active_count" label="有效映射" width="100" align="right" />
              <el-table-column label="最近更新" min-width="150">
                <template #default="{row}">{{ formatTime(row.last_updated_at) }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!readiness.providers?.length" :image-size="54" description="尚未接入认证来源" />
          </section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, CircleCheckFilled, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DataTable from '@/components/DataTable.vue'
import type { DataTableColumn } from '@/components/DataTable.vue'
import { http } from '@/utils/http'

type AnyRow = Record<string, any>
interface RoleRow { role_id:string; name:string; data_scope_type?:string }

const route = useRoute()
const router = useRouter()
const users = ref<AnyRow[]>([])
const roles = ref<RoleRow[]>([])
const summary = reactive({ total:0, active:0, mapped:0, pendingAuth:0, permissionIssues:0, disabled:0 })
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const initialLoading = ref(true)
const loadError = ref('')
const activeCard = ref('')

const filters = reactive({
  keyword:'', accountSource:'', roleId:'', authStatus:'', permissionStatus:'', status:'',
})
const draft = reactive({ ...filters })

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AnyRow|null>(null)
const accountDialogVisible = ref(false)
const editing = ref(false)
const editId = ref(0)
const saving = ref(false)
const form = reactive({ username:'', name:'', role_id:'', password:'' })
const authVisible = ref(false)
const authSaving = ref(false)
const authUser = ref<AnyRow|null>(null)
const authEditingProvider = ref(false)
const authForm = reactive({ provider:'unified_identity', subject_id:'', active:true })
const readinessVisible = ref(false)
const readinessLoading = ref(false)
const readiness = ref<AnyRow|null>(null)

const columns:DataTableColumn[] = [
  {key:'user',label:'用户与账号',width:185,fixed:'left',required:true,region:'identity'},
  {key:'account_source',label:'账号来源',width:100},
  {key:'auth',label:'统一身份认证',minWidth:170,tooltip:true},
  {key:'role',label:'默认工作身份',minWidth:145},
  {key:'permission',label:'权限准备度',minWidth:170},
  {key:'status',label:'状态',width:86},
  {key:'last_login',label:'最近登录',width:155,defaultVisible:false},
  {key:'staff_id',label:'教职工号',width:145,defaultVisible:false,tooltip:true},
  {key:'actions',label:'操作',width:100,fixed:'right',required:true,region:'action'},
]

const summaryCards = computed(() => [
  {key:'active',label:'有效账号',value:summary.active,description:'当前允许访问平台'},
  {key:'mapped',label:'已完成认证映射',value:summary.mapped,description:'具备统一认证主体'},
  {key:'unmapped',label:'待完成认证映射',value:summary.pendingAuth,description:'需要接入或核验'},
  {key:'issue',label:'权限准备异常',value:summary.permissionIssues,description:'身份、人员或范围不完整'},
  {key:'disabled',label:'已停用或归档',value:summary.disabled,description:'保留历史但禁止访问'},
])

function queryString() {
  const q = new URLSearchParams()
  q.set('page',String(page.value)); q.set('page_size',String(pageSize.value))
  if(filters.keyword) q.set('keyword',filters.keyword)
  if(filters.accountSource) q.set('account_source',filters.accountSource)
  if(filters.roleId) q.set('role_id',filters.roleId)
  if(filters.authStatus) q.set('auth_status',filters.authStatus)
  if(filters.permissionStatus) q.set('permission_status',filters.permissionStatus)
  if(filters.status) q.set('status',filters.status)
  return q.toString()
}

function syncRoute() {
  router.replace({query:{
    ...(filters.keyword?{keyword:filters.keyword}:{}),
    ...(filters.accountSource?{account_source:filters.accountSource}:{}),
    ...(filters.roleId?{role_id:filters.roleId}:{}),
    ...(filters.authStatus?{auth_status:filters.authStatus}:{}),
    ...(filters.permissionStatus?{permission_status:filters.permissionStatus}:{}),
    ...(filters.status?{status:filters.status}:{}),
    ...(page.value>1?{page:String(page.value)}:{}),
    ...(pageSize.value!==20?{page_size:String(pageSize.value)}:{}),
  }})
}

async function loadUsers() {
  loading.value=true; loadError.value=''
  try {
    const data:any = await http.get(`/admin/rbac/users?${queryString()}`)
    users.value=data.items||[]; total.value=Number(data.total||0)
    Object.assign(summary,data.summary||{})
    syncRoute()
  } catch(error:any) {
    loadError.value=error?.message||'请求失败'
  } finally { loading.value=false; initialLoading.value=false }
}

async function loadRoles() {
  roles.value=await http.get('/admin/rbac/roles')
}

function applyFilters() {
  Object.assign(filters,draft); activeCard.value=''; page.value=1; loadUsers()
}
function resetFilters() {
  Object.assign(filters,{keyword:'',accountSource:'',roleId:'',authStatus:'',permissionStatus:'',status:''})
  Object.assign(draft,filters); activeCard.value=''; page.value=1; loadUsers()
}
function applySummaryCard(key:string) {
  Object.assign(filters,{keyword:'',accountSource:'',roleId:'',authStatus:'',permissionStatus:'',status:''})
  if(key==='active') filters.status='active'
  if(key==='mapped') filters.authStatus='mapped'
  if(key==='unmapped') filters.authStatus='unmapped'
  if(key==='issue') filters.permissionStatus='issue'
  if(key==='disabled') filters.status='disabled'
  Object.assign(draft,filters); activeCard.value=key; page.value=1; loadUsers()
}

async function openDetail(row:AnyRow) {
  detailVisible.value=true; detailLoading.value=true; detail.value=null
  try { detail.value=await http.get(`/admin/rbac/users/${row.user_id}`) }
  finally { detailLoading.value=false }
}
function openCreate() {
  editing.value=false; editId.value=0
  Object.assign(form,{username:'',name:'',role_id:'',password:''})
  accountDialogVisible.value=true
}
function openEdit(row:AnyRow) {
  editing.value=true; editId.value=row.user_id
  Object.assign(form,{username:row.username,name:row.name||'',role_id:'',password:''})
  accountDialogVisible.value=true
}
async function saveAccount() {
  if(!form.username || (!editing.value&&!form.role_id)){ElMessage.warning('请填写用户名和初始工作身份');return}
  if(!editing.value&&!isStrongPassword(form.password,form.username)){ElMessage.warning('初始密码须为12~128位，并包含大小写字母、数字和特殊字符，且不能包含用户名');return}
  saving.value=true
  try {
    if(editing.value) await http.put(`/admin/rbac/users/${editId.value}`,{name:form.name})
    else await http.post('/admin/rbac/users',{username:form.username,name:form.name,role_id:form.role_id,password:form.password,status:'active',account_source:'local'})
    ElMessage.success('账号已保存');accountDialogVisible.value=false;await loadUsers()
  } finally { saving.value=false }
}

function openAuthMapping(row:AnyRow,mapping?:AnyRow) {
  authUser.value=row
  authEditingProvider.value=!!mapping
  Object.assign(authForm,{
    provider:mapping?.provider||'unified_identity',
    subject_id:mapping?.subject_id||row.staff_id||'',
    active:mapping?.status!=='inactive',
  })
  authVisible.value=true
}
async function saveAuthMapping() {
  if(!authUser.value||!authForm.subject_id.trim()){ElMessage.warning('请填写认证主体标识');return}
  authSaving.value=true
  try {
    await http.put(`/admin/rbac/users/${authUser.value.user_id}/auth-identity`,{
      provider:authForm.provider,subject_id:authForm.subject_id.trim(),
      status:authForm.active?'active':'inactive',
    })
    ElMessage.success('认证映射已保存');authVisible.value=false
    await loadUsers()
    if(detailVisible.value) await openDetail({user_id:authUser.value.user_id})
  } finally { authSaving.value=false }
}

async function changeStatus(row:AnyRow) {
  const next=row.status==='active'?'disabled':'active'
  const action=next==='active'?'启用':'停用'
  const {value}=await ElMessageBox.prompt(
    `请输入${action}账号「${row.username}」的原因。${next==='disabled'?'账号后续请求将立即被拒绝。':''}`,
    `${action}账号`,
    {inputPlaceholder:'填写变更原因',inputValidator:(v:string)=>v.trim().length>=2||'请填写至少2个字的原因',confirmButtonText:`确认${action}`},
  )
  await http.put(`/admin/rbac/users/${row.user_id}/status`,{status:next,reason:value.trim()})
  ElMessage.success(`账号已${action}`);await loadUsers()
}
async function archiveAccount(row:AnyRow) {
  const {value}=await ElMessageBox.prompt(
    `归档后账号不能登录，认证映射会停用，但工作身份和审计历史继续保留。请输入归档「${row.username}」的原因。`,
    '归档账号',
    {inputPlaceholder:'填写归档原因',inputValidator:(v:string)=>v.trim().length>=2||'请填写至少2个字的原因',confirmButtonText:'确认归档',type:'warning'},
  )
  await http.post(`/admin/rbac/users/${row.user_id}/archive`,{status:'disabled',reason:value.trim()})
  ElMessage.success('账号已归档');await loadUsers()
}
async function resetPwd(row:AnyRow) {
  const {value}=await ElMessageBox.prompt(`请输入本地账号「${row.username}」的新密码`,'重置本地密码',{
    inputType:'password',inputPlaceholder:'至少12位，包含大小写、数字和特殊字符',
    inputValidator:(v:string)=>isStrongPassword(v,row.username)||'密码强度不足或包含用户名',
    confirmButtonText:'确认重置',
  })
  await http.post(`/admin/rbac/users/${row.user_id}/reset-pwd`,{password:value})
  ElMessage.success('本地密码已安全重置')
}
function isStrongPassword(value:string,username=''){
  return value.length>=12&&value.length<=128&&/[a-z]/.test(value)&&/[A-Z]/.test(value)&&/\d/.test(value)&&/[^A-Za-z0-9]/.test(value)&&(!username||!value.toLowerCase().includes(username.toLowerCase()))
}
function goPermission(row:AnyRow) {
  detailVisible.value=false
  router.push({path:'/admin/system/permissions',query:{username:row.username,returnTo:route.fullPath}})
}
function handleCommand(command:string,row:AnyRow) {
  if(command==='auth') openAuthMapping(row)
  else if(command==='permission') goPermission(row)
  else if(command==='edit') openEdit(row)
  else if(command==='status') changeStatus(row)
  else if(command==='password') resetPwd(row)
  else if(command==='archive') archiveAccount(row)
}

async function openReadiness() {
  readinessVisible.value=true;readinessLoading.value=true
  try { readiness.value=await http.get('/admin/rbac/users/readiness') }
  finally { readinessLoading.value=false }
}
async function copyDeliveryTemplate() {
  const text=[
    '统一身份认证接入确认模板',
    '1. 稳定认证主体字段（subject/uid）：',
    '2. 教职工号字段：',
    '3. 姓名与所属组织字段：',
    '4. 人员有效/离职状态字段：',
    '5. 角色、带班、导师关系来源：',
    '6. 新增、调岗、离职、停用与恢复规则：',
    '7. 同步周期及责任部门：',
    '说明：认证密钥、票据和客户端凭据由部署环境管理，不填写在本模板中。',
  ].join('\n')
  await navigator.clipboard.writeText(text)
  ElMessage.success('接入确认模板已复制')
}

function sourceLabel(value:string){return({local:'本地账号',school_sync:'学校同步',service:'服务账号'} as AnyRow)[value]||'未知来源'}
function sourceTag(value:string){return value==='school_sync'?'success':value==='service'?'info':''}
function providerLabel(value:string){return({unified_identity:'学校统一身份认证',wecom:'企业微信',school_app:'学校小程序/APP'} as AnyRow)[value]||value||'—'}
function scopeTypeLabel(value:string){return({all:'全校业务数据',college:'学院范围',major:'专业范围',class:'行政班范围',teacher:'任课关系',staff_relation:'带班/带生关系'} as AnyRow)[value]||value||'未定义范围'}
function formatTime(value?:string){return value?String(value).replace('T',' ').slice(0,16):'—'}
function activeStaffIds(data:AnyRow){return(data.staffBindings||[]).filter((item:AnyRow)=>item.status==='active').map((item:AnyRow)=>item.staff_id)}
function auditLabel(action:string){return({ 'rbac.user.create':'创建账号','rbac.user.update':'更新账号','rbac.user.status_update':'调整账号状态','rbac.user.archive':'归档账号','rbac.user.password_reset':'重置本地密码','rbac.user.auth_identity_update':'更新认证映射'} as AnyRow)[action]||action}

watch(pageSize,()=>{page.value=1;loadUsers()})
onMounted(async()=>{
  Object.assign(filters,{
    keyword:String(route.query.keyword||''),accountSource:String(route.query.account_source||''),
    roleId:String(route.query.role_id||''),authStatus:String(route.query.auth_status||''),
    permissionStatus:String(route.query.permission_status||''),status:String(route.query.status||''),
  })
  Object.assign(draft,filters)
  page.value=Math.max(Number(route.query.page||1),1)
  pageSize.value=[10,20,50,100].includes(Number(route.query.page_size))?Number(route.query.page_size):20
  try { await Promise.all([loadRoles(),loadUsers()]) }
  finally { initialLoading.value=false }
})
</script>

<style scoped>
.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:14px}
.head-actions{display:flex;gap:8px;flex-shrink:0}.boundary-alert{margin-bottom:14px}
.account-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:14px}
.account-kpi{min-height:116px;padding:17px 18px;border:1px solid #e5eaf2;border-radius:14px;background:#fff;text-align:left;cursor:pointer;transition:.18s ease}
.account-kpi:hover,.account-kpi.active{border-color:#818cf8;box-shadow:0 7px 20px rgba(79,70,229,.09);transform:translateY(-1px)}
.account-kpi span{display:block;color:#475569;font-size:13px}.account-kpi strong{display:block;margin:8px 0 5px;color:#172554;font-size:28px;font-variant-numeric:tabular-nums}.account-kpi small{color:#94a3b8;font-size:12px}
.filter-card{margin-bottom:14px}.filter-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.filter-head span{color:#94a3b8;font-size:12px}
.filter-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.load-error{margin-bottom:14px}.account-table-card{padding:16px}
.table-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}.table-title div{display:flex;align-items:baseline;gap:12px}.table-title span{color:#94a3b8;font-size:12px}
.user-cell,.auth-cell{display:flex;flex-direction:column;gap:2px;min-width:0}.user-cell span,.auth-cell small,.inline-note{color:#94a3b8;font-size:11px}.auth-cell>span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.status-line{display:flex;align-items:center;gap:6px;font-size:12px}.status-line i{width:7px;height:7px;border-radius:50%}.status-line.ready{color:#047857}.status-line.ready i{background:#10b981}.status-line.issue{color:#c2410c}.status-line.issue i{background:#f59e0b}
.permission-issue small{display:block;margin-top:3px;color:#94a3b8;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row-actions{display:flex;align-items:center;gap:9px}
.account-table-card :deep(.el-pagination){justify-content:flex-end;margin-top:14px}.account-table-card :deep(.clickable-row){cursor:pointer}.account-table-card :deep(.clickable-row:hover td){background:#f8faff!important}
.detail-drawer,.readiness-drawer{padding:0 4px 24px}.detail-grid,.readiness-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:16px 0}
.detail-grid div,.readiness-grid div{padding:12px;border:1px solid #eef2f7;border-radius:10px;background:#f8fafc}.detail-grid span,.readiness-grid span{display:block;color:#64748b;font-size:12px}.detail-grid b,.readiness-grid b{display:block;margin-top:5px;color:#1e293b;font-size:14px}
.detail-section{margin-top:16px;padding:16px;border:1px solid #e9edf4;border-radius:12px}.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:12px}.section-head h3{margin:0;color:#1e293b;font-size:15px}.section-head p{margin:4px 0 0;color:#94a3b8;font-size:12px}
.mapping-list,.identity-list{display:flex;flex-direction:column;gap:8px}.mapping-row,.identity-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 12px;border-radius:9px;background:#f8fafc}.mapping-row>div:first-child,.identity-row>div:first-child{display:flex;flex-direction:column;gap:3px}.mapping-row span,.mapping-row small,.identity-row span{color:#64748b;font-size:12px}.mapping-row>div:last-child,.identity-row>div:last-child{display:flex;align-items:center;gap:8px}
.staff-summary{margin-top:10px;color:#64748b;font-size:12px}.dialog-alert{margin-bottom:16px}.readonly-tip{color:#64748b;font-size:12px}.check-row{display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid #f1f5f9}.check-row:last-child{border-bottom:0}.check-row .el-icon{margin-top:2px;font-size:18px}.check-row .el-icon.ready{color:#10b981}.check-row .el-icon.attention{color:#f59e0b}.check-row div{display:flex;flex-direction:column;gap:3px}.check-row span{color:#64748b;font-size:12px}
@media(max-width:1200px){.account-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.detail-grid,.readiness-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>

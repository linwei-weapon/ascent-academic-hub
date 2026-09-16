<!-- 账号管理：系统管理模块，沿用既有接口、治理操作与权限边界。 -->
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
          class="account-search"
          @keyup.enter="applyFilters"
        />
        <el-select v-model="draft.accountSource" clearable placeholder="全部账号来源" class="account-filter">
          <el-option label="本地账号" value="local" />
          <el-option label="学校同步" value="school_sync" />
          <el-option label="服务账号" value="service" />
        </el-select>
        <el-select v-model="draft.roleId" clearable filterable placeholder="全部工作身份" class="account-role-filter">
          <el-option v-for="role in roles" :key="role.role_id" :label="role.name" :value="role.role_id" />
        </el-select>
        <el-select v-model="draft.authStatus" clearable placeholder="全部认证状态" class="account-filter">
          <el-option label="已映射" value="mapped" />
          <el-option label="待映射" value="unmapped" />
        </el-select>
        <el-select v-model="draft.permissionStatus" clearable placeholder="全部权限状态" class="account-filter">
          <el-option label="权限就绪" value="ready" />
          <el-option label="需要处理" value="issue" />
        </el-select>
        <el-select v-model="draft.status" clearable placeholder="全部账号状态" class="account-status-filter">
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
      <AppTable
        :columns="columns"
        :data="users"
        storage-key="system:accounts"
        show-density
        show-column-settings
        :max-business-columns="6"
        :config-version="2"
        :page="pagination.page"
        :page-size="pagination.pageSize"
        :total="pagination.total"
        :loading="loading"
        @page-change="changePage"
        @page-size-change="changePageSize"
        :page-sizes="[10,20,50,100]"
        stripe
        row-key="user_id"
      >
        <!-- 标题复用表格工具栏左侧插槽，与密度和列设置共用一行。 -->
        <template #toolbar>
          <div class="table-title">
            <b>账号与接入状态</b>
            <span>共 {{ pagination.total }} 个结果；点击蓝色姓名或账号查看详情</span>
          </div>
        </template>
        <template #col-user="{ row }">
          <div class="user-cell">
            <button
              v-if="row.name && canViewAccount(row)"
              type="button"
              class="user-cell__link user-cell__link--name"
              :aria-label="`查看账号详情 ${row.name}`"
              @click.stop="openDetail(row)"
            >{{ row.name }}</button>
            <b v-else>{{ row.name || '未填写姓名' }}</b>
            <button
              v-if="row.username && canViewAccount(row)"
              type="button"
              class="user-cell__link"
              :aria-label="`查看账号 ${row.username}`"
              @click.stop="openDetail(row)"
            >{{ row.username }}</button>
            <span v-else>{{ row.username || '—' }}</span>
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
          <el-empty :description="loadError ? '账号列表加载失败，请重试' : '当前条件下没有账号'">
            <el-button v-if="loadError" @click="loadUsers">重新加载</el-button>
            <el-button v-else @click="resetFilters">清除查询条件</el-button>
          </el-empty>
        </template>
      </AppTable>
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
          <el-select v-model="form.role_id" filterable placeholder="选择初始工作身份" class="account-form-control">
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
          <el-select v-model="authForm.provider" :disabled="authEditingProvider" class="account-form-control">
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
            <AppTable
              :columns="providerColumns"
              storage-key="system:auth-providers"
              :pagination="false"
              :data="readiness.providers || []"
            >
              <template #col-provider="{row}">{{ providerLabel(row.provider) }}</template>
              <template #col-last_updated_at="{row}">{{ formatTime(row.last_updated_at) }}</template>
            </AppTable>
            <el-empty v-if="!readiness.providers?.length" :image-size="54" description="尚未接入认证来源" />
          </section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ArrowDown, CircleCheckFilled, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppTable from '@/components/AppTable.vue'
import { TABLE_PAGE_SIZES, type AppTableColumn } from '@/types/table'
import { tablePreferenceKey } from '@/utils/tablePreferences'
import { rememberAccountListReturn, takeAccountListReturn } from '@/store/accountList'
import * as accountsApi from '@/api/admin/accounts'

type AnyRow = Record<string, any>
interface RoleRow { role_id:string; name:string; data_scope_type?:string }

const route = useRoute()
const router = useRouter()
const users = ref<AnyRow[]>([])
const roles = ref<RoleRow[]>([])
const summary = reactive({ total:0, active:0, mapped:0, pendingAuth:0, permissionIssues:0, disabled:0 })
// 普通进入沿用 QuizTest 的 1 / 20；仅从数据权限返回时消费本次内存现场。
const accountContextKey = tablePreferenceKey('system:accounts', 2)
const returnState = takeAccountListReturn(accountContextKey)
const pagination = reactive({ page: returnState?.page ?? 1, pageSize: returnState?.pageSize ?? 20, total: 0 })
const loading = ref(false)
const initialLoading = ref(true)
const loadError = ref('')
const activeCard = ref(returnState?.activeCard ?? '')
let listRequestSequence = 0

const filters = reactive({
  keyword:'', accountSource:'', roleId:'', authStatus:'', permissionStatus:'', status:'',
  ...returnState?.filters,
})
const draft = reactive({ ...filters, ...returnState?.draft })

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

// 数据列按最小宽度自适应，隐藏列后重新分配空间；操作列保留稳定宽度。
const columns:AppTableColumn[] = [
  {key:'user',label:'用户与账号',minWidth:185,fixed:'left',required:true,region:'identity'},
  {key:'account_source',label:'账号来源',minWidth:100},
  {key:'auth',label:'统一身份认证',minWidth:170,tooltip:true},
  {key:'role',label:'默认工作身份',minWidth:145},
  {key:'permission',label:'权限准备度',minWidth:170},
  {key:'status',label:'状态',minWidth:86},
  {key:'last_login',label:'最近登录',minWidth:155,defaultVisible:false},
  {key:'staff_id',label:'教职工号',minWidth:145,defaultVisible:false,tooltip:true},
  {key:'actions',label:'操作',width:130,fixed:'right',required:true,region:'action'},
]

// 根据账号汇总结果生成筛选卡片，不在前端重算后台统计。
const summaryCards = computed(() => [
  {key:'active',label:'有效账号',value:summary.active,description:'当前允许访问平台'},
  {key:'mapped',label:'已完成认证映射',value:summary.mapped,description:'具备统一认证主体'},
  {key:'unmapped',label:'待完成认证映射',value:summary.pendingAuth,description:'需要接入或核验'},
  {key:'issue',label:'权限准备异常',value:summary.permissionIssues,description:'身份、人员或范围不完整'},
  {key:'disabled',label:'已停用或归档',value:summary.disabled,description:'保留历史但禁止访问'},
])

// 捕获已应用筛选，参数命名与序列化交给 API 模块；不写入页面路由。
function accountQuery(): accountsApi.AccountListQuery {
  return { page: pagination.page, pageSize: pagination.pageSize, ...filters }
}

// 每次捕获已应用条件；只有最新请求可以回写名单、汇总和分页。
async function loadUsers() {
  const sequence = ++listRequestSequence
  const query = accountQuery()
  const requestedPageSize = pagination.pageSize
  let requestedPage = pagination.page
  loading.value = true
  loadError.value = ''
  try {
    while (true) {
      const data:any = await accountsApi.listAccounts({ ...query, page: requestedPage })
      if (sequence !== listRequestSequence) return
      const resultTotal = Number(data.total || 0)
      const lastPage = Math.max(1, Math.ceil(resultTotal / requestedPageSize))
      // 账号状态或服务端总量变化后，回查最后有效页，不伪造或拼接当前页数据。
      if (requestedPage > lastPage) {
        requestedPage = lastPage
        continue
      }
      users.value = data.items || []
      pagination.total = resultTotal
      pagination.page = requestedPage
      Object.assign(summary, data.summary || {})
      break
    }
  } catch(error:any) {
    if (sequence !== listRequestSequence) return
    users.value = []
    pagination.total = 0
    loadError.value = error?.message || '请求失败'
  } finally {
    if (sequence === listRequestSequence) {
      loading.value = false
      initialLoading.value = false
    }
  }
}

// 读取可供账号创建和筛选使用的角色目录。
async function loadRoles() {
  roles.value=await accountsApi.listAccountRoles()
}

// 将草稿筛选应用到结果查询，并沿用原分页重置规则。
function applyFilters() {
  Object.assign(filters,draft); activeCard.value=''; pagination.page=1; loadUsers()
}
// 恢复本页面既有筛选默认值后重新查询。
function resetFilters() {
  Object.assign(filters,{keyword:'',accountSource:'',roleId:'',authStatus:'',permissionStatus:'',status:''})
  Object.assign(draft,filters); activeCard.value=''; pagination.page=1; loadUsers()
}
// 把汇总卡片映射为现有账号筛选条件后查询。
function applySummaryCard(key:string) {
  Object.assign(filters,{keyword:'',accountSource:'',roleId:'',authStatus:'',permissionStatus:'',status:''})
  if(key==='active') filters.status='active'
  if(key==='mapped') filters.authStatus='mapped'
  if(key==='unmapped') filters.authStatus='unmapped'
  if(key==='issue') filters.permissionStatus='issue'
  if(key==='disabled') filters.status='disabled'
  Object.assign(draft,filters); activeCard.value=key; pagination.page=1; loadUsers()
}

// 列表和详情沿用同一管理权限；仅校验详情标识，不按目标账号的状态限制查看。
function canViewAccount(row:AnyRow):boolean {
  const id = row.user_id
  if (typeof id !== 'number' && (typeof id !== 'string' || !/^\d+$/.test(id))) return false
  return Number.isSafeInteger(Number(id)) && Number(id) > 0
}

// 按用户主键加载详情，保留账号抽屉中的关联信息；无有效标识时不发起请求。
async function openDetail(row:AnyRow) {
  if (!canViewAccount(row)) return
  detailVisible.value=true; detailLoading.value=true; detail.value=null
  try { detail.value=await accountsApi.getAccount(row.user_id) }
  finally { detailLoading.value=false }
}
// 准备本地账号创建表单，不提前写入用户记录。
function openCreate() {
  editing.value=false; editId.value=0
  Object.assign(form,{username:'',name:'',role_id:'',password:''})
  accountDialogVisible.value=true
}
// 从选中账号填充编辑表单，沿用现有可编辑字段边界。
function openEdit(row:AnyRow) {
  editing.value=true; editId.value=row.user_id
  Object.assign(form,{username:row.username,name:row.name||'',role_id:'',password:''})
  accountDialogVisible.value=true
}
// 沿用账号校验和创建/编辑契约，保存成功后刷新列表。
async function saveAccount() {
  if(!form.username || (!editing.value&&!form.role_id)){ElMessage.warning('请填写用户名和初始工作身份');return}
  if(!editing.value&&!isStrongPassword(form.password,form.username)){ElMessage.warning('初始密码须为12~128位，并包含大小写字母、数字和特殊字符，且不能包含用户名');return}
  saving.value=true
  try {
    if(editing.value) await accountsApi.updateAccount(editId.value, {name:form.name})
    else await accountsApi.createAccount({username:form.username,name:form.name,role_id:form.role_id,password:form.password,status:'active',account_source:'local'})
    ElMessage.success('账号已保存');accountDialogVisible.value=false;await loadUsers()
  } finally { saving.value=false }
}

// 根据选中账号及已有提供方记录准备认证映射表单。
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
// 提交用户确认的认证主体与状态，不在前端合并账号。
async function saveAuthMapping() {
  if(!authUser.value||!authForm.subject_id.trim()){ElMessage.warning('请填写认证主体标识');return}
  authSaving.value=true
  try {
    await accountsApi.updateAuthMapping(authUser.value.user_id, {
      provider:authForm.provider,subject_id:authForm.subject_id.trim(),
      status:authForm.active?'active':'inactive',
    })
    ElMessage.success('认证映射已保存');authVisible.value=false
    await loadUsers()
    if(detailVisible.value) await openDetail({user_id:authUser.value.user_id})
  } finally { authSaving.value=false }
}

// 取得状态变更原因后提交启停操作，并刷新账号结果。
async function changeStatus(row:AnyRow) {
  const next=row.status==='active'?'disabled':'active'
  const action=next==='active'?'启用':'停用'
  const {value}=await ElMessageBox.prompt(
    `请输入${action}账号「${row.username}」的原因。${next==='disabled'?'账号后续请求将立即被拒绝。':''}`,
    `${action}账号`,
    {inputPlaceholder:'填写变更原因',inputValidator:(v:string)=>v.trim().length>=2||'请填写至少2个字的原因',confirmButtonText:`确认${action}`},
  )
  await accountsApi.updateAccountStatus(row.user_id, {status:next,reason:value.trim()})
  ElMessage.success(`账号已${action}`);await loadUsers()
}
// 取得归档原因后调用既有归档接口，历史关系由后端处理。
async function archiveAccount(row:AnyRow) {
  const {value}=await ElMessageBox.prompt(
    `归档后账号不能登录，认证映射会停用，但工作身份和审计历史继续保留。请输入归档「${row.username}」的原因。`,
    '归档账号',
    {inputPlaceholder:'填写归档原因',inputValidator:(v:string)=>v.trim().length>=2||'请填写至少2个字的原因',confirmButtonText:'确认归档',type:'warning'},
  )
  await accountsApi.archiveAccount(row.user_id, {status:'disabled',reason:value.trim()})
  ElMessage.success('账号已归档');await loadUsers()
}
// 按现有本地密码校验规则确认后提交重置。
async function resetPwd(row:AnyRow) {
  const {value}=await ElMessageBox.prompt(`请输入本地账号「${row.username}」的新密码`,'重置本地密码',{
    inputType:'password',inputPlaceholder:'至少12位，包含大小写、数字和特殊字符',
    inputValidator:(v:string)=>isStrongPassword(v,row.username)||'密码强度不足或包含用户名',
    confirmButtonText:'确认重置',
  })
  await accountsApi.resetAccountPassword(row.user_id, {password:value})
  ElMessage.success('本地密码已安全重置')
}
// 复用页面已有的本地密码强度要求，不调整账号认证规则。
function isStrongPassword(value:string,username=''){
  return value.length>=12&&value.length<=128&&/[a-z]/.test(value)&&/[A-Z]/.test(value)&&/\d/.test(value)&&/[^A-Za-z0-9]/.test(value)&&(!username||!value.toLowerCase().includes(username.toLowerCase()))
}
// 账号定向信息沿用原导航，列表筛选现场保存在内存中，不附加到返回地址。
function goPermission(row:AnyRow) {
  detailVisible.value=false
  rememberAccountListReturn(accountContextKey, {
    page: pagination.page, pageSize: pagination.pageSize, filters, draft, activeCard: activeCard.value,
  })
  router.push({path:'/admin/system/permissions',query:{username:row.username,returnTo:route.path}})
}
// 将账号行菜单动作分派到既有查看或治理流程。
function handleCommand(command:string,row:AnyRow) {
  if(command==='auth') openAuthMapping(row)
  else if(command==='permission') goPermission(row)
  else if(command==='edit') openEdit(row)
  else if(command==='status') changeStatus(row)
  else if(command==='password') resetPwd(row)
  else if(command==='archive') archiveAccount(row)
}

// 读取统一认证准备度，供接入资料核对使用。
async function openReadiness() {
  readinessVisible.value=true;readinessLoading.value=true
  try { readiness.value=await accountsApi.getAccountReadiness() }
  finally { readinessLoading.value=false }
}
// 复制学校接入确认字段，模板不包含认证密钥。
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

// 按既有账号来源枚举显示名称，未知来源沿用原兜底。
function sourceLabel(value:string){return({local:'本地账号',school_sync:'学校同步',service:'服务账号'} as AnyRow)[value]||'未知来源'}
// 按账号来源区分展示标签，不据此授予登录能力。
function sourceTag(value:string){return value==='school_sync'?'success':value==='service'?'info':''}
// 将认证提供方标识映射为展示名称，保留未知提供方。
function providerLabel(value:string){return({unified_identity:'学校统一身份认证',wecom:'企业微信',school_app:'学校小程序/APP'} as AnyRow)[value]||value||'—'}
// 按现有范围类型展示中文名称，未知枚举保留原兜底。
function scopeTypeLabel(value:string){return({all:'全校业务数据',college:'学院范围',major:'专业范围',class:'行政班范围',teacher:'任课关系',staff_relation:'带班/带生关系'} as AnyRow)[value]||value||'未定义范围'}
// 按现有格式展示接口时间，不改变时区或截取精度。
function formatTime(value?:string){return value?String(value).replace('T',' ').slice(0,16):'—'}
// 只展示当前有效的人员关联工号。
function activeStaffIds(data:AnyRow){return(data.staffBindings||[]).filter((item:AnyRow)=>item.status==='active').map((item:AnyRow)=>item.staff_id)}
// 将账号治理审计动作映射为已有可读文案。
function auditLabel(action:string){return({ 'rbac.user.create':'创建账号','rbac.user.update':'更新账号','rbac.user.status_update':'调整账号状态','rbac.user.archive':'归档账号','rbac.user.password_reset':'重置本地密码','rbac.user.auth_identity_update':'更新认证映射'} as AnyRow)[action]||action}

// 翻页只使用已应用筛选，不提交输入框中尚未查询的草稿。
function changePage(value: number): void {
  if (loading.value || value === pagination.page || !Number.isSafeInteger(value) || value < 1) return
  pagination.page = value
  void loadUsers()
}

// 页长操作统一回第一页并查询一次，不再叠加 watcher 和分页事件。
function changePageSize(value: number): void {
  if (loading.value || value === pagination.pageSize || !TABLE_PAGE_SIZES.some(size => size === value)) return
  pagination.pageSize = value
  pagination.page = 1
  void loadUsers()
}

// 同一账号页打开旧链接时在导航阶段规范路径，离开页面不触发路由回写。
onBeforeRouteUpdate(to => {
  if (to.path === '/admin/system/accounts' && Object.keys(to.query).length) {
    return { path: to.path, replace: true }
  }
})

// 状态在 setup 中一次初始化，挂载时只发起一轮角色和名单查询。
onMounted(async () => {
  if (Object.keys(route.query).length) void router.replace({ path: '/admin/system/accounts' })
  try { await Promise.all([loadRoles(), loadUsers()]) }
  finally { initialLoading.value = false }
})

// 页面离开后，旧列表响应不再覆盖用户已进入的页面或路由。
onBeforeUnmount(() => { listRequestSequence += 1 })
// 列定义只负责展示；单元格内容和业务操作沿用原页面。
const providerColumns: AppTableColumn[] = [
  { key: "provider", label: "认证来源", minWidth: 170 },
  { key: "active_count", label: "有效映射", minWidth: 100 },
  { key: "last_updated_at", label: "最近更新", minWidth: 150 },
]

</script>

<style scoped lang="scss">
// 页面区域、状态修饰与后代元素按相邻规则分组，保留原级联和弹窗作用域。
.sa-head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 14px;
}

.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.boundary-alert {
  margin-bottom: 14px;
}

.account-kpis {
  display: grid;
  grid-template-columns: repeat(5,minmax(0,1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.account-kpi {
  min-height: 116px;
  padding: 17px 18px;
  border: 1px solid #e5eaf2;
  border-radius: 14px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: .18s ease;

  &:hover, &.active {
    border-color: #818cf8;
    box-shadow: 0 7px 20px rgba(79,70,229,.09);
    transform: translateY(-1px);
  }

  span {
    display: block;
    color: #475569;
    font-size: 13px;
  }

  strong {
    display: block;
    margin: 8px 0 5px;
    color: #172554;
    font-size: 28px;
    font-variant-numeric: tabular-nums;
  }

  small {
    color: var(--sa-faint);
    font-size: 12px;
  }
}

.filter-card {
  margin-bottom: 14px;
}

.filter-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;

  span {
    color: var(--sa-faint);
    font-size: 12px;
  }
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.load-error {
  margin-bottom: 14px;
}

.account-table-card {
  padding: 16px;
}

.table-title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 12px;

  b {
    white-space: nowrap;
  }

  span {
    color: var(--sa-faint);
    font-size: 12px;
  }
}

.user-cell,.auth-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.user-cell span,.auth-cell small,.inline-note {
  color: var(--sa-faint);
  font-size: 11px;
}

.user-cell {
  // 悬停整个姓名与账号区域时，两行链接同步强调；灰色普通文字不参与。
  &:hover .user-cell__link {
    text-decoration: underline;
  }

  // 姓名和账号共用详情入口样式，保留姓名加粗、账号小字的层级。
  &__link {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--sa-primary);
    font: inherit;
    font-size: 11px;
    text-align: inherit;
    cursor: pointer;

    &--name {
      font-size: inherit;
      font-weight: 700;
    }

    &:focus-visible {
      outline: 2px solid var(--sa-primary);
      outline-offset: 2px;
      border-radius: var(--el-border-radius-small);
    }
  }
}

.auth-cell {

  &>span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.status-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;

  i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }

  &.ready {
    color: #047857;
  }

  &.ready i {
    background: #10b981;
  }

  &.issue {
    color: #c2410c;
  }

  &.issue i {
    background: #f59e0b;
  }
}

.permission-issue {

  small {
    display: block;
    margin-top: 3px;
    color: var(--sa-faint);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 9px;
}

.account-table-card {

  // 插槽内的纵向信息与横向操作组分别居中，作用范围限定在账号表格。
  .user-cell,.auth-cell {
    align-items: center;

    > * {
      max-width: 100%;
    }
  }

  .status-line,.row-actions {
    justify-content: center;
  }

  :deep(.el-table__row:hover td) {
    background: #f8faff !important;
  }
}

.detail-drawer,.readiness-drawer {
  padding: 0 4px 24px;
}

.detail-grid,.readiness-grid {
  display: grid;
  grid-template-columns: repeat(3,minmax(0,1fr));
  gap: 10px;
  margin: 16px 0;
}

.detail-grid div,.readiness-grid div {
  padding: 12px;
  border: 1px solid #eef2f7;
  border-radius: 10px;
  background: var(--sa-bg);
}

.detail-grid span,.readiness-grid span {
  display: block;
  color: var(--sa-muted);
  font-size: 12px;
}

.detail-grid b,.readiness-grid b {
  display: block;
  margin-top: 5px;
  color: var(--sa-text);
  font-size: 14px;
}

.detail-section {
  margin-top: 16px;
  padding: 16px;
  border: 1px solid #e9edf4;
  border-radius: 12px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;

  h3 {
    margin: 0;
    color: var(--sa-text);
    font-size: 15px;
  }

  p {
    margin: 4px 0 0;
    color: var(--sa-faint);
    font-size: 12px;
  }
}

.mapping-list,.identity-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mapping-row,.identity-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 9px;
  background: var(--sa-bg);
}

.mapping-row>div:first-child,.identity-row>div:first-child {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.mapping-row span,.mapping-row small,.identity-row span {
  color: var(--sa-muted);
  font-size: 12px;
}

.mapping-row>div:last-child,.identity-row>div:last-child {
  display: flex;
  align-items: center;
  gap: 8px;
}

.staff-summary {
  margin-top: 10px;
  color: var(--sa-muted);
  font-size: 12px;
}

.dialog-alert {
  margin-bottom: 16px;
}

.readonly-tip {
  color: var(--sa-muted);
  font-size: 12px;
}

.check-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--sa-row-hover);

  &:last-child {
    border-bottom: 0;
  }

  .el-icon {
    margin-top: 2px;
    font-size: 18px;
  }

  .el-icon.ready {
    color: #10b981;
  }

  .el-icon.attention {
    color: #f59e0b;
  }

  div {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  span {
    color: var(--sa-muted);
    font-size: 12px;
  }
}

@media (max-width:1200px) {
  .account-kpis {
    grid-template-columns: repeat(3,minmax(0,1fr));
  }

  .detail-grid,.readiness-grid {
    grid-template-columns: repeat(2,minmax(0,1fr));
  }

}

// 静态控件尺寸与局部布局由 class 管理，动态样式保留在原数据绑定中。
.account-search {
  width: 220px;
}

.account-filter {
  width: 150px;
}

.account-role-filter {
  width: 170px;
}

.account-status-filter {
  width: 135px;
}

.account-form-control {
  width: 100%;
}
</style>

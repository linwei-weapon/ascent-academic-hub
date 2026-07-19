<template>
  <div class="permission-page">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">数据权限</h2>
        <p class="sa-page-sub">
          管理“账号—工作身份—人员—数据范围”，并核验用户实际可见的数据，不改变教务系统中的业务关系。
        </p>
      </div>
      <el-button size="small" @click="loadUsers">刷新权限状态</el-button>
    </div>

    <el-alert
      title="角色决定可做什么，工作身份和人员关系决定能看哪些数据；范围缺失时系统默认拒绝访问。"
      type="info"
      :closable="false"
      show-icon
      class="scope-alert"
    />

    <div class="summary-grid">
      <div class="summary-card">
        <span>账号</span><strong>{{ summary.users }}</strong>
        <small>纳入统一权限上下文</small>
      </div>
      <div class="summary-card ready">
        <span>权限就绪</span><strong>{{ summary.ready }}</strong>
        <small>已有有效身份与范围</small>
      </div>
      <div class="summary-card warning">
        <span>待补映射</span><strong>{{ summary.missing }}</strong>
        <small>登录后将按最小权限拒绝</small>
      </div>
      <div class="summary-card">
        <span>工作身份</span><strong>{{ summary.identities }}</strong>
        <small>支持一人多身份切换</small>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="permission-tabs">
      <el-tab-pane label="账号与数据范围" name="accounts">
        <div class="toolbar">
          <el-input
            v-model="keyword"
            clearable
            placeholder="搜索账号或姓名"
            style="width: 260px"
            @keyup.enter="loadUsers"
            @clear="loadUsers"
          />
          <el-button type="primary" @click="loadUsers">查询</el-button>
        </div>
        <div class="sa-card table-card">
          <el-table :data="users" v-loading="loading" size="small">
            <el-table-column prop="name" label="用户" min-width="150">
              <template #default="{ row }">
                <div class="main-cell">{{ row.name || row.username }}</div>
                <div class="sub-cell">{{ row.username }}</div>
              </template>
            </el-table-column>
            <el-table-column label="默认工作身份" min-width="180">
              <template #default="{ row }">
                {{ row.defaultIdentity?.role_name || '未配置' }}
              </template>
            </el-table-column>
            <el-table-column prop="identity_count" label="身份" width="80" align="right" />
            <el-table-column prop="scope_count" label="组织范围" width="100" align="right" />
            <el-table-column label="人员关联" width="100" align="center">
              <template #default="{ row }">{{ row.staff_count ? '已关联' : '—' }}</template>
            </el-table-column>
            <el-table-column label="权限状态" width="130">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  effect="plain"
                  :type="row.permissionStatus === 'ready' ? 'success' : 'warning'"
                >
                  {{ row.permissionStatus === 'ready' ? '权限就绪' : '待补映射' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="待处理问题" min-width="220">
              <template #default="{ row }">
                <span v-if="!row.issues?.length" class="ok-text">无</span>
                <el-tooltip v-else :content="row.issues.join('；')" placement="top">
                  <span class="issue-text">{{ row.issues[0] }}{{ row.issues.length > 1 ? ` 等${row.issues.length}项` : '' }}</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="210" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" size="small" @click="openConfig(row)">配置</el-button>
                <el-button
                  text
                  size="small"
                  :disabled="!row.defaultIdentity"
                  @click="preview(row.username, row.defaultIdentity?.user_role_id)"
                >
                  核验权限
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="带班与带生关系" name="relationships">
        <div class="relation-summary" v-if="relationStats.length">
          <div v-for="item in relationStats" :key="item.relation_type" class="relation-stat">
            <strong>{{ relationLabel(item.relation_type) }}</strong>
            <span>{{ item.staff_count }} 人员 · {{ item.student_count }} 学生 · {{ item.relation_count }} 条关系</span>
          </div>
        </div>
        <el-alert
          v-if="relationshipQuality.temporaryStaff || relationshipQuality.expired || relationshipQuality.duplicateGroups || relationshipQuality.missingSource"
          class="relationship-quality"
          type="warning"
          :closable="false"
          show-icon
          :title="`关系数据核验：临时人员标识 ${relationshipQuality.temporaryStaff} 个，已失效 ${relationshipQuality.expired} 条，重复组合 ${relationshipQuality.duplicateGroups} 组，缺来源 ${relationshipQuality.missingSource} 条。`"
        />
        <div class="toolbar">
          <el-select v-model="relationType" clearable placeholder="全部关系类型" style="width:180px">
            <el-option label="班主任" value="class_adviser" />
            <el-option label="学业导师" value="学业导师" />
            <el-option label="导师" value="导师" />
            <el-option label="辅导员" value="counselor" />
          </el-select>
          <el-input v-model="relationKeyword" clearable placeholder="工号、学生或班级" style="width:240px" />
          <el-button type="primary" @click="loadRelationships(1)">查询</el-button>
        </div>
        <div class="sa-card table-card">
          <el-table :data="relationships" v-loading="relationLoading" size="small">
            <el-table-column prop="staff_id" label="人员工号" width="150" />
            <el-table-column label="关系" width="110">
              <template #default="{ row }">{{ relationLabel(row.relation_type) }}</template>
            </el-table-column>
            <el-table-column label="学生" min-width="170">
              <template #default="{ row }">
                <div class="main-cell">{{ row.student_name }}</div>
                <div class="sub-cell">{{ row.student_id }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="scope_ref" label="行政班/关系范围" min-width="170" />
            <el-table-column label="有效期" min-width="180">
              <template #default="{ row }">{{ row.valid_from }} 至 {{ row.valid_to || '长期' }}</template>
            </el-table-column>
            <el-table-column label="来源" min-width="150">
              <template #default="{ row }">
                <div>{{ row.source_system || '未知来源' }}</div>
                <div class="sub-cell">{{ row.source_updated_at || '未提供同步时间' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" effect="plain" :type="row.status === 'active' ? 'success' : 'info'">
                  {{ row.status === 'active' ? '有效' : '失效' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-if="relationTotal > relationPageSize"
            class="pagination"
            background
            layout="total, prev, pager, next"
            :total="relationTotal"
            :page-size="relationPageSize"
            :current-page="relationPage"
            @current-change="loadRelationships"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="configVisible" size="720px" :title="`配置数据权限 · ${detail?.name || detail?.username || ''}`">
      <div v-loading="detailLoading">
        <section class="config-section">
          <div class="section-head">
            <div>
              <h3>人员关联</h3>
              <p>辅导员、班主任、导师身份通过工号匹配学校同步的带班或带生关系。</p>
            </div>
            <el-button size="small" type="primary" plain @click="saveStaff">保存人员关联</el-button>
          </div>
          <div class="date-row">
            <el-input v-model="staffForm.staff_id" placeholder="输入教职工号；组织范围身份可不填">
              <template #prepend>教职工号</template>
            </el-input>
            <el-date-picker v-model="staffForm.valid_from" type="date" value-format="YYYY-MM-DD" placeholder="生效日期" />
            <el-date-picker v-model="staffForm.valid_to" type="date" value-format="YYYY-MM-DD" placeholder="长期有效" clearable />
          </div>
          <div class="source-note" v-if="activeStaff">
            当前来源：{{ activeStaff.source }}；有效期 {{ activeStaff.valid_from }} 至 {{ activeStaff.valid_to || '长期' }}
          </div>
        </section>

        <section class="config-section">
          <div class="section-head">
            <div>
              <h3>工作身份与数据范围</h3>
              <p>同一账号可有多个工作身份；切换身份后菜单、动作和数据范围同步变化。</p>
            </div>
            <el-button size="small" type="primary" @click="identityDialog = true">添加工作身份</el-button>
          </div>
          <div v-if="!detail?.identities?.length" class="empty-tip">尚未配置工作身份。</div>
          <div v-for="identity in detail?.identities || []" :key="identity.identity_id" class="identity-card">
            <div class="identity-head">
              <div>
                <strong>{{ identity.role_name || identity.role_id }}</strong>
                <el-tag v-if="identity.is_default" size="small" effect="plain">默认身份</el-tag>
                <el-tag v-if="identity.status !== 'active'" size="small" type="info" effect="plain">已失效</el-tag>
                <span class="identity-code">{{ identity.identity_id }}</span>
              </div>
              <div>
                <el-button
                  v-if="!identity.is_default"
                  text
                  type="primary"
                  size="small"
                  @click="setDefault(identity)"
                >设为默认</el-button>
                <el-button text size="small" @click="preview(detail.username, identity.identity_id)">核验</el-button>
                <el-popconfirm
                  v-if="!identity.is_default"
                  title="删除身份会同时删除其组织范围，确定继续？"
                  @confirm="removeIdentity(identity)"
                >
                  <template #reference><el-button text type="danger" size="small">删除</el-button></template>
                </el-popconfirm>
              </div>
            </div>
            <div class="scope-editor">
              <template v-if="identity.data_scope_type === 'all'">
                <el-tag type="success" effect="plain">全校业务数据</el-tag>
                <span>该身份无需配置组织范围。</span>
              </template>
              <template v-else-if="identity.data_scope_type === 'staff_relation'">
                <el-tag type="primary" effect="plain">按人员关系</el-tag>
                <span>根据上方教职工号及学校同步的带班/带生关系动态授权。</span>
              </template>
              <template v-else>
                <el-select
                  v-model="identity._scopeIds"
                  multiple
                  filterable
                  collapse-tags
                  collapse-tags-tooltip
                  :placeholder="`选择${scopeTypeLabel(identity.data_scope_type)}范围`"
                  style="flex:1"
                >
                  <el-option
                    v-for="option in optionsFor(identity.data_scope_type)"
                    :key="option.value"
                    :label="`${option.label}（${option.value}）`"
                    :value="option.value"
                  />
                </el-select>
                <el-button size="small" type="primary" @click="saveScopes(identity)">保存范围</el-button>
              </template>
            </div>
            <div
              v-if="!['all', 'staff_relation'].includes(identity.data_scope_type)"
              class="scope-period-row"
            >
              <span>范围有效期</span>
              <el-date-picker v-model="identity._scopeValidFrom" type="date" value-format="YYYY-MM-DD" placeholder="生效日期" />
              <span>至</span>
              <el-date-picker v-model="identity._scopeValidTo" type="date" value-format="YYYY-MM-DD" placeholder="长期有效" clearable />
              <span>本次保存对当前勾选范围统一生效</span>
            </div>
            <div class="identity-period-editor">
              <span>身份有效期</span>
              <el-date-picker v-model="identity.valid_from" type="date" value-format="YYYY-MM-DD" placeholder="立即生效" clearable />
              <span>至</span>
              <el-date-picker v-model="identity.valid_to" type="date" value-format="YYYY-MM-DD" placeholder="长期有效" clearable />
              <el-button size="small" text type="primary" @click="saveIdentityPeriod(identity)">保存有效期</el-button>
              <span>来源：{{ identity.source || '未知' }}</span>
            </div>
          </div>
        </section>
      </div>
    </el-drawer>

    <el-dialog v-model="identityDialog" title="添加工作身份" width="460px">
      <el-form label-width="90px">
        <el-form-item label="角色" required>
          <el-select v-model="identityForm.role_id" filterable style="width:100%">
            <el-option
              v-for="role in options.roles"
              :key="role.role_id"
              :label="`${role.name} · ${scopeTypeLabel(role.data_scope_type)}`"
              :value="role.role_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="默认身份">
          <el-switch v-model="identityForm.is_default" />
        </el-form-item>
        <el-form-item label="生效日期">
          <el-date-picker v-model="identityForm.valid_from" type="date" value-format="YYYY-MM-DD" placeholder="立即生效" clearable style="width:100%" />
        </el-form-item>
        <el-form-item label="失效日期">
          <el-date-picker v-model="identityForm.valid_to" type="date" value-format="YYYY-MM-DD" placeholder="长期有效" clearable style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="identityDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="addIdentity">添加</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="previewVisible" size="560px" title="权限核验结果">
      <div v-loading="previewLoading">
        <template v-if="previewData">
          <el-result
            :icon="previewData.permissionContext.authorized ? 'success' : 'warning'"
            :title="previewData.permissionContext.authorized ? '当前身份权限有效' : '当前身份不可访问业务数据'"
            :sub-title="previewData.permissionContext.authorizationIssue || '已按当前身份计算实际可见范围'"
          />
          <div class="preview-grid">
            <div><span>工作身份</span><strong>{{ previewData.permissionContext.activeRoleName }}</strong></div>
            <div><span>明细范围</span><strong>{{ scopeDescription(previewData.permissionContext.detailScope) }}</strong></div>
            <div><span>原型可见学生</span><strong>{{ previewData.visibleStudents.currentPrototype }} 人</strong></div>
            <div><span>真实数据可见学生</span><strong>{{ previewData.visibleStudents.realDataV2 ?? '待映射' }}</strong></div>
          </div>
          <div class="permission-list">
            <h3>关键操作权限</h3>
            <el-tag
              v-for="action in previewData.permissionContext.actionPermissions"
              :key="action"
              size="small"
              effect="plain"
            >{{ action }}</el-tag>
            <div v-if="!previewData.permissionContext.actionPermissions.length" class="empty-tip">没有配置关键操作权限。</div>
          </div>
          <el-alert
            v-if="previewData.visibleStudents.v2Issue"
            :title="`真实数据核验：${previewData.visibleStudents.v2Issue}`"
            type="warning"
            :closable="false"
          />
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { http } from '@/utils/http'

type AnyRow = Record<string, any>

const route = useRoute()
const activeTab = ref('accounts')
const keyword = ref('')
const users = ref<AnyRow[]>([])
const loading = ref(false)
const options = reactive<AnyRow>({ roles: [], colleges: [], majors: [], classes: [], teachers: [] })
const summary = computed(() => ({
  users: users.value.length,
  ready: users.value.filter(item => item.permissionStatus === 'ready').length,
  missing: users.value.filter(item => item.permissionStatus !== 'ready').length,
  identities: users.value.reduce((total, item) => total + Number(item.identity_count || 0), 0),
}))

const configVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AnyRow | null>(null)
const staffForm = reactive({ staff_id: '', valid_from: '1970-01-01', valid_to: '' })
const activeStaff = computed(() => detail.value?.staffBindings?.find((item: AnyRow) => item.status === 'active'))
const identityDialog = ref(false)
const identityForm = reactive({ role_id: '', is_default: false, valid_from: '', valid_to: '' })
const saving = ref(false)

const relationships = ref<AnyRow[]>([])
const relationStats = ref<AnyRow[]>([])
const relationLoading = ref(false)
const relationType = ref('')
const relationKeyword = ref('')
const relationPage = ref(1)
const relationPageSize = 50
const relationTotal = ref(0)
const relationshipQuality = reactive({ temporaryStaff: 0, expired: 0, duplicateGroups: 0, missingSource: 0 })

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewData = ref<AnyRow | null>(null)

async function loadUsers() {
  loading.value = true
  try {
    const query = keyword.value.trim() ? `?keyword=${encodeURIComponent(keyword.value.trim())}` : ''
    users.value = await http.get(`/admin/rbac/data-permissions${query}`)
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  Object.assign(options, await http.get('/admin/rbac/data-permissions/options'))
}

function normalizeDetail(data: AnyRow) {
  for (const identity of data.identities || []) {
    const activeScopes = (identity.scopes || []).filter((scope: AnyRow) => scope.status === 'active')
    identity._scopeIds = (identity.scopes || [])
      .filter((scope: AnyRow) => scope.status === 'active')
      .map((scope: AnyRow) => scope.scope_id)
    identity._scopeValidFrom = activeScopes[0]?.valid_from || '1970-01-01'
    identity._scopeValidTo = activeScopes[0]?.valid_to || ''
  }
  detail.value = data
  staffForm.staff_id = activeStaff.value?.staff_id || ''
  staffForm.valid_from = activeStaff.value?.valid_from || '1970-01-01'
  staffForm.valid_to = activeStaff.value?.valid_to || ''
}

async function openConfig(row: AnyRow) {
  configVisible.value = true
  detailLoading.value = true
  try {
    normalizeDetail(await http.get(`/admin/rbac/data-permissions/${encodeURIComponent(row.username)}`))
  } finally {
    detailLoading.value = false
  }
}

async function refreshDetail(data?: AnyRow) {
  if (!detail.value?.username) return
  normalizeDetail(data || await http.get(`/admin/rbac/data-permissions/${encodeURIComponent(detail.value.username)}`))
  await loadUsers()
}

async function saveStaff() {
  if (!detail.value?.username || !staffForm.staff_id.trim()) {
    ElMessage.warning('请填写教职工号')
    return
  }
  const data = await http.put(`/admin/rbac/data-permissions/${encodeURIComponent(detail.value.username)}/staff`, {
    staff_id: staffForm.staff_id.trim(),
    valid_from: staffForm.valid_from || '1970-01-01',
    valid_to: staffForm.valid_to || null,
    source: 'manual',
  })
  await refreshDetail(data)
  ElMessage.success('人员关联已保存')
}

async function addIdentity() {
  if (!detail.value?.username || !identityForm.role_id) {
    ElMessage.warning('请选择角色')
    return
  }
  saving.value = true
  try {
    const data = await http.post(
      `/admin/rbac/data-permissions/${encodeURIComponent(detail.value.username)}/identities`,
      identityForm,
    )
    identityDialog.value = false
    Object.assign(identityForm, { role_id: '', is_default: false, valid_from: '', valid_to: '' })
    await refreshDetail(data)
    ElMessage.success('工作身份已添加')
  } finally {
    saving.value = false
  }
}

async function setDefault(identity: AnyRow) {
  if (!detail.value?.username) return
  const data = await http.put(
    `/admin/rbac/data-permissions/${encodeURIComponent(detail.value.username)}/identities/${encodeURIComponent(identity.identity_id)}`,
    { is_default: true },
  )
  await refreshDetail(data)
  ElMessage.success('默认身份已更新')
}

async function saveIdentityPeriod(identity: AnyRow) {
  if (!detail.value?.username) return
  const data = await http.put(
    `/admin/rbac/data-permissions/${encodeURIComponent(detail.value.username)}/identities/${encodeURIComponent(identity.identity_id)}`,
    { valid_from: identity.valid_from || null, valid_to: identity.valid_to || null },
  )
  await refreshDetail(data)
  ElMessage.success('身份有效期已更新')
}

async function removeIdentity(identity: AnyRow) {
  if (!detail.value?.username) return
  const data = await http.del(
    `/admin/rbac/data-permissions/${encodeURIComponent(detail.value.username)}/identities/${encodeURIComponent(identity.identity_id)}`,
  )
  await refreshDetail(data)
  ElMessage.success('工作身份已删除')
}

async function saveScopes(identity: AnyRow) {
  if (!detail.value?.username) return
  const scopes = (identity._scopeIds || []).map((scopeId: string) => ({
    scope_type: identity.data_scope_type,
    scope_id: scopeId,
    valid_from: identity._scopeValidFrom || '1970-01-01',
    valid_to: identity._scopeValidTo || null,
  }))
  const data = await http.put(
    `/admin/rbac/data-permissions/${encodeURIComponent(detail.value.username)}/identities/${encodeURIComponent(identity.identity_id)}/scopes`,
    { scopes },
  )
  await refreshDetail(data)
  ElMessage.success('组织范围已保存')
}

async function preview(username: string, identityId: string) {
  if (!username || !identityId) return
  previewVisible.value = true
  previewLoading.value = true
  previewData.value = null
  try {
    previewData.value = await http.get(
      `/admin/rbac/data-permissions/${encodeURIComponent(username)}/preview/${encodeURIComponent(identityId)}`,
    )
  } finally {
    previewLoading.value = false
  }
}

async function loadRelationships(page = 1) {
  relationPage.value = page
  relationLoading.value = true
  try {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(relationPageSize),
    })
    if (relationType.value) params.set('relation_type', relationType.value)
    if (relationKeyword.value.trim()) params.set('keyword', relationKeyword.value.trim())
    const data = await http.get(`/admin/rbac/data-permissions/relationships/list?${params}`)
    relationships.value = data.list || []
    relationStats.value = data.stats || []
    Object.assign(relationshipQuality, data.quality || {})
    relationTotal.value = data.total || 0
  } finally {
    relationLoading.value = false
  }
}

function optionsFor(type: string) {
  return ({ college: options.colleges, major: options.majors, class: options.classes, teacher: options.teachers } as AnyRow)[type] || []
}
function scopeTypeLabel(type: string) {
  return ({ all: '全校', college: '学院', major: '专业', class: '行政班', teacher: '任课教师', staff_relation: '所带学生' } as AnyRow)[type] || type
}
function relationLabel(type: string) {
  return ({ class_adviser: '班主任', 学业导师: '学业导师', 导师: '导师', mentor: '导师', counselor: '辅导员' } as AnyRow)[type] || type
}
function scopeDescription(scope: AnyRow) {
  if (scope?.type === 'all') return '全校业务数据'
  if (scope?.type === 'staff_relation') return '人员关系内学生'
  const ids = scope?.sourceScopeIds || []
  return `${scopeTypeLabel(scope?.type)} · ${ids.length} 个范围`
}

watch(activeTab, value => {
  if (value === 'relationships' && !relationships.value.length) void loadRelationships()
})
onMounted(async () => {
  const routeUsername = typeof route.query.username === 'string' ? route.query.username.trim() : ''
  if (routeUsername) keyword.value = routeUsername
  await Promise.all([loadUsers(), loadOptions()])
  if (routeUsername) {
    const matched = users.value.find(item => item.username === routeUsername)
    if (matched) await openConfig(matched)
  }
})
</script>

<style scoped>
.permission-page { min-width: 920px; }
.sa-head-row { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:14px; }
.scope-alert { margin-bottom:14px; }
.summary-grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin-bottom:14px; }
.summary-card { background:#fff; border:1px solid var(--sa-border); border-radius:12px; padding:16px 18px; }
.summary-card span { display:block; color:var(--sa-muted); font-size:12px; }
.summary-card strong { display:block; color:var(--sa-text); font-size:28px; line-height:1.3; margin:4px 0; }
.summary-card small { color:var(--sa-faint); font-size:11px; }
.summary-card.ready strong { color:#059669; }
.summary-card.warning strong { color:#d97706; }
.permission-tabs { background:#fff; border:1px solid var(--sa-border); border-radius:12px; padding:0 16px 16px; }
.toolbar { display:flex; gap:8px; margin:4px 0 12px; }
.table-card { padding:0; box-shadow:none; border-radius:8px; overflow:hidden; }
.main-cell { color:var(--sa-text); font-weight:600; }
.sub-cell { color:var(--sa-faint); font-size:11px; margin-top:2px; }
.ok-text { color:#059669; font-size:12px; }
.issue-text { color:#d97706; font-size:12px; cursor:help; }
.pagination { justify-content:flex-end; padding:14px; }
.relation-summary { display:flex; gap:10px; margin:4px 0 12px; flex-wrap:wrap; }
.relationship-quality { margin-bottom:12px; }
.relation-stat { display:flex; gap:8px; align-items:center; background:#f8fafc; border:1px solid var(--sa-border); border-radius:8px; padding:9px 12px; }
.relation-stat strong { font-size:12px; color:var(--sa-text); }
.relation-stat span { font-size:11px; color:var(--sa-muted); }
.config-section { border:1px solid var(--sa-border); border-radius:12px; padding:16px; margin-bottom:14px; }
.section-head { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:14px; }
.section-head h3, .permission-list h3 { margin:0 0 4px; font-size:15px; color:var(--sa-text); }
.section-head p { margin:0; font-size:12px; color:var(--sa-muted); line-height:1.6; }
.source-note { margin-top:8px; color:var(--sa-faint); font-size:11px; }
.date-row { display:grid; grid-template-columns:1fr 150px 150px; gap:8px; }
.identity-card { border:1px solid #e2e8f0; background:#f8fafc; border-radius:10px; padding:13px; margin-top:10px; }
.identity-head { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
.identity-head strong { margin-right:8px; color:var(--sa-text); }
.identity-code { display:block; color:var(--sa-faint); font-size:10px; margin-top:4px; }
.scope-editor { display:flex; align-items:center; gap:10px; margin-top:12px; color:var(--sa-muted); font-size:12px; }
.identity-period-editor { display:flex; align-items:center; gap:7px; flex-wrap:wrap; margin-top:10px; color:var(--sa-faint); font-size:11px; }
.identity-period-editor :deep(.el-date-editor) { width:132px; }
.scope-period-row { display:flex; align-items:center; gap:7px; flex-wrap:wrap; margin-top:8px; color:var(--sa-faint); font-size:11px; }
.scope-period-row :deep(.el-date-editor) { width:132px; }
.empty-tip { color:var(--sa-faint); font-size:12px; padding:10px 0; }
.preview-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.preview-grid > div { border:1px solid var(--sa-border); border-radius:9px; padding:12px; }
.preview-grid span { display:block; font-size:11px; color:var(--sa-muted); margin-bottom:5px; }
.preview-grid strong { color:var(--sa-text); font-size:14px; }
.permission-list { margin:18px 0; }
.permission-list .el-tag { margin:0 6px 6px 0; }
</style>

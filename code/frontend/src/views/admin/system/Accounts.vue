<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">账号管理</h2>
        <p class="sa-page-sub">管理平台账号状态和统一身份认证映射；角色、人员和数据范围在独立权限页面维护。</p>
      </div>
      <el-button type="primary" size="small" @click="openDialog()">+ 新建账号</el-button>
    </div>

    <div class="sa-card">
      <el-table :data="users" size="small" v-loading="loading">
        <el-table-column prop="username" label="用户名" width="150" />
        <el-table-column prop="name" label="姓名" width="140" />
        <el-table-column label="统一身份认证" min-width="190">
          <template #default="{ row }">
            <div v-if="row.auth_subject_id">
              <div>{{ providerLabel(row.auth_provider) }}</div>
              <div class="sub-cell">{{ row.auth_subject_id }}</div>
            </div>
            <el-tag v-else size="small" type="warning" effect="plain">待绑定</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="staff_id" label="教职工号" width="130">
          <template #default="{row}">{{ row.staff_id || '—' }}</template>
        </el-table-column>
        <el-table-column prop="role_name" label="默认角色" min-width="150">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.role_name || row.role_id }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="identity_count" label="工作身份" width="90" align="right" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="row.status === 'active'"
              @change="(v: any) => toggleStatus(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openAuthMapping(row)">统一身份</el-button>
            <el-button
              size="small"
              text
              @click="$router.push({ path: '/admin/system/permissions', query: { username: row.username } })"
            >数据权限</el-button>
            <el-button size="small" text type="primary" @click="openDialog(row)">编辑</el-button>
            <el-button size="small" text type="warning" @click="resetPwd(row)">重置密码</el-button>
            <el-popconfirm title="确定删除该账号？" @confirm="remove(row)">
              <template #reference><el-button size="small" text type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑账号' : '新建账号'" width="460px">
      <el-form :model="form" label-width="80px" size="small">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" :disabled="editing" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.name" placeholder="显示姓名" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="form.role_id" placeholder="选择角色" style="width:100%">
            <el-option v-for="r in roles" :key="r.role_id" :label="r.name" :value="r.role_id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!editing" label="初始密码" required>
          <el-input v-model="form.password" type="password" show-password placeholder="至少12位，包含大小写、数字和特殊字符" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="authVisible" size="520px" :title="`统一身份认证映射 · ${authUser?.name || authUser?.username || ''}`">
      <el-alert type="info" :closable="false" show-icon
        title="平台不维护统一身份认证密码，只保存学校认证主体标识与本地账号的映射关系。" />
      <el-form label-width="110px" class="mapping-form">
        <el-form-item label="本地账号"><b>{{ authUser?.username }}</b></el-form-item>
        <el-form-item label="认证来源">
          <el-select v-model="authForm.provider" style="width:100%">
            <el-option label="学校统一身份认证" value="unified_identity" />
            <el-option label="企业微信" value="wecom" />
            <el-option label="学校小程序/APP" value="school_app" />
          </el-select>
        </el-form-item>
        <el-form-item label="认证主体标识" required>
          <el-input v-model="authForm.subject_id" placeholder="统一身份认证返回的稳定 subject / uid" />
        </el-form-item>
        <el-form-item label="映射状态"><el-switch v-model="authForm.active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="authVisible=false">取消</el-button>
        <el-button type="primary" :loading="authSaving" @click="saveAuthMapping">保存映射</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '@/utils/http'

interface UserRow {
  user_id: number; username: string; name: string
  role_id: string; role_name: string; status: string
  identity_count: number; staff_id?: string
  auth_provider?: string; auth_subject_id?: string
}
interface RoleRow { role_id: string; name: string }

const users = ref<UserRow[]>([])
const roles = ref<RoleRow[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref(false)
let editId = 0
const form = reactive({ username: '', name: '', role_id: '', password: '', active: true })
const authVisible = ref(false)
const authSaving = ref(false)
const authUser = ref<UserRow | null>(null)
const authForm = reactive({ provider: 'unified_identity', subject_id: '', active: true })

async function load() {
  loading.value = true
  try {
    users.value = await http.get('/admin/rbac/users')
    roles.value = await http.get('/admin/rbac/roles')
  } finally {
    loading.value = false
  }
}

function openDialog(row?: any) {
  if (row) {
    editing.value = true
    editId = row.user_id
    Object.assign(form, {
      username: row.username, name: row.name, role_id: row.role_id,
      password: '', active: row.status === 'active',
    })
  } else {
    editing.value = false
    Object.assign(form, { username: '', name: '', role_id: '', password: '', active: true })
  }
  dialogVisible.value = true
}

async function save() {
  if (!form.username || !form.role_id) {
    ElMessage.warning('用户名和角色为必填')
    return
  }
  if (!editing.value && !isStrongPassword(form.password, form.username)) {
    ElMessage.warning('初始密码须为12~128位，并包含大小写字母、数字和特殊字符，且不能包含用户名')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await http.put(`/admin/rbac/users/${editId}`, {
        name: form.name, role_id: form.role_id,
        status: form.active ? 'active' : 'disabled',
      })
    } else {
      await http.post('/admin/rbac/users', {
        username: form.username, name: form.name, role_id: form.role_id,
        password: form.password, status: form.active ? 'active' : 'disabled',
      })
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: any, v: any) {
  const on = !!v
  await http.put(`/admin/rbac/users/${row.user_id}`, { status: on ? 'active' : 'disabled' })
  row.status = on ? 'active' : 'disabled'
  ElMessage.success(on ? '已启用' : '已停用')
}

async function resetPwd(row: any) {
  const { value } = await ElMessageBox.prompt(
    `请输入账号「${row.username}」的新密码`, '重置密码', {
      inputType: 'password', inputPlaceholder: '至少12位，包含大小写、数字和特殊字符',
      inputValidator: (v: string) => isStrongPassword(v, row.username) || '密码强度不足或包含用户名',
      confirmButtonText: '确认重置',
    })
  await http.post(`/admin/rbac/users/${row.user_id}/reset-pwd`, { password: value })
  ElMessage.success('密码已安全重置')
}

function isStrongPassword(value: string, username = '') {
  return value.length >= 12 && value.length <= 128 && /[a-z]/.test(value) && /[A-Z]/.test(value)
    && /\d/.test(value) && /[^A-Za-z0-9]/.test(value)
    && (!username || !value.toLowerCase().includes(username.toLowerCase()))
}

async function remove(row: any) {
  await http.del(`/admin/rbac/users/${row.user_id}`)
  ElMessage.success('已删除')
  await load()
}

function providerLabel(provider:string) {
  return ({unified_identity:'学校统一身份认证',wecom:'企业微信',school_app:'学校小程序/APP'} as any)[provider] || provider
}

async function openAuthMapping(row:UserRow) {
  authUser.value = row
  authVisible.value = true
  const detail:any = await http.get(`/admin/rbac/users/${row.user_id}/auth-identity`)
  const current = detail.mappings?.find((item:any) => item.status === 'active') || detail.mappings?.[0]
  Object.assign(authForm, {
    provider: current?.provider || 'unified_identity',
    subject_id: current?.subject_id || row.staff_id || '',
    active: current?.status !== 'inactive',
  })
}

async function saveAuthMapping() {
  if (!authUser.value || !authForm.subject_id.trim()) {
    ElMessage.warning('请填写认证主体标识')
    return
  }
  authSaving.value = true
  try {
    await http.put(`/admin/rbac/users/${authUser.value.user_id}/auth-identity`, {
      provider:authForm.provider,
      subject_id:authForm.subject_id.trim(),
      status:authForm.active ? 'active' : 'inactive',
    })
    ElMessage.success('统一身份映射已保存')
    authVisible.value = false
    await load()
  } finally { authSaving.value = false }
}

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.sub-cell{margin-top:3px;color:#94a3b8;font-size:11px}.mapping-form{margin-top:18px}
</style>

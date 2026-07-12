<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">账号管理</h2>
        <p class="sa-page-sub">数据来源：sys_user / sys_role（菜单级权限）</p>
      </div>
      <div style="display:flex;gap:8px">
        <el-button size="small" @click="$router.push('/admin/system/audit')">安全审计</el-button>
        <el-button size="small" @click="$router.push('/admin/system/kpis')">指标配置</el-button>
        <el-button type="primary" size="small" @click="openDialog()">+ 新建账号</el-button>
      </div>
    </div>

    <div class="sa-card">
      <el-table :data="users" size="small" v-loading="loading">
        <el-table-column prop="username" label="用户名" width="150" />
        <el-table-column prop="name" label="姓名" width="140" />
        <el-table-column prop="role_name" label="角色" min-width="160">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.role_name || row.role_id }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="row.status === 'active'"
              @change="(v: any) => toggleStatus(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '@/utils/http'

interface UserRow {
  user_id: number; username: string; name: string
  role_id: string; role_name: string; status: string
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

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
</style>

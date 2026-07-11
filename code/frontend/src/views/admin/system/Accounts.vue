<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">账号管理</h2>
        <p class="sa-page-sub">数据来源：sys_user / sys_role（菜单级权限）</p>
      </div>
      <el-button type="primary" size="small" @click="openDialog()">+ 新建账号</el-button>
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
        <el-form-item v-if="!editing" label="初始密码">
          <el-input v-model="form.password" placeholder="留空则默认 Demo@2026" />
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
        password: form.password || null, status: form.active ? 'active' : 'disabled',
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
  const r = await http.post<{ password: string | null }>(`/admin/rbac/users/${row.user_id}/reset-pwd`, {})
  ElMessageBox.alert(`账号「${row.username}」密码已重置为：${r.password || 'Demo@2026'}`, '重置成功', {
    confirmButtonText: '知道了',
  })
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

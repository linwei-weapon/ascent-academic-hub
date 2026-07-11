<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">角色管理</h2>
        <p class="sa-page-sub">数据来源：sys_role / sys_role_menu（角色 ↔ 菜单绑定，菜单级权限）</p>
      </div>
      <el-button type="primary" size="small" @click="openRoleDialog()">+ 新建角色</el-button>
    </div>

    <div class="sa-card">
      <el-table :data="roles" size="small" v-loading="loading">
        <el-table-column prop="name" label="角色名称" width="180" />
        <el-table-column prop="role_id" label="角色 ID" width="170" />
        <el-table-column prop="user_count" label="账号数" width="90" align="right" />
        <el-table-column prop="menu_count" label="可见菜单数" width="110" align="right" />
        <el-table-column label="操作" min-width="220">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openMenuDrawer(row)">分配菜单</el-button>
            <el-button size="small" text @click="openRoleDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该角色？" @confirm="removeRole(row)">
              <template #reference><el-button size="small" text type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 角色编辑 -->
    <el-dialog v-model="roleDialogVisible" :title="editingRole ? '编辑角色' : '新建角色'" width="420px">
      <el-form :model="roleForm" label-width="80px" size="small">
        <el-form-item label="角色 ID" required>
          <el-input v-model="roleForm.role_id" :disabled="editingRole" placeholder="如 librarian" />
        </el-form-item>
        <el-form-item label="角色名称" required>
          <el-input v-model="roleForm.name" placeholder="如 图书馆管理员" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="roleDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>

    <!-- 菜单分配 -->
    <el-drawer v-model="drawerVisible" :title="`分配菜单 · ${current?.name || ''}`" size="380px">
      <div class="drawer-tip">勾选该角色可见的菜单，保存后即时生效（该角色下次登录或刷新可见）。</div>
      <el-tree
        ref="treeRef"
        :data="menuTree"
        show-checkbox
        node-key="menu_id"
        default-expand-all
        :props="{ label: 'title' }"
      />
      <template #footer>
        <el-button size="small" @click="drawerVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="saveMenus">保存菜单权限</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, nextTick } from 'vue'
import type { TreeInstance } from 'element-plus'
import { ElMessage } from 'element-plus'
import { http } from '@/utils/http'

interface RoleRow {
  role_id: string; name: string; data_scope_type: string | null
  user_count: number; menu_count: number
}
interface MenuRow { menu_id: string; title: string; sort_order: number }

const roles = ref<RoleRow[]>([])
const menuTree = ref<MenuRow[]>([])
const loading = ref(false)
const saving = ref(false)

const roleDialogVisible = ref(false)
const editingRole = ref(false)
const roleForm = reactive({ role_id: '', name: '' })

const drawerVisible = ref(false)
const current = ref<RoleRow | null>(null)
const treeRef = ref<TreeInstance>()

async function load() {
  loading.value = true
  try {
    roles.value = await http.get('/admin/rbac/roles')
    menuTree.value = await http.get('/admin/rbac/menus')
  } finally {
    loading.value = false
  }
}

function openRoleDialog(row?: any) {
  if (row) {
    editingRole.value = true
    Object.assign(roleForm, { role_id: row.role_id, name: row.name })
  } else {
    editingRole.value = false
    Object.assign(roleForm, { role_id: '', name: '' })
  }
  roleDialogVisible.value = true
}

async function saveRole() {
  if (!roleForm.role_id || !roleForm.name) {
    ElMessage.warning('角色 ID 和名称为必填')
    return
  }
  saving.value = true
  try {
    if (editingRole.value) {
      await http.put(`/admin/rbac/roles/${roleForm.role_id}`, { name: roleForm.name })
    } else {
      await http.post('/admin/rbac/roles', { role_id: roleForm.role_id, name: roleForm.name })
    }
    ElMessage.success('已保存')
    roleDialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function removeRole(row: any) {
  await http.del(`/admin/rbac/roles/${row.role_id}`)
  ElMessage.success('已删除')
  await load()
}

async function openMenuDrawer(row: any) {
  current.value = row
  drawerVisible.value = true
  const checked = await http.get<string[]>(`/admin/rbac/roles/${row.role_id}/menus`)
  await nextTick()
  treeRef.value?.setCheckedKeys(checked, false)
}

async function saveMenus() {
  if (!current.value) return
  const ids = (treeRef.value?.getCheckedKeys(false) || []) as string[]
  saving.value = true
  try {
    await http.put(`/admin/rbac/roles/${current.value.role_id}/menus`, { menu_ids: ids })
    ElMessage.success('菜单权限已保存')
    drawerVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.drawer-tip { font-size: 12px; color: var(--sa-muted); line-height: 1.7; margin-bottom: 14px; }
</style>

<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">角色管理</h2>
        <p class="sa-page-sub">角色定义功能能力上限；账号的实际数据范围仍由当前工作身份和人员关系决定。</p>
      </div>
      <el-button type="primary" size="small" @click="openRoleDialog()">+ 新建角色</el-button>
    </div>

    <div class="sa-card">
      <el-table :data="roles" size="small" v-loading="loading">
        <el-table-column prop="name" label="角色名称" width="180" />
        <el-table-column prop="role_id" label="角色 ID" width="170" />
        <el-table-column prop="user_count" label="账号数" width="90" align="right" />
        <el-table-column prop="menu_count" label="可见菜单数" width="110" align="right" />
        <el-table-column label="数据范围类型" width="130">
          <template #default="{row}">{{ scopeTypeLabel(row.data_scope_type) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="220">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openPermissionDrawer(row)">配置权限</el-button>
            <el-button size="small" text @click="previewRole(row)">权限预览</el-button>
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
        <el-form-item label="范围类型" required>
          <el-select v-model="roleForm.data_scope_type" style="width:100%">
            <el-option label="全校" value="all" />
            <el-option label="学院" value="college" />
            <el-option label="专业" value="major" />
            <el-option label="行政班" value="class" />
            <el-option label="任课关系" value="teacher" />
            <el-option label="带班/带生关系" value="staff_relation" />
          </el-select>
        </el-form-item>
        <el-alert type="info" :closable="false" title="范围类型只定义该角色需要哪类授权；具体学院、班级或人员关系在数据权限页面配置。" />
      </el-form>
      <template #footer>
        <el-button size="small" @click="roleDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>

    <!-- 功能权限配置 -->
    <el-drawer v-model="drawerVisible" :title="`配置功能权限 · ${current?.name || ''}`" size="620px">
      <div class="drawer-tip">菜单决定“能进入哪里”，动作权限决定“进入后能做什么”；数据范围不在这里配置。</div>
      <el-tabs v-model="permissionTab">
        <el-tab-pane label="菜单权限" name="menus">
          <el-tree
            ref="treeRef"
            :data="menuTree"
            show-checkbox
            node-key="menu_id"
            default-expand-all
            :props="{ label: 'title' }"
          />
        </el-tab-pane>
        <el-tab-pane label="页面与关键动作" name="actions">
          <section v-for="group in actionGroups" :key="group.name" class="action-group">
            <h4>{{ group.name }}</h4>
            <el-checkbox-group v-model="checkedActionIds">
              <el-checkbox v-for="action in group.actions" :key="action.action_id" :value="action.action_id">
                <b>{{ action.name }}</b><span>{{ action.description }}</span>
              </el-checkbox>
            </el-checkbox-group>
          </section>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button size="small" @click="drawerVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="savePermissions">保存功能权限</el-button>
      </template>
    </el-drawer>

    <el-drawer v-model="previewVisible" title="角色权限预览" size="560px">
      <template v-if="previewData">
        <el-alert type="info" :closable="false" show-icon :title="previewData.boundary" />
        <div class="preview-summary">
          <div><span>角色</span><b>{{ previewData.role.name }}</b></div>
          <div><span>数据范围类型</span><b>{{ scopeTypeLabel(previewData.role.data_scope_type) }}</b></div>
          <div><span>菜单入口</span><b>{{ previewData.menus.length }} 个</b></div>
          <div><span>关键动作</span><b>{{ previewData.actions.length }} 项</b></div>
        </div>
        <h4>菜单入口</h4>
        <el-tag v-for="menu in previewData.menus" :key="menu.menu_id" class="preview-tag" effect="plain">{{ menu.title }}</el-tag>
        <h4>关键动作</h4>
        <el-tag v-for="action in previewData.actions" :key="action.action_id" class="preview-tag" type="success" effect="plain">{{ action.name }}</el-tag>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted, nextTick } from 'vue'
import type { TreeInstance } from 'element-plus'
import { ElMessage } from 'element-plus'
import { http } from '@/utils/http'

interface RoleRow {
  role_id: string; name: string; data_scope_type: string | null
  user_count: number; menu_count: number
}
interface MenuRow {
  menu_id: string; parent_id: string | null; title: string
  path: string; sort_order: number; children?: MenuRow[]
}

const roles = ref<RoleRow[]>([])
const menuTree = ref<MenuRow[]>([])
const loading = ref(false)
const saving = ref(false)

const roleDialogVisible = ref(false)
const editingRole = ref(false)
const roleForm = reactive({ role_id: '', name: '', data_scope_type: 'all' })

const drawerVisible = ref(false)
const current = ref<RoleRow | null>(null)
const treeRef = ref<TreeInstance>()
const actionCatalog = ref<any[]>([])
const checkedActionIds = ref<string[]>([])
const permissionTab = ref('menus')
const previewVisible = ref(false)
const previewData = ref<any>(null)
const actionGroups = computed(() => {
  const groups = new Map<string,any[]>()
  for (const action of actionCatalog.value) {
    if (!groups.has(action.group)) groups.set(action.group, [])
    groups.get(action.group)?.push(action)
  }
  return [...groups.entries()].map(([name, actions]) => ({name,actions}))
})

async function load() {
  loading.value = true
  try {
    roles.value = await http.get('/admin/rbac/roles')
    const menus = await http.get<MenuRow[]>('/admin/rbac/menus')
    actionCatalog.value = await http.get('/admin/rbac/actions')
    menuTree.value = menus
      .filter(menu => !menu.parent_id)
      .map(parent => ({
        ...parent,
        children: menus
          .filter(menu => menu.parent_id === parent.menu_id)
          .sort((a, b) => a.sort_order - b.sort_order),
      }))
      .filter(parent => parent.children?.length)
      .sort((a, b) => a.sort_order - b.sort_order)
  } finally {
    loading.value = false
  }
}

function openRoleDialog(row?: any) {
  if (row) {
    editingRole.value = true
    Object.assign(roleForm, { role_id: row.role_id, name: row.name, data_scope_type: row.data_scope_type || 'all' })
  } else {
    editingRole.value = false
    Object.assign(roleForm, { role_id: '', name: '', data_scope_type: 'all' })
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
      await http.put(`/admin/rbac/roles/${roleForm.role_id}`, {
        name: roleForm.name, data_scope_type:roleForm.data_scope_type,
      })
    } else {
      await http.post('/admin/rbac/roles', {
        role_id: roleForm.role_id, name: roleForm.name,
        data_scope_type:roleForm.data_scope_type,
      })
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

async function openPermissionDrawer(row: any) {
  current.value = row
  permissionTab.value = 'menus'
  drawerVisible.value = true
  const [checkedMenus,checkedActions] = await Promise.all([
    http.get<string[]>(`/admin/rbac/roles/${row.role_id}/menus`),
    http.get<string[]>(`/admin/rbac/roles/${row.role_id}/actions`),
  ])
  checkedActionIds.value = checkedActions
  await nextTick()
  treeRef.value?.setCheckedKeys(checkedMenus, false)
}

async function savePermissions() {
  if (!current.value) return
  const ids = (treeRef.value?.getCheckedKeys(true) || []) as string[]
  saving.value = true
  try {
    await http.put(`/admin/rbac/roles/${current.value.role_id}/permissions`, {
      menu_ids:ids, action_ids:checkedActionIds.value,
    })
    ElMessage.success('菜单和动作权限已保存')
    drawerVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function previewRole(row:any) {
  previewData.value = await http.get(`/admin/rbac/roles/${row.role_id}/permission-preview`)
  previewVisible.value = true
}

function scopeTypeLabel(type:string) {
  return ({all:'全校',college:'学院',major:'专业',class:'行政班',teacher:'任课关系',staff_relation:'带班/带生关系'} as any)[type] || type
}

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.drawer-tip { font-size: 12px; color: var(--sa-muted); line-height: 1.7; margin-bottom: 14px; }
.action-group{margin-bottom:18px}.action-group h4{margin:0 0 9px;color:#334155}.action-group :deep(.el-checkbox-group){display:grid;gap:8px}.action-group :deep(.el-checkbox){height:auto;align-items:flex-start}.action-group b{display:block;color:#334155}.action-group span{display:block;color:#94a3b8;font-size:11px;line-height:1.5}.preview-summary{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.preview-summary>div{padding:12px;background:#f8fafc;border-radius:9px}.preview-summary span{display:block;color:#64748b;font-size:11px}.preview-summary b{display:block;margin-top:5px;color:#1e293b}.preview-tag{margin:0 7px 7px 0}
</style>

<!-- 角色与功能权限：系统管理模块，沿用既有接口、治理操作与权限边界。 -->
<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">角色管理</h2>
        <p class="sa-page-sub">角色定义功能能力上限；账号的实际数据范围仍由当前工作身份和人员关系决定。</p>
      </div>
      <el-button type="primary" size="small" @click="openRoleDialog()">+ 新建角色</el-button>
    </div>

    <div class="sa-card role-table-card">
      <!-- 全量角色由页面分页；公共组件统一展示设置，不改变角色接口和授权操作。 -->
      <AppTable
        :columns="columns"
        :data="pagedRoles"
        storage-key="system:roles"
        :show-density="false"
        :show-column-settings="false"
        default-density="default"
        :page="page"
        :page-size="pageSize"
        :total="roles.length"
        :loading="loading"
        row-key="role_id"
        stripe
        @page-change="changePage"
        @page-size-change="changePageSize"
      >
        <template #col-data_scope_type="{ row }">{{ scopeTypeLabel(row.data_scope_type) }}</template>
        <template #col-actions="{ row }">
          <div class="role-table-card__actions sa-button-row">
            <el-button size="small" text type="primary" @click="openPermissionDrawer(row)">配置权限</el-button>
            <el-button size="small" text @click="previewRole(row)">权限预览</el-button>
            <el-button size="small" text @click="openRoleDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该角色？" @confirm="removeRole(row)">
              <template #reference><el-button size="small" text type="danger">删除</el-button></template>
            </el-popconfirm>
          </div>
        </template>
      </AppTable>
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
          <el-select v-model="roleForm.data_scope_type" class="role-scope-control">
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
import AppTable from '@/components/AppTable.vue'
import { DEFAULT_TABLE_PAGE_SIZE, TABLE_PAGE_SIZES, type AppTableColumn } from '@/types/table'
import * as rolesApi from '@/api/admin/roles'

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

// 列标识用于保存显示偏好；数据列自适应，名称和操作在横向滚动时保持可见。
const columns: AppTableColumn[] = [
  { key: 'name', label: '角色名称', minWidth: 180, fixed: 'left', required: true, tooltip: true },
  { key: 'role_id', label: '角色 ID', minWidth: 170, tooltip: true },
  { key: 'user_count', label: '账号数', minWidth: 90 },
  { key: 'menu_count', label: '可见菜单数', minWidth: 110 },
  { key: 'data_scope_type', label: '数据范围类型', minWidth: 130 },
  { key: 'actions', label: '操作', width: 320, fixed: 'right', required: true },
]
const page = ref(1)
const pageSize = ref<number>(DEFAULT_TABLE_PAGE_SIZE)
const lastPage = computed(() => Math.max(1, Math.ceil(roles.value.length / pageSize.value)))

/** 接口返回完整角色集合；仅在页面切片一次，保留服务端顺序和原始统计字段。 */
const pagedRoles = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return roles.value.slice(start, start + pageSize.value)
})

/** 翻页只改变本页展示，不重复请求角色、菜单或动作目录，也不写入 URL。 */
function changePage(value: number): void {
  if (loading.value || !Number.isSafeInteger(value)) return
  page.value = Math.min(lastPage.value, Math.max(1, value))
}

/** 每页条数沿用公共选项，切换后回第一页；不从显示偏好中恢复页长。 */
function changePageSize(value: number): void {
  if (loading.value || !TABLE_PAGE_SIZES.some(size => size === value)) return
  pageSize.value = value
  page.value = 1
}

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
// 按动作目录的原分组构建功能权限选项。
const actionGroups = computed(() => {
  const groups = new Map<string,any[]>()
  for (const action of actionCatalog.value) {
    if (!groups.has(action.group)) groups.set(action.group, [])
    groups.get(action.group)?.push(action)
  }
  return [...groups.entries()].map(([name, actions]) => ({name,actions}))
})

// 读取角色、菜单和动作目录，沿用父子菜单排序。
async function load() {
  loading.value = true
  try {
    roles.value = await rolesApi.listRoles<RoleRow[]>()
    // 保存后保留当前页；删除导致末页消失时回到最近的有效页，空集合回第一页。
    page.value = Math.min(page.value, lastPage.value)
    const menus = await rolesApi.listRoleMenuOptions<MenuRow[]>()
    actionCatalog.value = await rolesApi.listRoleActionOptions()
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

// 按新增或编辑模式准备角色表单及原范围默认值。
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

// 保留必填校验和范围字段，成功后重新读取角色。
async function saveRole() {
  if (!roleForm.role_id || !roleForm.name) {
    ElMessage.warning('角色 ID 和名称为必填')
    return
  }
  saving.value = true
  try {
    if (editingRole.value) {
      await rolesApi.updateRole(roleForm.role_id, {
        name: roleForm.name, data_scope_type:roleForm.data_scope_type,
      })
    } else {
      await rolesApi.createRole({
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

// 经原确认流程删除角色并更新列表。
async function removeRole(row: any) {
  await rolesApi.deleteRole(row.role_id)
  ElMessage.success('已删除')
  await load()
}

// 读取当前角色已授权的菜单和动作，再同步勾选状态。
async function openPermissionDrawer(row: any) {
  current.value = row
  permissionTab.value = 'menus'
  drawerVisible.value = true
  const [checkedMenus,checkedActions] = await Promise.all([
    rolesApi.getRoleMenus<string[]>(row.role_id),
    rolesApi.getRoleActions<string[]>(row.role_id),
  ])
  checkedActionIds.value = checkedActions
  await nextTick()
  treeRef.value?.setCheckedKeys(checkedMenus, false)
}

// 提交选中的叶子菜单和动作，不以父菜单替代授权。
async function savePermissions() {
  if (!current.value) return
  const ids = (treeRef.value?.getCheckedKeys(true) || []) as string[]
  saving.value = true
  try {
    await rolesApi.saveRolePermissions(current.value.role_id, {
      menu_ids:ids, action_ids:checkedActionIds.value,
    })
    ElMessage.success('菜单和动作权限已保存')
    drawerVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

// 请求服务端汇总该角色的权限，不在前端扩展范围。
async function previewRole(row:any) {
  previewData.value = await rolesApi.previewRolePermissions(row.role_id)
  previewVisible.value = true
}

// 按现有范围类型展示中文名称，未知枚举保留原兜底。
function scopeTypeLabel(type:string) {
  return ({all:'全校',college:'学院',major:'专业',class:'行政班',teacher:'任课关系',staff_relation:'带班/带生关系'} as any)[type] || type
}

// 每次进入或刷新从第 1 页、每页 20 条开始，沿用原角色和权限目录加载流程。
onMounted(load)
</script>

<style scoped lang="scss">
// 页面区域、状态修饰与后代元素按相邻规则分组，保留原级联和弹窗作用域。
.sa-head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.role-table-card {
  min-width: 0;

  &__actions {
    display: flex;
    align-items: center;
    justify-content: center;
    white-space: nowrap;
  }
}

.drawer-tip {
  font-size: 12px;
  color: var(--sa-muted);
  line-height: 1.7;
  margin-bottom: 14px;
}

.action-group {
  margin-bottom: 18px;

  h4 {
    margin: 0 0 9px;
    color: #334155;
  }

  :deep(.el-checkbox-group) {
    display: grid;
    gap: 8px;
  }

  :deep(.el-checkbox) {
    height: auto;
    align-items: flex-start;
  }

  b {
    display: block;
    color: #334155;
  }

  span {
    display: block;
    color: var(--sa-faint);
    font-size: 11px;
    line-height: 1.5;
  }
}

.preview-summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin: 14px 0;

  &>div {
    padding: 12px;
    background: var(--sa-bg);
    border-radius: 9px;
  }

  span {
    display: block;
    color: var(--sa-muted);
    font-size: 11px;
  }

  b {
    display: block;
    margin-top: 5px;
    color: var(--sa-text);
  }
}

.preview-tag {
  margin: 0 7px 7px 0;
}

// 静态控件尺寸与局部布局由 class 管理，动态样式保留在原数据绑定中。
.role-scope-control {
  width: 100%;
}
</style>

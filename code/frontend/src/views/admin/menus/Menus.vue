<!-- 菜单管理：系统管理模块，沿用既有接口、治理操作与权限边界。 -->
<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">菜单管理</h2>
        <p class="sa-page-sub">数据来源：sys_menu（侧边栏菜单的真值源，登录后由后端返回）</p>
      </div>
      <el-button type="primary" size="small" @click="openDialog()">+ 新建菜单</el-button>
    </div>

    <div class="sa-card menu-table-card">
      <AppTable
        :columns="menuColumns"
        storage-key="system:menus"
        :pagination="false"
        :data="menuTree"
        row-key="menu_id"
        default-expand-all
        :indent="32"
        :tree-props="{ children: 'children' }"
        :loading="loading"
      >
        <!-- 编号保留自然宽度，与原生展开按钮相邻；层级位置由单元格布局控制。 -->
        <template #col-sort_order="{ row }"><span class="menu-sort-value">{{ row.sort_order }}</span></template>
        <template #col-level="{ row }">{{ row.parent_id ? '二级菜单' : '一级分组' }}</template>
        <template #col-actions="{ row }">
          <el-button size="small" text type="primary" @click="openDialog(row)">编辑</el-button>
          <el-popconfirm title="删除后所有角色将失去该菜单，确定？" @confirm="remove(row)">
            <template #reference><el-button size="small" text type="danger">删除</el-button></template>
          </el-popconfirm>
        </template>
      </AppTable>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑菜单' : '新建菜单'" width="460px">
      <el-form :model="form" label-width="90px" size="small">
        <el-form-item label="菜单 ID" required>
          <el-input v-model="form.menu_id" :disabled="editing" placeholder="如 /admin/foo（建议与路径一致）" />
        </el-form-item>
        <el-form-item label="菜单名称" required>
          <el-input v-model="form.title" placeholder="侧边栏显示名" />
        </el-form-item>
        <el-form-item label="父菜单">
          <el-select
            v-model="form.parent_id"
            clearable
            placeholder="留空表示一级分组"
            class="menu-parent-control"
          >
            <el-option
              v-for="parent in parentOptions"
              :key="parent.menu_id"
              :label="parent.title"
              :value="parent.menu_id"
              :disabled="parent.menu_id === form.menu_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="路由路径" required>
          <el-input v-model="form.path" placeholder="如 /admin/foo" />
        </el-form-item>
        <el-form-item label="图标">
          <el-input v-model="form.icon" placeholder="ElementPlus 图标名，如 Setting" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :step="1" controls-position="right" />
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
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import { computed, ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as menusApi from '@/api/admin/menus'

interface MenuRow {
  menu_id: string; parent_id: string | null; title: string
  path: string; icon: string | null; sort_order: number; role_count?: number; children?: MenuRow[]
}

const menus = ref<MenuRow[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref(false)
const form = reactive({
  menu_id: '', parent_id: '' as string, title: '',
  path: '', icon: '', sort_order: 0,
})
// 仅将现有顶级菜单作为父级选择项。
const parentOptions = computed(() => menus.value.filter(menu => !menu.parent_id))
// 按父子关系组装菜单树，并保留原排序规则。
const menuTree = computed<MenuRow[]>(() => menus.value
  .filter(menu => !menu.parent_id)
  .map(parent => ({
    ...parent,
    children: menus.value
      .filter(menu => menu.parent_id === parent.menu_id)
      .sort((a, b) => a.sort_order - b.sort_order),
  }))
  .sort((a, b) => a.sort_order - b.sort_order))

// 读取后端菜单目录，页面不自行新增权限。
async function load() {
  loading.value = true
  try {
    menus.value = await menusApi.listMenus()
  } finally {
    loading.value = false
  }
}

// 按新增或编辑模式填充原菜单字段。
function openDialog(row?: any) {
  if (row) {
    editing.value = true
    Object.assign(form, {
      menu_id: row.menu_id, title: row.title, path: row.path,
      parent_id: row.parent_id || '',
      icon: row.icon || '', sort_order: row.sort_order,
    })
  } else {
    editing.value = false
    Object.assign(form, {
      menu_id: '', parent_id: '', title: '', path: '',
      icon: '', sort_order: nextSort(),
    })
  }
  dialogVisible.value = true
}

// 从现有最大排序号推导新增菜单的初始顺序。
function nextSort(): number {
  return menus.value.reduce((m, x) => Math.max(m, x.sort_order), 0) + 1
}

// 校验原必填字段后提交菜单变更，父级空值语义保持不变。
async function save() {
  if (!form.menu_id || !form.title || !form.path) {
    ElMessage.warning('菜单 ID、名称、路径为必填')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await menusApi.updateMenu(form.menu_id, {
        parent_id: form.parent_id || null,
        title: form.title, path: form.path, icon: form.icon,
        sort_order: form.sort_order,
      })
    } else {
      await menusApi.createMenu({
        ...form, parent_id: form.parent_id || null,
      })
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

// 经页面原确认入口删除菜单，成功后重新读取目录。
async function remove(row: any) {
  await menusApi.deleteMenu(row.menu_id)
  ElMessage.success('已删除')
  await load()
}

// 进入页面时沿用原初始化与路由参数恢复流程。
onMounted(load)
// 列定义只负责展示；单元格内容和业务操作沿用原页面。
const menuColumns: AppTableColumn[] = [
  // 为树形前缀和编号预留空间，保持子级向右缩进。
  { key: "sort_order", label: "排序", minWidth: 120, align: "left" },
  { key: "title", label: "菜单名称", minWidth: 190 },
  { key: "level", label: "层级", minWidth: 90 },
  { key: "path", label: "路由路径", minWidth: 220 },
  { key: "icon", label: "图标", minWidth: 120 },
  { key: "role_count", label: "授权角色", minWidth: 90 },
  { key: "menu_id", label: "菜单 ID", minWidth: 200 },
  { key: "actions", label: "操作", minWidth: 150 },
]

</script>

<style scoped lang="scss">
// 页面区域、状态修饰与后代元素按相邻规则分组，保留原级联和弹窗作用域。
.sa-head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.menu-table-card {
  // 编号两侧等分剩余空间，一级编号对齐表头中心；32px 原生缩进使子级中心右移 16px。
  :deep(.el-table__body td:first-child .cell) {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center;
    white-space: nowrap;

    .el-table__indent {
      grid-area: 1 / 1;
    }

    // 箭头在编号前紧邻排列，保留 Element Plus 的展开、收起和键盘操作。
    .el-table__expand-icon,.el-table__placeholder {
      grid-area: 1 / 2;
      justify-self: end;
      width: 20px;
      height: 20px;
    }
  }

  .menu-sort-value {
    grid-area: 1 / 3;
  }
}

// 静态控件尺寸与局部布局由 class 管理，动态样式保留在原数据绑定中。
.menu-parent-control {
  width: 100%;
}
</style>

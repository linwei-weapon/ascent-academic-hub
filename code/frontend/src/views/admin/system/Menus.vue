<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">菜单管理</h2>
        <p class="sa-page-sub">数据来源：sys_menu（侧边栏菜单的真值源，登录后由后端返回）</p>
      </div>
      <el-button type="primary" size="small" @click="openDialog()">+ 新建菜单</el-button>
    </div>

    <div class="sa-card">
      <el-table :data="menus" size="small" v-loading="loading">
        <el-table-column prop="sort_order" label="排序" width="70" align="center" />
        <el-table-column prop="title" label="菜单名称" width="160" />
        <el-table-column prop="path" label="路由路径" min-width="220" />
        <el-table-column prop="icon" label="图标" width="120" />
        <el-table-column prop="menu_id" label="菜单 ID" min-width="200" />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDialog(row)">编辑</el-button>
            <el-popconfirm title="删除后所有角色将失去该菜单，确定？" @confirm="remove(row)">
              <template #reference><el-button size="small" text type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑菜单' : '新建菜单'" width="460px">
      <el-form :model="form" label-width="90px" size="small">
        <el-form-item label="菜单 ID" required>
          <el-input v-model="form.menu_id" :disabled="editing" placeholder="如 /admin/foo（建议与路径一致）" />
        </el-form-item>
        <el-form-item label="菜单名称" required>
          <el-input v-model="form.title" placeholder="侧边栏显示名" />
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
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { http } from '@/utils/http'

interface MenuRow {
  menu_id: string; parent_id: string | null; title: string
  path: string; icon: string | null; sort_order: number
}

const menus = ref<MenuRow[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref(false)
const form = reactive({ menu_id: '', title: '', path: '', icon: '', sort_order: 0 })

async function load() {
  loading.value = true
  try {
    menus.value = await http.get('/admin/rbac/menus')
  } finally {
    loading.value = false
  }
}

function openDialog(row?: any) {
  if (row) {
    editing.value = true
    Object.assign(form, {
      menu_id: row.menu_id, title: row.title, path: row.path,
      icon: row.icon || '', sort_order: row.sort_order,
    })
  } else {
    editing.value = false
    Object.assign(form, { menu_id: '', title: '', path: '', icon: '', sort_order: nextSort() })
  }
  dialogVisible.value = true
}

function nextSort(): number {
  return menus.value.reduce((m, x) => Math.max(m, x.sort_order), 0) + 1
}

async function save() {
  if (!form.menu_id || !form.title || !form.path) {
    ElMessage.warning('菜单 ID、名称、路径为必填')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await http.put(`/admin/rbac/menus/${encodeURIComponent(form.menu_id)}`, {
        title: form.title, path: form.path, icon: form.icon, sort_order: form.sort_order,
      })
    } else {
      await http.post('/admin/rbac/menus', { ...form })
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await http.del(`/admin/rbac/menus/${encodeURIComponent(row.menu_id)}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
</style>

<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/system/accounts'}">账号管理</el-breadcrumb-item>
      <el-breadcrumb-item>安全审计</el-breadcrumb-item>
    </el-breadcrumb>
    <h2 class="sa-page-title">安全审计</h2>
    <p class="sa-page-sub">登录、账号、角色与菜单敏感操作记录 · 只读</p>
    <div class="sa-card">
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <el-select v-model="action" clearable placeholder="全部操作" size="small" style="width:220px" @change="load(1)">
          <el-option v-for="item in actions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-button size="small" @click="load(page)">刷新</el-button>
      </div>
      <el-table :data="rows" size="small" v-loading="loading">
        <el-table-column prop="created_at" label="时间" width="190" />
        <el-table-column prop="actor" label="操作人" width="130" />
        <el-table-column prop="action" label="操作" min-width="190" />
        <el-table-column label="对象" min-width="150"><template #default="{row}">{{ row.target_type || '—' }} · {{ row.target_id || '—' }}</template></el-table-column>
        <el-table-column prop="result" label="结果" width="100"><template #default="{row}"><el-tag size="small" :type="row.result==='success'?'success':row.result==='failed'?'danger':'warning'">{{ row.result }}</el-tag></template></el-table-column>
        <el-table-column prop="client_key" label="客户端" width="130" />
        <el-table-column label="详情" min-width="220" show-overflow-tooltip><template #default="{row}">{{ detailText(row.detail) }}</template></el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px;justify-content:flex-end" background small
        layout="total, prev, pager, next" :total="total" :page-size="pageSize"
        :current-page="page" @current-change="load" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { http } from '@/utils/http'
const rows = ref<any[]>([]), total = ref(0), page = ref(1), loading = ref(false)
const pageSize = 50
const action = ref('')
const actions = ['auth.login','auth.logout','rbac.user.create','rbac.user.update','rbac.user.delete','rbac.user.password_reset','rbac.role.create','rbac.role.update','rbac.role.delete','rbac.role.menus_update','rbac.menu.create','rbac.menu.update','rbac.menu.delete']
const detailText = (detail:any) => detail && Object.keys(detail).length ? JSON.stringify(detail) : '—'
async function load(target=1) {
  loading.value = true
  try {
    const qs = new URLSearchParams({page:String(target),page_size:String(pageSize)})
    if (action.value) qs.set('action', action.value)
    const data:any = await http.get('/admin/rbac/security-audit?' + qs.toString())
    rows.value = data.list || []; total.value = data.total || 0; page.value = target
  } finally { loading.value = false }
}
onMounted(() => load(1))
</script>

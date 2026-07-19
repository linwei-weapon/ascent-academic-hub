<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/system/accounts'}">系统管理</el-breadcrumb-item>
      <el-breadcrumb-item>审计日志</el-breadcrumb-item>
    </el-breadcrumb>
    <h2 class="sa-page-title">审计日志</h2>
    <p class="sa-page-sub">统一记录登录、身份切换、敏感数据读取、导出、权限配置、指标、规则和AI分析方案操作。</p>
    <div class="sa-card">
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <el-select v-model="action" clearable placeholder="全部操作" size="small" style="width:220px" @change="load(1)">
          <el-option v-for="item in actions" :key="item.action" :label="`${actionLabel(item.action)}（${item.count}）`" :value="item.action" />
        </el-select>
        <el-button size="small" @click="load(page)">刷新</el-button>
      </div>
      <el-table :data="rows" size="small" v-loading="loading">
        <el-table-column prop="created_at" label="时间" width="190" />
        <el-table-column prop="actor" label="操作人" width="130" />
        <el-table-column label="操作" min-width="210"><template #default="{row}"><div>{{ actionLabel(row.action) }}</div><div class="sub-cell">{{ row.action }}</div></template></el-table-column>
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
const actions = ref<any[]>([])
const labels:Record<string,string> = {
  'auth.login':'登录','auth.logout':'登出','auth.identity.switch':'切换工作身份',
  'data.student.detail.read':'查看学生明细','data.student.list.read':'查看学生名单','data.export':'导出授权数据',
  'ai.analysis.run':'运行AI研判','ai.analysis_scheme.create':'创建分析方案','ai.analysis_scheme.test':'测试分析方案',
  'ai.analysis_scheme.publish':'发布分析方案','ai.analysis_scheme.retire':'停用分析方案','ai.analysis_scheme.roles_update':'调整方案适用角色',
  'ai.expert.version.create':'创建专家版本','ai.expert.version.publish':'发布专家版本','ai.expert.version.rollback':'回滚专家版本',
  'rbac.user.create':'创建账号','rbac.user.update':'修改账号','rbac.user.delete':'删除账号','rbac.user.password_reset':'重置密码',
  'rbac.user.auth_identity_update':'更新统一身份映射','rbac.role.create':'创建角色','rbac.role.update':'修改角色',
  'rbac.role.delete':'删除角色','rbac.role.permissions_update':'修改角色功能权限','rbac.menu.create':'创建菜单',
  'rbac.menu.update':'修改菜单','rbac.menu.delete':'删除菜单','rbac.permission.staff_update':'修改人员映射',
  'rbac.permission.identity_create':'添加工作身份','rbac.permission.identity_update':'修改工作身份',
  'rbac.permission.identity_delete':'删除工作身份','rbac.permission.scope_update':'修改数据范围',
  'settings.kpi.update':'修改指标展示配置','settings.kpi.rollback':'回滚指标展示配置',
  'system.parameter.update':'修改系统参数',
}
const actionLabel = (value:string) => labels[value] || value
const detailText = (detail:any) => detail && Object.keys(detail).length ? JSON.stringify(detail) : '—'
async function load(target=1) {
  loading.value = true
  try {
    const qs = new URLSearchParams({page:String(target),page_size:String(pageSize)})
    if (action.value) qs.set('action', action.value)
    const data:any = await http.get('/admin/rbac/security-audit?' + qs.toString())
    rows.value = data.list || []; total.value = data.total || 0; page.value = target
    actions.value = data.actions || []
  } finally { loading.value = false }
}
onMounted(() => load(1))
</script>

<style scoped>.sub-cell{margin-top:3px;color:#94a3b8;font-size:11px}</style>

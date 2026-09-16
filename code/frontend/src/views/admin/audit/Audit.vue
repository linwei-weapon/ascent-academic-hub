<!-- 审计日志：系统管理模块，沿用既有接口、治理操作与权限边界。 -->
<template>
  <div>
    <el-breadcrumb separator="›" class="audit-breadcrumb">
      <el-breadcrumb-item :to="{path:'/admin/system/accounts'}">系统管理</el-breadcrumb-item>
      <el-breadcrumb-item>审计日志</el-breadcrumb-item>
    </el-breadcrumb>
    <h2 class="sa-page-title">审计日志</h2>
    <p class="sa-page-sub">统一记录登录、身份切换、敏感数据读取、导出、权限配置、指标、规则和AI分析方案操作。</p>
    <div class="sa-card">
      <div class="audit-toolbar">
        <el-select v-model="action" clearable placeholder="全部操作" size="small" class="audit-action-filter" @change="load(1)">
          <el-option v-for="item in actions" :key="item.action" :label="`${actionLabel(item.action)}（${item.count}）`" :value="item.action" />
        </el-select>
        <el-button size="small" @click="load(page)">刷新</el-button>
      </div>
      <AppTable
        :columns="auditColumns"
        storage-key="system:audit"
        :page="page"
        :page-size="pageSize"
        :total="total"
        @page-change="load"
        @page-size-change="changePageSize"
        :data="rows"
        :loading="loading"
      >
        <template #col-action="{row}"><div>{{ actionLabel(row.action) }}</div><div class="sub-cell">{{ row.action }}</div></template>
        <template #col-target="{row}">{{ row.target_type || '—' }} · {{ row.target_id || '—' }}</template>
        <template #col-result="{row}"><el-tag size="small" :type="row.result==='success'?'success':row.result==='failed'?'danger':'warning'">{{ row.result }}</el-tag></template>
        <template #col-detail="{row}">{{ detailText(row.detail) }}</template>
      </AppTable>
    </div>
  </div>
</template>

<script setup lang="ts">
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import { onMounted, ref } from 'vue'
import * as auditApi from '@/api/admin/audit'
const rows = ref<any[]>([]), total = ref(0), page = ref(1), loading = ref(false)
const pageSize = ref(20)
const action = ref('')
const actions = ref<any[]>([])
const labels:Record<string,string> = {
  'auth.login':'登录','auth.logout':'登出','auth.identity.switch':'切换工作身份',
  'data.student.detail.read':'查看学生明细','data.student.list.read':'查看学生名单','data.export':'导出授权数据',
  'ai.analysis.run':'运行AI研判','ai.analysis_scheme.create':'创建分析方案','ai.analysis_scheme.update':'修改分析方案',
  'ai.analysis_scheme.test':'测试分析方案','ai.analysis_scheme.publish':'发布分析方案',
  'ai.analysis_scheme.retire':'停用分析方案','ai.analysis_scheme.rollback':'回滚分析方案',
  'ai.analysis_scheme.export':'导出分析方案','ai.analysis_scheme.import':'导入分析方案',
  'ai.analysis_scheme.roles_update':'调整方案适用角色',
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
// 将已知审计动作显示为中文，未知动作保留原始标识。
const actionLabel = (value:string) => labels[value] || value
// 只序列化已有审计详情用于展示，不修改记录内容。
const detailText = (detail:any) => detail && Object.keys(detail).length ? JSON.stringify(detail) : '—'
// 按操作筛选读取服务端分页，同时同步数量和可选动作。
async function load(target=1) {
  loading.value = true
  try {
    const qs = new URLSearchParams({page:String(target),page_size:String(pageSize.value)})
    if (action.value) qs.set('action', action.value)
    const data:any = await auditApi.listSecurityAudit(qs.toString())
    rows.value = data.list || []; total.value = data.total || 0; page.value = target
    actions.value = data.actions || []
  } finally { loading.value = false }
}
// 调整页长后从第一页查询，保留当前审计动作筛选。
function changePageSize(value: number) {
  if (value === pageSize.value) return
  pageSize.value = value
  load(1)
}

// 进入页面时沿用原初始化与路由参数恢复流程。
onMounted(() => load(1))
// 列定义只负责展示；单元格内容和业务操作沿用原页面。
const auditColumns: AppTableColumn[] = [
  { key: "created_at", label: "时间", minWidth: 190 },
  { key: "actor", label: "操作人", minWidth: 130 },
  { key: "action", label: "操作", minWidth: 210 },
  { key: "target", label: "对象", minWidth: 150 },
  { key: "result", label: "结果", minWidth: 100 },
  { key: "client_key", label: "客户端", minWidth: 130 },
  { key: "detail", label: "详情", minWidth: 220, tooltip: true },
]

</script>

<style scoped lang="scss">
// 页面区域、状态修饰与后代元素按相邻规则分组，保留原级联和弹窗作用域。
.sub-cell {
  margin-top: 3px;
  color: var(--sa-faint);
  font-size: 11px;
}

// 静态控件尺寸与局部布局由 class 管理，动态样式保留在原数据绑定中。
.audit-breadcrumb {
  margin-bottom: 12px;
}

.audit-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.audit-action-filter {
  width: 220px;
}

</style>

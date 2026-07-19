<template>
  <div>
    <el-breadcrumb separator="/" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/system/accounts'}">账号管理</el-breadcrumb-item>
      <el-breadcrumb-item>指标配置</el-breadcrumb-item>
    </el-breadcrumb>
    <h2 class="sa-page-title">指标与口径管理</h2>
    <p class="sa-page-sub">控制已注册指标的显示、顺序和提示阈值；计算口径由后端实现并保持只读。</p>
    <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
      title="为保证数据可验证，页面不支持录入任意公式。新增指标需先完成后端计算、权限范围和测试。" />
    <div class="sa-card">
      <el-table :data="rows" size="small" v-loading="loading" row-key="kpi_id">
        <el-table-column prop="label" label="指标" min-width="170" />
        <el-table-column prop="kpi_id" label="稳定标识" min-width="170" />
        <el-table-column prop="calc_type" label="计算类型" width="120" />
        <el-table-column prop="formula" label="注册口径" min-width="170" show-overflow-tooltip />
        <el-table-column prop="unit" label="单位" width="80" />
        <el-table-column label="显示" width="90">
          <template #default="{row}"><el-switch v-model="row.enabled" /></template>
        </el-table-column>
        <el-table-column label="顺序" width="120">
          <template #default="{row}"><el-input-number v-model="row.sort_order" :min="0" :max="999" size="small" controls-position="right" /></template>
        </el-table-column>
        <el-table-column label="关注阈值" width="135">
          <template #default="{row}"><el-input-number v-model="row.threshold_warn" :min="0" size="small" controls-position="right" /></template>
        </el-table-column>
        <el-table-column label="重点阈值" width="135">
          <template #default="{row}"><el-input-number v-model="row.threshold_danger" :min="0" size="small" controls-position="right" /></template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{row}"><el-button text type="primary" size="small" :loading="saving===row.kpi_id" @click="save(row)">保存</el-button></template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { http } from '@/utils/http'

const rows = ref<any[]>([])
const loading = ref(false)
const saving = ref('')

async function load() {
  loading.value = true
  try {
    const data:any[] = await http.get('/admin/settings/kpi-config?module=dashboard')
    rows.value = data.map(item => ({...item, enabled: !!item.enabled}))
  } finally { loading.value = false }
}

async function save(row:any) {
  saving.value = row.kpi_id
  try {
    await http.put(`/admin/settings/kpi-config/${row.kpi_id}`, {
      enabled: row.enabled,
      sort_order: row.sort_order,
      threshold_warn: row.threshold_warn,
      threshold_danger: row.threshold_danger,
    })
    ElMessage.success('指标配置已保存，刷新仪表盘后生效')
    await load()
  } finally { saving.value = '' }
}

onMounted(load)
</script>

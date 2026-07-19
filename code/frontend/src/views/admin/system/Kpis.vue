<template>
  <div>
    <el-breadcrumb separator="/" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/system/accounts'}">账号管理</el-breadcrumb-item>
      <el-breadcrumb-item>指标配置</el-breadcrumb-item>
    </el-breadcrumb>
    <h2 class="sa-page-title">指标与口径管理</h2>
    <p class="sa-page-sub">核对指标名称、公式、来源、粒度、更新周期、版本和页面引用；页面只调整展示配置。</p>
    <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
      title="为保证数据可验证，页面不支持录入任意公式。新增指标需先完成后端计算、权限范围和测试。" />
    <div class="sa-card">
      <el-table :data="rows" size="small" v-loading="loading" row-key="kpi_id">
        <el-table-column prop="label" label="指标" min-width="170" />
        <el-table-column prop="kpi_id" label="稳定标识" min-width="170" />
        <el-table-column prop="calc_type" label="计算类型" width="120" />
        <el-table-column prop="formula" label="注册口径" min-width="220" show-overflow-tooltip />
        <el-table-column prop="data_source" label="数据来源" min-width="150" show-overflow-tooltip />
        <el-table-column prop="version" label="版本" width="80" />
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
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{row}">
            <el-button text size="small" @click="openDetail(row)">详情</el-button>
            <el-button text type="primary" size="small" :loading="saving===row.kpi_id" @click="save(row)">保存</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="detailVisible" size="620px" :title="`指标口径 · ${current?.label || ''}`">
      <template v-if="current">
        <div class="detail-grid">
          <div><span>稳定标识</span><b>{{ current.kpi_id }}</b></div>
          <div><span>定义版本</span><b>{{ current.version }}</b></div>
          <div><span>数据来源</span><b>{{ current.data_source }}</b></div>
          <div><span>统计粒度</span><b>{{ current.grain }}</b></div>
          <div><span>更新周期</span><b>{{ current.update_cycle }}</b></div>
          <div><span>适用范围</span><b>{{ current.scope_applicable }}</b></div>
        </div>
        <section class="definition-block"><span>计算公式</span><p>{{ current.formula }}</p></section>
        <section class="definition-block"><span>管理意义</span><p>{{ current.management_value }}</p></section>
        <section class="definition-block"><span>页面引用</span>
          <div><el-tag v-for="path in pageRefs(current)" :key="path" effect="plain">{{ path }}</el-tag></div>
        </section>
        <h4>展示配置变更历史</h4>
        <el-table :data="history" size="small" v-loading="historyLoading">
          <el-table-column prop="changed_at" label="时间" width="160" />
          <el-table-column prop="changed_by" label="操作人" width="100" />
          <el-table-column prop="change_reason" label="原因" min-width="170" />
          <el-table-column label="操作" width="80">
            <template #default="{row}"><el-button text type="warning" size="small" @click="rollback(row)">回滚</el-button></template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '@/utils/http'

const rows = ref<any[]>([])
const loading = ref(false)
const saving = ref('')
const detailVisible = ref(false)
const current = ref<any>(null)
const history = ref<any[]>([])
const historyLoading = ref(false)

async function load() {
  loading.value = true
  try {
    const data:any[] = await http.get('/admin/settings/kpi-config?module=dashboard')
    rows.value = data.map(item => ({...item, enabled: !!item.enabled}))
  } finally { loading.value = false }
}

async function save(row:any) {
  const {value} = await ElMessageBox.prompt(
    '说明本次显示、顺序或关注阈值调整的原因。计算公式不会改变。',
    '保存指标展示配置',
    {inputValidator:(text:string) => text.trim().length >= 2 || '请填写变更原因'},
  )
  saving.value = row.kpi_id
  try {
    await http.put(`/admin/settings/kpi-config/${row.kpi_id}`, {
      enabled: row.enabled,
      sort_order: row.sort_order,
      threshold_warn: row.threshold_warn,
      threshold_danger: row.threshold_danger,
      change_reason:value.trim(),
    })
    ElMessage.success('指标配置已保存，刷新仪表盘后生效')
    await load()
  } finally { saving.value = '' }
}

function pageRefs(row:any) {
  if (Array.isArray(row.page_refs)) return row.page_refs
  try { return JSON.parse(row.page_refs || '[]') } catch { return [] }
}
async function openDetail(row:any) {
  current.value = row
  detailVisible.value = true
  historyLoading.value = true
  try { history.value = await http.get(`/admin/settings/kpi-config/${row.kpi_id}/history`) }
  finally { historyLoading.value = false }
}
async function rollback(row:any) {
  if (!current.value) return
  await ElMessageBox.confirm('只回滚显示、顺序和提示阈值，不回滚计算公式。是否继续？','回滚指标配置',{type:'warning'})
  await http.post(`/admin/settings/kpi-config/${current.value.kpi_id}/rollback/${row.history_id}`)
  ElMessage.success('指标展示配置已回滚')
  await load()
  await openDetail(rows.value.find(item => item.kpi_id === current.value.kpi_id))
}

onMounted(load)
</script>

<style scoped>
.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}.detail-grid>div,.definition-block{padding:12px;border:1px solid #e2e8f0;border-radius:9px;background:#f8fafc}.detail-grid span,.definition-block span{display:block;color:#64748b;font-size:11px}.detail-grid b{display:block;margin-top:5px;color:#1e293b}.definition-block{margin-bottom:10px}.definition-block p{margin:6px 0 0;color:#334155;line-height:1.7}.definition-block .el-tag{margin:7px 7px 0 0}
</style>

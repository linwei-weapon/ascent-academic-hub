<template>
  <div class="parameter-page">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">系统参数</h2>
        <p class="sa-page-sub">维护学校实例、学期默认值、模型接入边界、缓存和展示参数；不维护教务业务主数据。</p>
      </div>
      <el-button @click="load">刷新参数</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="boundary-alert"
      :title="data.boundary || '系统参数不包含学业预警规则。'" />
    <el-alert type="warning" :closable="false" show-icon class="boundary-alert"
      :title="data.secretBoundary || '密钥由部署环境管理，不在页面保存。'" />

    <el-tabs v-model="activeCategory">
      <el-tab-pane v-for="category in categories" :key="category" :label="category" :name="category">
        <div class="parameter-grid" v-loading="loading">
          <article v-for="item in grouped[category] || []" :key="item.parameter_key">
            <div class="parameter-head">
              <div>
                <b>{{ item.name }}</b>
                <span>{{ item.parameter_key }} · 版本 {{ item.version }}</span>
              </div>
              <el-button text type="primary" :disabled="!item.editable" @click="openEdit(item)">调整</el-button>
            </div>
            <div class="parameter-value">{{ valueLabel(item) }}</div>
            <p>{{ item.description }}</p>
            <small>更新：{{ item.updated_at }}{{ item.updated_by ? ` · ${item.updated_by}` : '' }}</small>
          </article>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="editVisible" :title="`调整参数 · ${current?.name || ''}`" width="540px">
      <el-alert type="info" :closable="false" show-icon :title="current?.description || ''" />
      <el-form label-width="90px" class="edit-form">
        <el-form-item label="参数值">
          <el-switch v-if="current?.value_type==='boolean'" v-model="editValue" />
          <el-input-number v-else-if="current?.value_type==='integer'" v-model="editValue" :min="1" :max="86400" style="width:100%" />
          <el-select v-else-if="current?.value_type==='enum'" v-model="editValue" style="width:100%">
            <el-option v-for="option in current.options || []" :key="option" :label="optionLabel(option)" :value="option" />
          </el-select>
          <el-input v-else v-model="editValue" />
        </el-form-item>
        <el-form-item label="变更原因" required>
          <el-input v-model="changeReason" type="textarea" :rows="3" maxlength="300" show-word-limit
            placeholder="说明为什么需要调整，以及影响哪些默认展示或运行行为" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存参数</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { http } from '@/utils/http'

const loading = ref(false)
const saving = ref(false)
const data = reactive<any>({parameters:[]})
const activeCategory = ref('')
const editVisible = ref(false)
const current = ref<any>(null)
const editValue = ref<any>('')
const changeReason = ref('')
const categories = computed<string[]>(() => [...new Set((data.parameters || []).map((item:any) => item.category))])
const grouped = computed<Record<string,any[]>>(() => Object.fromEntries(categories.value.map(category => [
  category, (data.parameters || []).filter((item:any) => item.category === category),
])))
const optionLabels:Record<string,string> = {
  school_approved_cloud:'学校批准的云端模型',private_model:'校内私有模型',disabled:'不接入模型',
  authorized_business_data:'当前授权业务数据',aggregate_only:'仅聚合数据',
  stable_demo_plus_model_samples:'稳定规则＋少量模型样例',deterministic_only:'仅确定性规则',model_online:'在线模型生成',
}

async function load() {
  loading.value = true
  try {
    Object.assign(data, await http.get('/admin/system/parameters'))
    if (!activeCategory.value) activeCategory.value = categories.value[0] || ''
  } finally { loading.value = false }
}
function optionLabel(value:any) { return optionLabels[String(value)] || String(value) }
function valueLabel(item:any) {
  if (item.value_type === 'boolean') return item.value ? '已启用' : '已关闭'
  if (item.value_type === 'enum') return optionLabel(item.value)
  if (item.parameter_key.includes('seconds')) return `${item.value} 秒`
  if (item.parameter_key.includes('page_size')) return `${item.value} 行/页`
  return String(item.value ?? '—')
}
function openEdit(item:any) {
  current.value = item
  editValue.value = item.value
  changeReason.value = ''
  editVisible.value = true
}
async function save() {
  if (!current.value || changeReason.value.trim().length < 2) {
    ElMessage.warning('请填写变更原因')
    return
  }
  saving.value = true
  try {
    await http.put(`/admin/system/parameters/${current.value.parameter_key}`, {
      value:editValue.value, changeReason:changeReason.value.trim(),
    })
    ElMessage.success('系统参数已保存并记录审计')
    editVisible.value = false
    await load()
  } finally { saving.value = false }
}
onMounted(load)
</script>

<style scoped>
.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}.boundary-alert{margin-bottom:10px}.parameter-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.parameter-grid article{padding:17px;background:#fff;border:1px solid var(--sa-border);border-radius:12px}.parameter-head{display:flex;justify-content:space-between;gap:12px}.parameter-head b{display:block;color:#1e293b}.parameter-head span{display:block;margin-top:4px;color:#94a3b8;font-size:11px}.parameter-value{margin:14px 0 8px;font-size:20px;font-weight:750;color:#4f46e5}.parameter-grid p{min-height:38px;color:#64748b;font-size:12px;line-height:1.65}.parameter-grid small{color:#94a3b8}.edit-form{margin-top:18px}
@media(max-width:900px){.parameter-grid{grid-template-columns:1fr}}
</style>

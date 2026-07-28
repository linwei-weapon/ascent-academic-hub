<template>
  <el-dialog :model-value="modelValue" :title="`${majorName} · 当前有效预警学生名单`"
    width="min(1120px, 95vw)" append-to-body destroy-on-close
    @update:model-value="emit('update:modelValue', $event)">
    <div class="scope-strip">
      <span>固定范围</span><b>{{ collegeName }} / {{ majorName }}</b>
      <span v-if="semester" class="scope-semester">统计学期：{{ semester }}</span>
      <small>{{ meta.currentSemester ? `当前预警周期：${meta.currentSemester}` : '按当前规则快照' }}</small>
    </div>
    <div class="alert-filters">
      <el-input v-model="draft.q" clearable placeholder="姓名或学号" style="width:170px" />
      <el-select v-model="draft.classId" clearable placeholder="行政班" style="width:150px">
        <el-option v-for="item in options.organizations?.class || []" :key="item.value"
          :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="draft.level" clearable placeholder="风险等级" style="width:125px">
        <el-option v-for="item in options.levels || []" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="draft.type" clearable placeholder="预警类型" style="width:150px">
        <el-option v-for="item in options.types || []" :key="item.value" :label="item.value" :value="item.value" />
      </el-select>
      <el-select v-model="draft.management" clearable placeholder="核查状态" style="width:135px">
        <el-option v-for="item in options.managementStates || []" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-button type="primary" :loading="loading" @click="applyFilters">查询</el-button>
      <el-button :disabled="loading" @click="resetFilters">重置</el-button>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon title="预警学生名单加载失败">
      <template #default>{{ loadError }} <el-button link type="primary" @click="loadRows">重新加载</el-button></template>
    </el-alert>
    <div v-if="initialLoading" class="dialog-loading"><el-skeleton :rows="9" animated /></div>
    <template v-else>
      <div v-if="loading" class="refresh-note">正在按新条件更新，当前结果暂时保留…</div>
      <DataTable :columns="columns" :data="rows" storage-key="dashboard:major-alert-students"
        :max-business-columns="7" :config-version="1" :page-size="pagination.pageSize"
        :page-sizes="[10,20,50]" size="small" empty-text="当前条件下没有有效预警学生"
        @update:page-size="changePageSize">
        <template #col-student="{row}">
          <button class="student-link" type="button" @click="openReview(row)">
            <b>{{ row.studentName }}</b><span>{{ row.studentId }}</span>
          </button>
        </template>
        <template #col-highestLevel="{row}">
          <el-tag size="small" :type="levelType(row.highestLevel)">{{ row.highestLevel }}</el-tag>
        </template>
        <template #col-primaryReason="{row}">
          <span class="reason">{{ row.primaryType }} · {{ row.primaryReason }}</span>
        </template>
        <template #col-managementLabel="{row}"><el-tag size="small" effect="plain">{{ row.managementLabel }}</el-tag></template>
        <template #col-action="{row}"><el-button link type="primary" @click="openReview(row)">核查</el-button></template>
      </DataTable>
      <div class="external-pager">
        <el-pagination v-model:current-page="pagination.page" :page-size="pagination.pageSize"
          :total="pagination.total" layout="total, prev, pager, next" small
          @current-change="loadRows" />
      </div>
    </template>
    <AlertStudentDrawer v-model="reviewVisible" :row="selectedRow" @changed="loadRows" />
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { http } from '@/utils/http'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import AlertStudentDrawer from '@/views/admin/alert/AlertStudentDrawer.vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  majorId: string
  majorName: string
  collegeName?: string
  semester?: string
}>(), { collegeName: '', semester: '' })
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const empty = () => ({ q: '', classId: '', level: '', type: '', management: '' })
const draft = reactive(empty())
const applied = reactive(empty())
const options = reactive<any>({ levels: [], types: [], managementStates: [], organizations: {} })
const meta = reactive<any>({})
const rows = ref<any[]>([])
const pagination = reactive({ page: 1, pageSize: 20, total: 0 })
const initialLoading = ref(false)
const loading = ref(false)
const loadError = ref('')
const reviewVisible = ref(false)
const selectedRow = ref<any>(null)
let requestSequence = 0

const columns: DataTableColumn[] = [
  { key: 'student', label: '学生', width: 135, fixed: 'left', region: 'identity', required: true },
  { key: 'grade', label: '年级', width: 80, required: true },
  { key: 'className', label: '行政班', minWidth: 130, required: true },
  { key: 'highestLevel', label: '最高风险', width: 90, required: true },
  { key: 'primaryReason', label: '主要触发证据', minWidth: 250, tooltip: true, required: true },
  { key: 'alertCount', label: '规则命中', width: 88, align: 'right' },
  { key: 'managementLabel', label: '核查状态', width: 108, required: true },
  { key: 'latestAt', label: '最近变化', width: 145, defaultVisible: false },
  { key: 'action', label: '核查', width: 62, fixed: 'right', region: 'action', required: true },
]

function params() {
  const value = new URLSearchParams({
    major: props.majorId,
    page: String(pagination.page),
    page_size: String(pagination.pageSize),
  })
  if (applied.q) value.set('q', applied.q)
  if (applied.classId) value.set('class_id', applied.classId)
  if (applied.level) value.set('level', applied.level)
  if (applied.type) value.set('type', applied.type)
  if (applied.management) value.set('management', applied.management)
  return value
}

async function loadOptions() {
  const result = await http.get<any>(`/admin/alerts/options?major=${encodeURIComponent(props.majorId)}`)
  Object.keys(options).forEach(key => delete options[key])
  Object.assign(options, result || {})
  Object.assign(meta, result?.meta || {})
}

async function loadRows() {
  const sequence = ++requestSequence
  loading.value = true
  loadError.value = ''
  try {
    const result = await http.get<any>(`/admin/alerts/students?${params().toString()}`)
    if (sequence !== requestSequence) return
    rows.value = result.items || []
    Object.assign(pagination, result.pagination || {})
    Object.assign(meta, result.meta || {})
  } catch (error: any) {
    if (sequence === requestSequence) loadError.value = error?.message || '请稍后重试'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function initialize() {
  initialLoading.value = true
  loadError.value = ''
  Object.assign(draft, empty())
  Object.assign(applied, empty())
  pagination.page = 1
  try {
    await Promise.all([loadOptions(), loadRows()])
  } catch (error: any) {
    loadError.value = error?.message || '请稍后重试'
  } finally {
    initialLoading.value = false
  }
}

function applyFilters() {
  Object.assign(applied, { ...draft })
  pagination.page = 1
  void loadRows()
}
function resetFilters() {
  Object.assign(draft, empty())
  Object.assign(applied, empty())
  pagination.page = 1
  void loadRows()
}
function changePageSize(value: number) {
  pagination.pageSize = value
  pagination.page = 1
  void loadRows()
}
function openReview(row: any) {
  selectedRow.value = row
  reviewVisible.value = true
}
function levelType(level: string) {
  return level === '严重' ? 'danger' : level === '警告' ? 'warning' : 'info'
}

watch(() => [props.modelValue, props.majorId], ([open]) => {
  if (open && props.majorId) void initialize()
}, { immediate: true })
</script>

<style scoped>
.scope-strip { display:flex; align-items:center; gap:10px; padding:10px 12px; border:1px solid var(--sa-border); border-radius:9px; background:var(--sa-bg); }
.scope-strip span,.scope-strip small { color:var(--sa-muted); font-size:12px; }
.scope-strip .scope-semester { padding-left:10px; border-left:1px solid var(--sa-border); color:var(--sa-text); }
.scope-strip small { margin-left:auto; }
.alert-filters { display:flex; flex-wrap:wrap; gap:9px; margin:12px 0; }
.dialog-loading { min-height:360px; }
.refresh-note { padding:7px 10px; color:var(--sa-primary); font-size:12px; }
.student-link { display:grid; gap:2px; padding:0; border:0; background:transparent; color:var(--sa-primary); text-align:left; cursor:pointer; }
.student-link span { color:var(--sa-muted); font-size:11px; }
.reason { color:var(--sa-text); }
.external-pager { display:flex; justify-content:flex-end; margin-top:10px; }
@media (max-width:760px) {
  .scope-strip { align-items:flex-start; flex-direction:column; }
  .scope-strip small { margin-left:0; }
}
</style>

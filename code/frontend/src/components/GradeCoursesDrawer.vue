<template>
  <el-drawer :model-value="modelValue" :title="`${majorName} · ${grade}级全部课程`"
    size="min(860px, 92vw)" destroy-on-close
    @update:model-value="emit('update:modelValue', $event)">
    <div class="scope-strip">
      <span>固定范围</span><b>{{ semester }} · {{ collegeName }} / {{ majorName }} / {{ grade }}级</b>
    </div>
    <div class="course-filter">
      <el-input v-model="draftKeyword" clearable placeholder="课程代码或名称" @keyup.enter="applyQuery" />
      <el-button type="primary" :loading="loading" @click="applyQuery">查询</el-button>
      <el-button :disabled="loading" @click="resetQuery">重置</el-button>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon title="课程列表加载失败">
      <template #default>{{ loadError }} <el-button link type="primary" @click="loadRows">重新加载</el-button></template>
    </el-alert>
    <div v-if="initialLoading" class="drawer-loading"><el-skeleton :rows="9" animated /></div>
    <template v-else>
      <div v-if="loading" class="refresh-note">正在按新条件更新，当前结果暂时保留…</div>
      <DataTable :columns="columns" :data="rows" :storage-key="`dashboard:grade-courses:${majorId}:${grade}`"
        :max-business-columns="5" :config-version="1" :page-size="pagination.pageSize"
        :page-sizes="[10,20,50]" size="small" empty-text="本学期暂无符合条件的课程"
        @update:page-size="changePageSize">
        <template #col-courseName="{row}">
          <button class="course-link" type="button" @click="openCourse(row)">{{ row.courseName }}</button>
        </template>
        <template #col-failRate="{row}">{{ row.failRate == null ? '—' : `${row.failRate}%` }}</template>
        <template #col-action="{row}"><el-button link type="primary" @click="openCourse(row)">详情</el-button></template>
      </DataTable>
      <div class="external-pager">
        <el-pagination v-model:current-page="pagination.page" :page-size="pagination.pageSize"
          :total="pagination.total" layout="total, prev, pager, next" small
          @current-change="loadRows" />
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { http } from '@/utils/http'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  majorId: string
  majorName: string
  collegeId?: string
  collegeName?: string
  grade: string
  semester: string
}>(), { collegeId: '', collegeName: '' })
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()
const router = useRouter()
const draftKeyword = ref('')
const appliedKeyword = ref('')
const rows = ref<any[]>([])
const pagination = reactive({ page: 1, pageSize: 20, total: 0 })
const initialLoading = ref(false)
const loading = ref(false)
const loadError = ref('')
let requestSequence = 0

const columns: DataTableColumn[] = [
  { key: 'courseId', label: '课程代码', width: 115, fixed: 'left', region: 'identity', required: true },
  { key: 'courseName', label: '课程名称', minWidth: 190, fixed: 'left', region: 'identity', required: true },
  { key: 'failCount', label: '未通过人次', width: 110, align: 'right', required: true },
  { key: 'totalCount', label: '有效成绩人次', width: 120, align: 'right', required: true },
  { key: 'failRate', label: '未通过人次率', width: 120, align: 'right', required: true },
  { key: 'action', label: '详情', width: 62, fixed: 'right', region: 'action', required: true },
]

async function loadRows() {
  if (!props.majorId || !props.grade || !props.semester) return
  const sequence = ++requestSequence
  loading.value = true
  loadError.value = ''
  const params = new URLSearchParams({
    grade: props.grade.replace(/级$/, ''),
    semester: props.semester,
    page: String(pagination.page),
    page_size: String(pagination.pageSize),
  })
  if (appliedKeyword.value) params.set('q', appliedKeyword.value)
  try {
    const result = await http.get<any>(`/admin/major/${encodeURIComponent(props.majorId)}/grade-courses?${params.toString()}`)
    if (sequence !== requestSequence) return
    rows.value = result.items || []
    pagination.total = result.total || 0
    pagination.page = result.page || pagination.page
    pagination.pageSize = result.pageSize || pagination.pageSize
  } catch (error: any) {
    if (sequence === requestSequence) loadError.value = error?.message || '请稍后重试'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function initialize() {
  initialLoading.value = true
  draftKeyword.value = ''
  appliedKeyword.value = ''
  pagination.page = 1
  await loadRows()
  initialLoading.value = false
}
function applyQuery() {
  appliedKeyword.value = draftKeyword.value.trim()
  pagination.page = 1
  void loadRows()
}
function resetQuery() {
  draftKeyword.value = ''
  appliedKeyword.value = ''
  pagination.page = 1
  void loadRows()
}
function changePageSize(value: number) {
  pagination.pageSize = value
  pagination.page = 1
  void loadRows()
}
function openCourse(row: any) {
  router.push({
    path: `/admin/course/${row.courseId}`,
    query: {
      ...(props.collegeId ? { collegeId: props.collegeId } : {}),
      ...(props.collegeName ? { collegeName: props.collegeName } : {}),
      majorId: props.majorId,
      majorName: props.majorName,
      grade: props.grade.replace(/级$/, ''),
      semester: props.semester,
    },
  })
}

watch(() => [props.modelValue, props.majorId, props.grade, props.semester], ([open]) => {
  if (open) void initialize()
}, { immediate: true })
</script>

<style scoped>
.scope-strip { display:flex; gap:10px; padding:10px 12px; border:1px solid var(--sa-border); border-radius:9px; background:var(--sa-bg); }
.scope-strip span { color:var(--sa-muted); font-size:12px; }
.course-filter { display:grid; grid-template-columns:minmax(180px,1fr) auto auto; gap:9px; margin:12px 0; }
.drawer-loading { min-height:340px; }
.refresh-note { padding:7px 10px; color:var(--sa-primary); font-size:12px; }
.course-link { padding:0; border:0; background:transparent; color:var(--sa-primary); cursor:pointer; }
.external-pager { display:flex; justify-content:flex-end; margin-top:10px; }
</style>
